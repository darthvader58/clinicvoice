"""Custom Presidio recognizers for clinical PHI across six languages.

Pattern recognizers fire on text regardless of NLP language because they are
pure regex — they cover all of EN, HI, UR, TA, ID, MS where structural PHI
(IDs, phone numbers, DOBs) typically remains in standard formats even when
prose is code-switched.
"""

from __future__ import annotations

from typing import List

from presidio_analyzer import Pattern, PatternRecognizer


class MedicalRecordRecognizer(PatternRecognizer):
    PATTERNS = [
        Pattern("MRN_FORMAT_1", r"\bMR[N#]?\s*[:\-]?\s*[A-Z0-9]{4,10}\b", 0.9),
        Pattern(
            "MRN_FORMAT_2",
            r"\b[Mm]edical\s+[Rr]ecord\s+(?:[Nn]umber\s+)?\d{6,10}\b",
            0.95,
        ),
        Pattern(
            "PATIENT_ID",
            r"\b[Pp]atient\s+ID\s*[:\-]?\s*[A-Z0-9]{4,12}\b",
            0.85,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="MEDICAL_RECORD_NUMBER",
            patterns=self.PATTERNS,
        )


class SingaporeNRICRecognizer(PatternRecognizer):
    PATTERNS = [Pattern("NRIC_SG", r"\b[STFGM]\d{7}[A-Z]\b", 0.95)]

    def __init__(self) -> None:
        super().__init__(supported_entity="NRIC_SG", patterns=self.PATTERNS)


class MalaysianICRecognizer(PatternRecognizer):
    PATTERNS = [Pattern("MY_IC", r"\b\d{6}-\d{2}-\d{4}\b", 0.90)]

    def __init__(self) -> None:
        super().__init__(supported_entity="IC_MY", patterns=self.PATTERNS)


class IndianPhoneRecognizer(PatternRecognizer):
    PATTERNS = [Pattern("IN_PHONE", r"\b(?:\+91|0)?[6-9]\d{9}\b", 0.85)]

    def __init__(self) -> None:
        super().__init__(supported_entity="PHONE_IN", patterns=self.PATTERNS)


class SingaporePhoneRecognizer(PatternRecognizer):
    PATTERNS = [Pattern("SG_PHONE", r"\b[689]\d{7}\b", 0.80)]

    def __init__(self) -> None:
        super().__init__(supported_entity="PHONE_NUMBER", patterns=self.PATTERNS)


class MalaysianPhoneRecognizer(PatternRecognizer):
    PATTERNS = [Pattern("MY_PHONE", r"\b(?:\+60|0)1[0-9]-?\d{7,8}\b", 0.85)]

    def __init__(self) -> None:
        super().__init__(supported_entity="PHONE_NUMBER", patterns=self.PATTERNS)


class PakistaniCNICRecognizer(PatternRecognizer):
    PATTERNS = [Pattern("PK_CNIC", r"\b\d{5}-\d{7}-\d{1}\b", 0.92)]

    def __init__(self) -> None:
        super().__init__(supported_entity="CNIC_PK", patterns=self.PATTERNS)


class IndonesianNIKRecognizer(PatternRecognizer):
    # Lower score due to bare 16-digit collision risk with other numerics.
    PATTERNS = [Pattern("NIK_ID", r"\b\d{16}\b", 0.75)]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="NIK_INDONESIA", patterns=self.PATTERNS
        )


class DOBRecognizer(PatternRecognizer):
    PATTERNS = [
        Pattern("DOB_SLASH", r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", 0.75),
        Pattern("DOB_DASH", r"\b\d{4}-\d{2}-\d{2}\b", 0.80),
        Pattern(
            "DOB_TEXT",
            r"\b(?:born|DOB|date of birth)[:\s]+\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b",
            0.90,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="DATE_OF_BIRTH", patterns=self.PATTERNS
        )


ALL_CUSTOM_RECOGNIZERS: List[PatternRecognizer] = [
    MedicalRecordRecognizer(),
    SingaporeNRICRecognizer(),
    MalaysianICRecognizer(),
    IndianPhoneRecognizer(),
    SingaporePhoneRecognizer(),
    MalaysianPhoneRecognizer(),
    PakistaniCNICRecognizer(),
    IndonesianNIKRecognizer(),
    DOBRecognizer(),
]


PHI_LOG_PATTERNS: List[str] = [
    r"\b[STFGM]\d{7}[A-Z]\b",
    r"\b\d{6}-\d{2}-\d{4}\b",
    r"\b(?:\+91|0)?[6-9]\d{9}\b",
    r"\b\d{5}-\d{7}-\d{1}\b",
    r"\bMR[N#]?\s*[:\-]?\s*[A-Z0-9]{4,10}\b",
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",
]
