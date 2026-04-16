from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d import (
    comparison as comparison_module,
)
from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.diagnostics import (
    _align_period_values_to_elapsed_days,
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


def test_resolve_solver_variant_exposes_both_petsc_surface_formulations() -> None:
    partition = resolve_solver_variant("petsc_partition")
    complementarity = resolve_solver_variant("petsc")

    assert partition.runtime_backend == "petsc"
    assert partition.surface_interaction_model == "regularized_partition"
    assert complementarity.runtime_backend == "petsc"
    assert complementarity.surface_interaction_model == "complementarity"


def test_compute_overflow_footprint_metrics_tracks_length_front_and_centroid() -> None:
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


def test_select_snapshot_indices_prioritizes_requested_days_then_caps_count() -> None:
    indices = select_snapshot_indices(
        np.asarray([0.0, 2.0, 4.0, 6.0, 8.0], dtype=float),
        requested_days=(0.1, 5.1, 7.9),
        max_snapshots=2,
    )

    assert indices == [0, 3]


def test_run_hillslope_overflow_scenario_rejects_duplicate_compare_solver(monkeypatch) -> None:
    monkeypatch.setattr(comparison_module, "load_case_metadata", lambda case_dir: {})

    with pytest.raises(ValueError, match="compare_solver must differ from solver"):
        comparison_module.run_hillslope_overflow_scenario(
            caller_file=Path("dummy_test.py"),
            solver="petsc_partition",
            compare_solver="petsc_partition",
        )


def test_resolve_case_settings_applies_preset_scale_and_solver_overrides() -> None:
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


def test_run_hillslope_overflow_scenario_keeps_primary_when_compare_solver_fails(
    monkeypatch,
) -> None:
    primary_result = object()
    primary_diag = object()

    monkeypatch.setattr(comparison_module, "load_case_metadata", lambda case_dir: {})

    def _fake_run(*, solver, **kwargs):
        if solver == "petsc":
            raise RuntimeError("secondary failed")
        return primary_result

    def _fake_build(*, result, metadata=None, overflow_threshold_mm_day=None):
        assert result is primary_result
        return primary_diag

    monkeypatch.setattr(comparison_module, "run_boussinesq_hillslope_overflow_case", _fake_run)
    monkeypatch.setattr(comparison_module, "build_hillslope_overflow_diagnostics", _fake_build)

    scenario = comparison_module.run_hillslope_overflow_scenario(
        caller_file=Path("dummy_test.py"),
        solver="petsc_partition",
        compare_solver="petsc",
    )

    assert scenario.primary is primary_diag
    assert scenario.secondary is None
    assert scenario.secondary_solver_name == "petsc"
    assert scenario.secondary_error == "secondary failed"


def test_resolve_recharge_series_mm_day_prefers_runtime_history() -> None:
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


def test_align_step_series_trims_to_common_length() -> None:
    x, y = _align_step_series(
        np.asarray([0.0, 1.0, 2.0, 3.0], dtype=float),
        np.asarray([10.0, 20.0], dtype=float),
    )

    assert np.allclose(x, [0.0, 1.0])
    assert np.allclose(y, [10.0, 20.0])


def test_align_period_values_to_elapsed_days_pads_initial_state() -> None:
    aligned = _align_period_values_to_elapsed_days(
        np.asarray([3.0, 7.0], dtype=float),
        elapsed_days=np.asarray([0.0, 2.0, 4.0], dtype=float),
    )

    assert np.allclose(aligned, [3.0, 3.0, 7.0])


def test_real_strong_and_extreme_presets_cover_40_days() -> None:
    metadata = load_case_metadata(CASE_DIR)

    for solver_name, preset_name in (
        ("petsc_partition", "strong"),
        ("petsc_partition", "extreme"),
    ):
        _, time_cfg, forcing_cfg, _, _ = _resolve_case_settings(
            metadata,
            variant=resolve_solver_variant(solver_name),
            forcing_preset=preset_name,
            forcing_scale=1.0,
            east_head_m=None,
            initial_head_m=None,
            dt_days=None,
            runtime_max_iterations=None,
            runtime_tol_residual_inf=None,
        )
        total_days = float(time_cfg["dt_days"]) * len(forcing_cfg["recharge_mm_day"])
        assert total_days == pytest.approx(40.0)


def test_real_alternating_preset_covers_20_days() -> None:
    metadata = load_case_metadata(CASE_DIR)

    _, time_cfg, forcing_cfg, _, _ = _resolve_case_settings(
        metadata,
        variant=resolve_solver_variant("petsc"),
        forcing_preset="alternating",
        forcing_scale=1.0,
        east_head_m=None,
        initial_head_m=None,
        dt_days=None,
        runtime_max_iterations=None,
        runtime_tol_residual_inf=None,
    )

    total_days = float(time_cfg["dt_days"]) * len(forcing_cfg["recharge_mm_day"])
    assert total_days == pytest.approx(20.0)
