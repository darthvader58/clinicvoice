"""Language-agnostic segment confidence scoring.

Maps Whisper's ``avg_logprob`` plus runtime signals (overlap, duration,
stem usage) onto a coarse ``low | med | high`` label that drives
escalation gating (see ``src.escalation.engine``).
"""

from __future__ import annotations

from typing import Literal


def compute_confidence(
    whisper_avg_logprob: float,
    no_speech_prob: float,
    overlap: bool,
    segment_duration: float,
    stem_used: bool,
) -> Literal["low", "med", "high"]:
    """Compute a coarse confidence label for an ASR segment.

    Parameters
    ----------
    whisper_avg_logprob : float
        Whisper's average log-probability; typically in ``[-2.0, 0.0]`` with
        values closer to zero indicating greater confidence.
    no_speech_prob : float
        Probability that the segment is silence/noise (0-1).
    overlap : bool
        Whether the segment overlaps with another speaker turn.
    segment_duration : float
        Length of the segment in seconds.
    stem_used : bool
        True if the segment was decoded from an Option-A separated stem.
    """

    # Hard "low" conditions — escalation engine will not fire on these.
    if overlap:
        return "low"
    if no_speech_prob > 0.6:
        return "low"
    if segment_duration < 0.5:
        return "low"

    # Normalize logprob onto a 0-1 scale (clamped).
    normalized = max(0.0, min(1.0, (whisper_avg_logprob + 2.0) / 2.0))

    # Stem-decoded turns get a small bump for reduced cross-talk bleed.
    if stem_used:
        normalized = min(1.0, normalized + 0.05)

    if normalized > 0.85:
        return "high"
    if normalized > 0.60:
        return "med"
    return "low"
