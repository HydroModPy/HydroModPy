"""Validate the stream depletion of a well pumping beside a stream held at a fixed head.

Compared with: the Glover and Balmer (1954) stream depletion `Qs / Q = erfc(sqrt(S a^2 / (4 T t)))` and the image-well drawdown of Theis (1941), `s = Q / (4 pi T) [E1(r1^2 S / (4 T t)) - E1(r2^2 S / (4 T t))]`, with the stream, the well and each monitor point at the centre of the cell the model computes.
"""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below, record_comparison, record_series
from validation_cases.analytical.transient.stream_depletion_glover_balmer_2d.comparison import (
    run_stream_depletion_comparison,
)


def _assert_stream_depletion_case(
    *,
    solver: str,
    require_modflow: bool,
    require_modflow6: bool,
) -> None:
    """Run one solver variant and compare the depletion and the drawdowns."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_stream_depletion_comparison(caller_file=__file__, solver=solver)
    record_comparison(comparison)
    record_series(
        "Stream depletion fraction",
        comparison.elapsed_days,
        comparison.analytical_depletion_fraction,
        comparison.numerical_depletion_fraction,
        x_label="time (d)",
        y_label="Qs / Q (-)",
    )
    depletion_tol = dict(comparison.tolerances.get("depletion", {}))
    space_time_tol = dict(comparison.tolerances.get("space_time", {}))
    final_time_tol = dict(comparison.tolerances.get("final_time", {}))
    linearization_tol = dict(comparison.tolerances.get("linearization", {}))

    assert_metric_below(
        "Stream depletion max abs error",
        comparison.depletion_max_error,
        float(depletion_tol["max_abs_error"]),
    )
    assert_metric_below(
        "Stream depletion final error",
        comparison.depletion_final_error,
        float(depletion_tol["final_abs_error"]),
    )
    assert_metric_below(
        "Drawdown space-time RMSE",
        comparison.space_time_rmse,
        float(space_time_tol["rmse"]),
        unit="m",
    )
    assert_metric_below(
        "Drawdown space-time max abs error",
        comparison.space_time_max_error,
        float(space_time_tol["max_abs_error"]),
        unit="m",
    )
    assert_metric_below(
        "Drawdown final-time RMSE",
        comparison.final_time_rmse,
        float(final_time_tol["rmse"]),
        unit="m",
    )
    assert_metric_below(
        "Drawdown final-time max abs error",
        comparison.final_time_max_error,
        float(final_time_tol["max_abs_error"]),
        unit="m",
    )
    assert_metric_below(
        "Well drawdown over saturated thickness",
        comparison.well_drawdown_fraction,
        float(linearization_tol["well_drawdown_fraction"]),
    )


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.parametrize(
    ("solver", "require_modflow", "require_modflow6"),
    [
        pytest.param("modflow_nwt", True, False, id="modflow_nwt", marks=pytest.mark.fast),
        pytest.param("modflow6", False, True, id="modflow6", marks=pytest.mark.fast),
        pytest.param(
            "modflow6_irregular_tri",
            False,
            True,
            id="modflow6_irregular_tri",
            marks=pytest.mark.slow,
        ),
        pytest.param(
            "modflow6_voronoi", False, True, id="modflow6_voronoi", marks=pytest.mark.fast
        ),
    ],
)
def test_stream_depletion_glover_balmer_2d_modflow(
    solver: str,
    require_modflow: bool,
    require_modflow6: bool,
) -> None:
    """Check the MODFLOW variants against the Glover and Balmer depletion.

    The triangle variant runs in about 33 s, the others in 12 to 23 s.
    """
    _assert_stream_depletion_case(
        solver=solver,
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
    )


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.petsc
def test_stream_depletion_glover_balmer_2d_boussinesq() -> None:
    """Check the Boussinesq solver on PETSc against the Glover and Balmer depletion."""
    _assert_stream_depletion_case(
        solver="boussinesq",
        require_modflow=False,
        require_modflow6=False,
    )


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.parametrize("solver", [pytest.param("boussinesq_local", id="boussinesq_local")])
def test_stream_depletion_glover_balmer_2d_default_engine(solver: str) -> None:
    """Check the default Boussinesq engine, which needs no PETSc.

    The mesh has 5783 cells, so 'auto' runs the sparse engine.
    """
    _assert_stream_depletion_case(
        solver=solver,
        require_modflow=False,
        require_modflow6=False,
    )
