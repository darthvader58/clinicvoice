"""REQUIRED: Pydantic schemas for diarization + ASR enforce invariants."""
from __future__ import annotations

import pytest

pytest.importorskip("src.diarize.schemas")
pytest.importorskip("src.asr.schemas")

from pydantic import ValidationError  # noqa: E402

from src.asr.schemas import ASRSegment, LanguageTag  # noqa: E402
from src.diarize.schemas import DiarizationResult, SpeakerTurn  # noqa: E402


def test_speaker_turn_valid(sample_segment):
    assert sample_segment.speaker_id == "S1"
    assert sample_segment.start_ts == 0.0
    assert sample_segment.end_ts == 3.5
    assert sample_segment.confidence == "high"


def test_speaker_turn_rejects_inverted_timestamps():
    with pytest.raises(ValidationError):
        SpeakerTurn(speaker_id="S1", start_ts=5.0, end_ts=2.0, confidence="high")


def test_asr_segment_all_required_fields():
    seg = ASRSegment(
        recording_id="rec-001",
        speaker_id="S1",
        start_ts=0.0,
        end_ts=3.5,
        raw_text="Patient has tachycardia.",
        language_tag=LanguageTag.EN,
        whisper_avg_logprob=-0.3,
        no_speech_prob=0.02,
        confidence="high",
        stem_used=True,
    )
    assert seg.speaker_id == "S1"
    assert seg.language_tag == LanguageTag.EN
    assert seg.confidence == "high"
    assert seg.stem_used is True


def test_segment_has_language_tag():
    seg = ASRSegment(
        recording_id="r1",
        speaker_id="S2",
        start_ts=1.0,
        end_ts=4.0,
        raw_text="test",
        language_tag=LanguageTag.HI,
        whisper_avg_logprob=-0.5,
        no_speech_prob=0.1,
        confidence="med",
    )
    assert str(seg.language_tag.value if hasattr(seg.language_tag, "value") else seg.language_tag) == "hi"


def test_diarization_result_structure():
    result = DiarizationResult(
        recording_id="r1",
        turns=[
            SpeakerTurn(speaker_id="S1", start_ts=0.0, end_ts=2.0, confidence="high"),
            SpeakerTurn(speaker_id="S2", start_ts=2.5, end_ts=5.0, confidence="med"),
        ],
        speaker_count=2,
        total_overlap_s=0.0,
        method="pyannote",
        track_mode="option_a_stems",
    )
    assert len(result.turns) >= 1
    for t in result.turns:
        assert t.speaker_id.startswith("S")
        assert t.end_ts > t.start_ts
        assert t.confidence in ["low", "med", "high"]
        assert hasattr(t, "overlap")
        assert hasattr(t, "stem_path")
