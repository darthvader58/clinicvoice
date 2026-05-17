"""English-only dosage and unit normalization.

Standardizes spacing around mg/mL/mcg, expands frequency shorthand
(BID/TID/QID/PRN…) and route shorthand (PO/IV/IM/SQ), and normalizes
blood-pressure utterances. Non-English passes through unchanged.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Tuple shape: (pattern, replacement, flags)
UNIT_PATTERNS: List[Tuple[str, str, int]] = [
    # spacing fixes for common units
    (r"(\d+)\s*mg\b", r"\1 mg", 0),
    (r"(\d+)\s*mL\b", r"\1 mL", re.IGNORECASE),
    (r"(\d+)\s*mcg\b", r"\1 mcg", 0),
    (r"(\d+)\s*units?\b", r"\1 unit(s)", 0),
    # frequency
    (r"\bBID\b", "twice daily", 0),
    (r"\bbid\b", "twice daily", 0),
    (r"\bTID\b", "three times daily", 0),
    (r"\btid\b", "three times daily", 0),
    (r"\bQID\b", "four times daily", 0),
    (r"\bqid\b", "four times daily", 0),
    (r"\bPRN\b", "as needed", 0),
    (r"\bprn\b", "as needed", 0),
    (r"\bQD\b", "once daily", 0),
    (r"\bqd\b", "once daily", 0),
    # route
    (r"\bPO\b", "by mouth", 0),
    (r"\bpo\b", "by mouth", 0),
    (r"\bIV\b", "intravenously", 0),
    (r"\bIM\b", "intramuscularly", 0),
    (r"\bSQ\b", "subcutaneously", 0),
    (r"\bSC\b", "subcutaneously", 0),
    (r"\bNPO\b", "nothing by mouth", 0),
    # interval shorthand: q6h → "every 6 hours"
    (r"q(\d+)h\b", r"every \1 hours", re.IGNORECASE),
    # blood pressure spacing
    (r"(\d+)/(\d+)\s*mmHg", r"\1/\2 mmHg", 0),
    (r"\bbp\s+(\d+)/(\d+)\b", r"blood pressure \1/\2 mmHg", re.IGNORECASE),
]


def normalize_units(text: str, language_tag: str) -> str:
    """Apply unit/frequency/route normalization to English text only."""

    if language_tag != "en" or not text:
        return text

    for pattern, replacement, flags in UNIT_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=flags)
    return text
