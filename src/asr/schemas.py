from __future__ import annotations

from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class LanguageTag(str, Enum):
    EN = "en"
    HI = "hi"
    UR = "ur"
    TA = "ta"
    ID = "id"
    MS = "ms"
    UNKNOWN = "unknown"


class ASRSegment(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    recording_id: str
    speaker_id: str
    start_ts: float
    end_ts: float
    # raw_text is EPHEMERAL: must never be persisted to DB or written to logs.
    # It exits the pipeline only after redact() produces redacted_text.
    raw_text: str
    language_tag: LanguageTag = LanguageTag.UNKNOWN
    whisper_avg_logprob: float = -1.0
    no_speech_prob: float = 1.0
    overlap_flag: bool = False
    confidence: Literal["low", "med", "high"] = "low"
    stem_used: bool = False
    normalized_text: Optional[str] = None

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_ts - self.start_ts)
