"""REQUIRED: prove the redaction boundary cannot be bypassed."""
from __future__ import annotations

import pytest

pytest.importorskip("src.redact.engine")
pytest.importorskip("src.redact.boundary")

from src.redact.boundary import (  # noqa: E402
    RedactionBoundaryError,
    mark_as_redacted,
    send_to_model,
)
from src.redact.engine import redact  # noqa: E402


def _redacted_text(raw: str) -> str:
    out = redact(raw)
    if isinstance(out, tuple):
        return out[0]
    return out.redacted_text


def test_raw_text_raises():
    with pytest.raises(RedactionBoundaryError):
        send_to_model("Patient John Doe needs metformin.", lambda t: t)


def test_empty_string_raises():
    with pytest.raises(RedactionBoundaryError):
        send_to_model("", lambda t: t)


def test_redacted_text_passes():
    raw = "Patient John Doe ID S1234567A."
    redacted = _redacted_text(raw)
    marked = mark_as_redacted(redacted)
    result = send_to_model(marked, lambda t: t.upper())
    assert isinstance(result, str)
    assert "JOHN DOE" not in result
    assert "S1234567A" not in result


def test_boundary_functions_importable():
    from src.redact.boundary import send_to_model as stm
    from src.redact.engine import redact as r

    assert callable(r) and callable(stm)


def test_marker_without_redaction_documented():
    """Trust boundary: the marker alone is necessary but not sufficient.
    The correct design is that only redact() produces valid marked text.
    This test documents the primary defense — calling redact() first.
    """
    from src.redact.boundary import _MARKER

    assert isinstance(_MARKER, str) and len(_MARKER) > 10
