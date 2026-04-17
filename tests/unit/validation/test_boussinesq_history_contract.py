from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.export_payload import build_state_history_export_payload
from hydromodpy.solver.boussinesq.history_contract import time_axis_sidecar_path
from validation_cases.shared.boussinesq_budget import compute_free_control_volume_budget
from validation_cases.shared.boussinesq_uniform_strip import (
    aggregate_triangle_history_to_structured_grids,
)
from validation_cases.shared.loaders import (
    align_snapshot_series_to_expected_count,
    load_npy_time_series_arrays_with_elapsed_seconds,
)


def _write_minimal_budget_bundle(bundle_dir: Path) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
                "0,triangle,0,1,2,,0.25,0.5,10.0,10.0,10.0,0.0,0.0,1,zone_1,1.0e-5,0.2",
                "1,triangle,1,2,3,,0.75,0.5,10.0,10.0,10.0,0.0,0.0,1,zone_1,1.0e-5,0.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "edges.csv").write_text(
        "\n".join(
            [
                "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
                "0,0,1,0,1,1.0,internal,false,zone_1,zone_1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle_dir


def test_build_state_history_export_payload_records_explicit_transient_axes() -> None:
    state = BoussinesqState(
        head_m=np.asarray([11.0, 10.0], dtype=float),
        saturated_thickness_m=np.asarray([6.0, 5.0], dtype=float),
        recharge_rate_m_s=np.asarray([2.0e-7, 1.0e-7], dtype=float),
        well_flux_m3_s=np.zeros(2, dtype=float),
        saturation_excess_rate_m_s=np.zeros(2, dtype=float),
        recharge_rate_history_m_s=np.asarray(
            [
                [0.0, 0.0],
                [1.0e-7, 1.0e-7],
                [2.0e-7, 1.0e-7],
            ],
            dtype=float,
        ),
        well_flux_history_m3_s=np.zeros((3, 2), dtype=float),
        head_history_m=np.asarray(
            [
                [10.0, 9.0],
                [10.5, 9.5],
                [11.0, 10.0],
            ],
            dtype=float,
        ),
        saturated_thickness_history_m=np.asarray(
            [
                [5.0, 4.0],
                [5.5, 4.5],
                [6.0, 5.0],
            ],
            dtype=float,
        ),
        saturation_excess_history_m_s=np.zeros((3, 2), dtype=float),
        internal_edge_flux_m3_s=np.zeros(1, dtype=float),
        internal_edge_flux_history_m3_s=np.zeros((3, 1), dtype=float),
        boundary_edge_flux_m3_s=np.zeros(1, dtype=float),
        boundary_edge_flux_history_m3_s=np.zeros((3, 1), dtype=float),
        prescribed_head_flux_m3_s=np.zeros(2, dtype=float),
        prescribed_head_flux_history_m3_s=np.zeros((3, 2), dtype=float),
        prescribed_head_m_by_cell=np.asarray([np.nan, 9.0], dtype=float),
        prescribed_head_history_m_by_cell=np.asarray(
            [
                [np.nan, 9.0],
                [np.nan, 9.0],
                [np.nan, 9.0],
            ],
            dtype=float,
        ),
        drainage_flux_m3_s=np.zeros(2, dtype=float),
        drainage_flux_history_m3_s=np.zeros((3, 2), dtype=float),
        period_lengths_seconds=(3600.0, 7200.0),
        nonlinear_iterations=(2, 3),
        converged_by_period=(True, True),
    )

    payload = build_state_history_export_payload(state)

    np.testing.assert_allclose(
        payload["snapshot_elapsed_seconds"],
        np.asarray([0.0, 3600.0, 10800.0], dtype=float),
    )
    np.testing.assert_allclose(
        payload["step_end_elapsed_seconds"],
        np.asarray([3600.0, 10800.0], dtype=float),
    )


def test_aggregate_triangle_history_to_structured_grids_writes_canonical_full_snapshot_history(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "model"
    (model_path / "_postprocess").mkdir(parents=True, exist_ok=True)
    model = SimpleNamespace(
        full_path=model_path,
        state=SimpleNamespace(
            head_history_m=np.asarray(
                [
                    [9.0, 8.0],
                    [9.5, 8.5],
                    [10.0, 9.0],
                ],
                dtype=float,
            ),
            period_lengths_seconds=(3600.0, 7200.0),
        ),
        mesh=SimpleNamespace(
            n_cells=2,
            x_min_m=0.0,
            x_max_m=1.0,
            y_min_m=0.0,
            y_max_m=1.0,
            cell_centroid_x_m=np.asarray([0.25, 0.75], dtype=float),
            cell_centroid_y_m=np.asarray([0.5, 0.5], dtype=float),
            z_top_m=np.asarray([10.0, 10.0], dtype=float),
        ),
    )

    aggregate_triangle_history_to_structured_grids(
        model,
        nx=2,
        ny=1,
    )

    payload = np.load(
        model_path / "_postprocess" / "watertable_elevation.npy",
        allow_pickle=True,
    ).item()
    time_axis_payload = np.load(
        time_axis_sidecar_path(model_path / "_postprocess" / "watertable_elevation.npy"),
        allow_pickle=True,
    ).item()

    assert sorted(payload) == [0, 1, 2]
    np.testing.assert_array_equal(
        np.asarray(time_axis_payload["time_keys"], dtype=int),
        np.asarray([0, 1, 2], dtype=int),
    )
    np.testing.assert_allclose(
        np.asarray(time_axis_payload["elapsed_seconds"], dtype=float),
        np.asarray([0.0, 3600.0, 10800.0], dtype=float),
    )


def test_load_npy_time_series_arrays_with_elapsed_seconds_reads_sidecar(
    tmp_path: Path,
) -> None:
    postprocess_dir = tmp_path / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(
        postprocess_dir / "demo.npy",
        {
            1: np.asarray([10.0], dtype=float),
            2: np.asarray([11.0], dtype=float),
        },
    )
    np.save(
        time_axis_sidecar_path(postprocess_dir / "demo.npy"),
        {
            "time_keys": np.asarray([1, 2], dtype=int),
            "elapsed_seconds": np.asarray([3600.0, 7200.0], dtype=float),
        },
    )

    time_keys, values, elapsed_seconds = load_npy_time_series_arrays_with_elapsed_seconds(
        postprocess_dir,
        "demo",
    )

    np.testing.assert_array_equal(time_keys, np.asarray([1, 2], dtype=int))
    np.testing.assert_allclose(values[:, 0], np.asarray([10.0, 11.0], dtype=float))
    assert elapsed_seconds is not None
    np.testing.assert_allclose(
        elapsed_seconds,
        np.asarray([3600.0, 7200.0], dtype=float),
    )


def test_align_snapshot_series_to_expected_count_drops_identified_initial_snapshot() -> None:
    time_keys, values, elapsed_seconds = align_snapshot_series_to_expected_count(
        np.asarray([0, 1, 2], dtype=int),
        np.asarray([[9.0], [10.0], [11.0]], dtype=float),
        np.asarray([0.0, 3600.0, 7200.0], dtype=float),
        expected_count=2,
        name="demo",
    )

    np.testing.assert_array_equal(time_keys, np.asarray([1, 2], dtype=int))
    np.testing.assert_allclose(values[:, 0], np.asarray([10.0, 11.0], dtype=float))
    assert elapsed_seconds is not None
    np.testing.assert_allclose(elapsed_seconds, np.asarray([3600.0, 7200.0], dtype=float))


def test_compute_free_control_volume_budget_returns_step_aligned_flux_series(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_budget_bundle(tmp_path / "bundle")
    state_history = {
        "head_history_m": np.asarray(
            [
                [10.0, 9.0],
                [11.0, 9.0],
                [13.0, 9.0],
            ],
            dtype=float,
        ),
        "recharge_rate_history_m_s": np.asarray(
            [
                [0.0, 0.0],
                [1.0e-7, 9.0e-7],
                [2.0e-7, 8.0e-7],
            ],
            dtype=float,
        ),
        "drainage_flux_history_m3_s": np.asarray(
            [
                [0.0, 0.0],
                [0.1, 0.2],
                [0.3, 0.4],
            ],
            dtype=float,
        ),
        "saturation_excess_history_m_s": np.asarray(
            [
                [0.0, 0.0],
                [0.01, 0.02],
                [0.03, 0.04],
            ],
            dtype=float,
        ),
        "internal_edge_flux_history_m3_s": np.asarray(
            [
                [0.0],
                [0.5],
                [0.6],
            ],
            dtype=float,
        ),
        "prescribed_head_history_m_by_cell": np.asarray(
            [
                [np.nan, 9.0],
                [np.nan, 9.0],
                [np.nan, 9.0],
            ],
            dtype=float,
        ),
        "period_lengths_seconds": np.asarray([86400.0, 86400.0], dtype=float),
    }

    budget = compute_free_control_volume_budget(
        bundle_dir=bundle_dir,
        state_history=state_history,
        seconds_per_day=86400.0,
        dt_days=1.0,
    )

    np.testing.assert_array_equal(budget.free_cell_mask, np.asarray([True, False]))
    assert budget.recharge_flux_m3_day.shape == (2,)
    assert budget.drainage_flux_m3_day.shape == (2,)
    assert budget.surface_excess_flux_m3_day.shape == (2,)
    assert budget.east_boundary_outflow_m3_day.shape == (2,)
    assert budget.storage_change_m3_day.shape == (2,)

    np.testing.assert_allclose(
        budget.recharge_flux_m3_day,
        np.asarray([0.0864, 0.1728], dtype=float),
    )
    np.testing.assert_allclose(
        budget.drainage_flux_m3_day,
        np.asarray([8640.0, 25920.0], dtype=float),
    )
    np.testing.assert_allclose(
        budget.surface_excess_flux_m3_day,
        np.asarray([8640.0, 25920.0], dtype=float),
    )
    np.testing.assert_allclose(
        budget.east_boundary_outflow_m3_day,
        np.asarray([43200.0, 51840.0], dtype=float),
    )
    np.testing.assert_allclose(
        budget.storage_change_m3_day,
        np.asarray([2.0, 4.0], dtype=float),
    )
