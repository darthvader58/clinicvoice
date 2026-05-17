"""Per-segment language detection.

Combines Whisper's own language detection with ``langdetect`` for text-based
confirmation. Returns ``LanguageTag.UNKNOWN`` for very short utterances or
when neither signal is confident enough to trust.
"""

from __future__ import annotations

from typing import Dict, Optional

from src.asr.schemas import LanguageTag

SUPPORTED = {"en", "hi", "ur", "ta", "id", "ms"}
LANGDETECT_TO_LANGUAGE_TAG: Dict[str, str] = {
    "en": "en",
    "hi": "hi",
    "ur": "ur",
    "ta": "ta",
    "id": "id",
    "ms": "ms",
}


def detect_language(
    text: str,
    whisper_detected: Optional[str] = None,
    whisper_language_prob: float = 0.0,
) -> LanguageTag:
    """Decide the language tag for a single ASR segment.

    Decision tree:
      1. If fewer than 5 words → ``UNKNOWN`` (not enough signal).
      2. If Whisper is confident (>0.7) and supported → trust Whisper.
      3. Else confirm with ``langdetect``; if it agrees or Whisper is silent,
         use the text-based detection.
      4. Fall back to Whisper even at lower confidence if supported.
      5. Otherwise ``UNKNOWN``.
    """

    if not text or len(text.split()) < 5:
        return LanguageTag.UNKNOWN

    # 1. Whisper's own detection is generally more accurate for audio context.
    if whisper_detected in SUPPORTED and whisper_language_prob > 0.7:
        return LanguageTag(whisper_detected)

    # 2. Text-based confirmation via langdetect.
    try:
        from langdetect import detect_langs  # type: ignore

        results = detect_langs(text)
        if results:
            top = results[0]
            if top.lang in LANGDETECT_TO_LANGUAGE_TAG and top.prob > 0.6:
                detected = LANGDETECT_TO_LANGUAGE_TAG[top.lang]
                if whisper_detected == detected or whisper_detected not in SUPPORTED:
                    return LanguageTag(detected)
    except Exception:
        # langdetect may raise on very short / mixed-script strings.
        pass

    # 3. Fall back to whisper even at lower confidence.
    if whisper_detected in SUPPORTED:
        return LanguageTag(whisper_detected)

    return LanguageTag.UNKNOWN
