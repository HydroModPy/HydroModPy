"""Skip only the legacy twin calibration tests.

The ``test_twin_*.py`` files depend on the pre-P09 ``ModelCalibrationLauncher``
tree that was removed in favour of ``hydromodpy.calibration``. Re-enable them
after porting ``validation_cases.calibration.shared.runtime`` to the new
engine. Other tests in this directory (e.g. standalone groundwater /
recession / reservoir cases built on the new engine) are collected normally.
"""

from __future__ import annotations

collect_ignore_glob = ["test_twin_*.py"]
