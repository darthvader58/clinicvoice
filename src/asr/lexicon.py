from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MedicalLexicon:
    # Whisper hard limit is 224 tokens for initial_prompt; we budget 200 to leave headroom.
    MAX_PROMPT_TOKENS = 200
    PROMPT_PREFIX = "Medical transcription. Clinical terms: "
    PROMPT_SUFFIX = ". Patient encounter."

    def __init__(self) -> None:
        self._terms: List[str] = []
        self._drug_names: List[str] = []
        self._abbreviations: Dict[str, str] = {}
        self._source_path: Optional[Path] = None

    @classmethod
    def load(cls, path: Path) -> "MedicalLexicon":
        path = Path(path)
        instance = cls()
        instance._source_path = path
        if not path.exists():
            logger.warning("lexicon_missing", extra={"path": str(path)})
            return instance
        data = json.loads(path.read_text(encoding="utf-8"))
        instance._terms = list(dict.fromkeys(data.get("terms", [])))
        instance._drug_names = list(dict.fromkeys(data.get("drug_names", [])))
        instance._abbreviations = dict(data.get("abbreviations", {}))
        instance._merge_persisted_corrections()
        return instance

    def _merge_persisted_corrections(self) -> None:
        try:
            from src.config import settings  # type: ignore

            corrections_path = Path(settings.CORRECTIONS_PATH)
        except Exception:
            return
        if not corrections_path.exists():
            return
        try:
            existing = json.loads(corrections_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for _wrong, correct in existing.items():
            if correct and correct not in self._terms and correct not in self._drug_names:
                self._terms.append(correct)

    def _count_tokens(self, text: str) -> int:
        try:
            import whisper  # type: ignore
            from whisper.tokenizer import get_tokenizer  # type: ignore

            tokenizer = get_tokenizer(multilingual=True)
            return len(tokenizer.encode(text))
        except Exception:
            # Word-based proxy: ~1.3 tokens per word for English medical terms.
            return int(len(text.split()) * 1.4) + 4

    def build_initial_prompt(self) -> str:
        ordered: List[str] = []
        seen = set()
        for source in (self._drug_names, self._terms, list(self._abbreviations.keys())):
            for term in source:
                key = term.lower()
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(term)

        accepted: List[str] = []
        for term in ordered:
            candidate = self.PROMPT_PREFIX + ", ".join(accepted + [term]) + self.PROMPT_SUFFIX
            if self._count_tokens(candidate) > self.MAX_PROMPT_TOKENS:
                break
            accepted.append(term)

        if not accepted:
            return "Medical transcription. Patient encounter."
        return self.PROMPT_PREFIX + ", ".join(accepted) + self.PROMPT_SUFFIX

    def get_term_list(self) -> List[str]:
        return list(self._terms) + list(self._drug_names) + list(self._abbreviations.keys())

    def get_drug_names(self) -> List[str]:
        return list(self._drug_names)

    def get_abbreviations(self) -> Dict[str, str]:
        return dict(self._abbreviations)

    def apply_corrections(self, corrections: Dict[str, str]) -> None:
        if not corrections:
            return
        for _wrong, correct in corrections.items():
            if not correct:
                continue
            if correct not in self._terms and correct not in self._drug_names:
                self._terms.append(correct)

        try:
            from src.config import settings  # type: ignore

            corrections_path = Path(settings.CORRECTIONS_PATH)
        except Exception:
            logger.warning("corrections_not_persisted_no_settings")
            return

        corrections_path.parent.mkdir(parents=True, exist_ok=True)
        existing: Dict[str, str] = {}
        if corrections_path.exists():
            try:
                existing = json.loads(corrections_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        existing.update({k: v for k, v in corrections.items() if v})
        corrections_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("lexicon_corrections_applied", extra={"count": len(corrections)})
