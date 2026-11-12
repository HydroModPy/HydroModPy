"""Hillslope case with a recharge pulse that overflows at the surface.

Recharge is in mm/day, heads and lengths in m, time in days. The tests cover the case
settings, the overflow diagnostics, the plot helpers and the run of the two solvers.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d import (
    comparison as comparison_module,
)
from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.diagnostics import (
    _align_period_values_to_elapsed_days,
    _resolve_mean_head_profiles_m,
    _resolve_recharge_series_mm_day,
    compute_overflow_footprint_metrics,
)
from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.plotting import (
    _align_step_series,
    select_snapshot_indices,
)
from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.runtime_boussinesq import (
    CASE_DIR,
    _resolve_case_settings,
    resolve_solver_variant,
)
from validation_cases.shared.loaders import load_case_metadata
from validation_cases.shared.runtime import ValidationRunResult, write_validation_fields_to_store


def test_solver_variants():
    partition = resolve_solver_variant("petsc_partition")
    complementarity = resolve_solver_variant("petsc")

    assert partition.runtime_backend == "petsc"
    assert partition.surface_interaction_model == "regularized_partition"
    assert complementarity.runtime_backend == "petsc"
    assert complementarity.surface_interaction_model == "complementarity"


def test_overflow_footprint_metrics():
    x_m = np.asarray([5.0, 15.0, 25.0, 35.0], dtype=float)
    profiles = np.asarray(
        [
            [0.00, 0.00, 0.00, 0.00],
            [0.00, 0.20, 0.80, 0.00],
            [0.00, 0.50, 1.00, 1.50],
        ],
        dtype=float,
    )

    active_length_m, front_x_m, centroid_x_m = compute_overflow_footprint_metrics(
        profiles,
        x_m=x_m,
        threshold_mm_day=0.15,
    )

    assert np.allclose(active_length_m, [0.0, 20.0, 30.0])
    assert np.isnan(front_x_m[0])
    assert np.allclose(front_x_m[1:], [25.0, 35.0])
    assert np.isnan(centroid_x_m[0])
    assert centroid_x_m[1] > 20.0
    assert centroid_x_m[2] > centroid_x_m[1]


def test_snapshot_indices():
    # Requested days come first, then the count is capped at two.
    indices = select_snapshot_indices(
        np.asarray([0.0, 2.0, 4.0, 6.0, 8.0], dtype=float),
        requested_days=(0.1, 5.1, 7.9),
        max_snapshots=2,
    )

    assert indices == [0, 3]


def test_scenario_refuses_one_solver_twice(monkeypatch):
    monkeypatch.setattr(comparison_module, "load_case_metadata", lambda case_dir: {})

    with pytest.raises(ValueError, match="compare_solver must differ from solver"):
        comparison_module.run_hillslope_overflow_scenario(
            caller_file=Path("dummy_test.py"),
            solver="petsc_partition",
            compare_solver="petsc_partition",
        )


def test_case_settings_apply_preset_scale_and_overrides():
    metadata = {
        "geometry": {
            "nx": 40,
            "ny": 3,
            "length_x_m": 400.0,
            "width_y_m": 30.0,
            "toe_elevation_m": 5.0,
            "topography_slope_m_per_m": 0.015,
            "east_head_m": 4.0,
            "initial_head_m": 4.2,
        },
        "time": {"dt_days": 2.0, "nper": 3},
        "forcing": {"recharge_mm_day": [0.0, 10.0, 20.0]},
        "forcing_presets": {
            "strong": {
                "dt_days": 1.0,
                "east_head_m": 3.5,
                "initial_head_m": 4.0,
                "recharge_mm_day": [5.0, 15.0, 25.0, 35.0],
            }
        },
        "solver_overrides": {
            "petsc": {
                "runtime_max_iterations": 60,
                "runtime_tol_residual_inf": 1.0e-8,
            }
        },
    }

    geometry_cfg, time_cfg, forcing_cfg, max_it, tol = _resolve_case_settings(
        metadata,
        variant=resolve_solver_variant("petsc"),
        context_preset=None,
        forcing_preset="strong",
        forcing_scale=2.0,
        east_head_m=None,
        initial_head_m=None,
        dt_days=None,
        runtime_max_iterations=None,
        runtime_tol_residual_inf=None,
    )

    assert geometry_cfg["east_head_m"] == 3.5
    assert geometry_cfg["initial_head_m"] == 4.0
    assert time_cfg["dt_days"] == 1.0
    assert time_cfg["nper"] == 4
    assert forcing_cfg["recharge_mm_day"] == [10.0, 30.0, 50.0, 70.0]
    assert max_it == 60
    assert tol == 1.0e-8


def test_scenario_keeps_primary_when_compare_fails(monkeypatch):
    primary_result = object()
    primary_diag = object()

    monkeypatch.setattr(comparison_module, "load_case_metadata", lambda case_dir: {})

    def fake_run(*, solver, **kwargs):
        if solver == "petsc":
            raise RuntimeError("secondary failed")
        return primary_result

    def fake_build(*, result, metadata=None, overflow_threshold_mm_day=None):
        assert result is primary_result
        return primary_diag

    monkeypatch.setattr(comparison_module, "run_boussinesq_hillslope_overflow_case", fake_run)
    monkeypatch.setattr(comparison_module, "build_hillslope_overflow_diagnostics", fake_build)

    scenario = comparison_module.run_hillslope_overflow_scenario(
        caller_file=Path("dummy_test.py"),
        solver="petsc_partition",
        compare_solver="petsc",
    )

    assert scenario.primary is primary_diag
    assert scenario.secondary is None
    assert scenario.secondary_solver_name == "petsc"
    assert scenario.secondary_error == "secondary failed"


def test_recharge_series_prefers_runtime_history():
    state_history = {
        "recharge_rate_history_m_s": np.asarray(
            [
                [0.0, 0.0],
                [1.0e-7, 3.0e-7],
                [2.0e-7, 4.0e-7],
            ],
            dtype=float,
        )
    }
    recharge_mm_day = _resolve_recharge_series_mm_day(
        state_history=state_history,
        forcing_cfg={"recharge_mm_day": [1.0, 2.0, 3.0]},
        cell_area_m2=np.asarray([1.0, 3.0], dtype=float),
        n_periods=2,
    )

    expected_m_s = np.asarray(
        [
            (1.0e-7 * 1.0 + 3.0e-7 * 3.0) / 4.0,
            (2.0e-7 * 1.0 + 4.0e-7 * 3.0) / 4.0,
        ],
        dtype=float,
    )
    assert np.allclose(recharge_mm_day, expected_m_s * 86_400.0 * 1_000.0)


def test_recharge_series_skips_imposed_head_cells():
    # The fixed-head cell takes no recharge: the mean is the forcing, not less.
    state_history = {
        "recharge_rate_history_m_s": np.asarray([[0.0, 0.0], [1.0e-7, 0.0]], dtype=float),
        "prescribed_head_history_m_by_cell": np.asarray(
            [[np.nan, 5.0], [np.nan, 5.0]], dtype=float
        ),
    }
    recharge_mm_day = _resolve_recharge_series_mm_day(
        state_history=state_history,
        forcing_cfg={"recharge_mm_day": [9.0]},
        cell_area_m2=np.asarray([1.0, 3.0], dtype=float),
        n_periods=1,
    )

    assert np.allclose(recharge_mm_day, [1.0e-7 * 86_400.0 * 1_000.0])


def test_step_series_trim_to_common_length():
    x, y = _align_step_series(
        np.asarray([0.0, 1.0, 2.0, 3.0], dtype=float),
        np.asarray([10.0, 20.0], dtype=float),
    )

    assert np.allclose(x, [0.0, 1.0])
    assert np.allclose(y, [10.0, 20.0])


def test_period_values_pad_initial_state():
    aligned = _align_period_values_to_elapsed_days(
        np.asarray([3.0, 7.0], dtype=float),
        elapsed_days=np.asarray([0.0, 2.0, 4.0], dtype=float),
    )

    assert np.allclose(aligned, [3.0, 3.0, 7.0])


def test_head_profile_falls_back_to_catalog_fields(tmp_path: Path):
    store, sim_id = write_validation_fields_to_store(
        out_path=tmp_path,
        fields={
            "watertable_elevation": {
                0: np.asarray([[1.0, 3.0], [5.0, 7.0]], dtype=float),
                1: np.asarray([[2.0, 4.0], [6.0, 8.0]], dtype=float),
            }
        },
        solver_name="boussinesq",
        flow_regime="transient",
    )
    try:
        result = ValidationRunResult(
            case_dir=tmp_path,
            solver_name="petsc_partition",
            out_path=tmp_path,
            model_ws=tmp_path,
            postprocess_dir=tmp_path / "_postprocess",
            particles_dir=tmp_path / "_postprocess" / "_particles",
            store=store,
            sim_id=sim_id,
        )

        profiles = _resolve_mean_head_profiles_m(
            result=result,
            state_history={},
            cell_x_m=np.asarray([], dtype=float),
            cell_y_m=np.asarray([], dtype=float),
            nx=2,
            ny=2,
            length_x_m=2.0,
            width_y_m=2.0,
        )

        np.testing.assert_allclose(
            profiles,
            np.asarray([[3.0, 5.0], [4.0, 6.0]], dtype=float),
        )
    finally:
        if store is not None:
            store.close()


PRESETS = [
    pytest.param("petsc_partition", "strong", 40.0, id="strong"),
    pytest.param("petsc_partition", "extreme", 40.0, id="extreme"),
    pytest.param("petsc", "alternating", 20.0, id="alternating"),
]


@pytest.mark.parametrize(("solver", "preset", "total_days"), PRESETS)
def test_real_presets_cover_their_duration(solver, preset, total_days):
    _, time_cfg, forcing_cfg, _, _ = _resolve_case_settings(
        load_case_metadata(CASE_DIR),
        variant=resolve_solver_variant(solver),
        context_preset=None,
        forcing_preset=preset,
        forcing_scale=1.0,
        east_head_m=None,
        initial_head_m=None,
        dt_days=None,
        runtime_max_iterations=None,
        runtime_tol_residual_inf=None,
    )

    assert float(time_cfg["dt_days"]) * len(forcing_cfg["recharge_mm_day"]) == pytest.approx(
        total_days
    )
