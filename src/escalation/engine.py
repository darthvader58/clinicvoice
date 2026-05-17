"""Escalation engine — scans redacted segments against the watchlist.

Inputs are always redacted text (post `redact()`). The engine never sees
raw transcripts. `watchlist_term` written into events is sourced from the
local watchlist JSON, not from the transcript, so events stay PHI-free.

Hard rules:
  * `confidence == "low"` segments produce no events, candidates, or notes.
  * High-acuity escalation supersedes medium — at most one escalation per segment.
  * Handoff notes only fire when `scenario == "hallway"`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from src.escalation.schemas import EscalationEvent, HandoffNote, MemoryCandidate


class EscalationEngine:
    """Stateless decision engine over the per-recording segment stream."""

    def __init__(self, watchlist_path: Path):
        self._watchlist = json.loads(Path(watchlist_path).read_text())

    def process_segment(
        self,
        segment_id: str,
        recording_id: str,
        redacted_text: str,
        speaker_id: str,
        confidence: str,
        scenario: str,
        start_ts: float,
    ) -> Tuple[List[EscalationEvent], Optional[MemoryCandidate], Optional[HandoffNote]]:
        """Classify one redacted segment.

        Returns (events, memory_candidate, handoff_note). Lists/optionals are
        empty when nothing fires. `redacted_text` MUST already have passed
        through `src.redact.engine.redact`.
        """
        events: List[EscalationEvent] = []
        memory_candidate: Optional[MemoryCandidate] = None
        handoff_note: Optional[HandoffNote] = None

        # HARD RULE: never escalate low-confidence segments.
        if confidence == "low":
            return events, memory_candidate, handoff_note

        text_lower = redacted_text.lower()

        # High-acuity escalation — wins over medium.
        for term in self._watchlist.get("escalation_high", []):
            if term.lower() in text_lower:
                events.append(
                    EscalationEvent(
                        recording_id=recording_id,
                        segment_id=segment_id,
                        event_type="escalation_high",
                        watchlist_term=term,
                        speaker_id=speaker_id,
                        confidence=confidence,
                    )
                )
                break  # one event per segment for high-acuity

        # Medium escalation — only if no high already fired.
        if not events:
            for term in self._watchlist.get("escalation_medium", []):
                if term.lower() in text_lower:
                    events.append(
                        EscalationEvent(
                            recording_id=recording_id,
                            segment_id=segment_id,
                            event_type="escalation_medium",
                            watchlist_term=term,
                            speaker_id=speaker_id,
                            confidence=confidence,
                        )
                    )
                    break

        # Memory candidate.
        for term in self._watchlist.get("memory_triggers", []):
            if term.lower() in text_lower:
                memory_candidate = MemoryCandidate(
                    segment_id=segment_id,
                    speaker_id=speaker_id,
                    redacted_text=redacted_text,
                    language_tag="en",
                    confidence=confidence,
                    category=self._classify_memory(text_lower),
                )
                break

        # Handoff note (hallway scenario only).
        if scenario == "hallway":
            for term in self._watchlist.get("handoff_triggers", []):
                if term.lower() in text_lower:
                    handoff_note = HandoffNote(
                        recording_id=recording_id,
                        from_speaker=speaker_id,
                        redacted_instruction=redacted_text,
                        start_ts=start_ts,
                        confidence=confidence,
                        watchlist_term=term,
                    )
                    break

        return events, memory_candidate, handoff_note

    def _classify_memory(self, text_lower: str) -> str:
        """Bucket a memory-candidate segment by its dominant intent."""
        if any(t in text_lower for t in ["prescribed", "prescription", "take", "dosage"]):
            return "prescription"
        if any(t in text_lower for t in ["referral", "specialist", "appointment"]):
            return "referral"
        if any(t in text_lower for t in ["discharged", "discharge"]):
            return "discharge"
        if any(t in text_lower for t in ["diagnosed", "diagnosis", "condition is"]):
            return "diagnosis"
        return "instruction"
