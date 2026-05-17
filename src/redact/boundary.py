"""Send-to-model boundary enforcement.

Every text payload destined for a model call, external API, log line, or
storage write MUST be marked by `mark_as_redacted()` first. `send_to_model()`
refuses anything not bearing the marker by raising `RedactionBoundaryError`.

This is the runtime guarantee that complements the static rule "no
`raw_text` column anywhere". Together they enforce: raw transcript text
exists only inside the redaction engine's local scope.
"""
from __future__ import annotations

from typing import Any, Callable

_MARKER = "__CLINICVOICE_REDACTED__"


class RedactionBoundaryError(RuntimeError):
    """Raised when raw (unredacted) text is passed to `send_to_model()`."""


def mark_as_redacted(redacted_text: str) -> str:
    """Stamp a redacted string so it can pass the boundary.

    Only `src/redact/engine.py` (after calling `redact()`) should invoke this.
    """
    return f"{_MARKER}{redacted_text}"


def send_to_model(text: str, model_fn: Callable[[str], Any]) -> Any:
    """Mandatory gateway for any text leaving the redaction module.

    Raises `RedactionBoundaryError` if the input was not produced by
    `mark_as_redacted()`. On success, strips the marker and calls
    `model_fn` with the clean redacted text.
    """
    if not isinstance(text, str) or not text.startswith(_MARKER):
        raise RedactionBoundaryError(
            "send_to_model() requires text marked by mark_as_redacted(). "
            "Call redact() first. Raw text must never reach this function."
        )
    return model_fn(text[len(_MARKER):])


def assert_no_phi_in_logs(log_message: str) -> bool:
    """Heuristic PHI leak check used in tests.

    Returns True when none of the configured PHI patterns match the log
    string. Imports are local so this module stays cheap to import.
    """
    import re

    from src.redact.patterns import PHI_LOG_PATTERNS

    return not any(re.search(p, log_message) for p in PHI_LOG_PATTERNS)
