"""ASR schemas — Pydantic v2 models for transcribed speech segments.

CRITICAL: ``ASRSegment.raw_text`` is EPHEMERAL. It must never be persisted to
the database and must never be logged. It crosses the redaction boundary in
``src.redact.boundary`` before any DB write or API response.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class LanguageTag(str, Enum):
    """BCP-47 language tags supported by clinicvoice."""

    EN = "en"
    HI = "hi"
    UR = "ur"
    TA = "ta"
    ID = "id"
    MS = "ms"
    UNKNOWN = "unknown"


class ASRSegment(BaseModel):
    """A single ASR turn produced by the Whisper engine.

    ``raw_text`` is the un-redacted transcription and is EPHEMERAL. It exists
    only in process memory until redaction strips PHI. Downstream code must
    use ``normalized_text`` (post-normalize) and then the redacted output of
    ``src.redact.engine.redact``.
    """

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    recording_id: str
    speaker_id: str
    start_ts: float
    end_ts: float
    raw_text: str  # EPHEMERAL — never stored in DB, never logged
    language_tag: LanguageTag = LanguageTag.UNKNOWN
    whisper_avg_logprob: float = -1.0
    no_speech_prob: float = 1.0
    confidence: Literal["low", "med", "high"] = "low"
    stem_used: bool = False
    normalized_text: Optional[str] = None  # set after normalization pipeline
