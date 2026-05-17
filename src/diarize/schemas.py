from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpeakerTurn(BaseModel):
    """One contiguous span attributed to a single speaker (or OVERLAP)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    speaker_id: str
    start_ts: float
    end_ts: float
    overlap: bool = False
    confidence: Literal["low", "med", "high"] = "high"
    stem_path: Optional[Path] = None

    @model_validator(mode="after")
    def _validate_timestamps(self) -> "SpeakerTurn":
        if self.start_ts < 0:
            raise ValueError(f"start_ts ({self.start_ts}) must be >= 0")
        if self.end_ts <= self.start_ts:
            raise ValueError(
                f"end_ts ({self.end_ts}) must be > start_ts ({self.start_ts})"
            )
        return self


class DiarizationResult(BaseModel):
    recording_id: str
    turns: List[SpeakerTurn] = Field(default_factory=list)
    speaker_count: int
    total_overlap_s: float = 0.0
    method: Literal["pyannote", "energy_fallback", "single_speaker"]
    track_mode: str
