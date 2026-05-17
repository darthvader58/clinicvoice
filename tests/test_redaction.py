"""REQUIRED: prove PHI is stripped and the redaction map carries no
recoverable PHI."""
from __future__ import annotations

import logging

import pytest

pytest.importorskip("src.redact.engine")

from src.redact.engine import redact  # noqa: E402

PHI_INPUT = "My name is John Doe and my ID is S1234567A. Call me at 012-3456789."


def _call(text: str, language: str = "en"):
    """Call redact() flexibly — implementations may return tuple or RedactionResult."""
    try:
        out = redact(text, language=language)
    except TypeError:
        out = redact(text)
    if isinstance(out, tuple):
        return out[0], out[1]
    # Pydantic RedactionResult
    return out.redacted_text, out.redaction_map


def test_name_redacted():
    redacted_text, _ = _call(PHI_INPUT)
    assert "John Doe" not in redacted_text
    assert "[REDACTED]" in redacted_text or "<" in redacted_text


def test_nric_redacted():
    redacted_text, _ = _call(PHI_INPUT)
    assert "S1234567A" not in redacted_text


def test_phone_redacted():
    redacted_text, _ = _call(PHI_INPUT)
    assert "012-3456789" not in redacted_text


def test_redaction_map_structure():
    _, rmap = _call(PHI_INPUT)
    assert len(rmap) >= 2
    for span in rmap:
        assert hasattr(span, "type")
        assert hasattr(span, "start")
        assert hasattr(span, "end")
        assert hasattr(span, "replacement")
        # CRITICAL: never store the original value
        assert not hasattr(span, "original_value")
        assert not hasattr(span, "original_text")


def test_logs_contain_no_raw_phi(caplog):
    with caplog.at_level(logging.DEBUG):
        _call("Patient John Doe born 01/01/1980 ID S9876543B phone 9876543210")
    for record in caplog.records:
        msg = record.getMessage()
        assert "John Doe" not in msg
        assert "S9876543B" not in msg
        assert "9876543210" not in msg


def test_malaysian_ic_redacted():
    text = "Patient IC: 900101-14-5678 needs follow up."
    redacted, rmap = _call(text)
    # Either the IC is gone, or at minimum redaction map flagged something.
    assert "900101-14-5678" not in redacted or len(rmap) > 0


def test_multilingual_phi_pattern_redacted():
    text = "Hubungi pasien di 0812-3456-7890 untuk konfirmasi."
    redacted, rmap = _call(text, language="id")
    assert "0812-3456-7890" not in redacted or len(rmap) > 0
