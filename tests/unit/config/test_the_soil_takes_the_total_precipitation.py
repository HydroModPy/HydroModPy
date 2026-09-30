"""The soil reservoir reads one precipitation grid: total, not liquid or solid.

Splitting rain and snow gives two grids the soil would have to average rather
than add, so ``[data.precipitation]`` must declare ``components = ["total"]``
when a soil section is present.
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
components = {components}

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
"""


def _write(tmp_path: Path, components: list[str]) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML.format(root=tmp_path.as_posix(), components=components),
        encoding="utf-8",
    )
    return config_path


@pytest.mark.parametrize("components", [["liquid"], ["liquid", "solid"]])
def test_components_other_than_total_are_refused(tmp_path: Path, components: list[str]) -> None:
    config_path = _write(tmp_path, components)

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        f"[data.precipitation] loads components = {components!r}, and the "
        "soil reservoir takes one precipitation grid: two grids would be "
        'averaged, not added. Write components = ["total"], which counts the '
        "snow as rain."
    ) in str(excinfo.value)


def test_total_alone_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, ["total"])

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.data.precipitation.sources[0].components == ["total"]
