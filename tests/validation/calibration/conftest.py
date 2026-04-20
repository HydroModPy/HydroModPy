"""Skip twin calibration validation tests that depend on the legacy launcher.

The ``validation_cases.calibration`` runtime imports the pre-P09
``ModelCalibrationLauncher`` tree, which was removed in favor of
``hydromodpy.calibration``. Re-enable these tests after porting the
validation-case runner to the new engine.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    skip_reason = pytest.mark.skip(
        reason="legacy calibration launcher removed in P09; porting pending"
    )
    for item in items:
        if "tests/validation/calibration/" in str(item.fspath):
            item.add_marker(skip_reason)


collect_ignore_glob = ["test_twin_*.py"]
