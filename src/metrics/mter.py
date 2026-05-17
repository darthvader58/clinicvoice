"""Medical Term Error Rate (MTER) — fraction of lexicon terms in the
reference that are missing from the hypothesis (case-insensitive)."""
from __future__ import annotations

from typing import Any, Dict, List


def _terms_from(lexicon: Any) -> List[str]:
    """Best-effort accessor for the term list of a MedicalLexicon."""
    if lexicon is None:
        return []
    if hasattr(lexicon, "get_term_list"):
        try:
            return list(lexicon.get_term_list())
        except Exception:
            pass
    if isinstance(lexicon, dict):
        return list(lexicon.get("terms", []))
    if isinstance(lexicon, (list, tuple, set)):
        return list(lexicon)
    return []


def compute_mter(hypothesis: str, reference: str, lexicon: Any) -> float:
    """Return the medical-term error rate in [0, 1].

    For every term in the lexicon that appears in `reference`, we count
    an error iff that term is missing from `hypothesis`. The rate is
    errors / present_in_ref. Returns 0.0 if no lexicon terms appear in
    the reference (i.e. nothing to score).
    """
    terms = _terms_from(lexicon)
    if not terms:
        return 0.0

    ref_lower = (reference or "").lower()
    hyp_lower = (hypothesis or "").lower()

    present_in_ref = [t for t in terms if t and t.lower() in ref_lower]
    if not present_in_ref:
        return 0.0

    errors = sum(1 for t in present_in_ref if t.lower() not in hyp_lower)
    return errors / len(present_in_ref)


def get_term_errors(
    hypothesis: str, reference: str, lexicon: Any
) -> List[Dict[str, Any]]:
    """Per-term breakdown for reporting/debugging."""
    terms = _terms_from(lexicon)
    ref_lower = (reference or "").lower()
    hyp_lower = (hypothesis or "").lower()
    return [
        {
            "term": t,
            "in_reference": True,
            "in_hypothesis": t.lower() in hyp_lower,
        }
        for t in terms
        if t and t.lower() in ref_lower
    ]
