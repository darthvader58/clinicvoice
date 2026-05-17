"""REQUIRED: WER/MTER computation and report serialization."""
from __future__ import annotations

import json

import pytest

from src.metrics.mter import compute_mter
from src.metrics.report import MetricsReporter
from src.metrics.wer import compute_wer


def test_wer_detects_error():
    wer = compute_wer("the patient has takicardia", "the patient has tachycardia")
    assert 0 < wer <= 1.0


def test_wer_perfect_match():
    text = "patient needs metformin twice daily"
    assert compute_wer(text, text) == 0.0


def test_wer_case_insensitive():
    assert compute_wer("METFORMIN", "metformin") == 0.0


def test_mter_detects_medical_errors(medical_lexicon):
    mter = compute_mter(
        "patient has takicardia and needs metforin",
        "patient has tachycardia and needs metformin",
        medical_lexicon,
    )
    assert 0 < mter <= 1.0


def test_mter_perfect_on_medical_terms(medical_lexicon):
    text = "patient has tachycardia and needs metformin"
    assert compute_mter(text, text, medical_lexicon) == 0.0


def test_report_file_created(tmp_path):
    reporter = MetricsReporter()
    report_path = tmp_path / "test_report.json"
    result = reporter.generate_report(
        recording_id="test-001",
        wer=0.15,
        mter=0.10,
        der_proxy=0.20,
        si_sdr=8.5,
        term_errors=[],
        speaker_quality={"f1": 0.88},
        track_mode="option_a_stems",
        output_path=report_path,
    )
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert "wer" in data
    assert "medical_term_error_rate" in data
    assert "si_sdr" in data
    assert data["track_mode"] == "option_a_stems"
    assert result["wer"] == 0.15
    csv_path = report_path.with_suffix(".csv")
    assert csv_path.exists()
    csv_content = csv_path.read_text()
    assert "recording_id" in csv_content
    assert "test-001" in csv_content
