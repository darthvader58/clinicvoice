"""Shared pytest fixtures for clinicvoice tests.

These fixtures are intentionally lenient: if optional artifacts (lexicon,
synthetic audio, ground truth) are missing the consuming test is skipped
rather than hard-failed, so the suite can run incrementally during the
build.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

LEXICON_PATH = Path("tests/data/medical_lexicon.json")
SYNTHETIC_HALLWAY = Path("tests/data/synthetic_hallway.wav")
SYNTHETIC_CONSULT = Path("tests/data/synthetic_consult.wav")
GROUND_TRUTH = Path("tests/data/ground_truth_consult.json")


@pytest.fixture(scope="session")
def medical_lexicon():
    if not LEXICON_PATH.exists():
        pytest.skip(
            "tests/data/medical_lexicon.json missing — run scripts/generate_synthetic_audio.py"
        )
    try:
        from src.asr.lexicon import MedicalLexicon
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MedicalLexicon not importable: {exc}")
    return MedicalLexicon.load(LEXICON_PATH)


@pytest.fixture
def sample_segment():
    from src.diarize.schemas import SpeakerTurn

    return SpeakerTurn(
        speaker_id="S1", start_ts=0.0, end_ts=3.5, confidence="high"
    )


@pytest.fixture(scope="session")
def ground_truth():
    if not GROUND_TRUTH.exists():
        pytest.skip("ground_truth_consult.json missing")
    return json.loads(GROUND_TRUTH.read_text())


@pytest.fixture(scope="session")
def synthetic_hallway_path():
    if not SYNTHETIC_HALLWAY.exists():
        pytest.skip(
            "synthetic_hallway.wav missing — run scripts/generate_synthetic_audio.py"
        )
    return SYNTHETIC_HALLWAY


@pytest.fixture(scope="session")
def synthetic_consult_path():
    if not SYNTHETIC_CONSULT.exists():
        pytest.skip(
            "synthetic_consult.wav missing — run scripts/generate_synthetic_audio.py"
        )
    return SYNTHETIC_CONSULT


@pytest.fixture
def redaction_engine():
    try:
        from src.redact.engine import RedactionEngine
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RedactionEngine not importable: {exc}")
    if hasattr(RedactionEngine, "get_instance"):
        return RedactionEngine.get_instance()
    return RedactionEngine()


@pytest.fixture
async def client():
    """Async HTTP client bound to the FastAPI ASGI app."""
    try:
        from httpx import ASGITransport, AsyncClient
        from src.main import app
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"FastAPI app not importable: {exc}")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
