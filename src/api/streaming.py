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

# Auto-detect thresholds. < DROP -> chunk emits empty text (likely silence
# or undetectable noise). > LOCK -> language is fixed for the rest of the
# session, suppressing detection drift across short chunks.
LANG_DROP_THRESHOLD = 0.5
LANG_LOCK_THRESHOLD = 0.7

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
    redacted_text_roman: Optional[str] = None
    language_tag: str
    language_locked: bool = False  # True if session is now sticky-locked to this lang
    language_source: str = "auto"  # "user" | "locked" | "detected" | "silence"
    redaction_count: int
    duration_s: float
    dropped: bool = False  # True when silent or low-conf detection muted this chunk


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
        "locked_language": None,  # set after first confident auto-detection
        "next_seq": 0,
        "chunks_dir": chunks_dir,
        "lock": asyncio.Lock(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        # Running cursor over the session's audio timeline. Each persisted
        # Segment uses this as its start_ts and bumps by the chunk's duration.
        "ts_cursor": 0.0,
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
    language: Optional[str] = Form(None),
) -> ChunkResponse:
    sess = _session(recording_id)
    seq = sess["next_seq"]
    sess["next_seq"] = seq + 1

    # Mid-session language change from the UI clears the sticky lock and
    # updates the session's user-language hint.
    if language is not None and language in SUPPORTED_LANGUAGES and language != sess["language"]:
        logger.info(
            "live_language_changed",
            extra={
                "recording_id_prefix": recording_id[:8],
                "old": sess["language"],
                "new": language,
            },
        )
        sess["language"] = language
        sess["locked_language"] = None

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

    # User-forced language always wins; otherwise reuse the locked language
    # from the first confident detection in this session.
    user_lang = sess["language"]
    language_source = "user"
    effective_language = user_lang
    if effective_language == "auto":
        if sess.get("locked_language"):
            effective_language = sess["locked_language"]
            language_source = "locked"
        else:
            language_source = "detected"

    # openai-whisper is not thread-safe; serialize per session.
    async with sess["lock"]:
        try:
            (
                redacted_text,
                redacted_text_roman,
                redaction_count,
                language_tag,
                duration_s,
                dropped,
                lock_now,
            ) = await asyncio.to_thread(
                _decode_chunk_sync, chunk_path, effective_language
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

        if lock_now and sess.get("locked_language") is None:
            sess["locked_language"] = language_tag
            language_source = "locked"
            logger.info(
                "live_language_locked",
                extra={
                    "recording_id_prefix": recording_id[:8],
                    "language_tag": language_tag,
                },
            )

    # Pure RMS-silence drops surface "unknown" language with dropped=True;
    # tag them distinctly so the UI can show "silence" instead of "auto".
    if dropped and language_tag == "unknown":
        language_source = "silence"

    language_locked = bool(sess.get("locked_language")) and user_lang == "auto"

    # Persist non-empty chunks to the DB now (not at consolidation) so the
    # canonical transcript is identical to what the user saw live. The
    # consolidation pass only stitches audio + updates metadata after this.
    start_ts = sess["ts_cursor"]
    end_ts = start_ts + duration_s
    sess["ts_cursor"] = end_ts
    if not dropped and redacted_text:
        await _persist_live_segment(
            recording_id=recording_id,
            start_ts=start_ts,
            end_ts=end_ts,
            language_tag=language_tag,
            redacted_text=redacted_text,
        )

    logger.info(
        "live_chunk_decoded",
        extra={
            "recording_id_prefix": recording_id[:8],
            "seq": seq,
            "duration_s": round(duration_s, 2),
            "language_tag": language_tag,
            "language_source": language_source,
            "language_locked": language_locked,
            "redaction_count": redaction_count,
            "dropped": dropped,
        },
    )
    return ChunkResponse(
        recording_id=recording_id,
        seq=seq,
        redacted_text=redacted_text,
        redacted_text_roman=redacted_text_roman,
        language_tag=language_tag,
        language_locked=language_locked,
        language_source=language_source,
        redaction_count=redaction_count,
        duration_s=duration_s,
        dropped=dropped,
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
) -> tuple[str, Optional[str], int, str, float, bool, bool]:
    """Decode a single chunk: ffmpeg/librosa -> Whisper -> redact -> romanize.

    Returns
    -------
    redacted_text : str
        Canonical redacted text in the detected script (may be empty when
        the chunk was dropped for low confidence).
    redacted_text_roman : str | None
        Latin/ASCII transliteration for UI display; None for English /
        already-Latin scripts and for dropped chunks.
    redaction_count : int
        Number of PHI spans redacted.
    language_tag : str
        ISO code of the resolved language ("en", "hi", ...) or "unknown".
    duration_s : float
        Audio duration of this chunk.
    dropped : bool
        True if low-confidence auto-detect muted this chunk.
    lock_now : bool
        True if the caller should lock this language for the session.
    """
    import librosa  # type: ignore
    import numpy as np  # type: ignore
    import whisper as _whisper  # type: ignore

    from src.asr.engine import WhisperEngine
    from src.normalize.romanize import to_roman
    from src.redact.engine import redact

    audio, _sr = librosa.load(str(chunk_path), sr=16000, mono=True)
    duration_s = float(len(audio)) / 16000.0

    # Hard silence gate — Whisper's no_speech_threshold isn't enough; it still
    # invents text on quiet clips. RMS check below ~-46 dBFS means the chunk
    # is effectively silent, so skip the model entirely and emit nothing.
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size > 0 else 0.0
    if rms < 0.005:
        return "", None, 0, language if language and language != "auto" else "unknown", duration_s, True, False

    engine = WhisperEngine.get_instance(settings)
    model = engine._model  # noqa: SLF001

    detected_lang: Optional[str] = None
    lang_prob = 1.0
    user_forced = bool(language) and language != "auto"
    if user_forced:
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

        # Drop chunk if detection is too uncertain — better empty than
        # hallucinated Polish/Russian on a Hindi clip.
        if lang_prob < LANG_DROP_THRESHOLD:
            return "", None, 0, detected_lang or "unknown", duration_s, True, False

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
    # Collapse "9 6 5 9 2 9"-style digit runs first so the phone / ID
    # recognizers see "965929" and actually fire.
    from src.normalize.digits import collapse_digit_runs

    raw_text = collapse_digit_runs(raw_text)
    redact_lang = lang_tag if lang_tag in {"en", "hi", "ur", "ta", "id", "ms"} else "en"
    redacted_text, redaction_map = redact(raw_text, redact_lang)
    redaction_count = len(redaction_map)
    redacted_roman = to_roman(redacted_text, lang_tag)

    # Dual-pass: the first call ran pattern recognizers + English NER only
    # when lang == 'en'. For non-English chunks we additionally run the
    # English-NER pass over the romanized text to catch Latin-script PHI
    # the first pass couldn't see (names, English-script numbers spoken
    # into Hindi/Urdu/Tamil audio).
    if redacted_roman and lang_tag != "en":
        roman_redacted, roman_map = redact(
            collapse_digit_runs(redacted_roman), "en"
        )
        if roman_map:
            redacted_roman = roman_redacted
            redaction_count += len(roman_map)

    lock_now = (not user_forced) and lang_prob >= LANG_LOCK_THRESHOLD
    return (
        redacted_text,
        redacted_roman,
        redaction_count,
        lang_tag,
        duration_s,
        False,
        lock_now,
    )


# --------------------------------------------------------------------------- #
# Per-chunk DB persistence.
#
# Each live chunk's decode is written to the canonical Segment +
# TranscriptSpan tables immediately so consolidation can't drift away from
# what the user already saw on screen.
# --------------------------------------------------------------------------- #
async def _persist_live_segment(
    *,
    recording_id: str,
    start_ts: float,
    end_ts: float,
    language_tag: str,
    redacted_text: str,
) -> None:
    import json as _json
    from uuid import uuid4

    from src.db.models import Segment, TranscriptSpan  # type: ignore
    from src.db.session import AsyncSessionLocal  # type: ignore

    try:
        async with AsyncSessionLocal() as session:
            seg = Segment(
                id=str(uuid4()),
                recording_id=recording_id,
                speaker_id="S1",
                start_ts=float(start_ts),
                end_ts=float(end_ts),
                confidence="med",
                language_tag=language_tag,
                overlap_flag=0,
                stem_used=0,
            )
            span = TranscriptSpan(
                segment_id=seg.id,
                redacted_text=redacted_text,
                redaction_map=_json.dumps([]),
                word_count=len(redacted_text.split()),
                char_count=len(redacted_text),
            )
            session.add_all([seg, span])
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "live_segment_persist_failed",
            extra={
                "recording_id_prefix": recording_id[:8],
                "error_type": type(exc).__name__,
            },
        )


