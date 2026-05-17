"""Redaction schemas — Pydantic v2 models for the PHI boundary.

CRITICAL: No model in this file may carry the original (pre-redaction) text.
Any field that could hold raw PHI is intentionally absent.
"""
from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class RedactionType(str, Enum):
    """Entity types this system can redact.

    Mirrors Presidio entity names where possible so values map 1:1.
    """

    PERSON = "PERSON"
    PHONE = "PHONE_NUMBER"
    EMAIL = "EMAIL_ADDRESS"
    DOB = "DATE_OF_BIRTH"
    LOCATION = "LOCATION"
    MRN = "MEDICAL_RECORD_NUMBER"
    NRIC = "NRIC_SG"
    MY_IC = "IC_MY"
    IN_PHONE = "PHONE_IN"
    PK_CNIC = "CNIC_PK"
    ID_IN = "AADHAAR"
    NIK_ID = "NIK_INDONESIA"


class RedactionSpan(BaseModel):
    """A single redacted region in a transcript.

    CRITICAL: no `original_value` field — ever. Only offsets and the
    replacement marker are stored so the original PHI cannot be recovered
    from the redaction map.
    """

    type: RedactionType
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    replacement: str = "[REDACTED]"


class RedactionResult(BaseModel):
    """Result of running `redact()` over a single text input.

    CRITICAL: no `original_text` field — ever. The raw transcript dies
    at the redaction boundary; only the redacted form survives.
    """

    redacted_text: str
    redaction_map: List[RedactionSpan]
    original_char_count: int = Field(ge=0)
    redacted_count: int = Field(ge=0)
    language: str
