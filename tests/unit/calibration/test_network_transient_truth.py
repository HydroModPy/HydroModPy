from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.network_transient_truth import (
    discharge_rmse_cost,
    mesh_cell_geometry,
    q_total_release_from_drain_by_cell,
    score_network_transient_candidate,
    score_network_transient_candidate_from_runs,
    write_network_transient_truth_package,
)


def test_mesh_cell_geometry_handles_triangle_and_quad() -> None:
    vertices = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
            [2.0, 0.0],
        ],
        dtype=float,
    )
    faces = np.array(
        [
            [0, 1, 2, 3],
            [1, 4, 2, -1],
        ],
        dtype=int,
    )

    centroids, area = mesh_cell_geometry(vertices, faces)

    np.testing.assert_allclose(centroids[0], [0.5, 0.5])
    np.testing.assert_allclose(centroids[1], [4.0 / 3.0, 1.0 / 3.0])
    np.testing.assert_allclose(area, [1.0, 0.5])


def test_q_total_release_from_drain_by_cell_sums_positive_rows() -> None:
    drain = np.array(
        [
            [1.0, -2.0, 0.5],
            [0.0, 3.0, np.nan],
        ]
    )

    out = q_total_release_from_drain_by_cell(drain)

    np.testing.assert_allclose(out, [1.5, 3.0])


def test_discharge_rmse_cost_uses_fraction_of_mean_reference() -> None:
    cost, components = discharge_rmse_cost(
        [1.1, 1.9, 3.0],
        [1.0, 2.0, 3.0],
        alpha_q=0.10,
    )

    rmse = np.sqrt((0.1**2 + 0.1**2) / 3.0)
    assert components["RMSE_Q"] == pytest.approx(rmse)
    assert components["Qbar_ref"] == pytest.approx(2.0)
    assert cost == pytest.approx(rmse / 0.2)


def test_write_truth_package_and_score_identity(tmp_path) -> None:
    steady = np.array([1.0, 2.0, 0.0, 1.0], dtype=float)
    q_ref = np.array([0.5, 1.0, 2.0, 3.0], dtype=float)
    centroids = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
        ],
        dtype=float,
    )
    area = np.ones(4, dtype=float)
    time_index = pd.date_range("2020-01-01", periods=4, freq="MS")

    summary = write_network_transient_truth_package(
        tmp_path,
        steady_drain_by_cell=steady,
        transient_q_total_release=q_ref,
        centroids=centroids,
        cell_area=area,
        time_index=time_index,
        metadata={"site_id": "synthetic"},
        d_tol=1.0,
        warmup_periods=1,
        scored_periods=3,
    )
    score = score_network_transient_candidate(
        tmp_path,
        candidate_steady_drain_by_cell=steady,
        candidate_q_total_release=q_ref,
    )

    assert summary.q_ref_steady == pytest.approx(4.0)
    assert summary.qbar_ref == pytest.approx(2.0)
    assert summary.n_ref_active == 3
    assert score.total == pytest.approx(0.0)
    assert score.components["C_reseau_phys"] == pytest.approx(0.0)
    assert score.components["C_debit_phys"] == pytest.approx(0.0)

    normalization = json.loads((tmp_path / "normalization.json").read_text(encoding="utf-8"))
    assert normalization["score_start_index"] == 1
    assert normalization["score_stop_index"] == 4
    assert (tmp_path / "steady_network_drain_by_cell.npz").is_file()
    assert (tmp_path / "transient_q_total_release.csv").is_file()


def test_score_candidate_combines_network_and_discharge_costs(tmp_path) -> None:
    steady = np.array([1.0, 1.0, 0.0, 0.0], dtype=float)
    q_ref = np.array([1.0, 1.0, 1.0], dtype=float)
    centroids = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
        ],
        dtype=float,
    )
    area = np.ones(4, dtype=float)

    write_network_transient_truth_package(
        tmp_path,
        steady_drain_by_cell=steady,
        transient_q_total_release=q_ref,
        centroids=centroids,
        cell_area=area,
        d_tol=1.0,
        eta_flux=1.0,
        eta_dist=1.0,
        eta_len=1.0,
        alpha_q=0.5,
    )

    score = score_network_transient_candidate(
        tmp_path,
        candidate_steady_drain_by_cell=np.zeros_like(steady),
        candidate_q_total_release=np.array([1.5, 1.5, 1.5]),
    )

    assert score.components["C_reseau_phys"] > 0.0
    assert score.components["C_debit_phys"] == pytest.approx(1.0)
    assert score.total == pytest.approx(
        0.5 * score.components["C_reseau_phys"] + 0.5 * score.components["C_debit_phys"]
    )


def test_score_candidate_from_runs_uses_outflow_drain_fields(tmp_path) -> None:
    steady = np.array([1.0, 0.0, 1.0], dtype=float)
    q_ref = np.array([2.0, 2.0], dtype=float)
    centroids = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]], dtype=float)
    area = np.ones(3, dtype=float)
    write_network_transient_truth_package(
        tmp_path,
        steady_drain_by_cell=steady,
        transient_q_total_release=q_ref,
        centroids=centroids,
        cell_area=area,
        d_tol=1.0,
    )

    class _Stack:
        def __init__(self, data):
            self.data = np.asarray(data, dtype=float)

    class _Run:
        def __init__(self, steady_field=None, stack=None):
            self._steady_field = steady_field
            self._stack = stack

        def field(self, variable, timestep=-1):
            del timestep
            assert variable == "outflow_drain"
            return self._steady_field

        def fields(self, variable):
            assert variable == "outflow_drain"
            return _Stack(self._stack)

    score = score_network_transient_candidate_from_runs(
        tmp_path,
        steady_run=_Run(steady_field=steady),
        transient_run=_Run(stack=np.array([[1.0, 0.0, 1.0], [1.0, 0.0, 1.0]])),
    )

    assert score.total == pytest.approx(0.0)
