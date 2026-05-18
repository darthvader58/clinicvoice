"""FastAPI routes for clinicvoice — all 8 endpoints under ``/api``.

CRITICAL CONTRACTS
==================
* Responses never carry raw transcripts. ``raw_text`` dies at the redaction
  boundary in ``src.redact.engine``; only ``redacted_text`` + ``redaction_map``
  are surfaced.
* Request bodies, headers, and query params are never logged here (the
  ``PHIFreeLoggingMiddleware`` is the only thing that logs the request edge).
* Heavy pipeline work (normalize → separate → diarize → ASR → normalize_text
  → redact → escalate → metrics → persist) runs in a background task. The
  ``/api/upload`` endpoint persists a ``Recording`` row synchronously and
  returns immediately with ``status="processing"``.
* Downstream modules (ingest/diarize/asr/redact/escalation/metrics) are
  imported lazily inside the pipeline task so this file imports cleanly even
  when other agents' modules are still landing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings

logger = logging.getLogger("clinicvoice.api.routes")

router = APIRouter(prefix="/api")

VERSION = "0.1.0"

# ---------------------------------------------------------------------------#
# Module-loaded flags (best-effort — used by /api/health).
# ---------------------------------------------------------------------------#
def _flag(modname: str) -> bool:
    try:
        __import__(modname)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------#
# Lightweight in-process progress map. The DB is the source of truth for
# state that needs to survive a restart; this map exists so /api/status can
# show progress for an in-flight upload.
# ---------------------------------------------------------------------------#
_PROGRESS: dict[str, dict[str, Any]] = {}


def _set_progress(recording_id: str, **fields: Any) -> None:
    state = _PROGRESS.setdefault(recording_id, {})
    state.update(fields)


# ---------------------------------------------------------------------------#
# Response models — kept small and JSON-friendly.
# ---------------------------------------------------------------------------#
class UploadResponse(BaseModel):
    recording_id: str
    status: str = "processing"
    track_mode: str = "pending"


class StatusResponse(BaseModel):
    recording_id: str
    status: str
    progress: float = Field(ge=0.0, le=1.0, default=0.0)
    track_mode: str | None = None
    si_sdr: float | None = None
    stage: str | None = None


class TranscriptSegmentOut(BaseModel):
    segment_id: str
    speaker_id: str
    start_ts: float
    end_ts: float
    confidence: str
    language_tag: str
    overlap_flag: bool
    stem_used: bool
    redacted_text: str
    redacted_text_roman: str | None = None
    redaction_map: list[dict[str, Any]] = Field(default_factory=list)


class TranscriptResponse(BaseModel):
    recording_id: str
    track_mode: str | None
    si_sdr: float | None
    segments: list[TranscriptSegmentOut]


class MetricsResponse(BaseModel):
    recording_id: str
    wer: float | None = None
    medical_ter: float | None = None
    der_proxy: float | None = None
    si_sdr: float | None = None
    speaker_count: int | None = None
    segment_count: int | None = None
    track_mode: str | None = None
    run_at: str | None = None


class HealthResponse(BaseModel):
    status: str
    whisper_loaded: bool
    pyannote_loaded: bool
    asteroid_loaded: bool
    version: str = VERSION


# ---------------------------------------------------------------------------#
# DB session dependency — imported lazily because src.db.session is owned
# by ALPHA and may not exist while this file is being authored.
# ---------------------------------------------------------------------------#
async def get_db() -> AsyncSession:  # pragma: no cover - thin shim
    from src.db.session import get_db as _real_get_db  # type: ignore

    async for session in _real_get_db():
        yield session


# ---------------------------------------------------------------------------#
# POST /api/upload
# ---------------------------------------------------------------------------#
SUPPORTED_LANGUAGES = {"en", "hi", "ur", "ta", "id", "ms", "auto"}


@router.post("/upload", response_model=UploadResponse)
async def upload_recording(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    scenario: str = Form("unknown"),
    language: str = Form("auto"),
) -> UploadResponse:
    """Accept an audio upload and kick off the pipeline asynchronously.

    The request returns quickly with ``status="processing"``. Progress can be
    polled via ``GET /api/status/{recording_id}``.
    """
    if scenario not in {"hallway", "consult", "unknown"}:
        raise HTTPException(status_code=422, detail="invalid_scenario")
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="invalid_language")

    # Stream the upload to disk; never inspect or log its bytes.
    storage = Path(settings.AUDIO_STORAGE_PATH)
    storage.mkdir(parents=True, exist_ok=True)
    recording_id = str(uuid4())
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    dest = storage / f"{recording_id}{suffix}"

    sha = hashlib.sha256()
    size_bytes = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1 << 20)  # 1 MiB
                if not chunk:
                    break
                sha.update(chunk)
                out.write(chunk)
                size_bytes += len(chunk)
    finally:
        await file.close()

    if size_bytes == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="empty_file")

    file_hash = sha.hexdigest()

    # Persist the Recording row immediately (Option A/B unknown until the
    # separator runs; track_mode stays NULL until then).
    try:
        from src.db.models import Recording
        from src.db.session import AsyncSessionLocal  # type: ignore

        async with AsyncSessionLocal() as session:
            recording = Recording(
                id=recording_id,
                file_hash=file_hash,
                scenario=scenario,
                retention_ttl=settings.AUDIO_RETENTION_TTL_S,
            )
            session.add(recording)
            await session.commit()
    except Exception as exc:  # pragma: no cover - DB shim may be absent in tests
        logger.warning(
            "recording_insert_failed",
            extra={"recording_id_prefix": recording_id[:8], "error_type": type(exc).__name__},
        )

    _set_progress(
        recording_id,
        status="processing",
        progress=0.05,
        track_mode=None,
        si_sdr=None,
        stage="queued",
    )

    background_tasks.add_task(_run_pipeline, recording_id, dest, scenario, language)

    return UploadResponse(recording_id=recording_id, status="processing", track_mode="pending")


# ---------------------------------------------------------------------------#
# Pipeline orchestrator — runs in a BackgroundTask.
# ---------------------------------------------------------------------------#
async def _run_pipeline(
    recording_id: str, audio_path: Path, scenario: str, language: str = "auto"
) -> None:
    """End-to-end orchestration with full PHI discipline.

    Steps: normalize → separate → diarize → transcribe → normalize_text →
    redact → escalate → metrics → persist. Every step is wrapped so a single
    failure does not crash the worker.
    """
    try:
        _set_progress(recording_id, stage="normalize", progress=0.1)
        from src.ingest.normalizer import normalize_audio

        normalized = await normalize_audio(audio_path, scenario)

        _set_progress(recording_id, stage="separate", progress=0.25)
        try:
            from src.ingest.separator import separate_speakers  # type: ignore

            separation = await separate_speakers(
                normalized, settings, Path(settings.AUDIO_STORAGE_PATH)
            )
            track_mode = separation.track_mode
            si_sdr = separation.si_sdr_max
        except Exception as exc:
            logger.warning(
                "separator_unavailable_falling_back_option_b",
                extra={"error_type": type(exc).__name__},
            )
            track_mode = "option_b_single"
            si_sdr = 0.0
            separation = None

        _set_progress(recording_id, track_mode=track_mode, si_sdr=si_sdr)

        _set_progress(recording_id, stage="diarize", progress=0.45)
        from src.diarize.engine import diarize_audio  # type: ignore

        diar = await diarize_audio(
            audio_path=normalized.path,
            separation=separation,
            max_speakers=settings.MAX_SPEAKERS,
            settings=settings,
            recording_id=recording_id,
        )

        # If only one speaker was diarized, ConvTasNet stems are noise/artifacts
        # rather than real isolations. Strip stem_paths so ASR decodes the
        # original audio — Option A still "ran" per spec, but we don't feed
        # fabricated stems into Whisper.
        unique_speakers = {
            getattr(t, "speaker_id", None)
            for t in diar.turns
            if getattr(t, "speaker_id", None) not in (None, "OVERLAP")
        }
        if len(unique_speakers) <= 1 and separation is not None:
            logger.info(
                "skipping_stems_single_speaker",
                extra={"recording_id_prefix": recording_id[:8]},
            )
            diar = diar.model_copy(
                update={
                    "turns": [t.model_copy(update={"stem_path": None}) for t in diar.turns]
                }
            )

        _set_progress(recording_id, stage="asr", progress=0.6)
        from src.asr.engine import WhisperEngine  # type: ignore
        from src.asr.lexicon import MedicalLexicon  # type: ignore

        whisper = WhisperEngine(settings)
        lexicon = MedicalLexicon.load(settings.MEDICAL_LEXICON_PATH)
        asr_segments = await whisper.transcribe_recording(
            normalized_audio=normalized,
            diarization=diar,
            lexicon=lexicon,
            recording_id=recording_id,
            language=language,
        )

        # Per-segment: normalize → redact → escalate → persist.
        _set_progress(recording_id, stage="postprocess", progress=0.75)
        from src.normalize.confidence import compute_confidence  # type: ignore
        from src.redact.engine import redact  # type: ignore

        # Escalation is optional in early test runs.
        try:
            from src.escalation.engine import EscalationEngine  # type: ignore

            escalation = EscalationEngine(
                watchlist_path=Path("src/escalation/watchlist.json")
            )
        except Exception:
            escalation = None

        try:
            from src.normalize.acronyms import expand_acronyms  # type: ignore
            from src.normalize.casing import apply_casing  # type: ignore
            from src.normalize.units import normalize_units  # type: ignore
        except Exception:
            expand_acronyms = apply_casing = normalize_units = None  # type: ignore

        from src.db.models import EscalationEvent, Segment, TranscriptSpan
        from src.db.session import AsyncSessionLocal  # type: ignore

        async with AsyncSessionLocal() as session:
            for asr in asr_segments:
                text = asr.raw_text
                lang = (
                    asr.language_tag.value
                    if hasattr(asr.language_tag, "value")
                    else str(asr.language_tag)
                )

                # English-only text normalization (CLAUDE.md rule).
                if lang == "en" and expand_acronyms and normalize_units and apply_casing:
                    try:
                        text = expand_acronyms(text)
                        text = normalize_units(text)
                        text = apply_casing(text)
                    except Exception as exc:
                        logger.warning(
                            "text_normalize_failed",
                            extra={"error_type": type(exc).__name__},
                        )

                # Confidence (all languages).
                try:
                    conf = compute_confidence(
                        whisper_avg_logprob=asr.whisper_avg_logprob,
                        no_speech_prob=asr.no_speech_prob,
                        overlap=bool(getattr(asr, "overlap_flag", False)),
                        segment_duration=asr.end_ts - asr.start_ts,
                        stem_used=asr.stem_used,
                    )
                except Exception:
                    conf = asr.confidence

                # ⚠ REDACTION BOUNDARY ⚠ — raw_text dies here.
                redacted_text, redaction_map = redact(text, lang)
                redaction_map_json = json.dumps(
                    [span.model_dump() for span in redaction_map]
                )

                segment = Segment(
                    id=asr.id,
                    recording_id=recording_id,
                    speaker_id=asr.speaker_id,
                    start_ts=asr.start_ts,
                    end_ts=asr.end_ts,
                    confidence=conf,
                    language_tag=lang,
                    overlap_flag=int(getattr(asr, "overlap_flag", False)),
                    stem_used=int(asr.stem_used),
                )
                span = TranscriptSpan(
                    segment_id=segment.id,
                    redacted_text=redacted_text,
                    redaction_map=redaction_map_json,
                    word_count=len(redacted_text.split()),
                    char_count=len(redacted_text),
                )
                session.add_all([segment, span])
                await session.flush()

                # Escalation runs only on non-low confidence — engine enforces, too.
                if escalation is not None:
                    try:
                        events, _memory, _handoff = escalation.process_segment(
                            segment_id=segment.id,
                            recording_id=recording_id,
                            speaker_id=asr.speaker_id,
                            redacted_text=redacted_text,
                            confidence=conf,
                            scenario=scenario,
                            start_ts=asr.start_ts,
                        )
                        for evt in events or []:
                            session.add(
                                EscalationEvent(
                                    recording_id=recording_id,
                                    segment_id=segment.id,
                                    event_type=evt.event_type,
                                    watchlist_term=evt.watchlist_term,
                                    speaker_id=asr.speaker_id,
                                    confidence=conf,
                                )
                            )
                    except Exception as exc:
                        logger.warning(
                            "escalation_failed",
                            extra={"error_type": type(exc).__name__},
                        )

            # Update Recording with final track_mode + speaker_count.
            from src.db.models import Recording as _Recording

            rec = await session.get(_Recording, recording_id)
            if rec is not None:
                rec.track_mode = track_mode
                rec.si_sdr = si_sdr
                rec.duration_s = normalized.duration_s
                rec.speaker_count = len({s.speaker_id for s in asr_segments})
            await session.commit()

        # Metrics — persist what we can compute without ground truth.
        # WER / MTER / DER need a reference transcript; for a live recording
        # we only have SI-SDR + counts. The benchmark script fills in the
        # ground-truth-based numbers separately.
        try:
            from datetime import datetime, timezone

            from src.db.models import MetricsRun

            async with AsyncSessionLocal() as session:
                session.add(
                    MetricsRun(
                        recording_id=recording_id,
                        wer=None,
                        medical_ter=None,
                        der_proxy=None,
                        si_sdr=si_sdr,
                        speaker_count=len(unique_speakers),
                        segment_count=len(asr_segments),
                        track_mode=track_mode,
                        run_at=datetime.now(timezone.utc).isoformat(),
                        report_path=None,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.info(
                "metrics_skipped",
                extra={"error_type": type(exc).__name__},
            )

        _set_progress(recording_id, status="done", stage="done", progress=1.0)

    except Exception as exc:  # pragma: no cover - last-ditch guard
        logger.error(
            "pipeline_failed",
            extra={
                "recording_id_prefix": recording_id[:8],
                "error_type": type(exc).__name__,
            },
        )
        _set_progress(recording_id, status="error", stage="error", progress=1.0)


# ---------------------------------------------------------------------------#
# GET /api/status/{recording_id}
# ---------------------------------------------------------------------------#
@router.get("/status/{recording_id}", response_model=StatusResponse)
async def get_status(recording_id: str) -> StatusResponse:
    """Return current pipeline state for a recording."""
    prog = _PROGRESS.get(recording_id, {})

    track_mode = prog.get("track_mode")
    si_sdr = prog.get("si_sdr")
    status_val = prog.get("status", "unknown")

    # If we don't have an in-memory entry, fall back to the DB.
    if not prog:
        try:
            from src.db.models import Recording
            from src.db.session import AsyncSessionLocal  # type: ignore

            async with AsyncSessionLocal() as session:
                rec = await session.get(Recording, recording_id)
                if rec is None:
                    raise HTTPException(status_code=404, detail="recording_not_found")
                track_mode = rec.track_mode
                si_sdr = rec.si_sdr
                status_val = "done" if rec.track_mode else "processing"
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=404, detail="recording_not_found")

    return StatusResponse(
        recording_id=recording_id,
        status=status_val,
        progress=float(prog.get("progress", 1.0 if status_val == "done" else 0.0)),
        track_mode=track_mode,
        si_sdr=si_sdr,
        stage=prog.get("stage"),
    )


# ---------------------------------------------------------------------------#
# GET /api/transcript/{recording_id}
# ---------------------------------------------------------------------------#
@router.get("/transcript/{recording_id}", response_model=TranscriptResponse)
async def get_transcript(recording_id: str) -> TranscriptResponse:
    """Return the redacted transcript for a recording.

    NEVER returns ``raw_text`` — only ``redacted_text`` + ``redaction_map``.
    """
    try:
        from src.db.models import Recording, Segment, TranscriptSpan
        from src.db.session import AsyncSessionLocal  # type: ignore
    except Exception:
        raise HTTPException(status_code=503, detail="db_unavailable")

    async with AsyncSessionLocal() as session:
        rec = await session.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recording_not_found")

        stmt = (
            select(Segment, TranscriptSpan)
            .join(TranscriptSpan, TranscriptSpan.segment_id == Segment.id)
            .where(Segment.recording_id == recording_id)
            .order_by(Segment.start_ts)
        )
        rows = (await session.execute(stmt)).all()

        from src.normalize.romanize import to_roman
        from src.redact.engine import redact as _redact

        segs: list[TranscriptSegmentOut] = []
        for seg, span in rows:
            try:
                redaction_map = json.loads(span.redaction_map) if span.redaction_map else []
            except Exception:
                redaction_map = []

            redacted_roman = to_roman(span.redacted_text, seg.language_tag)
            # Dual-pass: the stored redacted_text was produced with the
            # segment's language, which means Presidio NER ran only for EN.
            # For non-EN segments we re-run the EN-NER pass over the
            # romanized text so names and Latin-script PHI get caught for
            # the displayed transcript. Digit-run collapse first so phone
            # numbers spoken digit-by-digit ("9 6 5 9 2 9") become a single
            # token the recognizers can match.
            if redacted_roman and seg.language_tag != "en":
                try:
                    from src.normalize.digits import collapse_digit_runs

                    extra_redacted, extra_map = _redact(
                        collapse_digit_runs(redacted_roman), "en"
                    )
                    if extra_map:
                        redacted_roman = extra_redacted
                except Exception:
                    pass

            segs.append(
                TranscriptSegmentOut(
                    segment_id=seg.id,
                    speaker_id=seg.speaker_id,
                    start_ts=seg.start_ts,
                    end_ts=seg.end_ts,
                    confidence=seg.confidence,
                    language_tag=seg.language_tag,
                    overlap_flag=bool(seg.overlap_flag),
                    stem_used=bool(seg.stem_used),
                    redacted_text=span.redacted_text,
                    redacted_text_roman=redacted_roman,
                    redaction_map=redaction_map,
                )
            )

        return TranscriptResponse(
            recording_id=recording_id,
            track_mode=rec.track_mode,
            si_sdr=rec.si_sdr,
            segments=segs,
        )


# ---------------------------------------------------------------------------#
# GET /api/metrics/{recording_id}
# ---------------------------------------------------------------------------#
@router.get("/metrics/{recording_id}", response_model=MetricsResponse)
async def get_metrics(recording_id: str) -> MetricsResponse:
    """Return the most recent MetricsRun for a recording."""
    try:
        from src.db.models import MetricsRun
        from src.db.session import AsyncSessionLocal  # type: ignore
    except Exception:
        raise HTTPException(status_code=503, detail="db_unavailable")

    async with AsyncSessionLocal() as session:
        stmt = (
            select(MetricsRun)
            .where(MetricsRun.recording_id == recording_id)
            .order_by(MetricsRun.run_at.desc())
        )
        row = (await session.execute(stmt)).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="metrics_not_found")
        return MetricsResponse(
            recording_id=recording_id,
            wer=row.wer,
            medical_ter=row.medical_ter,
            der_proxy=row.der_proxy,
            si_sdr=row.si_sdr,
            speaker_count=row.speaker_count,
            segment_count=row.segment_count,
            track_mode=row.track_mode,
            run_at=row.run_at,
        )


# ---------------------------------------------------------------------------#
# GET /api/escalation/{recording_id}
# ---------------------------------------------------------------------------#
@router.get("/escalation/{recording_id}")
async def get_escalation(recording_id: str) -> JSONResponse:
    """Return all escalation events / memory candidates / handoff notes."""
    try:
        from src.db.models import EscalationEvent
        from src.db.session import AsyncSessionLocal  # type: ignore
    except Exception:
        raise HTTPException(status_code=503, detail="db_unavailable")

    async with AsyncSessionLocal() as session:
        stmt = (
            select(EscalationEvent)
            .where(EscalationEvent.recording_id == recording_id)
            .order_by(EscalationEvent.triggered_at)
        )
        rows = (await session.execute(stmt)).scalars().all()
        events: list[dict[str, Any]] = []
        memory: list[dict[str, Any]] = []
        handoff: list[dict[str, Any]] = []
        for r in rows:
            payload = {
                "id": r.id,
                "segment_id": r.segment_id,
                "event_type": r.event_type,
                "watchlist_term": r.watchlist_term,
                "speaker_id": r.speaker_id,
                "confidence": r.confidence,
                "triggered_at": r.triggered_at,
                "resolved": bool(r.resolved),
            }
            if r.event_type.startswith("escalation"):
                events.append(payload)
            elif r.event_type == "memory_candidate":
                memory.append(payload)
            elif r.event_type == "handoff_note":
                handoff.append(payload)
        return JSONResponse(
            {
                "recording_id": recording_id,
                "events": events,
                "memory_candidates": memory,
                "handoff_notes": handoff,
            }
        )


# ---------------------------------------------------------------------------#
# POST /api/corrections/{recording_id}
# ---------------------------------------------------------------------------#
class CorrectionIn(BaseModel):
    term: str
    correction: str
    language: str = "en"


@router.post("/corrections/{recording_id}")
async def post_correction(recording_id: str, payload: CorrectionIn) -> JSONResponse:
    """Add a lexicon correction and (best-effort) recompute MTER for the recording."""
    try:
        from src.asr.lexicon import MedicalLexicon  # type: ignore

        lexicon = MedicalLexicon.load()
        lexicon.add_correction(payload.term, payload.correction, language=payload.language)
        lexicon.save()
    except Exception as exc:
        logger.warning(
            "correction_save_failed",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=503, detail="lexicon_unavailable")

    new_mter: float | None = None
    try:
        from src.metrics.report import MetricsReporter  # type: ignore

        run = await MetricsReporter().run_for_recording(recording_id)
        new_mter = getattr(run, "medical_ter", None)
    except Exception:
        new_mter = None

    return JSONResponse(
        {
            "recording_id": recording_id,
            "term": payload.term,
            "correction": payload.correction,
            "language": payload.language,
            "medical_ter": new_mter,
        }
    )


# ---------------------------------------------------------------------------#
# GET /api/benchmark
# ---------------------------------------------------------------------------#
@router.get("/benchmark")
async def get_benchmark() -> JSONResponse:
    """Return the benchmark report produced by ``scripts/benchmark.py``."""
    path = Path(settings.REPORTS_PATH) / "benchmark_results.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="benchmark_not_run")
    try:
        data = json.loads(path.read_text())
    except Exception:
        raise HTTPException(status_code=500, detail="benchmark_unreadable")
    return JSONResponse(data)


# ---------------------------------------------------------------------------#
# GET /api/health
# ---------------------------------------------------------------------------#
@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Lightweight liveness + dependency check.

    The model flags are best-effort: ``True`` if the import succeeds, which
    implies the model can be loaded on demand. We do not eagerly load models
    here — that would defeat the lazy-load pattern used elsewhere.
    """
    return HealthResponse(
        status="ok",
        whisper_loaded=_flag("whisper"),
        pyannote_loaded=_flag("pyannote.audio"),
        asteroid_loaded=_flag("asteroid"),
        version=VERSION,
    )


__all__ = ["router"]
