from __future__ import annotations

import logging
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
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError, IncompatibleCapabilitiesError
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data.loading.config_schema import DataManagersConfig
from hydromodpy.data.variables.soil_capacity.config import (
    CustomSoilCapacitySource,
    SoilCapacityConfig,
)
from hydromodpy.model.boundaries.climate import (
    _peak_mm_day_of_a_recharge_source,
    apply_recharge_load_result_to_flow,
)
from hydromodpy.model.forcing.validation import refuse_an_impossible_recharge
from hydromodpy.model.soil.config import soil_reservoir_of

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


SOIL_PROJECT_TOML_2 = """
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
kind = "steady_state"

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
"""


def _write_2(tmp_path: Path, solver: str) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML_2.format(root=tmp_path.as_posix(), solver=solver),
        encoding="utf-8",
    )
    return config_path


@pytest.mark.parametrize("solver", ["modflow_nwt", "boussinesq"])
def test_a_non_modflow6_solver_is_refused_by_name(tmp_path: Path, solver: str) -> None:
    config_path = _write_2(tmp_path, solver)

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
    config_path = _write_2(tmp_path, "modflow6")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.ru == 150.0


SOIL_PROJECT_TOML_3 = """
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
components = {components}

[[data.etp.sources]]
source = "sim2"
extent = "watershed"

[flow]
active_sinks_sources = ["recharge", "etp"]
active_bc = ["drainage"]
first_period_steady = false

[flow.ic]
kind = "steady_state"

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
"""


def _write_3(tmp_path: Path, components: list[str]) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML_3.format(root=tmp_path.as_posix(), components=components),
        encoding="utf-8",
    )
    return config_path


@pytest.mark.parametrize("components", [["liquid"], ["liquid", "solid"]])
def test_components_other_than_total_are_refused(tmp_path: Path, components: list[str]) -> None:
    config_path = _write_3(tmp_path, components)

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        f"[data.precipitation] loads components = {components!r}, and the "
        "soil reservoir takes one precipitation grid: two grids would be "
        'averaged, not added. Write components = ["total"], which counts the '
        "snow as rain."
    ) in str(excinfo.value)


def test_total_alone_loads(tmp_path: Path) -> None:
    config_path = _write_3(tmp_path, ["total"])

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.data.precipitation.sources[0].components == ["total"]


SOIL_PROJECT_TOML_4 = """
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
first_period_steady = {first_period_steady}

[flow.ic]
kind = "steady_state"

[flow.bc.drainage]

[flow.sinks_sources.etp]

{soil_section}
"""


SOIL_SECTION = '[flow.sinks_sources.recharge.soil]\nru = "150 mm"\n'


def _write_4(tmp_path: Path, *, first_period_steady: bool, soil_section: str) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML_4.format(
            root=tmp_path.as_posix(),
            first_period_steady=str(first_period_steady).lower(),
            soil_section=soil_section,
        ),
        encoding="utf-8",
    )
    return config_path


def test_a_soil_run_with_a_steady_first_period_is_refused(tmp_path: Path) -> None:
    config_path = _write_4(tmp_path, first_period_steady=True, soil_section=SOIL_SECTION)

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] sends each day's recharge to "
        "MODFLOW, and flow.first_period_steady = true solves the first "
        "stress period (1 day) as a steady state under that period's "
        "recharge alone, zero after a dry day: the run would start from a "
        "drained aquifer. Write first_period_steady = false under [flow] "
        'and add [flow.ic] kind = "steady_state", which starts the run from '
        "the steady state under the mean recharge of the whole run."
    ) in str(excinfo.value)


def test_a_soil_run_with_a_transient_first_period_loads(tmp_path: Path) -> None:
    config_path = _write_4(tmp_path, first_period_steady=False, soil_section=SOIL_SECTION)

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.first_period_steady is False


def test_the_same_steady_first_period_without_soil_loads(tmp_path: Path) -> None:
    config_path = _write_4(tmp_path, first_period_steady=True, soil_section="")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert soil_reservoir_of(cfg.flow) is None


SOIL_PROJECT_TOML_5 = """
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
kind = "steady_state"

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
spinup = "{spinup}"
"""


def _write_5(tmp_path: Path, *, end_datetime: str, spinup: str) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML_5.format(
            root=tmp_path.as_posix(), end_datetime=end_datetime, spinup=spinup
        ),
        encoding="utf-8",
    )
    return config_path


def test_a_run_shorter_than_a_year_is_refused_by_name(tmp_path: Path) -> None:
    # [2015-01-01, 2015-12-30) is 363 days.
    config_path = _write_5(tmp_path, end_datetime="2015-12-29", spinup="first_year")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        'spinup = "first_year" repeats the first 52 weeks (364 days) of the run, and '
        '[simulation.time] covers 363 days: write spinup = "none" under '
        "[flow.sinks_sources.recharge.soil] to start from a full soil, or "
        "extend the run to 52 weeks at least."
    ) in str(excinfo.value)


