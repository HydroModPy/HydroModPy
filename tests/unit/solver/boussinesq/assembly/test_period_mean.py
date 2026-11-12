"""The assembly a stress period exports: last state, step-weighted mean of the fluxes (m3/s)."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.assembly.period_mean import period_mean_assembly
from hydromodpy.solver.boussinesq.assembly.types import BoussinesqAssembly


def step(
    head_m: float, flux_m3_s: float, *, dry_deficit: float | None = None
) -> BoussinesqAssembly:
    """One-cell assembly whose every flux is ``flux_m3_s``."""
    cell = np.asarray([flux_m3_s])
    return BoussinesqAssembly(
        head_m=np.asarray([head_m]),
        saturated_thickness_m=np.asarray([head_m]),
        transmissivity_m2_s=np.asarray([1.0e-4]),
        recharge_rate_m_s=cell,
        well_flux_m3_s=cell,
        saturation_excess_rate_m_s=cell,
        internal_edge_flux_m3_s=cell,
        prescribed_head_flux_m3_s=cell,
        prescribed_head_m_by_cell=np.asarray([np.nan]),
        head_constraint_residual_m=np.zeros(1),
        boundary_edge_flux_m3_s=cell,
        drainage_flux_m3_s=cell,
        flow_residual_m3_s=cell,
        solver_residual=cell,
        residual_m3_s=cell,
        dry_deficit_rate_m_s=None if dry_deficit is None else np.asarray([dry_deficit]),
    )


def test_one_full_step_is_returned_as_is() -> None:
    only = step(5.0, 2.0)

    assert period_mean_assembly([only], [1.0]) is only


def test_fluxes_are_weighted_and_state_is_the_last() -> None:
    first, last = step(4.0, 1.0), step(6.0, 3.0)

    mean = period_mean_assembly([first, last], [0.25, 0.75])

    # 0.25 x 1 + 0.75 x 3 m3/s
    np.testing.assert_allclose(mean.drainage_flux_m3_s, [2.5])
    np.testing.assert_allclose(mean.head_m, [6.0])
    assert mean.dry_deficit_rate_m_s is None


def test_a_step_without_dry_deficit_counts_zero() -> None:
    first, last = step(4.0, 1.0), step(6.0, 3.0, dry_deficit=2.0)

    mean = period_mean_assembly([first, last], [0.5, 0.5])

    np.testing.assert_allclose(mean.dry_deficit_rate_m_s, [1.0])


REFUSALS = [
    pytest.param([step(4.0, 1.0)], [0.5, 0.5], "1 assemblies for 2 weights", id="too few steps"),
    pytest.param([], [], "0 assemblies for 0 weights", id="no step"),
]


@pytest.mark.parametrize(("assemblies", "weights", "message"), REFUSALS)
def test_refusals(assemblies, weights, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        period_mean_assembly(assemblies, weights)
