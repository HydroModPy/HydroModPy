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

from hydromodpy.model.forcing.soil_budget import _no_negative_zero, soil_budget_lines
from hydromodpy.model.forcing.soil_columns import SoilColumns
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.forcing.soil_forcing import SoilForcings
from hydromodpy.model.soil.kernel import SoilParameters, full_soil, run_soil_balance


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


def test_the_third_line_says_the_soil_started_full() -> None:
    _forcings_obj, lines = _lines()
    assert lines[2] == 'starting soil: full (spinup = "none")'


def test_the_storage_change_row_is_signed() -> None:
    _forcings_obj, lines = _lines()
    assert lines[9] == f"{'storage change':<22}{0.0:>+8.1f}{0.0:>+18.1f}{0.0:>+17.1f}"


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
        "[flow.sinks_sources.etp] to let a shallow water table evaporate it"
    )


def test_a_value_that_rounds_to_zero_never_prints_a_negative_sign() -> None:
    assert f"{_no_negative_zero(-1e-16, 1):.1f}" == "0.0"
    assert f"{_no_negative_zero(-0.04, 1):.1f}" == "0.0"
    assert f"{_no_negative_zero(-0.05, 1):.1f}" == "-0.1"
