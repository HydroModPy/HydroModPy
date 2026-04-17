from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tools import investigate_linux_nwt_boussinesq_transient as case


def _make_diagnostics() -> SimpleNamespace:
    return SimpleNamespace(
        result=SimpleNamespace(out_path=Path("dummy"), postprocess_dir=Path("dummy/_postprocess")),
        elapsed_days=np.asarray([0.0, 15.0, 30.0], dtype=float),
        x_m=np.asarray([5.0, 15.0, 25.0], dtype=float),
        topography_profile_m=np.asarray([6.0, 5.0, 4.0], dtype=float),
        mean_head_profiles_m=np.asarray(
            [
                [5.4, 4.5, 3.8],
                [5.6, 4.8, 4.1],
                [5.5, 4.7, 4.0],
            ],
            dtype=float,
        ),
        mean_head_clearance_m=np.asarray(
            [
                [-0.6, -0.5, -0.2],
                [-0.4, -0.2, 0.1],
                [-0.5, -0.3, 0.0],
            ],
            dtype=float,
        ),
        drainage_flux_m3_day=np.asarray([0.05, 0.10, 0.08], dtype=float),
        total_outflow_m3_day=np.asarray([1.0, 2.0, 1.5], dtype=float),
        east_boundary_outflow_m3_day=np.asarray([0.2, 0.4, 0.3], dtype=float),
        surface_excess_flux_m3_day=np.asarray([0.8, 1.6, 1.2], dtype=float),
        recharge_flux_m3_day=np.asarray([2.0, 4.0, 0.0], dtype=float),
        storage_balance_m3_day=np.asarray([1.0, 2.0, -1.5], dtype=float),
        onset_day=15.0,
    )


def test_recharge_schedule_has_expected_shape() -> None:
    assert len(case.RECHARGE_SERIES_MM_DAY) == 42
    assert case.SOLVER_ORDER == ("modflownwt", "petsc_partition", "petsc")
    assert case.PARTITION_REGULARIZATION_RADIUS == 0.005
    assert case.HYDRAULIC_CONDUCTIVITY_SCALE == 0.1
    assert case.DRAINAGE_CONDUCTANCE_M2_S == 2.0e-4
    assert case.BOUSS_NX == 80
    assert case.BOUSS_NY == 6
    assert case.RECHARGE_SERIES_MM_DAY[:12] == (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0)
    assert case.RECHARGE_SERIES_MM_DAY[12:24] == (5.5, 5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0, 0.5, 0.25)
    assert case.RECHARGE_SERIES_MM_DAY[24:] == (0.0,) * 18


def test_bouss_diagnostics_to_result_maps_total_outflow_and_surface_flux() -> None:
    result = case._bouss_diagnostics_to_result(
        "petsc_partition",
        diagnostics=_make_diagnostics(),
        wall_time_seconds=12.5,
    )

    assert result.solver == "petsc_partition"
    assert result.peak_total_outflow_m3_day == 2.0
    assert result.peak_total_outflow_day == 15.0
    assert result.peak_drainage_flux_m3_day == 0.10
    assert result.peak_drainage_day == 15.0
    assert np.allclose(result.drainage_flux_m3_day, [0.05, 0.10, 0.08])
    assert np.allclose(result.bouss_surface_flux_m3_day, [0.8, 1.6, 1.2])
