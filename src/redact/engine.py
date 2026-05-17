"""Presidio-backed redaction engine — the privacy core.

THIS IS THE PRIVACY CORE.

`redact()` is the single, mandatory gateway between raw transcript text and
anything downstream (DB writes, logs, API responses, model calls). Raw text
must never be stored, logged, or returned past this module.

The engine is a lazy singleton: heavy dependencies (presidio, spacy) are
imported inside `__init__` so this module is safe to import at test-collection
time even if optional models are missing. If `en_core_web_sm` cannot be loaded,
we log a warning and fall back to pattern-only recognition (still PHI-safe
for IDs, phones, DOBs — just no NER for free-text names).
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from src.redact.patterns import ALL_CUSTOM_RECOGNIZERS
from src.redact.schemas import RedactionResult, RedactionSpan, RedactionType

logger = logging.getLogger(__name__)


class RedactionEngine:
    """Lazy singleton wrapping Presidio analyzer + anonymizer."""

    _instance: Optional["RedactionEngine"] = None

    @classmethod
    def get_instance(cls) -> "RedactionEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        # Lazy imports — keep module import-time light and test-friendly.
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine
        from presidio_anonymizer.entities import OperatorConfig

        registry = RecognizerRegistry()
        nlp_engine = None

        try:
            import spacy  # noqa: F401  (presence check — Presidio loads via NlpEngineProvider)

            try:
                # Validates the model is installed before handing the name to Presidio.
                spacy.load("en_core_web_sm")
                nlp_engine = NlpEngineProvider(
                    nlp_configuration={
                        "nlp_engine_name": "spacy",
                        "models": [
                            {"lang_code": "en", "model_name": "en_core_web_sm"}
                        ],
                    }
                ).create_engine()
                registry.load_predefined_recognizers()
            except OSError:
                logger.warning(
                    "spacy model 'en_core_web_sm' not installed — "
                    "redaction will fall back to pattern-only recognition. "
                    "Run: python -m spacy download en_core_web_sm"
                )
        except ImportError:
            logger.warning(
                "spacy not importable — redaction will fall back to "
                "pattern-only recognition."
            )

        for recognizer in ALL_CUSTOM_RECOGNIZERS:
            registry.add_recognizer(recognizer)

        analyzer_kwargs = {"registry": registry, "supported_languages": ["en"]}
        if nlp_engine is not None:
            analyzer_kwargs["nlp_engine"] = nlp_engine

        self._analyzer = AnalyzerEngine(**analyzer_kwargs)
        self._anonymizer = AnonymizerEngine()
        self._operator_config = {
            "DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"})
        }
        # NEVER log self._analyzer / self._anonymizer state with text content.

    def redact(self, text: str, language: str = "en") -> RedactionResult:
        """Run the mandatory redaction gateway.

        Input text is never stored, logged, or returned by this method.
        Only offsets and replacement markers leave the function.
        """
        # Presidio's NER only supports 'en'. Pattern recognizers ignore the
        # language tag, so they fire regardless. We coerce the analyzer
        # language to 'en' for non-EN inputs and rely on patterns alone.
        analyzer_language = "en"

        target_entities = [
            "PERSON",
            "PHONE_NUMBER",
            "EMAIL_ADDRESS",
            "LOCATION",
            "DATE_OF_BIRTH",
            "MEDICAL_RECORD_NUMBER",
            "NRIC_SG",
            "IC_MY",
            "PHONE_IN",
            "CNIC_PK",
            "NIK_INDONESIA",
        ]

        analyzer_results = self._analyzer.analyze(
            text=text,
            language=analyzer_language,
            entities=target_entities,
        )

        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=analyzer_results,
            operators=self._operator_config,
        )

        redaction_map: List[RedactionSpan] = [
            RedactionSpan(
                type=(
                    RedactionType(r.entity_type)
                    if r.entity_type in RedactionType._value2member_map_
                    else RedactionType.PERSON
                ),
                start=r.start,
                end=r.end,
                replacement="[REDACTED]",
            )
            for r in analyzer_results
        ]

        return RedactionResult(
            redacted_text=anonymized.text,
            redaction_map=redaction_map,
            original_char_count=len(text),
            redacted_count=len(analyzer_results),
            language=language,
            # original_text is intentionally absent.
        )


def redact(text: str, language: str = "en") -> Tuple[str, List[RedactionSpan]]:
    """Public, module-level redaction API.

    Returns the redacted text and the span map. The original `text`
    argument is never persisted or logged by this module.
    """
    result = RedactionEngine.get_instance().redact(text, language)
    return result.redacted_text, result.redaction_map
