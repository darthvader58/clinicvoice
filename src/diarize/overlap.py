from __future__ import annotations

import logging
from typing import List

from src.diarize.schemas import SpeakerTurn

logger = logging.getLogger("clinicvoice.diarize.overlap")

# Thresholds (seconds)
MERGE_THRESHOLD_S = 0.8   # overlap longer than this → merge into single OVERLAP turn
FLAG_THRESHOLD_S = 0.3    # overlap longer than this → flag both turns, drop confidence
JITTER_THRESHOLD_S = 0.0  # overlap above this and ≤ FLAG → silent trim of earlier end


def _degrade_confidence(level: str) -> str:
    if level == "high":
        return "low"
    if level == "med":
        return "low"
    return level


def detect_overlaps(turns: List[SpeakerTurn]) -> List[SpeakerTurn]:
    """Detect overlapping speaker turns and adjust per the spec rules.

    For adjacent turns sorted by start_ts:
      overlap_s = max(0, turn[i].end_ts - turn[i+1].start_ts)
        > 0.8s  → merge both into single turn, speaker_id="OVERLAP", confidence="low"
        > 0.3s  → both turns: confidence="low", overlap=True
        > 0s    → boundary jitter, trim turn[i].end_ts = turn[i+1].start_ts (silent)
    """
    if not turns:
        return []

    ordered = sorted(turns, key=lambda t: (t.start_ts, t.end_ts))
    result: List[SpeakerTurn] = []
    i = 0
    while i < len(ordered):
        current = ordered[i]
        if i + 1 >= len(ordered):
            result.append(current)
            i += 1
            continue

        nxt = ordered[i + 1]
        overlap_s = max(0.0, float(current.end_ts) - float(nxt.start_ts))

        if overlap_s > MERGE_THRESHOLD_S:
            merged_start = float(current.start_ts)
            merged_end = max(float(current.end_ts), float(nxt.end_ts))
            merged = SpeakerTurn(
                speaker_id="OVERLAP",
                start_ts=merged_start,
                end_ts=merged_end,
                overlap=True,
                confidence="low",
                stem_path=None,
            )
            result.append(merged)
            logger.info(
                "overlap_merged",
                extra={
                    "speakers": [current.speaker_id, nxt.speaker_id],
                    "overlap_s": round(overlap_s, 3),
                    "duration_s": round(merged_end - merged_start, 3),
                },
            )
            i += 2
            continue

        if overlap_s > FLAG_THRESHOLD_S:
            current_flagged = current.model_copy(
                update={"overlap": True, "confidence": _degrade_confidence(current.confidence)}
            )
            nxt_flagged = nxt.model_copy(
                update={"overlap": True, "confidence": _degrade_confidence(nxt.confidence)}
            )
            result.append(current_flagged)
            ordered[i + 1] = nxt_flagged
            logger.info(
                "overlap_flagged",
                extra={
                    "speakers": [current.speaker_id, nxt.speaker_id],
                    "overlap_s": round(overlap_s, 3),
                },
            )
            i += 1
            continue

        if overlap_s > JITTER_THRESHOLD_S:
            trimmed = current.model_copy(update={"end_ts": float(nxt.start_ts)})
            if trimmed.end_ts > trimmed.start_ts:
                result.append(trimmed)
            else:
                result.append(current)
            i += 1
            continue

        result.append(current)
        i += 1

    return result
