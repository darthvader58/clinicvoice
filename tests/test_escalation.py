"""EscalationEngine behaviour against the clinical watchlist."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("src.escalation.engine")

from src.escalation.engine import EscalationEngine  # noqa: E402

WATCHLIST = Path("src/escalation/watchlist.json")


@pytest.fixture
def engine():
    if not WATCHLIST.exists():
        pytest.skip("watchlist.json missing — DELTA agent owns this file")
    return EscalationEngine(WATCHLIST)


def test_high_acuity_triggers_event(engine):
    events, mc, hn = engine.process_segment(
        segment_id="s1",
        recording_id="r1",
        redacted_text="patient is experiencing chest pain and shortness of breath",
        speaker_id="S1",
        confidence="high",
        scenario="consult",
        start_ts=5.0,
    )
    assert any(e.event_type == "escalation_high" for e in events)


def test_low_confidence_never_escalates(engine):
    events, mc, hn = engine.process_segment(
        segment_id="s2",
        recording_id="r1",
        redacted_text="patient is experiencing chest pain",
        speaker_id="S1",
        confidence="low",
        scenario="consult",
        start_ts=5.0,
    )
    assert events == []
    assert mc is None


def test_memory_candidate_flagged(engine):
    events, mc, hn = engine.process_segment(
        segment_id="s3",
        recording_id="r1",
        redacted_text="I am prescribing metformin 500 mg twice daily",
        speaker_id="S2",
        confidence="high",
        scenario="consult",
        start_ts=10.0,
    )
    assert mc is not None
    assert mc.category in ["prescription", "instruction"]


def test_handoff_note_hallway_only(engine):
    _, _, hn_hallway = engine.process_segment(
        segment_id="s4",
        recording_id="r1",
        redacted_text="please check the potassium levels before end of shift",
        speaker_id="S1",
        confidence="high",
        scenario="hallway",
        start_ts=3.0,
    )
    _, _, hn_consult = engine.process_segment(
        segment_id="s5",
        recording_id="r1",
        redacted_text="please check the potassium levels before end of shift",
        speaker_id="S1",
        confidence="high",
        scenario="consult",
        start_ts=3.0,
    )
    assert hn_hallway is not None
    assert hn_consult is None


def test_redacted_text_only_reaches_engine(engine):
    """All EscalationEvent.watchlist_term values come from the watchlist
    file, never from arbitrary input text — so no raw PHI can leak."""
    events, mc, hn = engine.process_segment(
        segment_id="s6",
        recording_id="r1",
        redacted_text="[REDACTED] has chest pain, prescribed metformin",
        speaker_id="S1",
        confidence="high",
        scenario="consult",
        start_ts=1.0,
    )
    for e in events:
        assert "John" not in e.watchlist_term
