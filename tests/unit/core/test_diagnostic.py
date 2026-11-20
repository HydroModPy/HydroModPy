"""The one shape of a finding of a check: its pointer, its record, its line."""

from __future__ import annotations

import pytest

from hydromodpy.core.diagnostic import Diagnostic


@pytest.mark.parametrize(
    ("diagnostic", "line"),
    [
        (
            Diagnostic("calibration.parameters.K", "calibration_preflight", "error", "no bounds"),
            "ERROR   calibration.parameters.K: no bounds",
        ),
        (
            Diagnostic("", "cross_warning", "warning", "one layer"),
            "WARNING <document>: one layer",
        ),
        (
            Diagnostic("geographic", "to_fill", "to_fill", "required"),
            "TO_FILL geographic: required",
        ),
    ],
)
def test_a_diagnostic_prints_as_one_line(diagnostic: Diagnostic, line: str) -> None:
    assert diagnostic.line() == line


def test_a_diagnostic_is_frozen() -> None:
    diagnostic = Diagnostic("geographic", "to_fill", "to_fill")
    with pytest.raises(AttributeError):
        diagnostic.code = "unknown_key"  # type: ignore[misc]
