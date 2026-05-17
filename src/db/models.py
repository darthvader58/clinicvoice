"""SQLAlchemy 2.0 ORM models for clinicvoice.

Six tables: Recording, AudioAsset, Segment, TranscriptSpan,
EscalationEvent, MetricsRun.

INVARIANT: `TranscriptSpan` has NO `raw_text` column. Only
`redacted_text` + `redaction_map` are persisted. Raw transcript
strings live in process memory and die at the redaction boundary.

INVARIANT: No PHI lives in any column. Watchlist terms, hashed IDs,
durations, and counts are safe; free-form patient text is not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import Float


def _uuid() -> str:
    return str(uuid4())


def _utc_iso() -> str:
    """ISO-8601 UTC timestamp string (DB-agnostic)."""
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    """Declarative base for all clinicvoice ORM models."""


# --------------------------------------------------------------------------- #
# Recording — one row per uploaded/recorded session
# --------------------------------------------------------------------------- #
class Recording(Base):
    __tablename__ = "recording"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_utc_iso)
    file_hash: Mapped[str] = mapped_column(String, nullable=False)  # SHA-256 of original bytes
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    scenario: Mapped[str | None] = mapped_column(String, nullable=True)  # 'hallway' | 'consult'
    track_mode: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # 'option_a_stems' | 'option_b_single'
    si_sdr: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_ttl: Mapped[int] = mapped_column(Integer, nullable=False, default=86400)
    purged_at: Mapped[str | None] = mapped_column(String, nullable=True)

    # relationships (no cascade-delete — retention task handles purging explicitly)
    assets: Mapped[list["AudioAsset"]] = relationship(
        "AudioAsset", back_populates="recording"
    )
    segments: Mapped[list["Segment"]] = relationship(
        "Segment", back_populates="recording"
    )
    escalations: Mapped[list["EscalationEvent"]] = relationship(
        "EscalationEvent", back_populates="recording"
    )
    metrics: Mapped[list["MetricsRun"]] = relationship(
        "MetricsRun", back_populates="recording"
    )


# --------------------------------------------------------------------------- #
# AudioAsset — source, normalized, and per-speaker stems
# --------------------------------------------------------------------------- #
class AudioAsset(Base):
    __tablename__ = "audio_asset"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    recording_id: Mapped[str] = mapped_column(
        String, ForeignKey("recording.id"), nullable=False, index=True
    )
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_type: Mapped[str] = mapped_column(
        String, nullable=False, default="source"
    )  # 'source' | 'normalized' | 'stem'
    speaker_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # NULL for source/normalized; 'S1','S2' for stems
    format: Mapped[str | None] = mapped_column(String, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)

    recording: Mapped["Recording"] = relationship("Recording", back_populates="assets")


# --------------------------------------------------------------------------- #
# Segment — diarized + ASR'd window
# --------------------------------------------------------------------------- #
class Segment(Base):
    __tablename__ = "segment"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    recording_id: Mapped[str] = mapped_column(
        String, ForeignKey("recording.id"), nullable=False, index=True
    )
    speaker_id: Mapped[str] = mapped_column(String, nullable=False)
    start_ts: Mapped[float] = mapped_column(Float, nullable=False)
    end_ts: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[str] = mapped_column(String, nullable=False)  # 'low'|'med'|'high'
    language_tag: Mapped[str] = mapped_column(String, nullable=False)  # BCP-47 or 'unknown'
    overlap_flag: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stem_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    recording: Mapped["Recording"] = relationship("Recording", back_populates="segments")
    spans: Mapped[list["TranscriptSpan"]] = relationship(
        "TranscriptSpan", back_populates="segment"
    )
    escalations: Mapped[list["EscalationEvent"]] = relationship(
        "EscalationEvent", back_populates="segment"
    )


# --------------------------------------------------------------------------- #
# TranscriptSpan — redacted text + redaction map only. NO raw_text.
# --------------------------------------------------------------------------- #
class TranscriptSpan(Base):
    __tablename__ = "transcript_span"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    segment_id: Mapped[str] = mapped_column(
        String, ForeignKey("segment.id"), nullable=False, index=True
    )
    # NOTE: `raw_text` is intentionally absent. Do not add it.
    redacted_text: Mapped[str] = mapped_column(Text, nullable=False)
    redaction_map: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # JSON-encoded List[RedactionSpan]
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    segment: Mapped["Segment"] = relationship("Segment", back_populates="spans")


# --------------------------------------------------------------------------- #
# EscalationEvent — fires on watchlist matches at non-low confidence
# --------------------------------------------------------------------------- #
class EscalationEvent(Base):
    __tablename__ = "escalation_event"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    recording_id: Mapped[str] = mapped_column(
        String, ForeignKey("recording.id"), nullable=False, index=True
    )
    segment_id: Mapped[str] = mapped_column(
        String, ForeignKey("segment.id"), nullable=False, index=True
    )
    triggered_at: Mapped[str] = mapped_column(String, nullable=False, default=_utc_iso)
    event_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'escalation_high'|'escalation_medium'|'memory_candidate'|'handoff_note'
    watchlist_term: Mapped[str] = mapped_column(
        String, nullable=False
    )  # from watchlist, not PHI
    speaker_id: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    resolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    recording: Mapped["Recording"] = relationship("Recording", back_populates="escalations")
    segment: Mapped["Segment"] = relationship("Segment", back_populates="escalations")


# --------------------------------------------------------------------------- #
# MetricsRun — WER / MTER / DER-proxy / SI-SDR
# --------------------------------------------------------------------------- #
class MetricsRun(Base):
    __tablename__ = "metrics_run"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    recording_id: Mapped[str] = mapped_column(
        String, ForeignKey("recording.id"), nullable=False, index=True
    )
    wer: Mapped[float | None] = mapped_column(Float, nullable=True)
    medical_ter: Mapped[float | None] = mapped_column(Float, nullable=True)
    der_proxy: Mapped[float | None] = mapped_column(Float, nullable=True)
    si_sdr: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    run_at: Mapped[str] = mapped_column(String, nullable=False, default=_utc_iso)
    report_path: Mapped[str | None] = mapped_column(String, nullable=True)

    recording: Mapped["Recording"] = relationship("Recording", back_populates="metrics")


__all__ = [
    "Base",
    "Recording",
    "AudioAsset",
    "Segment",
    "TranscriptSpan",
    "EscalationEvent",
    "MetricsRun",
]
