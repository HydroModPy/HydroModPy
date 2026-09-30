"""A lake in soil mode only sees the water the stream network routes to it.

The soil reservoir sends its recharge to the aquifer through drains, not
through a direct lake package: without ``"sfr"`` in ``flow.active_bc``, a lake
or a reservoir would never receive any of it.
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
active_bc = {active_bc}
first_period_steady = false

[flow.ic]
type = "steady_state"

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
"""


def _write(tmp_path: Path, active_bc: list[str]) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML.format(root=tmp_path.as_posix(), active_bc=active_bc),
        encoding="utf-8",
    )
    return config_path


@pytest.mark.parametrize("token", ["lake", "reservoir"])
def test_a_lake_or_reservoir_without_sfr_is_refused_by_name(tmp_path: Path, token: str) -> None:
    config_path = _write(tmp_path, ["drainage", token])

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        f'flow.active_bc lists "{token}" without "sfr": in soil mode the '
        "water that seeps out of the ground reaches a lake only through the "
        'stream network, so the lake would receive none of it. Add "sfr" '
        "with its [flow.sinks_sources.sfr] network, or remove "
        "[flow.sinks_sources.recharge.soil] and load [data.runoff] as before."
    ) in str(excinfo.value)


def test_a_lake_with_sfr_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, ["drainage", "lake", "sfr"])

    cfg = HydroModPyConfig.from_toml(config_path)

    assert "lake" in cfg.flow.active_bc
