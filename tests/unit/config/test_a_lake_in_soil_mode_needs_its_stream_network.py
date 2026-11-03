"""A lake in soil mode only sees the water the stream network routes to it.

The soil reservoir sends its recharge to the aquifer through drains, not
through a direct lake package: without a ``[flow.sinks_sources.sfr]`` network, a
lake would never receive any of it.
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

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
{tables}
"""

LAKE = """
[flow.sinks_sources.lakes.pond]
bedleak = 1e-6
initial_stage = "10 m"
"""


def _write(tmp_path: Path, tables: str = "") -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(SOIL_PROJECT_TOML.format(tables=tables), encoding="utf-8")
    return config_path


def test_a_lake_without_a_network_is_refused(tmp_path: Path) -> None:
    config_path = _write(tmp_path, LAKE)

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.lakes] declares a lake with no stream network: in soil "
        "mode the water that seeps out of the ground reaches a lake only through the "
        "stream network, so the lake would receive none of it. Declare a "
        "[flow.sinks_sources.sfr] network, or remove [flow.sinks_sources.recharge.soil] "
        "and load [data.runoff] as before."
    ) in str(excinfo.value)


def test_a_lake_with_a_network_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, LAKE + "[flow.sinks_sources.sfr.main]\n")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert {"lake", "sfr"} <= set(cfg.flow.active_bc)


def _write_with_network(tmp_path: Path, network_lines: str) -> Path:
    return _write(tmp_path, LAKE + "[flow.sinks_sources.sfr.main]\n" + network_lines)


def test_route_drainage_is_on_by_default() -> None:
    from hydromodpy.physics.flow.sinks_sources.sfr import FlowReachNetworkConfig

    assert FlowReachNetworkConfig.model_fields["route_drainage"].default is True


def test_a_lake_in_soil_mode_refuses_route_drainage_off(tmp_path: Path) -> None:
    config_path = _write_with_network(tmp_path, "route_drainage = false\n")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert "route_drainage = false with a lake" in str(excinfo.value)


def test_a_lake_in_soil_mode_accepts_the_default_route_drainage(tmp_path: Path) -> None:
    config_path = _write_with_network(tmp_path, "")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.sfr["main"].route_drainage is True
