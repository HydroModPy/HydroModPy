"""A soil reservoir names the forcing and the time window it cannot run without.

``[flow.sinks_sources.recharge.soil]`` fills and empties day by day: it needs
daily precipitation and ETP, and a ``[simulation.time]`` window to walk.
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

{time_section}
[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[data]
types = {data_types}

{precipitation_section}
{etp_section}
[flow]
active_sinks_sources = ["recharge", "etp"]
active_bc = ["drainage"]
first_period_steady = false

[flow.ic]
type = "steady_state"

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
"""

TIME_SECTION = (
    "[simulation.time]\n"
    'start_datetime = "2015-01-01"\n'
    'end_datetime = "2020-12-31"\n'
    'step_value = "1 day"\n\n'
)
PRECIPITATION_SECTION = '[[data.precipitation.sources]]\nsource = "sim2"\nextent = "watershed"\n\n'
ETP_SECTION = '[[data.etp.sources]]\nsource = "sim2"\nextent = "watershed"\n\n'


def _write(
    tmp_path: Path,
    *,
    data_types: list[str],
    time_section: str = TIME_SECTION,
    precipitation_section: str = PRECIPITATION_SECTION,
    etp_section: str = ETP_SECTION,
) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML.format(
            root=tmp_path.as_posix(),
            data_types=data_types,
            time_section=time_section,
            precipitation_section=precipitation_section,
            etp_section=etp_section,
        ),
        encoding="utf-8",
    )
    return config_path


def test_no_precipitation_section_is_refused_by_name(tmp_path: Path) -> None:
    config_path = _write(tmp_path, data_types=["etp"], precipitation_section="")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] fills the soil with daily "
        "precipitation, and no [data.precipitation] section says where to "
        "read it: add a [[data.precipitation.sources]] block, for example "
        'source = "sim2" with extent = "watershed".'
    ) in str(excinfo.value)


def test_no_etp_section_is_refused_by_name(tmp_path: Path) -> None:
    config_path = _write(tmp_path, data_types=["precipitation"], etp_section="")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] empties the soil with daily ETP, "
        "and no [data.etp] section says where to read it: add a "
        '[[data.etp.sources]] block, for example source = "sim2" with extent '
        '= "watershed".'
    ) in str(excinfo.value)


def test_no_simulation_time_is_refused_by_name(tmp_path: Path) -> None:
    config_path = _write(tmp_path, data_types=["precipitation", "etp"], time_section="")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] runs day by day over "
        "[simulation.time], which this file does not declare: add "
        "start_datetime, end_datetime and step_value."
    ) in str(excinfo.value)


def test_all_three_declared_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, data_types=["precipitation", "etp"])

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.ru == 150.0
