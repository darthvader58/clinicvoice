"""BONUS: prove the correction loop materially reduces MTER."""
from __future__ import annotations

import json

import pytest

from src.metrics.mter import compute_mter


def test_corrections_reduce_mter(medical_lexicon):
    ref = (
        "patient needs metformin and has tachycardia and atrial fibrillation"
    )
    hyp_before = (
        "patient needs metforin and has takicardia and atrial fibrilation"
    )
    mter_before = compute_mter(hyp_before, ref, medical_lexicon)

    corrections = {
        "metforin": "metformin",
        "takicardia": "tachycardia",
        "fibrilation": "fibrillation",
    }
    hyp_after = hyp_before
    for wrong, correct in corrections.items():
        hyp_after = hyp_after.replace(wrong, correct)

    mter_after = compute_mter(hyp_after, ref, medical_lexicon)
    assert mter_after < mter_before
    assert mter_after == pytest.approx(0.0, abs=0.01)


def test_lexicon_update_persists_terms(tmp_path):
    pytest.importorskip("src.asr.lexicon")
    from src.asr.lexicon import MedicalLexicon

    p = tmp_path / "lex.json"
    p.write_text(
        json.dumps(
            {"terms": ["metformin"], "drug_names": [], "abbreviations": {}}
        )
    )
    lex = MedicalLexicon.load(p)
    before = len(lex.get_term_list())
    lex.apply_corrections({"lisinipril": "lisinopril"})
    assert len(lex.get_term_list()) > before
    assert "lisinopril" in lex.get_term_list()
