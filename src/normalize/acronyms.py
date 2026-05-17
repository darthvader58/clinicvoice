"""English-only medical acronym expansion.

For non-English language tags the input is returned untouched — expansion
risks corrupting code-switched clinical phrasing in HI/UR/TA/ID/MS.
"""

from __future__ import annotations

import re
from typing import Dict

EN_ABBREVIATIONS: Dict[str, str] = {
    # lowercase clinical shorthand
    "pt": "patient",
    "pts": "patients",
    "hx": "history",
    "dx": "diagnosis",
    "tx": "treatment",
    "rx": "prescription",
    "sx": "symptoms",
    "px": "procedure",
    # uppercase conditions
    "MI": "myocardial infarction",
    "CHF": "congestive heart failure",
    "COPD": "chronic obstructive pulmonary disease",
    "HTN": "hypertension",
    "DM": "diabetes mellitus",
    "CKD": "chronic kidney disease",
    "AKI": "acute kidney injury",
    "UTI": "urinary tract infection",
    "CAP": "community-acquired pneumonia",
    "CVA": "cerebrovascular accident",
    "DVT": "deep vein thrombosis",
    "PE": "pulmonary embolism",
    "A-fib": "atrial fibrillation",
    "A fib": "atrial fibrillation",
    "GI": "gastrointestinal",
    "ENT": "ear nose and throat",
    "OD": "overdose",
    "ED": "emergency department",
    "ICU": "intensive care unit",
    "OR": "operating room",
    "SOB": "shortness of breath",
    "CP": "chest pain",
    "LOC": "loss of consciousness",
    "AMS": "altered mental status",
    "ARDS": "acute respiratory distress syndrome",
    "DKA": "diabetic ketoacidosis",
}


def expand_acronyms(text: str, language_tag: str) -> str:
    """Expand standalone medical abbreviations in English text.

    The match is a strict word-boundary match. Lowercase abbreviations are
    matched case-insensitively; uppercase abbreviations are matched exactly
    so that ordinary English words ("or", "ed") are not over-expanded.
    """

    if language_tag != "en" or not text:
        return text

    for abbr, expansion in EN_ABBREVIATIONS.items():
        pattern = rf"\b{re.escape(abbr)}\b"
        flags = re.IGNORECASE if abbr.islower() else 0
        text = re.sub(pattern, expansion, text, flags=flags)
    return text
