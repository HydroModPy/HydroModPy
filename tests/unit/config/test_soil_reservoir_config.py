"""Checks a project file must pass to run the soil reservoir of recharge.

``[flow.sinks_sources.recharge.soil]`` (ru in mm) fills and empties day by day.
It needs daily precipitation and ETP, a run of at least 52 weeks, and no other
source of recharge or runoff. Rates of a plain recharge (mm/day) are checked here too.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin

from hydromodpy.calibration.parameter_resolution import RECHARGE_VALUES_PATH
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.cli.commands import config as config_cmd
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data.loading.config_schema import DataConfig
from hydromodpy.data.variables.user_rasters import (
    FileSoilCapacitySource,
    SoilCapacityConfig,
)
from hydromodpy.model.boundaries.climate import (
    _peak_mm_day_of_a_recharge_source,
    apply_recharge_load_result_to_flow,
)

# A daily run with SIM2 precipitation and ETP and a soil of 150 mm. Each hole
# is one thing a case changes, the defaults give a file that loads.
SOIL_TOML = """
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
end_datetime = "{end_datetime}"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[data]
types = {data_types}
{precipitation}{etp}{loaded}
[flow]
first_period_steady = {first_period_steady}

[flow.ic]
kind = "steady_state"

[flow.bc.drainage]

[flow.sinks_sources.etp]

