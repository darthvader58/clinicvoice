"""Audio retention background task.

Periodically scans `recording` rows past their TTL, deletes their
on-disk audio assets, and stamps `purged_at`. Logs are PHI-free —
we only emit hashed recording IDs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from src.config import Settings, settings as default_settings
from src.db.models import AudioAsset, Recording
from src.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Run every hour. Cheap on SQLite, plenty granular for a 24h default TTL.
PURGE_INTERVAL_S: int = 3600


def _hash_id(recording_id: str) -> str:
    """Stable short hash for PHI-free logging."""
    return hashlib.sha256(recording_id.encode("utf-8")).hexdigest()[:12]


async def purge_once(settings: Settings) -> int:
    """Run a single purge pass. Returns the number of recordings purged."""
    if settings.AUDIO_RETENTION_TTL_S <= 0:
        # 0 means "retain forever" — bail out cleanly.
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.AUDIO_RETENTION_TTL_S)
    cutoff_iso = cutoff.isoformat()
    purged = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Recording).where(
                Recording.retention_ttl > 0,
                Recording.purged_at.is_(None),
                Recording.created_at < cutoff_iso,
            )
        )
        for rec in result.scalars().all():
            asset_rows = await db.execute(
                select(AudioAsset).where(AudioAsset.recording_id == rec.id)
            )
            for asset in asset_rows.scalars().all():
                if asset.file_path:
                    path = Path(asset.file_path)
                    if path.exists():
                        try:
                            path.unlink()
                        except OSError as err:
                            logger.warning(
                                "audio_purge_unlink_failed",
                                extra={
                                    "recording_hash": _hash_id(rec.id),
                                    "error": err.__class__.__name__,
                                },
                            )
                # null out the file_path so a re-scan won't re-attempt
                asset.file_path = None

            rec.purged_at = datetime.now(timezone.utc).isoformat()
            purged += 1
            logger.info(
                "audio_purged",
                extra={"recording_hash": _hash_id(rec.id)},
            )

        await db.commit()

    return purged


async def retention_loop(settings: Settings | None = None) -> None:
    """Forever-loop purging audio past TTL. Cancel-safe."""
    settings = settings or default_settings
    logger.info(
        "retention_loop_started",
        extra={"interval_s": PURGE_INTERVAL_S, "ttl_s": settings.AUDIO_RETENTION_TTL_S},
    )
    try:
        while True:
            await asyncio.sleep(PURGE_INTERVAL_S)
            try:
                count = await purge_once(settings)
                if count:
                    logger.info("retention_pass_complete", extra={"purged_count": count})
            except Exception:  # noqa: BLE001 — never let the loop die
                logger.exception("retention_pass_failed")
    except asyncio.CancelledError:
        logger.info("retention_loop_cancelled")
        raise


__all__ = ["retention_loop", "purge_once", "PURGE_INTERVAL_S"]
