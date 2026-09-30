"""``spinup = "first_year"`` needs a run of at least one year to repeat.

The default spin-up repeats the first 365 days of the run until the soil
storage settles; a run shorter than that has no first year to repeat.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError

SOIL_PROJECT_TOML = """
[workflow]
mode = "simulation"

[workspace]
project_root = "{root}"

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[simulation]
name = "soil_config_test"

[simulation.time]
start_datetime = "2015-01-01"
end_datetime = "{end_datetime}"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[data]
types = ["precipitation", "etp"]

[[data.precipitation.sources]]
source = "sim2"
extent = "watershed"

[[data.etp.sources]]
source = "sim2"
extent = "watershed"

[flow]
active_sinks_sources = ["recharge", "etp"]
active_bc = ["drainage"]
first_period_steady = false

[flow.ic]
type = "steady_state"

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
spinup = "{spinup}"
"""


def _write(tmp_path: Path, *, end_datetime: str, spinup: str) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML.format(
            root=tmp_path.as_posix(), end_datetime=end_datetime, spinup=spinup
        ),
        encoding="utf-8",
    )
    return config_path


def test_a_run_shorter_than_a_year_is_refused_by_name(tmp_path: Path) -> None:
    # [2015-01-01, 2015-12-31) is 364 days.
    config_path = _write(tmp_path, end_datetime="2015-12-30", spinup="first_year")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        'spinup = "first_year" repeats the first 365 days of the run, and '
        '[simulation.time] covers 364 days: write spinup = "none" under '
        "[flow.sinks_sources.recharge.soil] to start from a full soil, or "
        "extend the run to one year at least."
    ) in str(excinfo.value)


def test_a_run_of_exactly_a_year_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, end_datetime="2015-12-31", spinup="first_year")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.spinup == "first_year"


def test_no_spinup_needs_no_year(tmp_path: Path) -> None:
    config_path = _write(tmp_path, end_datetime="2015-12-30", spinup="none")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.spinup == "none"
