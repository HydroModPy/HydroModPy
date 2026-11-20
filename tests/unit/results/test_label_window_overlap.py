"""Label of a run whose score window and calibration window share days.

A run is scored on 2016-01-01 to 2020-12-31 (WINDOW), 1827 daily samples.
`evaluated` needs a score window with no day in common with the calibration window.
"""

from __future__ import annotations

from hydromodpy.results.validity_rules import label_for
from tests._helpers.run_records import WINDOW, make_calibrated_by, make_checks


def test_equal_windows_stay_calibrated() -> None:
    checks = make_checks(calibrated_by=make_calibrated_by(WINDOW))

    result = label_for(checks, hydromodpy_version="2.0.0a5", issues=())

    assert result.label == "calibrated"
    assert len(result.reasons) == 1
