"""English-only casing normalization.

Ensures medical acronyms are uppercase, frequency shorthand is lowercase,
and generic drug names are lowercased (proprietary names stay capitalized).
Non-English text passes through unchanged.
"""

from __future__ import annotations

from typing import Dict, Set

ALWAYS_UPPER: Set[str] = {
    "ECG", "EEG", "MRI", "CT", "CBC", "BMP", "ABG", "INR", "GCS",
    "IV", "IM", "SQ", "ICU", "ED", "OR", "HEENT", "PERRLA", "PT",
    "PTT", "DVT", "PE", "GI", "CPR", "AED", "NICU", "PICU",
}

ALWAYS_LOWER_ABBR: Set[str] = {
    "bid", "tid", "qid", "prn", "po", "sc", "sq", "qd", "npo",
}

# Generic drug names should be lowercase. The mapping handles common
# capitalized variants emitted by Whisper.
TITLE_CASE_DRUGS: Dict[str, str] = {
    "Metformin": "metformin",
    "Atorvastatin": "atorvastatin",
    "Lisinopril": "lisinopril",
    "Amlodipine": "amlodipine",
    "Metoprolol": "metoprolol",
    "Losartan": "losartan",
    "Simvastatin": "simvastatin",
    "Levothyroxine": "levothyroxine",
    "Omeprazole": "omeprazole",
    "Pantoprazole": "pantoprazole",
    "Amoxicillin": "amoxicillin",
    "Azithromycin": "azithromycin",
    "Ceftriaxone": "ceftriaxone",
    "Vancomycin": "vancomycin",
    "Warfarin": "warfarin",
    "Heparin": "heparin",
    "Aspirin": "aspirin",
    "Clopidogrel": "clopidogrel",
    "Furosemide": "furosemide",
    "Spironolactone": "spironolactone",
    "Insulin": "insulin",
    "Glipizide": "glipizide",
    "Prednisone": "prednisone",
    "Ibuprofen": "ibuprofen",
    "Acetaminophen": "acetaminophen",
    "Morphine": "morphine",
    "Fentanyl": "fentanyl",
}

_PUNCT_STRIP = ".,;:()[]?!\"'"


def normalize_casing(text: str, language_tag: str) -> str:
    """Apply casing rules to English text only.

    Splits on whitespace, then strips trailing punctuation per token so that
    ``"ecg."`` is detected as ``ECG``. Punctuation is reattached after the
    casing decision.
    """

    if language_tag != "en" or not text:
        return text

    words = text.split()
    result = []
    for i, word in enumerate(words):
        clean = word.strip(_PUNCT_STRIP)
        # Preserve leading punctuation as well as trailing.
        leading_len = len(word) - len(word.lstrip(_PUNCT_STRIP))
        leading = word[:leading_len]
        trailing = word[leading_len + len(clean):]

        if not clean:
            result.append(word)
            continue

        if clean.upper() in ALWAYS_UPPER:
            result.append(leading + clean.upper() + trailing)
        elif clean.lower() in ALWAYS_LOWER_ABBR:
            result.append(leading + clean.lower() + trailing)
        elif clean in TITLE_CASE_DRUGS:
            result.append(leading + TITLE_CASE_DRUGS[clean] + trailing)
        elif clean.capitalize() in TITLE_CASE_DRUGS:
            result.append(leading + TITLE_CASE_DRUGS[clean.capitalize()] + trailing)
        elif i == 0:
            result.append(leading + clean[:1].upper() + clean[1:] + trailing)
        else:
            result.append(word)
    return " ".join(result)
