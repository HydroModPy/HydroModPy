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
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.steady.dupuit_seepage_limit_1d.comparison import (
    SeepageLimitComparison,
    drain_outflow_ratio,
    head_disagreement_m,
    mask_disagreement_cells,
    run_seepage_limit_sweep,
)

REFERENCE_SOLVER = "modflow6"
SCALED_SOLVERS = ("modflow6_scaled_down", "modflow6_scaled_up")
CONTROL_SOLVER = "modflow6_k_only"
ALL_SOLVERS = (REFERENCE_SOLVER, *SCALED_SOLVERS, CONTROL_SOLVER)

pytestmark = [
    pytest.mark.validation,
    pytest.mark.analytical,
    pytest.mark.steady,
    pytest.mark.mf6,
    pytest.mark.fast,
    pytest.mark.xdist_group(name="dupuit_seepage_limit"),
]


@pytest.fixture(scope="module")
def scenarios() -> Iterator[dict[str, SeepageLimitComparison]]:
    """Run every declared scenario once and share them across the module."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    runs = run_seepage_limit_sweep(caller_file=__file__)
    try:
        yield runs
    finally:
        for scenario in runs.values():
            store = getattr(scenario.result, "store", None)
            if store is not None:
                store.close()


def test_every_declared_scenario_is_exercised(
    scenarios: dict[str, SeepageLimitComparison],
) -> None:
    """The case declares exactly the scenarios this module asserts on."""
    assert set(scenarios) == set(ALL_SOLVERS)


@pytest.mark.parametrize("solver", ALL_SOLVERS)
def test_seepage_limit_matches_the_closed_form(
    scenarios: dict[str, SeepageLimitComparison],
    solver: str,
) -> None:
    """The mask starts at ``x_e = L / (1 + slope**2 * K/R)`` in every scenario."""
    scenario = scenarios[solver]
    seepage_tol = dict(scenario.tolerances["seepage_limit"])

    assert scenario.mask_row_disagreement == 0, (
        f"{solver}: the quasi-1D rows disagree on {scenario.mask_row_disagreement} cells."
    )
    assert scenario.mask_is_contiguous, (
        f"{solver}: the seeping cells do not form one block down to the toe."
    )
    assert_metric_below(
        f"{solver} seepage-limit position error",
        scenario.seepage_limit_error_m,
        float(seepage_tol["position_error"]),
        unit="m",
    )
    assert_metric_below(
        f"{solver} head-profile max abs error",
        scenario.head_profile_max_error_m,
        float(seepage_tol["head_profile_max_abs_error"]),
        unit="m",
    )


@pytest.mark.parametrize("solver", SCALED_SOLVERS)
def test_seepage_mask_and_head_are_invariant_in_conductivity_over_recharge(
    scenarios: dict[str, SeepageLimitComparison],
    solver: str,
) -> None:
    """Scaling K and R together must leave the mask and the head where they are."""
    base = scenarios[REFERENCE_SOLVER]
    scaled = scenarios[solver]

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


def test_conductivity_alone_moves_the_mask_but_not_the_discharge(
    scenarios: dict[str, SeepageLimitComparison],
) -> None:
    """Negative control: without it, the invariance could pass on a blind model."""
    base = scenarios[REFERENCE_SOLVER]
    control = scenarios[CONTROL_SOLVER]

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