def test_a_run_of_52_weeks_loads(tmp_path: Path) -> None:
    # [2015-01-01, 2015-12-31) is 364 days.
    config_path = _write_5(tmp_path, end_datetime="2015-12-30", spinup="first_year")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.spinup == "first_year"


def test_a_run_of_exactly_a_year_loads(tmp_path: Path) -> None:
    config_path = _write_5(tmp_path, end_datetime="2015-12-31", spinup="first_year")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.spinup == "first_year"


def test_no_spinup_needs_no_year(tmp_path: Path) -> None:
    config_path = _write_5(tmp_path, end_datetime="2015-12-30", spinup="none")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.spinup == "none"


# A soil reservoir names the forcing and the time window it cannot run without.
#
# ``[flow.sinks_sources.recharge.soil]`` fills and empties day by day: it needs
# daily precipitation and ETP, and a ``[simulation.time]`` window to walk.


SOIL_PROJECT_TOML_6 = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[simulation]
name = "soil_config_test"

{time_section}
[[simulation.process]]
id = "flow_main"
kind = "flow"
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
kind = "steady_state"

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


def _write_6(
    tmp_path: Path,
    *,
    data_types: list[str],
    time_section: str = TIME_SECTION,
    precipitation_section: str = PRECIPITATION_SECTION,
    etp_section: str = ETP_SECTION,
) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML_6.format(
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
    config_path = _write_6(tmp_path, data_types=["etp"], precipitation_section="")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] fills the soil with daily "
        "precipitation, and no [data.precipitation] section says where to "
        "read it: add a [[data.precipitation.sources]] block, for example "
        'source = "sim2" with extent = "watershed".'
    ) in str(excinfo.value)


def test_no_etp_section_is_refused_by_name(tmp_path: Path) -> None:
    config_path = _write_6(tmp_path, data_types=["precipitation"], etp_section="")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] empties the soil with daily ETP, "
        "and no [data.etp] section says where to read it: add a "
        '[[data.etp.sources]] block, for example source = "sim2" with extent '
        '= "watershed".'
    ) in str(excinfo.value)


def test_no_simulation_time_is_refused_by_name(tmp_path: Path) -> None:
    config_path = _write_6(tmp_path, data_types=["precipitation", "etp"], time_section="")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.recharge.soil] runs day by day over "
        "[simulation.time], which this file does not declare: add "
        "start_datetime, end_datetime and step_value."
    ) in str(excinfo.value)


def test_all_three_declared_loads(tmp_path: Path) -> None:
    config_path = _write_6(tmp_path, data_types=["precipitation", "etp"])

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.ru == 150.0


# A soil reservoir and a loaded recharge or runoff would both reach the model.
#
# ``[flow.sinks_sources.recharge.soil]`` computes the recharge itself; a
# ``[data.recharge]`` or ``[data.runoff]`` section loaded beside it would add,
# or double-count, a flux the soil already produces. ``data.types`` is read as
# declared here: neither family is ever inferred (``data/loading/planner.py``).


SOIL_PROJECT_TOML_7 = """
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
kind = "steady_state"

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
"""


def _write_7(tmp_path: Path, data_types: list[str]) -> Path:
    # A type listed in data.types needs its section, or the file is refused
    # before the soil reservoir is looked at.
    extra_sections = "".join(
        f'\n[[data.{name}.sources]]\nsource = "sim2"\nextent = "watershed"\n'
        for name in data_types
        if name in ("recharge", "runoff")
    )
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        SOIL_PROJECT_TOML_7.format(
            root=tmp_path.as_posix(),
            data_types=data_types,
            extra_sections=extra_sections,
        ),
        encoding="utf-8",
    )
    return config_path


def test_a_loaded_recharge_beside_the_soil_is_refused(tmp_path: Path) -> None:
    config_path = _write_7(tmp_path, ["precipitation", "etp", "recharge"])

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
    config_path = _write_7(tmp_path, ["precipitation", "etp", "runoff"])

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
    config_path = _write_7(tmp_path, ["precipitation", "etp"])

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.ru == 150.0


# A rate written beside a loaded recharge, or beyond any rainfall, is refused.
#
# ``values`` beside ``[data.recharge]`` was dropped without a word, and a wrong unit
# passed at 2392 mm/day. A recharge left out of ``active_sinks_sources`` gave zero and
# said nothing.


PROJECT_TOML = """
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
active_sinks_sources = ["recharge"]
active_bc = ["drainage"]

[flow.sinks_sources.recharge]
{recharge}
"""


LOADED = '["recharge"]', '[[data.recharge.sources]]\nsource = "synthetic"\nvalues = [1.0]\n'


NOT_LOADED = "[]", ""


def _load(tmp_path: Path, recharge: str, loaded: tuple[str, str]) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(
        PROJECT_TOML.format(data_types=loaded[0], data_recharge=loaded[1], recharge=recharge),
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(path)


@pytest.mark.fast
def test_a_rate_beside_a_loaded_recharge_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match=r"replaced by the series \[data.recharge\]"):
        _load(tmp_path, "values = 7.0", LOADED)


