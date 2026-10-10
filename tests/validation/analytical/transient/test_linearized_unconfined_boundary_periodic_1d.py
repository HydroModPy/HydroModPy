"""Validate the propagation of a tide into an unconfined strip against the Ferris solution.

Compared with: the Ferris (1951) tide `h = h0 + A exp(-x / lam) cos(2 pi t / t0 - x / lam)`, `lam = sqrt(t0 T / (pi S))`, over the last four of eight daily tides read as hourly means, with the sea head posed where the model holds it.
"""

from __future__ import annotations

import platform

import numpy as np
import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import (
    assert_metric_below,
    assert_space_time_metrics,
    record_comparison,
    record_series,
)
from validation_cases.analytical.transient.linearized_unconfined_boundary_periodic_1d.comparison import (
    run_linearized_unconfined_boundary_periodic_comparison,
)


def _assert_tidal_case(*, solver: str) -> None:
    """Run one solver and compare its tides with the Ferris solution."""
    comparison = run_linearized_unconfined_boundary_periodic_comparison(
        caller_file=__file__, solver=solver
    )
    assert comparison.result.solver_name == solver
    record_comparison(comparison)
    columns = comparison.harmonic_columns
    distance = comparison.x[columns] - comparison.sea_x
    record_series(
        "Tide amplitude over the sea amplitude",
        distance,
        comparison.amplitude_ratio_reference[columns],
        comparison.amplitude_ratio_simulated[columns],
        x_label="distance from the sea (m)",
        y_label="amplitude / A (-)",
    )
    record_series(
        "Tide lag behind the sea",
        distance,
        comparison.phase_lag_reference_hours[columns],
        comparison.phase_lag_simulated_hours[columns],
        x_label="distance from the sea (m)",
        y_label="lag (h)",
    )

    assert np.all(np.isfinite(comparison.numerical_profiles))
    assert_space_time_metrics(comparison)
    final_tol = dict(comparison.tolerances["final_profile"])
    assert_metric_below(
        "Final-profile RMSE", comparison.final_profile_rmse, float(final_tol["rmse"]), unit="m"
    )
    assert_metric_below(
        "Final-profile max abs error",
        comparison.final_profile_max_error,
        float(final_tol["max_abs_error"]),
        unit="m",
    )
    tide_tol = dict(comparison.tolerances["tide"])
    assert_metric_below(
        "Decay length relative error",
        comparison.decay_length_relative_error,
        float(tide_tol["decay_length_relative_error"]),
    )
    assert_metric_below(
        "Lag length relative error",
        comparison.lag_length_relative_error,
        float(tide_tol["lag_length_relative_error"]),
    )


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.parametrize(
    ("solver", "require_modflow", "require_modflow6"),
    [
        pytest.param("modflow_nwt", True, False, id="modflow_nwt"),
        pytest.param("modflow6", False, True, id="modflow6"),
        pytest.param("modflow6_irregular_tri", False, True, id="modflow6_irregular_tri"),
        pytest.param("modflow6_voronoi", False, True, id="modflow6_voronoi"),
    ],
)
def test_tide_matches_ferris_modflow(
    solver: str, require_modflow: bool, require_modflow6: bool
) -> None:
    """Propagate the tide with MODFLOW on the grid, the triangles and their Voronoi dual."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )
    _assert_tidal_case(solver=solver)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.parametrize("solver", [pytest.param("boussinesq_local", id="boussinesq_local")])
def test_tide_matches_ferris_default_engine(solver: str) -> None:
    """Propagate the tide with the default Boussinesq engine, which needs no PETSc."""
    _assert_tidal_case(solver=solver)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.petsc
@pytest.mark.parametrize("solver", [pytest.param("boussinesq", id="boussinesq")])
def test_tide_matches_ferris_boussinesq_petsc(solver: str) -> None:
    """Propagate the tide with the Boussinesq PETSc runtime."""
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")
    _assert_tidal_case(solver=solver)
