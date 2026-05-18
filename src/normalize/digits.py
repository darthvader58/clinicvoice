"""Collapse spaces inside digit runs so phone / ID patterns match.

When Whisper transcribes a phone number that the speaker said digit-by-
digit ("nine six five nine two nine"), the output looks like
``9 6 5 9 2 9``. Presidio's phone / NRIC / Aadhaar / CNIC recognizers
all expect contiguous digit runs, so the spaces cause them to miss.

This helper collapses any whitespace that sits between two digits,
turning ``9 6 5 9 2 9`` into ``965929`` while leaving ``9 + 5 = 14``
alone (the `+` and `=` break the digit run).
"""

from __future__ import annotations

import re

_DIGIT_GAP_RE = re.compile(r"(?<=\d)[ \t]+(?=\d)")


def collapse_digit_runs(text: str) -> str:
    if not text or " " not in text and "\t" not in text:
        return text
    return _DIGIT_GAP_RE.sub("", text)
