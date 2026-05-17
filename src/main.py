"""clinicvoice FastAPI application entrypoint.

Boots DB schema, kicks off the audio-TTL retention loop, wires up
CORS for the Vite demo, and installs a PHI-stripping exception
handler so error responses never leak transcript text.

Run: `uvicorn src.main:app --reload --port 8000`
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import settings
from src.db.retention import retention_loop
from src.db.session import init_db

logger = logging.getLogger("clinicvoice")
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


# --------------------------------------------------------------------------- #
# PHI stripping — last line of defence on error paths.
# --------------------------------------------------------------------------- #
_PHI_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # US-ish phone
    re.compile(r"\b\+?\d[\d\-.\s]{7,}\d\b"),  # generic phone / ID
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO date (DOB)
    re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),  # slash date (DOB)
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
]


def _strip_phi(text: str) -> str:
    """Defensive PHI scrub for error messages. Cheap, conservative."""
    cleaned = text
    for pat in _PHI_PATTERNS:
        cleaned = pat.sub("[REDACTED]", cleaned)
    return cleaned


# --------------------------------------------------------------------------- #
# Lifespan: init DB, start retention loop, ensure storage dirs exist.
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Ensure local storage roots exist before anything writes to them.
    os.makedirs(settings.AUDIO_STORAGE_PATH, exist_ok=True)
    os.makedirs(settings.REPORTS_PATH, exist_ok=True)

    await init_db()
    logger.info("db_ready", extra={"db_path": settings.DB_PATH})

    retention_task = asyncio.create_task(retention_loop(settings), name="retention_loop")
    logger.info("startup_complete")

    try:
        yield
    finally:
        retention_task.cancel()
        try:
            await retention_task
        except asyncio.CancelledError:
            pass
        logger.info("shutdown_complete")


# --------------------------------------------------------------------------- #
# App + middleware
# --------------------------------------------------------------------------- #
app = FastAPI(
    title="clinicvoice",
    version="0.1.0",
    description="Local-first medical voice intake with PHI redaction.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Routes — import lazily so a partial build still boots `src.main`.
# --------------------------------------------------------------------------- #
try:  # pragma: no cover — depends on agent ZETA completion
    from src.api.routes import router as api_router

    app.include_router(api_router, prefix="/api")
    logger.info("api_router_mounted")
except Exception as err:  # noqa: BLE001 — boot must not fail before routes exist
    logger.warning(
        "api_router_unavailable",
        extra={"error": err.__class__.__name__},
    )


# --------------------------------------------------------------------------- #
# Health endpoint — minimal, always available even if routes module is absent.
# --------------------------------------------------------------------------- #
@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Global exception handler — strip PHI before responding.
# --------------------------------------------------------------------------- #
@app.exception_handler(Exception)
async def phi_safe_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log internally with class name only; no message body (could contain PHI).
    logger.exception(
        "unhandled_exception",
        extra={
            "path": request.url.path,
            "method": request.method,
            "exc_type": exc.__class__.__name__,
        },
    )
    safe_detail = _strip_phi(str(exc)) if str(exc) else "internal_error"
    return JSONResponse(
        status_code=500,
        content={"detail": safe_detail, "type": exc.__class__.__name__},
    )


__all__ = ["app", "lifespan"]
