"""Application configuration loaded from environment / .env.

All runtime tunables live here. Defaults are safe for local dev.
"""

from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for clinicvoice. Override any field via env or .env."""

    # --- persistence ---
    DB_PATH: str = "clinicvoice.db"
    AUDIO_STORAGE_PATH: str = "data/audio"
    REPORTS_PATH: str = "data/reports"

    # --- ASR (whisper) ---
    WHISPER_MODEL: str = "small"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_LANGUAGE: Optional[str] = None  # None = auto-detect

    # --- diarization (pyannote) ---
    PYANNOTE_HF_TOKEN: Optional[str] = None  # None → energy-based fallback
    PYANNOTE_MODEL: str = "pyannote/speaker-diarization-3.1"
    MAX_SPEAKERS: int = 4

    # --- source separation (asteroid ConvTasNet) ---
    ASTEROID_MODEL: str = "JorisCos/ConvTasNet_Libri2Mix_sepclean_16k"
    SEPARATION_SI_SDR_THRESHOLD: float = 5.0  # dB

    # --- retention ---
    AUDIO_RETENTION_TTL_S: int = 86400  # 24h; 0 = retain forever

    # --- medical lexicon ---
    MEDICAL_LEXICON_PATH: str = "tests/data/medical_lexicon.json"
    CORRECTIONS_PATH: str = "data/medical_lexicon_corrections.json"

    # --- cloud ASR gate (off by default; both flags required) ---
    USE_CLOUD_ASR: bool = False
    CLOUD_REDACT_FIRST: bool = False

    # --- observability ---
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


# Module-level singleton — import this everywhere.
settings = Settings()
