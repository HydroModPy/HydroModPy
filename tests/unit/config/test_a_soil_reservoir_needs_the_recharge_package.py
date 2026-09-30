"""A soil reservoir whose recharge is not activated would never reach MODFLOW.

``flow.active_sinks_sources`` is what turns a computed flux into an assembled
package; a soil section computes ``recharge`` whether or not the run lists it.
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
active_sinks_sources = {active_sinks_sources}
active_bc = ["drainage"]
first_period_steady = false

[flow.ic]
type = "steady_state"

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
"""


def _write(tmp_path: Path, active_sinks_sources: list[str]) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML.format(
            root=tmp_path.as_posix(), active_sinks_sources=active_sinks_sources
        ),
        encoding="utf-8",
    )
    return config_path


def test_recharge_missing_from_active_sinks_sources_is_refused(tmp_path: Path) -> None:
    config_path = _write(tmp_path, ["etp"])

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] computes a recharge that "
        "flow.active_sinks_sources does not list, so MODFLOW would receive "
        'none: add "recharge" to flow.active_sinks_sources.'
    ) in str(excinfo.value)


def test_recharge_listed_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, ["recharge", "etp"])

    cfg = HydroModPyConfig.from_toml(config_path)

    assert "recharge" in cfg.flow.active_sinks_sources
