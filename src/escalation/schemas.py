"""Escalation, memory, and handoff schemas — Pydantic v2 models.

These models cross module boundaries and are persisted into the DB or
returned through API endpoints. They never carry raw (unredacted) text:
`redacted_text`/`redacted_instruction` are post-redaction strings, and
`watchlist_term` is sourced from the local watchlist file, not the
transcript.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class EscalationEvent(BaseModel):
    """A clinical alert raised against a single segment."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    recording_id: str
    segment_id: str
    triggered_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    event_type: Literal[
        "escalation_high",
        "escalation_medium",
        "memory_candidate",
        "handoff_note",
    ]
    watchlist_term: str  # term from watchlist (not PHI from transcript)
    speaker_id: str
    confidence: Literal["low", "med", "high"]
    resolved: bool = False


class MemoryCandidate(BaseModel):
    """A segment worth writing to Nightingale long-term memory."""

    segment_id: str
    speaker_id: str
    redacted_text: str
    language_tag: str
    confidence: str
    category: Literal[
        "instruction",
        "prescription",
        "referral",
        "discharge",
        "diagnosis",
        "general",
    ]


class HandoffNote(BaseModel):
    """A shift-transition instruction captured from a hallway scenario."""

    recording_id: str
    from_speaker: str
    redacted_instruction: str
    start_ts: float
    confidence: str
    watchlist_term: str
