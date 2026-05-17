from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field


class RecordingIn(BaseModel):
    scenario: Literal["hallway", "consult", "unknown"] = "unknown"


class NormalizedAudio(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path
    sample_rate: int
    duration_s: float
    file_hash: str
    speech_segments: List[Tuple[float, float]] = Field(default_factory=list)
    noise_reduced: bool = False


class StemAsset(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    speaker_id: str
    path: Path
    si_sdr: float


class SeparationResult(BaseModel):
    track_mode: Literal["option_a_stems", "option_b_single"]
    stems: List[StemAsset] = Field(default_factory=list)
    si_sdr_max: float
    si_sdr_threshold_used: float


class AudioAssetOut(BaseModel):
    id: str
    recording_id: str
    file_path: Optional[str] = None
    format: str
    sample_rate: int
    duration_s: float
    file_hash: str
    track_mode: str = "pending"
    si_sdr: Optional[float] = None
