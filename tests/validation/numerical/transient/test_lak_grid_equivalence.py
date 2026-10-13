"""LAK grid-equivalence validation (regular quad vs triangle and Voronoi DISV).

Compared with: the same lake problem solved on a regular quad grid; only the mesh changes.

The SAME transient multi-layer lake-aquifer problem (Plainfield Lakes abacus, one
reservoir incised across the top two layers of a 4-layer aquifer) is solved through
the production HMP LAK builders and MF6 on three grids:

* REGULAR: the 15x15 quad DISV (225 cells, 40 m), the reference. It has its own
  test, which checks that it closes its LAK water balance.
* TRIANGLE: a refined Delaunay triangle DISV (~772 cells, ~20 m near the lake).
* VORONOI: a ragged Voronoi DISV (372 cells of 4 to 9 edges, 20 m over the lake),
  the default HydroModPy grid. Its edges run along the lake polygon, so the lake
  footprint is the same 200 m x 200 m.

Only the mesh changes: the domain, layers, lake footprint, abacus, bedleak, aquifer
K / recharge, TDIS and per-period rainfall / evaporation / runoff are shared. The
cross-grid test, run once per irregular grid, asserts:

* the irregular grid is a genuine non-rectangular mesh that resolves the lake at
  least as finely as the quad grid;
* the per-period lake stages agree within the documented stage envelope;
* the steady lake-aquifer exchange flux agrees within the documented envelope;
* both grids close their LAK water balance.

A materially diverging grid (wrong CONNECTIONDATA geometry, lost bank seepage)
would break the stage envelope by an order of magnitude. The Voronoi stage gap
(0.054 m, against 0.038 m for the triangles) is the cell size at the lake bank,
not the builder: see ``tolerances_grid_equivalence_voronoi.toml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.validation.helpers import assert_metric_below, record_metric
from validation_cases.numerical.transient.lak_pleasant_transient.cross_grid import (
    load_cross_grid_tolerances,
    run_cross_grid_scenario,
    run_regular_grid,
)

NOT_APPLICABLE = {
    "modflow_nwt": "HydroModPy builds no LAK package on MODFLOW-NWT, and this case checks the HydroModPy MODFLOW 6 DISV lake builder on two meshes. NWT also works on the structured grid only.",
    "boussinesq": "The Boussinesq solver has no lake package: a lake boundary is refused with IncompatibleCapabilitiesError, and the lake boundary lists modflow6 as its only backend.",
    "boussinesq_local": "The Boussinesq solver has no lake package: a lake boundary is refused with IncompatibleCapabilitiesError, and the lake boundary lists modflow6 as its only backend.",
}

_KIND = {"modflow6_irregular_tri": "triangle", "modflow6_voronoi": "voronoi"}


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.fast
@pytest.mark.allow_subprocess
def test_lak_regular_grid_closes_its_budget(tmp_path: Path) -> None:
    """The quad leg, the reference of the cross-grid tests, is a sound lake run."""
    geometry, regular = run_regular_grid(workspace=tmp_path)
    budget_tol = dict(load_cross_grid_tolerances("triangle")["budget"])

    assert regular.is_structured
    assert regular.n_cells == geometry.n_cells
    assert regular.n_lake_cells == len(geometry.lake_cell_ids)
    assert len(regular.period_stages) == geometry.n_periods

    assert_metric_below(
        "Worst LAK budget discrepancy, quad grid",
        regular.max_budget_percent,
        float(budget_tol["budget_percent_discrepancy"]),
        unit="%",
    )
    # The lake stays wet (above the bed) and inside the abacus range.
    abacus_stage_max = geometry.abacus_rows[-1][0]
    for stage in regular.period_stages:
        assert geometry.bed_elevation_m < stage < abacus_stage_max


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.fast
@pytest.mark.allow_subprocess
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow6_irregular_tri", id="modflow6_irregular_tri"),
        pytest.param("modflow6_voronoi", id="modflow6_voronoi"),
    ],
)
def test_lak_regular_and_irregular_grids_agree(solver: str, tmp_path: Path) -> None:
    """The lake stage and exchange flux on the irregular grid match the quad grid."""
    kind = _KIND[solver]
    scenario = run_cross_grid_scenario(workspace=tmp_path, kind=kind)
    tolerances = load_cross_grid_tolerances(kind)
    stage_tol = dict(tolerances["stage"])
    exchange_tol = dict(tolerances["exchange"])
    budget_tol = dict(tolerances["budget"])
    mesh_tol = dict(tolerances["mesh"])

    # MESH: the irregular grid is a genuine non-rectangular mesh with at least as
    # many lake cells as the quad grid, and both grids span all periods.
    assert not scenario.irregular.is_structured
    assert scenario.regular.is_structured
    assert scenario.irregular.n_cells > scenario.regular.n_cells
    assert scenario.irregular.n_lake_cells >= int(mesh_tol["min_irregular_lake_cells"])
    assert scenario.n_periods == scenario.geometry.n_periods
    assert len(scenario.irregular.period_stages) == scenario.n_periods

    # GRID INDEPENDENCE: per-period stages and the steady exchange flux agree.
    assert_metric_below(
        "Largest per-period lake stage difference between the grids",
        scenario.max_abs_stage_diff_m,
        float(stage_tol["max_abs_stage_diff_m"]),
        unit="m",
        inclusive=True,
    )
    assert_metric_below(
        "Steady lake-aquifer exchange flux, relative difference",
        scenario.steady_exchange_rel_diff,
        float(exchange_tol["steady_exchange_rel_diff"]),
        inclusive=True,
    )

    # BUDGET: both grids close their LAK water balance.
    budget_limit = float(budget_tol["budget_percent_discrepancy"])
    assert_metric_below(
        "Worst LAK budget discrepancy, irregular grid",
        scenario.irregular.max_budget_percent,
        budget_limit,
        unit="%",
        inclusive=True,
    )
    record_metric(
        "Worst LAK budget discrepancy, quad grid",
        scenario.regular.max_budget_percent,
        budget_limit,
        op="<=",
        unit="%",
    )
    assert scenario.regular.max_budget_percent <= budget_limit

    # Sanity: the lake stays wet (above the bed) and within the abacus range on
    # both grids, so the stage comparison is meaningful.
    bed = scenario.geometry.bed_elevation_m
    abacus_stage_max = scenario.geometry.abacus_rows[-1][0]
    for stage in (*scenario.regular.period_stages, *scenario.irregular.period_stages):
        assert bed < stage < abacus_stage_max
