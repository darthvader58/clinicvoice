"""Romanize non-English text for display.

Whisper outputs in the script of the detected language (Devanagari for
Hindi, Arabic script for Urdu, Tamil script for Tamil, etc.). A clinician
reviewing the demo may not read those scripts, so we render a Latin/ASCII
transliteration alongside the canonical text.

Uses ``anyascii`` — pure-Python, ~345 KB, covers every Unicode script.
This is a presentation concern only; the canonical ``redacted_text`` stays
in the original script for downstream consumers (Nightingale, audit).
"""

from __future__ import annotations

from typing import Optional

from anyascii import anyascii  # type: ignore

# Languages we surface in the UI. EN already uses Latin script, so we skip
# the transliteration pass — anyascii would no-op anyway but skipping saves
# work and signals intent.
_NEEDS_ROMAN = {"hi", "ur", "ta"}
# Indonesian / Malay are already Latin-script. English is too. Both pass
# through untouched.


def to_roman(text: str, language: Optional[str]) -> Optional[str]:
    """Return a Latin-script transliteration of ``text`` when relevant.

    Returns ``None`` when no romanization is needed (English, Indonesian,
    Malay, or empty text) so callers can omit the field in API responses
    instead of duplicating identical strings.
    """

    if not text:
        return None
    if not language or language in {"en", "id", "ms"}:
        return None
    if language not in _NEEDS_ROMAN and language != "unknown":
        # Unknown language → still romanize defensively; better readable.
        pass
    return anyascii(text)
