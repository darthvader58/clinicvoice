"""Schemas for the redaction layer.

Hard invariants:
- RedactionSpan never carries the original PHI substring.
- RedactionResult never carries the original (pre-redaction) text.
"""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class RedactionType(str, Enum):
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
    type: RedactionType
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    replacement: str


class RedactionResult(BaseModel):
    redacted_text: str
    redaction_map: List[RedactionSpan]
    original_char_count: int = Field(..., ge=0)
    redacted_count: int = Field(..., ge=0)
    language: str
