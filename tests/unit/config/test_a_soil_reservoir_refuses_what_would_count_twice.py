"""A soil reservoir and a loaded recharge or runoff would both reach the model.

``[flow.sinks_sources.recharge.soil]`` computes the recharge itself; a
``[data.recharge]`` or ``[data.runoff]`` section loaded beside it would add,
or double-count, a flux the soil already produces. ``data.types`` is read as
declared here: neither family is ever inferred (``data/loading/planner.py``).
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
types = {data_types}

[[data.precipitation.sources]]
source = "sim2"
extent = "watershed"

[[data.etp.sources]]
source = "sim2"
extent = "watershed"
{extra_sections}
[flow]
active_sinks_sources = ["recharge", "etp"]
active_bc = ["drainage"]
first_period_steady = false

[flow.ic]
type = "steady_state"

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
"""


def _write(tmp_path: Path, data_types: list[str]) -> Path:
    # A type listed in data.types needs its section, or the file is refused
    # before the soil reservoir is looked at.
    extra_sections = "".join(
        f'\n[[data.{name}.sources]]\nsource = "sim2"\nextent = "watershed"\n'
        for name in data_types
        if name in ("recharge", "runoff")
    )
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML.format(
            root=tmp_path.as_posix(),
            data_types=data_types,
            extra_sections=extra_sections,
        ),
        encoding="utf-8",
    )
    return config_path


def test_a_loaded_recharge_beside_the_soil_is_refused(tmp_path: Path) -> None:
    config_path = _write(tmp_path, ["precipitation", "etp", "recharge"])

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] computes the recharge from the "
        "precipitation and the ETP, and data.types also loads one from "
        "[data.recharge]: the model would receive one and ignore the other. "
        'Remove "recharge" from data.types to keep the soil reservoir (and '
        "write recharge__delete = true under [data] if a base file declares "
        "it), or remove [flow.sinks_sources.recharge.soil] to use the loaded "
        "recharge."
    ) in str(excinfo.value)


def test_a_loaded_runoff_beside_the_soil_is_refused(tmp_path: Path) -> None:
    config_path = _write(tmp_path, ["precipitation", "etp", "runoff"])

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[data.runoff] loads a surface runoff that already takes its share of "
        "the rain the soil reservoir receives (SIM2 RUNC, for instance): the "
        "streams, the lakes and the gauged discharge would count that water "
        'twice. Remove "runoff" from data.types (and write runoff__delete = '
        "true under [data] if a base file declares it); in soil mode the water "
        "that seeps out of saturated ground reaches the streams through the "
        "drains, and sealed ground through impervious_fraction."
    ) in str(excinfo.value)


def test_neither_recharge_nor_runoff_declared_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, ["precipitation", "etp"])

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.ru == 150.0
