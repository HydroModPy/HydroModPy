"""The printed water-budget block reads in mm/year, one line per fact.

``soil_budget_lines`` renders the block of spec section 5.2 from a
``SoilForcings``. A single-cell, single-year run under a steady climate
reaches its recharge on day one and holds it: every quantity is then exact
arithmetic, so the block's text is checked line by line against the
documented format.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
)
from hydromodpy.simulation.soil_recharge import (
    SoilColumns,
    SoilForcings,
    _no_negative_zero,
    soil_budget_lines,
)


def _forcings() -> SoilForcings:
    days = pd.date_range("2015-01-01", "2015-12-31", freq="D")
    n_days = len(days)
    precipitation = np.full((n_days, 1), 10.0)
    etp = np.full((n_days, 1), 2.0)
    params = SoilParameters(
        ru_mm=np.array([50.0]),
        alpha=1.0,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )
    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
    columns = SoilColumns(
        cell_index=np.array([0]),
        class_index=np.array([0]),
        x=np.array([0.0]),
        y=np.array([0.0]),
        ru_shape=np.array([1.0]),
        cell_fraction=np.array([1.0]),
        basin_weight=np.array([1.0]),
    )
    config = SoilReservoirConfig(ru=50.0, alpha=1.0, kc=1.0, spinup="none")
    return SoilForcings(
        recharge=None,
        residual_etp=None,
        runoff=None,
        days=days.values,
        precipitation=precipitation,
        etp=etp,
        fluxes=fluxes,
        columns=columns,
        config=config,
        parameters=params,
        spinup_cycles=0,
        never_full_columns=0,
        crs="EPSG:2154",
    )


def _lines():
    forcings = _forcings()
    ladder = ((50.0, 2920.0), (100.0, 2500.0))
    lines = soil_budget_lines(
        forcings,
        ladder=ladder,
        gauged_line="gauged discharge TEST: 300.0 mm/year on 365 of 365 days, catchment 10.00 km2",
        sent_to_evt=True,
    )
    return forcings, lines


def test_the_first_line_names_the_window_and_the_grid() -> None:
    _forcings_obj, lines = _lines()
    assert lines[0] == (
        "Soil reservoir, 2015-01-01 to 2015-12-31 (365 days), 1 SAFRAN cells, 1 capacity class each"
    )


def test_the_second_line_names_the_parameters() -> None:
    _forcings_obj, lines = _lines()
    assert lines[1] == "ru 50 mm, alpha 1, kc 1.0, impervious 0 %, bypass 0 %, transit time 0 days"


def test_the_third_line_says_the_soil_started_full() -> None:
    _forcings_obj, lines = _lines()
    assert lines[2] == 'starting soil: full (spinup = "none")'


def test_the_header_names_the_single_full_year_twice() -> None:
    _forcings_obj, lines = _lines()
    assert lines[3] == f"{'mm/year':<22}{'mean':>8}{'2015 least rain':>18}{'2015 most rain':>17}"


def test_the_data_rows_scale_the_mean_to_a_calendar_year() -> None:
    _forcings_obj, lines = _lines()
    scale = 365 / 365.25
    expected = {
        "precipitation": 3650.0,
        "ETP": 730.0,
        "ETR": 730.0,
        "recharge to MODFLOW": 2920.0,
        "impervious runoff": 0.0,
    }
    by_label = {line[:22].strip(): line for line in lines[4:9]}
    for label, total in expected.items():
        mean = total / scale
        assert by_label[label] == f"{label:<22}{mean:>8.1f}{total:>18.1f}{total:>17.1f}"


def test_the_storage_change_row_is_signed() -> None:
    _forcings_obj, lines = _lines()
    assert lines[9] == f"{'storage change':<22}{0.0:>+8.1f}{0.0:>+18.1f}{0.0:>+17.1f}"


def test_the_closure_row_stays_at_zero() -> None:
    _forcings_obj, lines = _lines()
    assert lines[10] == f"{'closure':<22}{0.0:>8.1f}{0.0:>18.1f}{0.0:>17.1f}"


def test_a_fully_satisfied_etp_reports_no_unmet_demand() -> None:
    _forcings_obj, lines = _lines()
    assert lines[11] == (
        "unmet ETP 0.0 mm/year, offered to EVT: the water table gives it only where it is shallow"
    )


def test_unmet_etp_names_the_missing_activation_when_not_sent() -> None:
    forcings = _forcings()
    lines = soil_budget_lines(
        forcings,
        ladder=(),
        gauged_line="gauged discharge: not shown, no [data.hydrometry] loaded",
        sent_to_evt=False,
    )
    unmet_line = next(line for line in lines if line.startswith("unmet ETP"))
    assert unmet_line == (
        'unmet ETP 0.0 mm/year, not sent to MODFLOW: add "etp" to '
        "flow.active_sinks_sources to let a shallow water table evaporate it"
    )


def test_the_summer_line_reads_the_steady_daily_rate() -> None:
    _forcings_obj, lines = _lines()
    summer_line = next(line for line in lines if line.startswith("recharge July-September"))
    assert summer_line == "recharge July-September: 8.000 mm/day"


def test_the_ladder_line_joins_every_value() -> None:
    _forcings_obj, lines = _lines()
    ladder_line = next(line for line in lines if line.startswith("recharge for other ru"))
    assert ladder_line == "recharge for other ru, mm/year: 50 mm 2920.0 | 100 mm 2500.0"


def test_the_gauged_discharge_line_is_appended_as_given() -> None:
    _forcings_obj, lines = _lines()
    assert (
        lines[-1] == "gauged discharge TEST: 300.0 mm/year on 365 of 365 days, catchment 10.00 km2"
    )


def test_a_value_that_rounds_to_zero_never_prints_a_negative_sign() -> None:
    assert f"{_no_negative_zero(-1e-16, 1):.1f}" == "0.0"
    assert f"{_no_negative_zero(-0.04, 1):.1f}" == "0.0"
    assert f"{_no_negative_zero(-0.05, 1):.1f}" == "-0.1"