@pytest.mark.fast
def test_a_zero_beside_a_loaded_recharge_is_the_default_a_frozen_config_spells(
    tmp_path: Path,
) -> None:
    _load(tmp_path, "values = 0.0", LOADED)


@pytest.mark.fast
def test_a_rate_without_a_loaded_recharge_stays(tmp_path: Path) -> None:
    _load(tmp_path, "values = 7.0", NOT_LOADED)


@pytest.mark.fast
@pytest.mark.parametrize(("loaded", "listed"), [(LOADED, False), (NOT_LOADED, True)])
def test_the_targets_listing_drops_a_rate_the_run_replaces(
    tmp_path: Path, loaded: tuple[str, str], listed: bool, capsys
) -> None:
    _load(tmp_path, "values = 0.0", loaded)

    config_cmd._cmd_config_targets(
        SimpleNamespace(config=tmp_path / "project.toml", json=True, file=tmp_path / "project.toml")
    )

    assert (RECHARGE_VALUES_PATH in capsys.readouterr().out) is listed


@pytest.mark.parametrize(
    "recharge",
    ["values = 1500.0", 'values = 2.0\nunits = "m/day"', 'values = [1.0, 5e-5]\nunits = "m/s"'],
)
def test_a_rate_beyond_any_rainfall_is_refused(tmp_path: Path, recharge: str) -> None:
    with pytest.raises(ConfigValidationError, match="beyond any daily rainfall"):
        _load(tmp_path, recharge, NOT_LOADED)


@pytest.mark.fast
def test_a_heavy_but_possible_rate_passes(tmp_path: Path) -> None:
    _load(tmp_path, "values = 500.0", NOT_LOADED)


@pytest.mark.fast
def test_a_loaded_rate_beyond_any_rainfall_is_refused() -> None:
    with pytest.raises(ValueError, match="2392 mm/day"):
        refuse_an_impossible_recharge(2392.0, label="[data.recharge]")


def _flow(active: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        active_sinks_sources=active,
        sinks_sources={},
        set_recharge=lambda config: None,
    )


def _station(values: list[float]) -> SimpleNamespace:
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
def test_the_peak_of_a_station_source_reads_its_values() -> None:
    assert _peak_mm_day_of_a_recharge_source(_station([1.0, -3.0])) == pytest.approx(3.0)


@pytest.mark.fast
def test_a_recharge_left_out_of_the_active_list_is_said(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.model.boundaries.climate"):
        apply_recharge_load_result_to_flow(flow=_flow(["etp"]), recharge_result=_station([1.0]))

    assert any("receives no recharge" in r.getMessage() for r in caplog.records)


@pytest.mark.fast
def test_an_active_recharge_says_nothing(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.model.boundaries.climate"):
        apply_recharge_load_result_to_flow(
            flow=_flow(["recharge"]), recharge_result=_station([1.0])
        )

    assert not any("receives no recharge" in r.getMessage() for r in caplog.records)


@pytest.mark.fast
def test_a_zero_series_has_no_peak() -> None:
    assert _peak_mm_day_of_a_recharge_source(_station([0.0, 0.0])) == 0.0
    assert np.isfinite(_peak_mm_day_of_a_recharge_source(_station([0.0])))


# A soil capacity raster without a soil reservoir would never be read.
#
# ``[data.soil_capacity]`` spreads the ``ru`` of
# ``[flow.sinks_sources.recharge.soil]`` over classes: without that section the
# raster has nothing to spread and would be loaded for no reader.


def _write_geotiff(path: Path) -> Path:
    data = np.full((3, 4), 150.0, dtype="float32")
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, 100.0, 25.0, 25.0),
    ) as dst:
        dst.write(data, 1)
    return path


def _base_kwargs(tmp_path: Path) -> dict:
    return {
        "workflow": {"mode": "simulation"},
        "workspace": WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        "geographic": GeographicConfig(source_mode="synthetic"),
    }


def test_a_capacity_map_without_a_soil_section_is_rejected(tmp_path: Path) -> None:
    raster = _write_geotiff(tmp_path / "ru.tif")
    data = DataManagersConfig(
        soil_capacity=SoilCapacityConfig(sources=[CustomSoilCapacitySource(path=raster)])
    )

    with pytest.raises(ValidationError, match=r"\[data.soil_capacity\]"):
        HydroModPyConfig(**_base_kwargs(tmp_path), data=data)


def test_a_capacity_map_without_a_soil_section_names_the_fix(tmp_path: Path) -> None:
    raster = _write_geotiff(tmp_path / "ru.tif")
    data = DataManagersConfig(
        soil_capacity=SoilCapacityConfig(sources=[CustomSoilCapacitySource(path=raster)])
    )

    with pytest.raises(ValidationError) as excinfo:
        HydroModPyConfig(**_base_kwargs(tmp_path), data=data)

    assert "declare the soil section, or remove [data.soil_capacity]" in str(excinfo.value)