{recharge_table}
[flow.sinks_sources.recharge.soil]
ru = "150 mm"
{soil_keys}
{after_soil}"""

SIM2 = 'source = "sim2"\nextent = "watershed"\n'
HOLES = {
    "end_datetime": "2020-12-31",
    "data_types": '["precipitation", "etp"]',
    "precipitation": f"\n[[data.precipitation.sources]]\n{SIM2}",
    "etp": f"\n[[data.etp.sources]]\n{SIM2}",
    "loaded": "",
    "first_period_steady": "false",
    "recharge_table": "",
    "soil_keys": "",
    "after_soil": "",
}

LAKE = """
[flow.sinks_sources.lakes.pond]
bedleak = 1e-6
initial_stage = "10 m"
"""

# A type listed in data.types needs its section, or the file is refused before
# the soil reservoir is looked at.
LOADED_RECHARGE = f"\n[[data.recharge.sources]]\n{SIM2}"
LOADED_RUNOFF = f"\n[[data.runoff.sources]]\n{SIM2}"


def load_soil(tmp_path: Path, **holes: str) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(SOIL_TOML.format(**(HOLES | holes)), encoding="utf-8")
    return HydroModPyConfig.from_toml(path)


REFUSALS = [
    pytest.param(
        {"recharge_table": "[flow.sinks_sources.recharge]\nenabled = false\n"},
        "[flow.sinks_sources.recharge.soil] computes a recharge and its table "
        "says enabled = false, so MODFLOW would receive none: remove "
        "enabled = false, or remove the soil section.",
        id="recharge switched off",
    ),
    pytest.param(
        {"precipitation": f'\n[[data.precipitation.sources]]\n{SIM2}components = ["liquid"]\n'},
        "[data.precipitation] loads components = ['liquid'], and the "
        "soil reservoir takes one precipitation grid: two grids would be "
        'averaged, not added. Write components = ["total"], which counts the '
        "snow as rain.",
        id="liquid precipitation only",
    ),
    pytest.param(
        {
            "precipitation": f"\n[[data.precipitation.sources]]\n{SIM2}"
            'components = ["liquid", "solid"]\n'
        },
        "[data.precipitation] loads components = ['liquid', 'solid'], and the "
        "soil reservoir takes one precipitation grid: two grids would be "
        'averaged, not added. Write components = ["total"], which counts the '
        "snow as rain.",
        id="liquid and solid precipitation",
    ),
    pytest.param(
        {"first_period_steady": "true"},
        "[flow.sinks_sources.recharge.soil] sends each day's recharge to "
        "MODFLOW, and flow.first_period_steady = true solves the first "
        "stress period (1 day) as a steady state under that period's "
        "recharge alone, zero after a dry day: the run would start from a "
        "drained aquifer. Write first_period_steady = false under [flow] "
        'and add [flow.ic] kind = "steady_state", which starts the run from '
        "the steady state under the mean recharge of the whole run.",
        id="steady first period",
    ),
    pytest.param(
        # [2015-01-01, 2015-12-30) is 363 days.
        {"end_datetime": "2015-12-29", "soil_keys": 'spinup = "first_year"\n'},
        'spinup = "first_year" repeats the first 52 weeks (364 days) of the run, and '
        '[simulation.time] covers 363 days: write spinup = "none" under '
        "[flow.sinks_sources.recharge.soil] to start from a full soil, or "
        "extend the run to 52 weeks at least.",
        id="run shorter than a year",
    ),
    pytest.param(
        {"data_types": '["etp"]', "precipitation": ""},
        "[flow.sinks_sources.recharge.soil] fills the soil with daily "
        "precipitation, and no [data.precipitation] section says where to "
        "read it: add a [[data.precipitation.sources]] block, for example "
        'source = "sim2" with extent = "watershed".',
        id="no precipitation",
    ),
    pytest.param(
        {"data_types": '["precipitation"]', "etp": ""},
        "[flow.sinks_sources.recharge.soil] empties the soil with daily ETP, "
        "and no [data.etp] section says where to read it: add a "
        '[[data.etp.sources]] block, for example source = "sim2" with extent '
        '= "watershed".',
        id="no etp",
    ),
    pytest.param(
        {"data_types": '["precipitation", "etp", "recharge"]', "loaded": LOADED_RECHARGE},
        "[flow.sinks_sources.recharge.soil] computes the recharge from the "
        "precipitation and the ETP, and data.types also loads one from "
        "[data.recharge]: the model would receive one and ignore the other. "
        'Remove "recharge" from data.types to keep the soil reservoir (and '
        "write recharge__delete = true under [data] if a base file declares "
        "it), or remove [flow.sinks_sources.recharge.soil] to use the loaded "
        "recharge.",
        id="loaded recharge",
    ),
    pytest.param(
        {"data_types": '["precipitation", "etp", "runoff"]', "loaded": LOADED_RUNOFF},
        "[data.runoff] loads a surface runoff that already takes its share of "
        "the rain the soil reservoir receives (SIM2 RUNC, for instance): the "
        "streams, the lakes and the gauged discharge would count that water "
        'twice. Remove "runoff" from data.types (and write runoff__delete = '
        "true under [data] if a base file declares it); in soil mode the water "
        "that seeps out of saturated ground reaches the streams through the "
        "drains, and sealed ground through impervious_fraction.",
        id="loaded runoff",
    ),
    pytest.param(
        {"after_soil": LAKE},
        "[flow.sinks_sources.lakes] declares a lake with no stream network: in soil "
        "mode the water that seeps out of the ground reaches a lake only through the "
        "stream network, so the lake would receive none of it. Declare a "
        "[flow.sinks_sources.sfr] network, or remove [flow.sinks_sources.recharge.soil] "
        "and load [data.runoff] as before.",
        id="lake without a network",
    ),
    pytest.param(
        {"after_soil": LAKE + "[flow.sinks_sources.sfr.main]\nroute_drainage = false\n"},
        "route_drainage = false with a lake",
        id="lake with drainage not routed",
    ),
]


@pytest.mark.parametrize(("holes", "message"), REFUSALS)
def test_refusals(tmp_path: Path, holes: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigValidationError, match=re.escape(message)):
        load_soil(tmp_path, **holes)


def test_a_lake_with_a_network_loads(tmp_path: Path) -> None:
    cfg = load_soil(tmp_path, after_soil=LAKE + "[flow.sinks_sources.sfr.main]\n")

    assert {"lake", "sfr"} <= set(cfg.flow.active_bc)
    assert cfg.flow.sinks_sources.sfr["main"].route_drainage is True


def test_route_drainage_is_on_by_default() -> None:
    from hydromodpy.model.sinks_sources.sfr import FlowReachNetworkConfig

    assert FlowReachNetworkConfig.model_fields["route_drainage"].default is True


# A plain recharge (no soil) over one year of monthly steps.
RATE_TOML = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[simulation]
name = "recharge_rate_test"

[simulation.time]
start_datetime = "2015-01-01"
end_datetime = "2015-12-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[data]
types = {data_types}
{data_recharge}
[flow]

[flow.bc.drainage]

[flow.sinks_sources.recharge]
{recharge}
"""