# --------------------------------------------------------------------------- #
# Consolidation — single-speaker live-mode path.
#
# We intentionally do NOT run the full Option A pipeline (ConvTasNet +
# pyannote) on live-stitched audio. The live recorder captures one mic /
# one speaker; ConvTasNet trained on Libri2Mix fabricates noise stems on
# single-speaker audio, and energy-fallback diarization over-splits the
# stream into S1/S2/S3 producing 1-second turns full of Whisper
# hallucinations (the "KwiJeuonian / rophamaAiMaJwim Blue" effect).
#
# Instead we re-transcribe the stitched audio once with Whisper, redact
# the same way the live ticker did, and persist as a single-speaker
# (`option_b_single`) recording. The canonical transcript ends up
# matching what the user already saw live.
# --------------------------------------------------------------------------- #
async def _consolidate(
    recording_id: str, chunks_dir: Path, _scenario: str, _language: str
) -> None:
    """Thin consolidation: stitch audio, update recording metadata, write
    metrics. The transcript is already in the DB from per-chunk persistence
    in :func:`_persist_live_segment`, so we do NOT re-run Whisper here — that
    used to produce slightly different tokenization than the live chunks
    and degraded redaction accuracy.
    """
    from src.api.routes import _set_progress

    _set_progress(
        recording_id,
        status="processing",
        progress=0.7,
        stage="consolidating",
        track_mode="option_b_single",
    )

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
        _set_progress(recording_id, status="error", stage="error", progress=1.0)
        return

    try:
        await _finalize_live_recording(recording_id, stitched)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "live_consolidate_finalize_failed",
            extra={
                "recording_id_prefix": recording_id[:8],
                "error_type": type(exc).__name__,
            },
        )
        _set_progress(recording_id, status="error", stage="error", progress=1.0)
        return

    _set_progress(
        recording_id,
        status="done",
        stage="done",
        progress=1.0,
        track_mode="option_b_single",
    )
    logger.info(
        "live_consolidation_done",
        extra={"recording_id_prefix": recording_id[:8]},
    )


