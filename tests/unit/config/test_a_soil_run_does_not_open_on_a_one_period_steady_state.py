"""A soil run refuses to solve its first stress period as a steady state.

``flow.first_period_steady`` would solve the opening period under that
period's own recharge alone; a soil run sends a different value every day, so
the steady state that period would solve is not the one the run should start
from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.physics.hydrology.soil_reservoir.config import soil_reservoir_of

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
end_datetime = "2020-12-31"
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
first_period_steady = {first_period_steady}

[flow.ic]
type = "steady_state"

{soil_section}
"""

SOIL_SECTION = '[flow.sinks_sources.recharge.soil]\nru = "150 mm"\n'


def _write(tmp_path: Path, *, first_period_steady: bool, soil_section: str) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML.format(
            root=tmp_path.as_posix(),
            first_period_steady=str(first_period_steady).lower(),
            soil_section=soil_section,
        ),
        encoding="utf-8",
    )
    return config_path


def test_a_soil_run_with_a_steady_first_period_is_refused(tmp_path: Path) -> None:
    config_path = _write(tmp_path, first_period_steady=True, soil_section=SOIL_SECTION)

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] sends each day's recharge to "
        "MODFLOW, and flow.first_period_steady = true solves the first "
        "stress period (1 day) as a steady state under that period's "
        "recharge alone, zero after a dry day: the run would start from a "
        "drained aquifer. Write first_period_steady = false under [flow] "
        'and add [flow.ic] type = "steady_state", which starts the run from '
        "the steady state under the mean recharge of the whole run."
    ) in str(excinfo.value)


def test_a_soil_run_with_a_transient_first_period_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, first_period_steady=False, soil_section=SOIL_SECTION)

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.first_period_steady is False


def test_the_same_steady_first_period_without_soil_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, first_period_steady=True, soil_section="")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert soil_reservoir_of(cfg.flow) is None
