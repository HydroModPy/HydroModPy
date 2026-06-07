from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.calibration.natural_observations import (
    discharge_log_nse_cost,
    natural_network_cost,
    score_natural_network_transient_candidate,
    write_natural_observation_package,
)


def _line_geometry(n_cells: int = 5) -> tuple[np.ndarray, np.ndarray]:
    centroids = np.column_stack([np.arange(n_cells, dtype=float), np.zeros(n_cells, dtype=float)])
    area = np.ones(n_cells, dtype=float)
    return centroids, area


def _line_distance_to_observed_network(n_cells: int = 5, *, center: float = 1.5) -> np.ndarray:
    return np.abs(np.arange(n_cells, dtype=float) - float(center))


def test_natural_network_cost_is_zero_for_same_support() -> None:
    centroids, area = _line_geometry()
    observed = np.array([False, True, True, False, False])
    candidate = np.array([0.0, 2.0, 1.0, 0.0, 0.0])
    distance = _line_distance_to_observed_network()

    score = natural_network_cost(
        candidate,
        observed,
        distance,
        centroids,
        area,
        d_tol=1.0,
    )

    assert score.total == pytest.approx(0.0)
    assert score.components["E_dist"] == pytest.approx(0.0)
    assert score.components["distance_ratio"] == pytest.approx(1.0)
    assert "C_len" not in score.components


def test_natural_network_cost_penalizes_shifted_support() -> None:
    centroids, area = _line_geometry()
    observed = np.array([False, True, True, False, False])
    candidate = np.array([0.0, 0.0, 0.0, 2.0, 1.0])
    distance = _line_distance_to_observed_network()

    score = natural_network_cost(
        candidate,
        observed,
        distance,
        centroids,
        area,
        d_tol=1.0,
    )

    assert score.total > 0.0
    assert score.components["E_dist"] > 0.0
    assert score.components["E_dist_ratio_abs_minus_one"] == pytest.approx(3.0)


def test_write_natural_package_and_score_identity(tmp_path: Path) -> None:
    centroids, area = _line_geometry()
    observed_network = np.array([False, True, True, False, False])
    observed_distance = _line_distance_to_observed_network()
    observed_q = np.array([1.0, 1.2, 0.8, 1.1])

    summary = write_natural_observation_package(
        tmp_path,
        observed_q_total_release=observed_q,
        observed_network_mask=observed_network,
        observed_network_distance_by_cell=observed_distance,
        centroids=centroids,
        cell_area=area,
        metadata={"site_id": "unit"},
        d_tol=1.0,
    )

    score = score_natural_network_transient_candidate(
        tmp_path,
        candidate_steady_drain_by_cell=observed_network.astype(float),
        candidate_q_total_release=observed_q,
    )
    metadata = json.loads((tmp_path / "metadata.json").read_text("utf-8"))
    normalization = json.loads((tmp_path / "normalization.json").read_text("utf-8"))

    assert summary.n_observed_network_active == 2
    assert score.total == pytest.approx(0.0)
    assert score.components["C_reseau_naturel"] == pytest.approx(0.0)
    assert score.components["C_debit_obs"] == pytest.approx(0.0)
    assert score.components["discharge.NSElog"] == pytest.approx(1.0)
    assert metadata["package_type"] == "natural_observation_package"
    assert metadata["discharge_observable"] == "observed_streamflow_nse_log"
    assert normalization["discharge_metric"] == "nse_log"
    assert (tmp_path / "steady_network_drain_by_cell.npz").is_file()
    assert (tmp_path / "transient_q_total_release.csv").is_file()
    assert (tmp_path / "observed_network_distance_by_cell.npz").is_file()


def test_score_natural_candidate_combines_network_and_discharge(tmp_path: Path) -> None:
    centroids, area = _line_geometry()
    observed_network = np.array([False, True, True, False, False])
    observed_distance = _line_distance_to_observed_network()
    observed_q = np.array([0.8, 1.0, 1.4, 1.1])
    write_natural_observation_package(
        tmp_path,
        observed_q_total_release=observed_q,
        observed_network_mask=observed_network,
        observed_network_distance_by_cell=observed_distance,
        centroids=centroids,
        cell_area=area,
        d_tol=1.0,
    )

    score = score_natural_network_transient_candidate(
        tmp_path,
        candidate_steady_drain_by_cell=np.array([0.0, 0.0, 0.0, 1.0, 1.0]),
        candidate_q_total_release=np.array([2.0, 2.0, 2.0, 2.0]),
    )

    assert score.total > 0.0
    assert score.components["C_reseau_naturel"] > 0.0
    assert score.components["C_debit_obs"] > 0.0


def test_discharge_log_nse_cost_is_zero_for_perfect_series() -> None:
    q_obs = np.array([0.8, 1.0, 1.3, 1.1])

    cost, components = discharge_log_nse_cost(q_obs, q_obs)

    assert cost == pytest.approx(0.0)
    assert components["NSElog"] == pytest.approx(1.0)


def test_discharge_log_nse_cost_penalizes_low_flow_ratio_errors() -> None:
    q_obs = np.array([0.2, 0.4, 1.0, 2.0])
    q_sim = np.array([0.4, 0.8, 1.0, 2.0])

    cost, components = discharge_log_nse_cost(q_sim, q_obs)

    assert cost > 0.0
    assert components["NSElog"] < 1.0
