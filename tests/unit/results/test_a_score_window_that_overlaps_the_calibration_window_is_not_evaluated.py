"""`evaluated` needs a score window that shares no day with the calibration window."""

from __future__ import annotations

from datetime import date

from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.record.checks import Checks
from hydromodpy.results.validity_rules import label_for
from tests._helpers.run_records import (
    WINDOW,
    make_calibrated_by,
    make_checks,
)

# The run is scored on 2016-01-01 to 2020-12-31 (WINDOW), 1827 samples.


def _label(calibration: DateWindow, **overrides):
    checks: Checks = make_checks(calibrated_by=make_calibrated_by(calibration), **overrides)
    return label_for(checks, hydromodpy_version="2.0.0a5", issues=())


def _window(start: tuple[int, int, int], end: tuple[int, int, int]) -> DateWindow:
    return DateWindow(start=date(*start), end=date(*end))


def test_equal_windows_stay_calibrated_without_an_overlap_reason():
    result = _label(WINDOW)

    assert result.label == "calibrated"
    assert len(result.reasons) == 1
