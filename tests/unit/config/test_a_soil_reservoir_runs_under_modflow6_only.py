"""``[flow.sinks_sources.recharge.soil]`` is wired to MODFLOW 6 only.

The recharge and the unmet ETP it computes reach MODFLOW 6 through its own
RCHA/EVTA builders (``solver/modflow6/builders/recharge.py``); no other
backend reads them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import IncompatibleCapabilitiesError

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
solvers = ["{solver}"]

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
"""


def _write(tmp_path: Path, solver: str) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML.format(root=tmp_path.as_posix(), solver=solver),
        encoding="utf-8",
    )
    return config_path


@pytest.mark.parametrize("solver", ["modflow_nwt", "boussinesq"])
def test_a_non_modflow6_solver_is_refused_by_name(tmp_path: Path, solver: str) -> None:
    config_path = _write(tmp_path, solver)

    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] is wired to MODFLOW 6 only, and "
        f"this run's flow solver is {solver!r}: the recharge it computes "
        'would never reach that solver. Write solvers = ["modflow6"] in '
        "[[simulation.process]], or remove [flow.sinks_sources.recharge.soil] "
        "and declare [data.recharge]."
    ) in str(excinfo.value)


def test_modflow6_is_accepted(tmp_path: Path) -> None:
    config_path = _write(tmp_path, "modflow6")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.ru == 150.0
