from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_PATH: str = "clinicvoice.db"
    AUDIO_STORAGE_PATH: str = "data/audio"
    REPORTS_PATH: str = "data/reports"

    WHISPER_MODEL: str = "large-v3-turbo"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_LANGUAGE: Optional[str] = None

    PYANNOTE_HF_TOKEN: Optional[str] = None
    PYANNOTE_MODEL: str = "pyannote/speaker-diarization-3.1"
    MAX_SPEAKERS: int = 4

    ASTEROID_MODEL: str = "JorisCos/ConvTasNet_Libri2Mix_sepclean_16k"
    SEPARATION_SI_SDR_THRESHOLD: float = 5.0

    AUDIO_RETENTION_TTL_S: int = 86400

    MEDICAL_LEXICON_PATH: str = "tests/data/medical_lexicon.json"
    CORRECTIONS_PATH: str = "data/medical_lexicon_corrections.json"

    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
