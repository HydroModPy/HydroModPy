"""A calibration file loads with the defaults of its project, as the runners read it.

``[site] gauge`` is the station a point output observes when it names none,
and ``[metrics] window`` the scoring window when the section writes none. The
calibration runners applied them; ``from_toml``, and so ``hmp config check``,
did not, and refused a file the run accepted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError

pytestmark = pytest.mark.unit

DOCUMENT = """\
[site]
name = "nancon"
gauge = "NANCON"

[metrics]
window = { start = "2001-01-01", end = "2002-12-31" }

[geographic]
source_mode = "synthetic"

[flow]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[calibration]
method = "grid"
max_trials = 3

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
target = "flow.param.K.field.value"

[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
{observes}
[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse"
uses_outputs = ["hydrograph"]
"""


def _write(tmp_path: Path, observes: str = "") -> Path:
    path = tmp_path / "calage.toml"
    path.write_text(DOCUMENT.replace("{observes}", observes), encoding="utf-8")
    return path


def test_a_point_output_that_names_no_station_observes_the_gauge(tmp_path) -> None:
    cfg = HydroModPyConfig.from_toml(_write(tmp_path))

    assert cfg.calibration is not None
    assert cfg.calibration.outputs["hydrograph"].observes == "NANCON"


def test_the_metrics_window_is_the_scoring_window(tmp_path) -> None:
    cfg = HydroModPyConfig.from_toml(_write(tmp_path))

    window = cfg.calibration.window
    assert (window.start, window.end) == ("2001-01-01", "2002-12-31")


def test_a_station_that_is_not_the_gauge_is_refused_with_both_keys(tmp_path) -> None:
    with pytest.raises(ConfigValidationError, match="NANCON") as caught:
        HydroModPyConfig.from_toml(_write(tmp_path, observes='observes = "OTHER"'))

    assert "OTHER" in str(caught.value)
