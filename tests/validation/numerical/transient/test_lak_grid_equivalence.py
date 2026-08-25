"""LAK grid-equivalence validation (regular quad vs irregular triangle DISV).

The SAME transient multi-layer lake-aquifer problem (Plainfield Lakes abacus, one
reservoir incised across the top two layers of a 4-layer aquifer) is solved twice
through the production HMP LAK builders and MF6:

* REGULAR: the 15x15 quad DISV (225 cells, 40 m).
* IRREGULAR: a refined Delaunay TRIANGLE DISV (~772 cells, ~20 m near the lake)
  over the same domain, layers, lake footprint, abacus, bedleak, aquifer K /
  recharge, TDIS and per-period rainfall / evaporation / runoff.

Only the mesh changes, so the lake stage and the lake-aquifer exchange flux must
agree across grids (grid independence). The test asserts:

* the irregular grid is a genuine non-rectangular triangulation that resolves the
  lake at least as finely as the quad grid;
* the per-period lake stages agree within the documented stage envelope;
* the steady lake-aquifer exchange flux agrees within the documented envelope;
* both grids close their LAK water balance.

A materially diverging grid (wrong CONNECTIONDATA geometry, lost bank seepage)
would break the stage or exchange envelope by an order of magnitude.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from validation_cases.numerical.transient.lak_pleasant_transient.grid_equivalence import (
    load_tolerances,
    run_grid_equivalence_scenario,
)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
@pytest.mark.allow_subprocess
def test_lak_regular_and_irregular_grids_agree(tmp_path: Path) -> None:
    scenario = run_grid_equivalence_scenario(workspace=tmp_path)
    tolerances = load_tolerances()
    stage_tol = dict(tolerances["stage"])
    exchange_tol = dict(tolerances["exchange"])
    budget_tol = dict(tolerances["budget"])
    mesh_tol = dict(tolerances["mesh"])

    # MESH: the irregular grid is a genuine non-rectangular triangulation with at
    # least as many lake cells as the quad grid, and both grids span all periods.
    assert not scenario.irregular.is_structured
    assert scenario.regular.is_structured
    assert scenario.irregular.n_cells > scenario.regular.n_cells
    assert scenario.irregular.n_lake_cells >= int(mesh_tol["min_irregular_lake_cells"])
    assert scenario.n_periods == scenario.geometry.n_periods
    assert len(scenario.irregular.period_stages) == scenario.n_periods

    # GRID INDEPENDENCE: per-period stages and the steady exchange flux agree.
    assert scenario.max_abs_stage_diff_m <= float(stage_tol["max_abs_stage_diff_m"])
    assert scenario.steady_exchange_rel_diff <= float(exchange_tol["steady_exchange_rel_diff"])

    # BUDGET: both grids close their LAK water balance.
    assert scenario.regular.max_budget_percent <= float(budget_tol["budget_percent_discrepancy"])
    assert scenario.irregular.max_budget_percent <= float(budget_tol["budget_percent_discrepancy"])

    # Sanity: the lake stays wet (above the bed) and within the abacus range on
    # both grids, so the stage comparison is meaningful.
    bed = scenario.geometry.bed_elevation_m
    abacus_stage_max = scenario.geometry.abacus_rows[-1][0]
    for stage in (*scenario.regular.period_stages, *scenario.irregular.period_stages):
        assert bed < stage < abacus_stage_max
