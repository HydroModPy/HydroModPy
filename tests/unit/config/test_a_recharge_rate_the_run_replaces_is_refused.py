"""A rate written beside a loaded recharge, or beyond any rainfall, is refused.

``values`` beside ``[data.recharge]`` was dropped without a word, and a wrong unit
passed at 2392 mm/day. A recharge left out of ``active_sinks_sources`` gave zero and
said nothing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.parameter_resolution import RECHARGE_VALUES_PATH
from hydromodpy.cli.commands import config as config_cmd
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.physics.flow.structure_binders import (
    _peak_mm_day_of_a_recharge_source,
    apply_recharge_load_result_to_flow,
)
from hydromodpy.physics.forcing.validation import refuse_an_impossible_recharge

pytestmark = pytest.mark.fast


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
type = "flow"
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


def test_a_rate_beside_a_loaded_recharge_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match=r"replaced by the series \[data.recharge\]"):
        _load(tmp_path, "values = 7.0", LOADED)


def test_a_zero_beside_a_loaded_recharge_is_the_default_a_frozen_config_spells(
    tmp_path: Path,
) -> None:
    _load(tmp_path, "values = 0.0", LOADED)


def test_a_rate_without_a_loaded_recharge_stays(tmp_path: Path) -> None:
    _load(tmp_path, "values = 7.0", NOT_LOADED)


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


def test_a_heavy_but_possible_rate_passes(tmp_path: Path) -> None:
    _load(tmp_path, "values = 500.0", NOT_LOADED)


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


def test_the_peak_of_a_station_source_reads_its_values() -> None:
    assert _peak_mm_day_of_a_recharge_source(_station([1.0, -3.0])) == pytest.approx(3.0)


def test_a_recharge_left_out_of_the_active_list_is_said(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.physics.flow.structure_binders"):
        apply_recharge_load_result_to_flow(flow=_flow(["etp"]), recharge_result=_station([1.0]))

    assert any("receives no recharge" in r.getMessage() for r in caplog.records)


def test_an_active_recharge_says_nothing(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.physics.flow.structure_binders"):
        apply_recharge_load_result_to_flow(
            flow=_flow(["recharge"]), recharge_result=_station([1.0])
        )

    assert not any("receives no recharge" in r.getMessage() for r in caplog.records)


def test_a_zero_series_has_no_peak() -> None:
    assert _peak_mm_day_of_a_recharge_source(_station([0.0, 0.0])) == 0.0
    assert np.isfinite(_peak_mm_day_of_a_recharge_source(_station([0.0])))
