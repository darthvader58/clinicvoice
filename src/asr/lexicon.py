"""Medical lexicon used as a Whisper ``initial_prompt`` to bias decoding.

The lexicon is loaded from JSON (see ``tests/data/medical_lexicon.json``)
and offers a prompt that fits within the Whisper token budget. The
correction loop (``apply_corrections``) extends the in-memory lexicon and
persists future-run corrections to ``settings.CORRECTIONS_PATH``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


class MedicalLexicon:
    """Holds the medical vocabulary used to seed Whisper decoding."""

    # Whisper initial_prompt budget (approximation in whitespace tokens).
    MAX_PROMPT_TOKENS: int = 200

    def __init__(self) -> None:
        self._terms: List[str] = []
        self._drug_names: List[str] = []
        self._abbreviations: Dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: Path) -> "MedicalLexicon":
        """Load the lexicon JSON from disk."""

        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        instance = cls()
        instance._terms = list(data.get("terms", []))
        instance._drug_names = list(data.get("drug_names", []))
        instance._abbreviations = dict(data.get("abbreviations", {}))
        return instance

    # ------------------------------------------------------------------ #
    # Prompt / query helpers
    # ------------------------------------------------------------------ #
    def build_initial_prompt(self) -> str:
        """Construct the Whisper ``initial_prompt`` within the token budget.

        Priority order: drug names > clinical terms. Abbreviations are not
        injected verbatim — Whisper biases better on full names.
        """

        prefix = "Medical transcription. Clinical terms: "
        suffix = ". Patient encounter."
        all_terms = list(self._drug_names) + list(self._terms)

        added: List[str] = []
        # Pre-count the prefix/suffix word budget.
        base_tokens = len(prefix.split()) + len(suffix.split())

        for term in all_terms:
            candidate = added + [term]
            joined = ", ".join(candidate)
            total_tokens = base_tokens + len(joined.split())
            if total_tokens > self.MAX_PROMPT_TOKENS:
                break
            added.append(term)

        return prefix + ", ".join(added) + suffix

    def get_term_list(self) -> List[str]:
        """Flat list of every term known to the lexicon."""

        return list(self._terms) + list(self._drug_names) + list(self._abbreviations.keys())

    @property
    def terms(self) -> List[str]:
        return list(self._terms)

    @property
    def drug_names(self) -> List[str]:
        return list(self._drug_names)

    @property
    def abbreviations(self) -> Dict[str, str]:
        return dict(self._abbreviations)

    # ------------------------------------------------------------------ #
    # Correction loop
    # ------------------------------------------------------------------ #
    def apply_corrections(self, corrections: Dict[str, str]) -> None:
        """Append corrected terms to the lexicon and persist them.

        ``corrections`` maps an incorrect transcription to the correct
        medical term. The correct term is appended to the lexicon so the
        next prompt biases toward it. Corrections are persisted to
        ``settings.CORRECTIONS_PATH`` for use by future processes.
        """

        # Lazy import to avoid a circular dependency with src.config.
        from src.config import settings

        for _, correct in corrections.items():
            if not correct:
                continue
            if correct not in self._terms and correct not in self._drug_names:
                self._terms.append(correct)

        corrections_path = Path(settings.CORRECTIONS_PATH)
        corrections_path.parent.mkdir(parents=True, exist_ok=True)
        if corrections_path.exists():
            try:
                existing = json.loads(corrections_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
        else:
            existing = {}
        existing.update(corrections)
        corrections_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
