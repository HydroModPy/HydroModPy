"""Every trial is scored by blocks, so no objective is left beside them.

``ScalarObjective`` scored one metric over an ``ObservationSet`` with its own
station average, its own sign flip and no window, burn-in or sampling step.
Since decision m10 the one-line form is read as implicit blocks, and nothing
in the package built one any more: it is gone with the payload it read.
"""

from __future__ import annotations

import hydromodpy.calibration as calibration
from hydromodpy.calibration.optim import objective


def test_the_package_exports_no_objective_beside_the_blocks() -> None:
    for name in ("ScalarObjective", "ObservationSet"):
        assert name not in calibration.__all__
        assert not hasattr(calibration, name)
        assert not hasattr(objective, name)


def test_the_blocks_and_their_sum_remain() -> None:
    assert "ConfigBlockObjective" in calibration.__all__
    assert "CompositeObjective" in calibration.__all__
