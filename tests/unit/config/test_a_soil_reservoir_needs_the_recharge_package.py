"""A soil reservoir whose recharge is switched off would never reach MODFLOW.

A recharge table builds the package unless it says ``enabled = false``; a soil
section computes a recharge whether or not the table is on.
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
kind = "flow"
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
first_period_steady = false

[flow.ic]
kind = "steady_state"

[flow.bc.drainage]

[flow.sinks_sources.etp]

{recharge}
[flow.sinks_sources.recharge.soil]
ru = "150 mm"
"""


def _write(tmp_path: Path, recharge: str = "") -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(SOIL_PROJECT_TOML.format(recharge=recharge), encoding="utf-8")
    return config_path


def test_a_switched_off_recharge_is_refused(tmp_path: Path) -> None:
    config_path = _write(tmp_path, "[flow.sinks_sources.recharge]\nenabled = false\n")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] computes a recharge and its table "
        "says enabled = false, so MODFLOW would receive none: remove "
        "enabled = false, or remove the soil section."
    ) in str(excinfo.value)


def test_a_declared_soil_activates_the_recharge(tmp_path: Path) -> None:
    config_path = _write(tmp_path)

    cfg = HydroModPyConfig.from_toml(config_path)

    assert "recharge" in cfg.flow.active_sinks_sources