LOADED = '["recharge"]', '[[data.recharge.sources]]\nsource = "synthetic"\nvalues = [1.0]\n'
NOT_LOADED = "[]", ""


def load_rate(tmp_path: Path, recharge: str, loaded: tuple[str, str]) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(
        RATE_TOML.format(data_types=loaded[0], data_recharge=loaded[1], recharge=recharge),
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(path)


RATE_REFUSALS = [
    pytest.param(
        "values = 7.0", LOADED, r"replaced by the series \[data.recharge\]", id="beside a series"
    ),
    pytest.param("values = 1500.0", NOT_LOADED, "beyond any daily rainfall", id="1500 mm/day"),
    pytest.param(
        'values = 2.0\nunits = "m/day"', NOT_LOADED, "beyond any daily rainfall", id="2 m/day"
    ),
    pytest.param(
        'values = [1.0, 5e-5]\nunits = "m/s"',
        NOT_LOADED,
        "beyond any daily rainfall",
        id="1 m/s in a list",
    ),
]


@pytest.mark.fast
@pytest.mark.parametrize(("recharge", "loaded", "message"), RATE_REFUSALS)
def test_rate_refusals(tmp_path: Path, recharge: str, loaded: tuple[str, str], message: str):
    with pytest.raises(ConfigValidationError, match=message):
        load_rate(tmp_path, recharge, loaded)


@pytest.mark.fast
@pytest.mark.parametrize(("loaded", "listed"), [(LOADED, False), (NOT_LOADED, True)])
def test_targets_drop_a_rate_the_run_replaces(
    tmp_path: Path, loaded: tuple[str, str], listed: bool, capsys
) -> None:
    load_rate(tmp_path, "values = 0.0", loaded)

    config_cmd._cmd_config_targets(
        SimpleNamespace(config=tmp_path / "project.toml", json=True, file=tmp_path / "project.toml")
    )

    assert (RECHARGE_VALUES_PATH in capsys.readouterr().out) is listed


def station(values: list[float]) -> SimpleNamespace:
    frame = pd.DataFrame(
        {"datetime": pd.date_range("2000-01-01", periods=len(values)), "value": values}
    )
    return SimpleNamespace(
        points=[SimpleNamespace(data=frame, location=None)],
        fields=[],
        has_fields=False,
        has_points=True,
    )


@pytest.mark.fast
def test_peak_of_a_station_source() -> None:
    assert _peak_mm_day_of_a_recharge_source(station([1.0, -3.0])) == pytest.approx(3.0)


@pytest.mark.fast
def test_recharge_left_out_of_the_active_list_is_said(caplog) -> None:
    flow = SimpleNamespace(
        active_sinks_sources=["etp"], sinks_sources={}, set_recharge=lambda config: None
    )

    with caplog.at_level(logging.WARNING, logger="hydromodpy.model.boundaries.climate"):
        apply_recharge_load_result_to_flow(flow=flow, recharge_result=station([1.0]))

    assert any("receives no recharge" in r.getMessage() for r in caplog.records)


def test_a_capacity_map_needs_a_soil_section(tmp_path: Path) -> None:
    raster = tmp_path / "ru.tif"
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        height=3,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, 100.0, 25.0, 25.0),
    ) as dst:
        dst.write(np.full((3, 4), 150.0, dtype="float32"), 1)
    data = DataConfig(
        soil_capacity=SoilCapacityConfig(sources=[FileSoilCapacitySource(path=raster)])
    )

    with pytest.raises(ValidationError, match=r"\[data.soil_capacity\]"):
        HydroModPyConfig(
            workflow={"mode": "simulation"},
            workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
            geographic=GeographicConfig(source_mode="synthetic"),
            data=data,
        )
