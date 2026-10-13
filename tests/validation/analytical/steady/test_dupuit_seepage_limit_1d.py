"""Validate the steady Dupuit seepage limit and its invariance in K/R.

Three claims, in decreasing order of importance:

1. the seepage mask starts where the Dupuit closed form says it does,
2. scaling ``K`` and ``R`` by the same factor leaves the mask identical cell for
   cell and the head equal to a tight band - the property the whole calibration
   method rests on,
3. the same factor on ``K`` alone moves the mask, while the total drain
   discharge does not move at all.

Claim 3 is why claim 2 never looks at the discharge: mass balance pins the total
drain outflow at ``R * area`` whatever the conductance does, so a
discharge-based invariance check passes on a model that ignores ``K`` entirely.

Six solvers run it, each on four scenarios (the reference, ``K`` and ``R`` scaled
down and up, ``K`` alone doubled): MODFLOW-NWT and MODFLOW 6 on a structured
grid, MODFLOW 6 on irregular triangles and on their Voronoi dual, with a drain
at the land surface, and the in-house Boussinesq solver on its PETSc VI obstacle
and its default local engine. A Boussinesq run has no drain: its seepage mask is
read from the heads, and the water that leaves is its surface-excess flux.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below, record_comparison
from validation_cases.analytical.steady.dupuit_seepage_limit_1d.comparison import (
    CASE_DIR,
    SeepageLimitComparison,
    backend_of,
    drain_outflow_ratio,
    head_disagreement_m,
    mask_disagreement_cells,
    run_seepage_limit_comparison,
)
from validation_cases.shared import load_case_metadata

NWT_SOLVERS = (
    "modflow_nwt",
    "modflow_nwt_scaled_down",
    "modflow_nwt_scaled_up",
    "modflow_nwt_k_only",
)
MODFLOW6_SOLVERS = (
    "modflow6",
    "modflow6_scaled_down",
    "modflow6_scaled_up",
    "modflow6_k_only",
)
TRIANGLE_SOLVERS = (
    "modflow6_irregular_tri",
    "modflow6_irregular_tri_scaled_down",
    "modflow6_irregular_tri_scaled_up",
    "modflow6_irregular_tri_k_only",
)
VORONOI_SOLVERS = (
    "modflow6_voronoi",
    "modflow6_voronoi_scaled_down",
    "modflow6_voronoi_scaled_up",
    "modflow6_voronoi_k_only",
)
PETSC_SOLVERS = (
    "boussinesq",
    "boussinesq_scaled_down",
    "boussinesq_scaled_up",
    "boussinesq_k_only",
)
LOCAL_SOLVERS = (
    "boussinesq_local",
    "boussinesq_local_scaled_down",
    "boussinesq_local_scaled_up",
    "boussinesq_local_k_only",
)
ALL_SOLVERS = (
    *NWT_SOLVERS,
    *MODFLOW6_SOLVERS,
    *TRIANGLE_SOLVERS,
    *VORONOI_SOLVERS,
    *PETSC_SOLVERS,
    *LOCAL_SOLVERS,
)

# The executables each solver needs, as (MODFLOW-NWT, MODFLOW 6).
EXECUTABLES = {
    "modflow_nwt": (True, False),
    "modflow6": (False, True),
    "modflow6_irregular_tri": (False, True),
    "modflow6_voronoi": (False, True),
    "boussinesq": (False, False),
    "boussinesq_local": (False, False),
}

pytestmark = [
    pytest.mark.validation,
    pytest.mark.analytical,
    pytest.mark.steady,
    pytest.mark.xdist_group(name="dupuit_seepage_limit"),
]


class ScenarioRuns:
    """Run each scenario once, on first use, and share it across the module."""

    def __init__(self) -> None:
        self._runs: dict[str, SeepageLimitComparison] = {}

    def __call__(self, solver: str) -> SeepageLimitComparison:
        if solver not in self._runs:
            require_modflow, require_modflow6 = EXECUTABLES[backend_of(solver)]
            assert_required_executables(
                require_modflow=require_modflow,
                require_modflow6=require_modflow6,
                require_modpath=False,
                require_mt3dms=False,
            )
            self._runs[solver] = run_seepage_limit_comparison(caller_file=__file__, solver=solver)
        return self._runs[solver]

    def close(self) -> None:
        for scenario in self._runs.values():
            store = getattr(scenario.result, "store", None)
            if store is not None:
                store.close()


@pytest.fixture(scope="module")
def scenario() -> Iterator[ScenarioRuns]:
    """Return the runner that gives each scenario, run on first request."""
    runs = ScenarioRuns()
    try:
        yield runs
    finally:
        runs.close()


def _reference_of(solver: str) -> str:
    """Return the reference scenario of the solver of a scaled or control scenario."""
    return backend_of(solver)


def test_every_declared_scenario_is_exercised() -> None:
    """The case declares exactly the scenarios this module asserts on."""
    declared = set(dict(load_case_metadata(CASE_DIR)["config_files"]))
    assert declared == set(ALL_SOLVERS)


@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow_nwt", marks=pytest.mark.slow, id="modflow_nwt"),
        pytest.param(
            "modflow_nwt_scaled_down", marks=pytest.mark.slow, id="modflow_nwt_scaled_down"
        ),
        pytest.param("modflow_nwt_scaled_up", marks=pytest.mark.slow, id="modflow_nwt_scaled_up"),
        pytest.param("modflow_nwt_k_only", marks=pytest.mark.slow, id="modflow_nwt_k_only"),
        pytest.param("modflow6", marks=pytest.mark.fast, id="modflow6"),
        pytest.param("modflow6_scaled_down", marks=pytest.mark.fast, id="modflow6_scaled_down"),
        pytest.param("modflow6_scaled_up", marks=pytest.mark.fast, id="modflow6_scaled_up"),
        pytest.param("modflow6_k_only", marks=pytest.mark.fast, id="modflow6_k_only"),
        pytest.param("modflow6_irregular_tri", marks=pytest.mark.slow, id="modflow6_irregular_tri"),
        pytest.param(
            "modflow6_irregular_tri_scaled_down",
            marks=pytest.mark.slow,
            id="modflow6_irregular_tri_scaled_down",
        ),
        pytest.param(
            "modflow6_irregular_tri_scaled_up",
            marks=pytest.mark.slow,
            id="modflow6_irregular_tri_scaled_up",
        ),
        pytest.param(
            "modflow6_irregular_tri_k_only",
            marks=pytest.mark.slow,
            id="modflow6_irregular_tri_k_only",
        ),
        pytest.param("modflow6_voronoi", marks=pytest.mark.slow, id="modflow6_voronoi"),
        pytest.param(
            "modflow6_voronoi_scaled_down",
            marks=pytest.mark.slow,
            id="modflow6_voronoi_scaled_down",
        ),
        pytest.param(
            "modflow6_voronoi_scaled_up", marks=pytest.mark.slow, id="modflow6_voronoi_scaled_up"
        ),
        pytest.param(
            "modflow6_voronoi_k_only", marks=pytest.mark.slow, id="modflow6_voronoi_k_only"
        ),
        pytest.param("boussinesq", marks=[pytest.mark.petsc, pytest.mark.fast], id="boussinesq"),
        pytest.param(
            "boussinesq_scaled_down",
            marks=[pytest.mark.petsc, pytest.mark.fast],
            id="boussinesq_scaled_down",
        ),
        pytest.param(
            "boussinesq_scaled_up",
            marks=[pytest.mark.petsc, pytest.mark.fast],
            id="boussinesq_scaled_up",
        ),
        pytest.param(
            "boussinesq_k_only",
            marks=[pytest.mark.petsc, pytest.mark.fast],
            id="boussinesq_k_only",
        ),
        pytest.param("boussinesq_local", marks=pytest.mark.slow, id="boussinesq_local"),
        pytest.param(
            "boussinesq_local_scaled_down",
            marks=pytest.mark.slow,
            id="boussinesq_local_scaled_down",
        ),
        pytest.param(
            "boussinesq_local_scaled_up", marks=pytest.mark.slow, id="boussinesq_local_scaled_up"
        ),
        pytest.param(
            "boussinesq_local_k_only", marks=pytest.mark.slow, id="boussinesq_local_k_only"
        ),
    ],
)
def test_seepage_limit_matches_the_closed_form(
    scenario: ScenarioRuns,
    solver: str,
) -> None:
    """The mask starts at ``x_e = L / (1 + slope**2 * K/R)`` in every scenario."""
    run = scenario(solver)
    record_comparison(run)
    seepage_tol = dict(run.tolerances["seepage_limit"])

    # Cells of an unstructured grid that disagree with their 5 m column sit where
    # the limit falls inside it; a structured grid has none.
    allowed = int(seepage_tol.get("mask_row_disagreement_max", 0))
    assert run.mask_row_disagreement <= allowed, (
        f"{solver}: {run.mask_row_disagreement} cells differ from the seepage state of their "
        f"column, more than the {allowed} the grid allows."
    )
    assert run.mask_is_contiguous, (
        f"{solver}: the seeping cells do not form one block down to the toe."
    )
    assert_metric_below(
        f"{solver} seepage-limit position error",
        run.seepage_limit_error_m,
        float(seepage_tol["position_error"]),
        unit="m",
    )
    assert_metric_below(
        f"{solver} head-profile max abs error",
        run.head_profile_max_error_m,
        float(seepage_tol["head_profile_max_abs_error"]),
        unit="m",
    )


@pytest.mark.parametrize(
    "solver",
    [
        pytest.param(
            "modflow_nwt_scaled_down", marks=pytest.mark.slow, id="modflow_nwt_scaled_down"
        ),
        pytest.param("modflow_nwt_scaled_up", marks=pytest.mark.slow, id="modflow_nwt_scaled_up"),
        pytest.param("modflow6_scaled_down", marks=pytest.mark.fast, id="modflow6_scaled_down"),
        pytest.param("modflow6_scaled_up", marks=pytest.mark.fast, id="modflow6_scaled_up"),
        pytest.param(
            "modflow6_irregular_tri_scaled_down",
            marks=pytest.mark.slow,
            id="modflow6_irregular_tri_scaled_down",
        ),
        pytest.param(
            "modflow6_irregular_tri_scaled_up",
            marks=pytest.mark.slow,
            id="modflow6_irregular_tri_scaled_up",
        ),
        pytest.param(
            "modflow6_voronoi_scaled_down",
            marks=pytest.mark.slow,
            id="modflow6_voronoi_scaled_down",
        ),
        pytest.param(
            "modflow6_voronoi_scaled_up", marks=pytest.mark.slow, id="modflow6_voronoi_scaled_up"
        ),
        pytest.param(
            "boussinesq_scaled_down",
            marks=[pytest.mark.petsc, pytest.mark.fast],
            id="boussinesq_scaled_down",
        ),
        pytest.param(
            "boussinesq_scaled_up",
            marks=[pytest.mark.petsc, pytest.mark.fast],
            id="boussinesq_scaled_up",
        ),
        pytest.param(
            "boussinesq_local_scaled_down",
            marks=pytest.mark.slow,
            id="boussinesq_local_scaled_down",
        ),
        pytest.param(
            "boussinesq_local_scaled_up", marks=pytest.mark.slow, id="boussinesq_local_scaled_up"
        ),
    ],
)
def test_seepage_mask_and_head_are_invariant_in_conductivity_over_recharge(
    scenario: ScenarioRuns,
    solver: str,
) -> None:
    """Scaling K and R together must leave the mask and the head where they are."""
    base = scenario(_reference_of(solver))
    scaled = scenario(solver)

    assert scaled.hydraulic_conductivity_m_per_s != base.hydraulic_conductivity_m_per_s
    assert scaled.recharge_m_per_s != base.recharge_m_per_s
    assert scaled.conductivity_over_recharge == pytest.approx(base.conductivity_over_recharge)

    moved = mask_disagreement_cells(base, scaled)
    assert moved == 0, (
        f"{solver}: the seepage mask moved on {moved} cells while K/R did not change. "
        "The drain conductance must stay proportional to K for the mask to be invariant."
    )
    assert_metric_below(
        f"{solver} water-table difference vs the reference scenario",
        head_disagreement_m(base, scaled),
        float(base.tolerances["invariance"]["head_max_abs_error"]),
        unit="m",
    )


@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow_nwt_k_only", marks=pytest.mark.slow, id="modflow_nwt_k_only"),
        pytest.param("modflow6_k_only", marks=pytest.mark.fast, id="modflow6_k_only"),
        pytest.param(
            "modflow6_irregular_tri_k_only",
            marks=pytest.mark.slow,
            id="modflow6_irregular_tri_k_only",
        ),
        pytest.param(
            "modflow6_voronoi_k_only", marks=pytest.mark.slow, id="modflow6_voronoi_k_only"
        ),
        pytest.param(
            "boussinesq_k_only",
            marks=[pytest.mark.petsc, pytest.mark.fast],
            id="boussinesq_k_only",
        ),
        pytest.param(
            "boussinesq_local_k_only", marks=pytest.mark.slow, id="boussinesq_local_k_only"
        ),
    ],
)
def test_conductivity_alone_moves_the_mask_but_not_the_discharge(
    scenario: ScenarioRuns,
    solver: str,
) -> None:
    """Negative control: without it, the invariance could pass on a blind model."""
    base = scenario(_reference_of(solver))
    control = scenario(solver)

    assert control.recharge_m_per_s == base.recharge_m_per_s
    assert control.hydraulic_conductivity_m_per_s > base.hydraulic_conductivity_m_per_s

    moved = mask_disagreement_cells(base, control)
    nrow = int(base.seepage_mask.shape[0])
    assert moved >= nrow, (
        f"Doubling K moved only {moved} cells of the seepage mask (less than one "
        f"column of {nrow} cells): the mask does not see the conductivity."
    )
    assert_metric_below(
        "Drain-outflow drift when K alone doubles",
        abs(drain_outflow_ratio(control, base) - 1.0),
        float(base.tolerances["control"]["drain_outflow_ratio_error"]),
    )
