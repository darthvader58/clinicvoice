from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db.models import AudioAsset, Recording
from src.db.session import get_db

logger = logging.getLogger("clinicvoice.ingest.receiver")

router = APIRouter(prefix="/api", tags=["ingest"])

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".webm", ".ogg", ".flac", ".aac"}
ALLOWED_CONTENT_PREFIXES = ("audio/", "video/webm", "application/octet-stream")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
ALLOWED_SCENARIOS = {"hallway", "consult", "unknown"}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    base = Path(name).name or "upload"
    return _SAFE_NAME.sub("_", base)[:128]


def _validate_upload(file: UploadFile, scenario: str, size: int) -> None:
    if scenario not in ALLOWED_SCENARIOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid scenario; allowed: {sorted(ALLOWED_SCENARIOS)}",
        )

    if size <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty upload",
        )
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds {MAX_UPLOAD_BYTES} bytes",
        )

    suffix = Path(file.filename or "").suffix.lower()
    content_type = (file.content_type or "").lower()
    ext_ok = suffix in ALLOWED_EXTENSIONS
    ct_ok = any(content_type.startswith(p) for p in ALLOWED_CONTENT_PREFIXES)
    if not (ext_ok or ct_ok):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported audio format: ext={suffix!r} ct={content_type!r}",
        )


async def handle_upload(
    file: UploadFile,
    scenario: str,
    db: AsyncSession,
) -> dict:
    """Persist an uploaded audio file plus its source AudioAsset row.

    Returns a RecordingIn-compatible dict containing recording_id, scenario,
    track_mode (pending), file_hash, file_path, format. The full pipeline
    (normalize, separate, diarize, ASR) is orchestrated by API routes."""
    settings = get_settings()

    data = await file.read()
    size = len(data)
    _validate_upload(file, scenario, size)

    file_hash = hashlib.sha256(data).hexdigest()

    storage_root = Path(settings.AUDIO_STORAGE_PATH)
    storage_root.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "").suffix.lower() or ".wav"
    safe_name = _safe_filename(file.filename or f"upload{suffix}")
    target_dir = storage_root / file_hash[:12]
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_name

    try:
        target_path.write_bytes(data)
    except OSError as exc:
        logger.warning(
            "upload_write_failed",
            extra={"error_type": type(exc).__name__, "hash_prefix": file_hash[:12]},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to persist upload",
        ) from exc

    recording = Recording(
        file_hash=file_hash,
        scenario=scenario,
        retention_ttl=settings.AUDIO_RETENTION_TTL_S,
    )
    db.add(recording)
    await db.flush()

    asset = AudioAsset(
        recording_id=recording.id,
        file_path=str(target_path),
        asset_type="source",
        format=suffix.lstrip("."),
        sample_rate=None,
        channels=None,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(recording)
    await db.refresh(asset)

    logger.info(
        "upload_accepted",
        extra={
            "recording_id": recording.id,
            "asset_id": asset.id,
            "file_hash_prefix": file_hash[:12],
            "size_bytes": size,
            "scenario": scenario,
            "format": suffix.lstrip("."),
        },
    )

    return {
        "recording_id": recording.id,
        "asset_id": asset.id,
        "scenario": scenario,
        "track_mode": "pending",
        "file_hash": file_hash,
        "file_path": str(target_path),
        "format": suffix.lstrip("."),
        "size_bytes": size,
    }


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_endpoint(
    file: UploadFile,
    scenario: str = Form("unknown"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing file field",
        )
    return await handle_upload(file=file, scenario=scenario, db=db)
