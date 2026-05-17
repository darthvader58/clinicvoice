"""Custom Presidio recognizers for clinic PHI across 6 locales.

EN coverage uses Presidio's built-in NER (en_core_web_sm) plus all patterns
below. HI/UR/TA/ID/MS coverage is pattern-only — names won't be caught for
those languages; that limitation is documented in the project README.

Also exports `PHI_LOG_PATTERNS` — a compact regex set used by the logging
filter and `assert_no_phi_in_logs` test helper to verify nothing leaks.
"""
from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer


class MedicalRecordRecognizer(PatternRecognizer):
    """Generic MRN / patient-ID strings such as 'MRN: AB12345' or 'Patient ID 9001'."""

    PATTERNS = [
        Pattern("MRN_FORMAT_1", r"\bMR[N#]?\s*[:\-]?\s*[A-Z0-9]{4,10}\b", 0.9),
        Pattern(
            "MRN_FORMAT_2",
            r"\b[Mm]edical\s+[Rr]ecord\s+(?:[Nn]umber\s+)?\d{6,10}\b",
            0.95,
        ),
        Pattern("PATIENT_ID", r"\b[Pp]atient\s+ID\s*[:\-]?\s*[A-Z0-9]{4,12}\b", 0.85),
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="MEDICAL_RECORD_NUMBER", patterns=self.PATTERNS
        )


class SingaporeNRICRecognizer(PatternRecognizer):
    """Singapore NRIC / FIN: S/T/F/G/M + 7 digits + checksum letter."""

    PATTERNS = [Pattern("NRIC_SG", r"\b[STFGM]\d{7}[A-Z]\b", 0.95)]

    def __init__(self) -> None:
        super().__init__(supported_entity="NRIC_SG", patterns=self.PATTERNS)


class MalaysianICRecognizer(PatternRecognizer):
    """Malaysian IC: YYMMDD-PB-NNNN."""

    PATTERNS = [Pattern("MY_IC", r"\b\d{6}-\d{2}-\d{4}\b", 0.90)]

    def __init__(self) -> None:
        super().__init__(supported_entity="IC_MY", patterns=self.PATTERNS)


class IndianPhoneRecognizer(PatternRecognizer):
    """Indian mobile: optional +91/0 prefix then 10 digits starting 6-9."""

    PATTERNS = [Pattern("IN_PHONE", r"\b(?:\+91|0)?[6-9]\d{9}\b", 0.85)]

    def __init__(self) -> None:
        super().__init__(supported_entity="PHONE_IN", patterns=self.PATTERNS)


class SingaporePhoneRecognizer(PatternRecognizer):
    """Singapore 8-digit phone starting 6/8/9."""

    PATTERNS = [Pattern("SG_PHONE", r"\b[689]\d{7}\b", 0.80)]

    def __init__(self) -> None:
        super().__init__(supported_entity="PHONE_NUMBER", patterns=self.PATTERNS)


class MalaysianPhoneRecognizer(PatternRecognizer):
    """Malaysian mobile: optional +60/0 prefix, 01X-XXXXXXXX."""

    PATTERNS = [Pattern("MY_PHONE", r"\b(?:\+60|0)1[0-9]-?\d{7,8}\b", 0.85)]

    def __init__(self) -> None:
        super().__init__(supported_entity="PHONE_NUMBER", patterns=self.PATTERNS)


class PakistaniCNICRecognizer(PatternRecognizer):
    """Pakistani CNIC: XXXXX-XXXXXXX-X."""

    PATTERNS = [Pattern("PK_CNIC", r"\b\d{5}-\d{7}-\d{1}\b", 0.92)]

    def __init__(self) -> None:
        super().__init__(supported_entity="CNIC_PK", patterns=self.PATTERNS)


class IndonesianNIKRecognizer(PatternRecognizer):
    """Indonesian NIK: 16 digits.

    Score intentionally lower than other ID recognizers because 16-digit
    sequences collide with credit cards and other numerics.
    """

    PATTERNS = [Pattern("NIK_ID", r"\b\d{16}\b", 0.75)]

    def __init__(self) -> None:
        super().__init__(supported_entity="NIK_INDONESIA", patterns=self.PATTERNS)


class DOBRecognizer(PatternRecognizer):
    """Dates of birth in slash, dash, or 'born/DOB:' textual forms."""

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
        super().__init__(supported_entity="DATE_OF_BIRTH", patterns=self.PATTERNS)


# All custom recognizer instances — wired into the analyzer registry in engine.py
ALL_CUSTOM_RECOGNIZERS = [
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


# Patterns used by the PHI logging filter and `assert_no_phi_in_logs` test helper.
# Kept as a compact subset of the recognizer regexes — tuned for false-negative
# avoidance over precision (logs must not leak PHI).
PHI_LOG_PATTERNS = [
    r"\b[STFGM]\d{7}[A-Z]\b",                  # NRIC SG
    r"\b\d{6}-\d{2}-\d{4}\b",                  # MY IC
    r"\b(?:\+91|0)?[6-9]\d{9}\b",              # IN phone
    r"\b\d{5}-\d{7}-\d{1}\b",                  # PK CNIC
    r"\bMR[N#]?\s*[:\-]?\s*[A-Z0-9]{4,10}\b",  # MRN
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",              # DOB
]
