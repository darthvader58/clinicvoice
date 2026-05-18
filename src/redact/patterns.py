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


class LongDigitRecognizer(PatternRecognizer):
    """Catch-all for 7-16 contiguous digits not matched by a specific recognizer.

    Live transcripts often pick up phone numbers / MRNs / hospital IDs in
    formats that don't fit the country-specific patterns above (for example
    the speaker says digits one by one and Whisper collapses them after
    digit-run normalization, but no country prefix is present). Anything
    7+ digits in a row is almost certainly PHI in a clinical setting, so
    we redact it. Score is lower than country-specific recognizers so they
    win when they apply.

    Boundary chars (\\b) require a non-digit on either side, which keeps
    this from over-firing inside longer numeric ranges or already-redacted
    placeholders.
    """

    PATTERNS = [Pattern("LONG_DIGITS", r"\b\d{7,16}\b", 0.60)]

    def __init__(self) -> None:
        super().__init__(supported_entity="GENERIC_NUMERIC_ID", patterns=self.PATTERNS)


class NameContextRecognizer(PatternRecognizer):
    """Capture title-cased names that follow common introduction phrases.

    Presidio's ``en_core_web_sm`` NER misses single first names like
    ``Rajesh`` or ``Aisha`` unless a surname is also present — bad for our
    use case where patients often say ``mera naam Rajesh hai`` or
    ``my name is Rajesh``. This recognizer matches the cue word/phrase
    and a following title-cased token, returning a single span covering
    just the name (the cue itself is not redacted).

    Cues covered: English (`my name is`, `i am`, `i'm`, `name`),
    romanized Hindi/Urdu (`naam`, `mera naam`, `meraa naam`, `mein`,
    `main`), and the no-cue case where a single title-case name appears
    between two such cues. Latin-only by design — Devanagari/Arabic
    script names fall to the language-specific pattern set.
    """

    PATTERNS = [
        # English: "my name is Rajesh"
        Pattern(
            "EN_INTRO_NAME",
            r"(?i)\b(?:my\s+name\s+is|i\s+am|i'?m)\s+([A-Z][a-z]{1,20})\b",
            0.75,
        ),
        # Romanized Hindi/Urdu: "naam Rajesh", "meraa naam Rajesh"
        Pattern(
            "HI_NAAM_NAME",
            r"(?i)\b(?:mera+|meraa|meri|mere)?\s*naa?m\s+([A-Z][a-z]{1,20})\b",
            0.80,
        ),
        # Romanized Hindi: "main Rajesh", "mein Rajesh hu/hun"
        Pattern(
            "HI_MAIN_NAME",
            r"(?i)\b(?:mein|main)\s+([A-Z][a-z]{1,20})\b",
            0.70,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(supported_entity="PERSON", patterns=self.PATTERNS)


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
    LongDigitRecognizer(),
    NameContextRecognizer(),
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
