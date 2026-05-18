"""Live streaming endpoints — rolling chunk upload pattern.

Frontend records via MediaRecorder rolling stop->start (~10 s chunks), POSTs
each chunk here, gets back redacted text immediately for live UX. When the
client calls /stop, a background consolidation pass stitches all chunks and
runs the full Option-A pipeline for the canonical transcript.

CLAUDE.md rules respected:
- raw_text never persists. The redaction boundary runs here before the
  response is built and before any DB write.
- Whisper runs locally. The singleton is warmed at app startup so the first
  chunk does not pay the 1-2 minute model load cost.
- Logs never contain transcript text; only hashed IDs and counters.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.config import settings

logger = logging.getLogger("clinicvoice.api.streaming")

router = APIRouter(prefix="/api/stream")

SUPPORTED_LANGUAGES = {"en", "hi", "ur", "ta", "id", "ms", "auto"}

# In-process registry of live sessions, keyed by recording_id.
_LIVE: Dict[str, Dict[str, Any]] = {}


def _session(recording_id: str) -> Dict[str, Any]:
    sess = _LIVE.get(recording_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="live_session_not_found")
    return sess


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #
class StartResponse(BaseModel):
    recording_id: str
    status: str = "live"


class ChunkResponse(BaseModel):
    recording_id: str
    seq: int
    redacted_text: str
    language_tag: str
    redaction_count: int
    duration_s: float


class StopResponse(BaseModel):
    recording_id: str
    status: str = "consolidating"
    chunks: int


# --------------------------------------------------------------------------- #
# POST /api/stream/start
# --------------------------------------------------------------------------- #
@router.post("/start", response_model=StartResponse)
async def start_session(
    scenario: str = Form("unknown"),
    language: str = Form("auto"),
) -> StartResponse:
    if scenario not in {"hallway", "consult", "unknown"}:
        raise HTTPException(status_code=422, detail="invalid_scenario")
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="invalid_language")

    recording_id = str(uuid4())
    chunks_dir = Path(settings.AUDIO_STORAGE_PATH) / recording_id / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    try:
        from src.db.models import Recording
        from src.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            session.add(
                Recording(
                    id=recording_id,
                    file_hash="",
                    scenario=scenario,
                    retention_ttl=settings.AUDIO_RETENTION_TTL_S,
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "live_recording_insert_failed",
            extra={
                "recording_id_prefix": recording_id[:8],
                "error_type": type(exc).__name__,
            },
        )

    _LIVE[recording_id] = {
        "scenario": scenario,
        "language": language,
        "next_seq": 0,
        "chunks_dir": chunks_dir,
        "lock": asyncio.Lock(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        "live_session_started",
        extra={"recording_id_prefix": recording_id[:8], "language": language},
    )
    return StartResponse(recording_id=recording_id)


# --------------------------------------------------------------------------- #
# POST /api/stream/{recording_id}/chunk
# --------------------------------------------------------------------------- #
@router.post("/{recording_id}/chunk", response_model=ChunkResponse)
async def post_chunk(
    recording_id: str,
    file: UploadFile = File(...),
) -> ChunkResponse:
    sess = _session(recording_id)
    seq = sess["next_seq"]
    sess["next_seq"] = seq + 1

    suffix = Path(file.filename or "chunk.webm").suffix or ".webm"
    chunk_path = sess["chunks_dir"] / f"chunk-{seq:04d}{suffix}"
    size = 0
    with chunk_path.open("wb") as out:
        while True:
            blob = await file.read(1 << 20)
            if not blob:
                break
            out.write(blob)
            size += len(blob)
    await file.close()

    if size == 0:
        chunk_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="empty_chunk")

    # openai-whisper is not thread-safe; serialize per session.
    async with sess["lock"]:
        try:
            redacted_text, redaction_count, language_tag, duration_s = (
                await asyncio.to_thread(
                    _decode_chunk_sync,
                    chunk_path,
                    sess["language"],
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "live_chunk_failed",
                extra={
                    "recording_id_prefix": recording_id[:8],
                    "seq": seq,
                    "error_type": type(exc).__name__,
                },
            )
            raise HTTPException(status_code=500, detail="chunk_decode_failed")

    logger.info(
        "live_chunk_decoded",
        extra={
            "recording_id_prefix": recording_id[:8],
            "seq": seq,
            "duration_s": round(duration_s, 2),
            "language_tag": language_tag,
            "redaction_count": redaction_count,
        },
    )
    return ChunkResponse(
        recording_id=recording_id,
        seq=seq,
        redacted_text=redacted_text,
        language_tag=language_tag,
        redaction_count=redaction_count,
        duration_s=duration_s,
    )


# --------------------------------------------------------------------------- #
# POST /api/stream/{recording_id}/stop
# --------------------------------------------------------------------------- #
@router.post("/{recording_id}/stop", response_model=StopResponse)
async def stop_session(
    recording_id: str, background_tasks: BackgroundTasks
) -> StopResponse:
    sess = _session(recording_id)
    chunks = sess["next_seq"]
    background_tasks.add_task(
        _consolidate,
        recording_id,
        sess["chunks_dir"],
        sess["scenario"],
        sess["language"],
    )
    logger.info(
        "live_session_stopped",
        extra={"recording_id_prefix": recording_id[:8], "chunks": chunks},
    )
    return StopResponse(recording_id=recording_id, chunks=chunks)


# --------------------------------------------------------------------------- #
# Sync helpers — heavy work runs in a thread.
# --------------------------------------------------------------------------- #
def _decode_chunk_sync(
    chunk_path: Path, language: str
) -> tuple[str, int, str, float]:
    """Decode a single chunk: ffmpeg/librosa -> Whisper -> redact.

    Returns (redacted_text, redaction_count, language_tag_str, duration_s).
    """
    import librosa  # type: ignore
    import whisper as _whisper  # type: ignore

    from src.asr.engine import WhisperEngine
    from src.redact.engine import redact

    audio, _sr = librosa.load(str(chunk_path), sr=16000, mono=True)
    duration_s = float(len(audio)) / 16000.0

    engine = WhisperEngine.get_instance(settings)
    model = engine._model  # noqa: SLF001

    detected_lang: Optional[str] = None
    lang_prob = 1.0
    if language and language != "auto":
        detected_lang = language
    else:
        lang_prob = 0.0
        try:
            clip = _whisper.pad_or_trim(audio)
            n_mels = getattr(getattr(model, "dims", None), "n_mels", 80)
            mel = _whisper.log_mel_spectrogram(clip, n_mels=n_mels).to(model.device)
            _, probs = model.detect_language(mel)
            detected_lang = max(probs, key=probs.get)
            lang_prob = float(probs[detected_lang])
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "live_lang_detect_failed",
                extra={"error_type": type(exc).__name__},
            )

    result = model.transcribe(
        audio,
        language=detected_lang,
        initial_prompt=None,  # no English bias on live chunks
        word_timestamps=False,
        task="transcribe",
        no_speech_threshold=0.6,
        compression_ratio_threshold=2.4,
        condition_on_previous_text=False,
        logprob_threshold=-1.0,
    )
    raw_text = (result.get("text") or "").strip()
    lang_tag = detected_lang or "unknown"

    # === REDACTION BOUNDARY === raw_text dies here.
    redacted_text, redaction_map = redact(raw_text, lang_tag if lang_tag in {
        "en", "hi", "ur", "ta", "id", "ms"
    } else "en")
    return redacted_text, len(redaction_map), lang_tag, duration_s


# --------------------------------------------------------------------------- #
# Consolidation — run full Option A pipeline on the stitched audio.
# --------------------------------------------------------------------------- #
async def _consolidate(
    recording_id: str, chunks_dir: Path, scenario: str, language: str
) -> None:
    """Stitch all chunks into one file, then hand off to the batch pipeline.

    The batch pipeline writes the canonical transcript with proper speaker
    labels (S1/S2…), runs the SI-SDR gate, and produces the metrics row.
    """
    from src.api.routes import _run_pipeline

    stitched = Path(settings.AUDIO_STORAGE_PATH) / f"{recording_id}.wav"
    try:
        await asyncio.to_thread(_stitch_sync, chunks_dir, stitched)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "live_stitch_failed",
            extra={
                "recording_id_prefix": recording_id[:8],
                "error_type": type(exc).__name__,
            },
        )
        return

    try:
        await _run_pipeline(recording_id, stitched, scenario, language)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "live_consolidate_pipeline_failed",
            extra={
                "recording_id_prefix": recording_id[:8],
                "error_type": type(exc).__name__,
            },
        )


def _stitch_sync(chunks_dir: Path, dest: Path) -> None:
    """Concatenate every chunk-*.* file into a single 16 kHz mono WAV.

    Uses librosa to decode each chunk (handles whatever container the browser
    emitted), then writes the concatenated samples as PCM_16 via soundfile.
    """
    import librosa  # type: ignore
    import numpy as np
    import soundfile as sf  # type: ignore

    chunks = sorted(chunks_dir.glob("chunk-*"))
    if not chunks:
        raise RuntimeError("no_chunks_to_stitch")

    samples: List[Any] = []
    for path in chunks:
        audio, _sr = librosa.load(str(path), sr=16000, mono=True)
        samples.append(audio)
    full = np.concatenate(samples) if samples else np.zeros(0, dtype="float32")
    dest.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dest), full, 16000, subtype="PCM_16")


__all__ = ["router"]