async def _finalize_live_recording(recording_id: str, stitched_path: Path) -> None:
    """Update Recording with stitched-audio metadata and write a metrics row.

    Transcript rows are already in place from per-chunk persistence; this
    only touches Recording + MetricsRun.
    """
    import hashlib
    from datetime import datetime, timezone

    from sqlalchemy import func, select as _select

    from src.db.models import MetricsRun, Recording, Segment  # type: ignore
    from src.db.session import AsyncSessionLocal  # type: ignore

    file_hash = hashlib.sha256(stitched_path.read_bytes()).hexdigest()

    import soundfile as sf  # type: ignore

    info = sf.info(str(stitched_path))
    duration_s = float(info.frames) / float(info.samplerate)

    async with AsyncSessionLocal() as session:
        seg_count_row = await session.execute(
            _select(func.count(Segment.id)).where(
                Segment.recording_id == recording_id
            )
        )
        seg_count = int(seg_count_row.scalar_one() or 0)

        rec = await session.get(Recording, recording_id)
        if rec is not None:
            rec.file_hash = file_hash
            rec.duration_s = duration_s
            rec.track_mode = "option_b_single"
            rec.si_sdr = None
            rec.speaker_count = 1

        session.add(
            MetricsRun(
                recording_id=recording_id,
                wer=None,
                medical_ter=None,
                der_proxy=None,
                si_sdr=None,
                speaker_count=1,
                segment_count=seg_count,
                track_mode="option_b_single",
                run_at=datetime.now(timezone.utc).isoformat(),
                report_path=None,
            )
        )
        await session.commit()


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
