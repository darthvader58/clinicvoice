"""Diarization Error Rate (DER) proxy via IoU alignment.

The spec calls for a lightweight DER proxy that does not require pyannote.
For each reference turn we find the best-matching hypothesis turn (same
speaker label preferred, otherwise any) and compute IoU on time spans.
The proxy error is `1 - mean(IoU)` in [0, 1], where 0 = perfect overlap.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Tuple


def _span(turn: Any) -> Tuple[float, float, str]:
    """Extract (start, end, speaker_id) from a Pydantic model, dict, or tuple."""
    if hasattr(turn, "start_ts") and hasattr(turn, "end_ts"):
        speaker = getattr(turn, "speaker_id", "") or ""
        return float(turn.start_ts), float(turn.end_ts), str(speaker)
    if isinstance(turn, dict):
        return (
            float(turn.get("start_ts", turn.get("start", 0.0))),
            float(turn.get("end_ts", turn.get("end", 0.0))),
            str(turn.get("speaker_id", turn.get("speaker", ""))),
        )
    if isinstance(turn, (list, tuple)):
        start, end = float(turn[0]), float(turn[1])
        speaker = str(turn[2]) if len(turn) > 2 else ""
        return start, end, speaker
    raise TypeError(f"Cannot interpret turn: {turn!r}")


def _iou(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Interval IoU on (start, end) pairs."""
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    if union <= 0:
        return 0.0
    return inter / union


def compute_der_proxy(
    reference_turns: Iterable[Any],
    hypothesis_turns: Iterable[Any],
) -> float:
    """Return 1 - mean(best IoU per reference turn). 0.0 if no reference turns."""
    refs: List[Tuple[float, float, str]] = [_span(t) for t in reference_turns]
    hyps: List[Tuple[float, float, str]] = [_span(t) for t in hypothesis_turns]

    if not refs:
        return 0.0
    if not hyps:
        return 1.0

    ious: List[float] = []
    for r_start, r_end, r_spk in refs:
        best = 0.0
        # Prefer same-speaker match; fall back to any hypothesis turn.
        same_speaker = [h for h in hyps if r_spk and h[2] == r_spk]
        candidates = same_speaker if same_speaker else hyps
        for h_start, h_end, _ in candidates:
            best = max(best, _iou((r_start, r_end), (h_start, h_end)))
        ious.append(best)

    mean_iou = sum(ious) / len(ious)
    return max(0.0, min(1.0, 1.0 - mean_iou))
