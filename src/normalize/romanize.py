"""Romanize non-English text for display.

Whisper outputs in the script of the detected language (Devanagari for
Hindi, Arabic script for Urdu, Tamil script for Tamil, etc.). A clinician
reviewing the demo may not read those scripts, so we render a Latin/ASCII
transliteration alongside the canonical text.

Strategy:
- Devanagari (hi) and Tamil (ta) go through ``indic-transliteration`` in
  the Velthuis scheme then a small cleanup pass that strips its marker
  characters. Produces vowel-full ASCII output like ``meraa naama
  raajesa hai`` — readable to English speakers.
- Arabic script (ur) falls back to ``anyascii``. The script genuinely
  does not write short vowels, so we get consonant-heavy output by
  design. To get vowels for Hindi-speaking patients, pick "Hindi" in
  the dropdown so Whisper outputs Devanagari instead.
- English (en), Indonesian (id), Malay (ms) are already Latin and
  return ``None`` so the field can be omitted in API responses.

This is a presentation concern only; the canonical ``redacted_text``
stays in the original script for downstream consumers (Nightingale,
audit trail).
"""

from __future__ import annotations

import re
from typing import Optional

from anyascii import anyascii  # type: ignore

# Languages that need transliteration. EN already uses Latin script.
# Indonesian / Malay are also already Latin. Both pass through untouched.
_LATIN_LANGS = {"en", "id", "ms"}

# Indic scripts where indic-transliteration's Velthuis scheme produces
# better (vowel-full) output than anyascii's character-level mapping.
# Maps the language tag → source script enum name for the library.
_INDIC_LANG_TO_SCRIPT = {
    "hi": "devanagari",  # Whisper outputs Devanagari for Hindi
    # Tamil intentionally omitted — indic-transliteration's Tamil output
    # leaves source chars un-mapped (`èன` instead of `e na`). anyascii
    # gives more consistent (still imperfect) Latin for Tamil.
}

# Velthuis scheme uses ASCII markers for retroflex/aspirate/anusvara that
# look like noise (`"sa`, `.m`, `~n`). Strip them for casual readability.
# Convert the Devanagari sentence-end danda (|) and double danda (||) into
# ordinary punctuation.
_VELTHUIS_NOISE_RE = re.compile(r'["~_]|\.(?=[mnhrs])')
_DANDA_RE = re.compile(r"\|\|?")


def _clean_velthuis(text: str) -> str:
    text = _VELTHUIS_NOISE_RE.sub("", text)
    text = _DANDA_RE.sub(".", text)
    return text


def to_roman(text: str, language: Optional[str]) -> Optional[str]:
    """Return a Latin-script transliteration of ``text`` when relevant.

    Returns ``None`` when no romanization is needed (English, Indonesian,
    Malay, or empty text) so callers can omit the field in API responses
    instead of duplicating identical strings.
    """

    if not text:
        return None
    if not language or language in _LATIN_LANGS:
        return None

    script = _INDIC_LANG_TO_SCRIPT.get(language)
    if script is not None:
        try:
            from indic_transliteration.sanscript import (  # type: ignore
                transliterate,
            )

            return _clean_velthuis(transliterate(text, script, "velthuis"))
        except Exception:
            # Library mishap → fall through to anyascii so we still emit
            # something readable instead of swallowing the segment.
            pass

    # Arabic script (ur) and any other script: character-level mapping.
    return anyascii(text)
