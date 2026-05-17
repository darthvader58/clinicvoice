"""Word Error Rate computation using jiwer with normalization pipeline."""
from __future__ import annotations

from typing import List

import jiwer


# Standard normalization: lowercase, strip punctuation, whitespace, tokenize.
NORMALIZE = jiwer.Compose(
    [
        jiwer.ToLowerCase(),
        jiwer.RemovePunctuation(),
        jiwer.RemoveMultipleSpaces(),
        jiwer.Strip(),
        jiwer.ReduceToListOfListOfWords(),
    ]
)


def compute_wer(hypothesis: str, reference: str) -> float:
    """Compute case-insensitive, punctuation-stripped WER.

    Returns 0.0 when the reference is effectively empty, since there is
    no denominator to score against.
    """
    if not reference or not reference.strip():
        return 0.0
    return float(
        jiwer.wer(
            reference,
            hypothesis,
            reference_transform=NORMALIZE,
            hypothesis_transform=NORMALIZE,
        )
    )


def compute_weighted_wer(
    hypothesis: str,
    reference: str,
    high_weight_terms: List[str],
    weight: float = 3.0,
) -> float:
    """WER with medical terms duplicated so their errors count `weight`x."""
    rep = max(int(weight), 1)
    for term in high_weight_terms:
        if not term:
            continue
        reference = reference.replace(term, (term + " ") * rep)
        hypothesis = hypothesis.replace(term, (term + " ") * rep)
    return compute_wer(hypothesis, reference)
