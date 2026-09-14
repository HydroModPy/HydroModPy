"""Transient multi-layer LAK validation (Plainfield Lakes abacus).

End-to-end validation of HMP's home-grown DISV LAK build on a multi-layer,
transient reservoir. One lake is incised across the TOP 2 layers of a 4-layer
aquifer on a structured-as-DISV grid; TDIS runs one initial steady period then
3 transient periods with per-period rainfall / evaporation / runoff. Two levels:

* STRUCTURAL: the generated CONNECTIONDATA carries one VERTICAL leakage per lake
  column plus HORIZONTAL bank seepage in BOTH occupied layers (proving the lake is
  incised across the top two layers);
* TRANSIENT: the per-period forcings move the lake stage by a meaningful swing and
  every period's LAK water balance closes within the documented envelope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from validation_cases.numerical.transient.lak_pleasant_transient.comparison import (
    load_tolerances,
    run_pleasant_transient_scenario,
)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
@pytest.mark.allow_subprocess
def test_lak_pleasant_transient_matches_tolerances(tmp_path: Path) -> None:
    scenario = run_pleasant_transient_scenario(workspace=tmp_path)
    tolerances = load_tolerances()
    structural_tol = dict(tolerances["structural"])
    stage_tol = dict(tolerances["stage"])
    budget_tol = dict(tolerances["budget"])

    # STRUCTURAL: multi-layer CONNECTIONDATA spans both occupied layers.
    assert scenario.structural.n_connections == int(structural_tol["n_connections"])
    assert scenario.structural.n_vertical == int(structural_tol["n_vertical"])
    assert scenario.structural.n_horizontal == int(structural_tol["n_horizontal"])
    assert scenario.structural.horizontal_by_layer.get(0, 0) == int(
        structural_tol["horizontal_layer_0"]
    )
    assert scenario.structural.horizontal_by_layer.get(1, 0) == int(
        structural_tol["horizontal_layer_1"]
    )
    assert scenario.structural.occupied_layers == int(structural_tol["occupied_layers"])
    assert scenario.structural.spans_occupied_layers

    # TRANSIENT: one stage per stress period, a meaningful swing, and per-period
    # water-balance closure within tolerance.
    assert scenario.n_periods == scenario.geometry.n_periods
    assert scenario.stage_swing_m >= float(stage_tol["min_stage_swing_m"])
    assert scenario.max_budget_percent_discrepancy <= float(
        budget_tol["budget_percent_discrepancy"]
    )

    # Sanity: the lake stays wet (above its bed) for every period and within the
    # abacus stage range, so the stage metric is meaningful.
    bed = scenario.geometry.bed_elevation_m
    abacus_stage_max = scenario.geometry.abacus_rows[-1][0]
    for stage in scenario.period_stages_m:
        assert bed < stage < abacus_stage_max
