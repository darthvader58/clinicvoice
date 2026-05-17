from uuid import uuid4

from sqlalchemy import Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Recording(Base):
    __tablename__ = "recording"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    created_at: Mapped[str] = mapped_column(Text, server_default=func.now(), nullable=False)
    file_hash: Mapped[str] = mapped_column(Text, nullable=False)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    scenario: Mapped[str | None] = mapped_column(Text, nullable=True)
    track_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    si_sdr: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_ttl: Mapped[int] = mapped_column(Integer, default=86400, nullable=False)
    purged_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    assets: Mapped[list["AudioAsset"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan"
    )
    segments: Mapped[list["Segment"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan"
    )
    escalation_events: Mapped[list["EscalationEvent"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan"
    )
    metrics_runs: Mapped[list["MetricsRun"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan"
    )


class AudioAsset(Base):
    __tablename__ = "audio_asset"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    recording_id: Mapped[str] = mapped_column(
        String, ForeignKey("recording.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_type: Mapped[str] = mapped_column(Text, default="source", nullable=False)
    speaker_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    format: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)

    recording: Mapped["Recording"] = relationship(back_populates="assets")


class Segment(Base):
    __tablename__ = "segment"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    recording_id: Mapped[str] = mapped_column(
        String, ForeignKey("recording.id", ondelete="CASCADE"), nullable=False
    )
    speaker_id: Mapped[str] = mapped_column(Text, nullable=False)
    start_ts: Mapped[float] = mapped_column(Float, nullable=False)
    end_ts: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    language_tag: Mapped[str] = mapped_column(Text, nullable=False)
    overlap_flag: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stem_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    recording: Mapped["Recording"] = relationship(back_populates="segments")
    transcript_spans: Mapped[list["TranscriptSpan"]] = relationship(
        back_populates="segment", cascade="all, delete-orphan"
    )


class TranscriptSpan(Base):
    __tablename__ = "transcript_span"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    segment_id: Mapped[str] = mapped_column(
        String, ForeignKey("segment.id", ondelete="CASCADE"), nullable=False
    )
    redacted_text: Mapped[str] = mapped_column(Text, nullable=False)
    redaction_map: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    segment: Mapped["Segment"] = relationship(back_populates="transcript_spans")


class EscalationEvent(Base):
    __tablename__ = "escalation_event"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    recording_id: Mapped[str] = mapped_column(
        String, ForeignKey("recording.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[str] = mapped_column(
        String, ForeignKey("segment.id", ondelete="CASCADE"), nullable=False
    )
    triggered_at: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    watchlist_term: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_id: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    recording: Mapped["Recording"] = relationship(back_populates="escalation_events")


class MetricsRun(Base):
    __tablename__ = "metrics_run"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    recording_id: Mapped[str] = mapped_column(
        String, ForeignKey("recording.id", ondelete="CASCADE"), nullable=False
    )
    wer: Mapped[float | None] = mapped_column(Float, nullable=True)
    medical_ter: Mapped[float | None] = mapped_column(Float, nullable=True)
    der_proxy: Mapped[float | None] = mapped_column(Float, nullable=True)
    si_sdr: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_at: Mapped[str] = mapped_column(Text, nullable=False)
    report_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    recording: Mapped["Recording"] = relationship(back_populates="metrics_runs")
