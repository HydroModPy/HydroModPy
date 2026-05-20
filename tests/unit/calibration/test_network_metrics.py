"""Unit tests for physical network calibration metrics."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.metrics.network import (
    active_network_mask,
    network_cost,
    network_distance_error,
    network_flux_error,
    network_length_error,
    positive_outflow,
)


def _grid_5x5() -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.meshgrid(np.arange(5, dtype=float), np.arange(5, dtype=float), indexing="ij")
    centroids = np.column_stack([xx.reshape(-1), yy.reshape(-1)])
    cell_area = np.ones(25, dtype=float)
    return centroids, cell_area


def _reference_network() -> np.ndarray:
    ref = np.zeros((5, 5), dtype=float)
    ref[:, 2] = 1.0
    ref[2, 3] = 0.2
    return ref.reshape(-1)


def test_positive_outflow_removes_negative_nan_and_nodata_values() -> None:
    out = positive_outflow([1.0, -2.0, np.nan, -9999.0, 0.5])
    np.testing.assert_allclose(out, [1.0, 0.0, 0.0, 0.0, 0.5])
    assert active_network_mask(out).tolist() == [True, False, False, False, True]


def test_identical_network_has_zero_cost() -> None:
    centroids, cell_area = _grid_5x5()
    ref = _reference_network()

    out = network_cost(ref, ref, centroids, cell_area, d_tol=1.0)

    assert out.total == pytest.approx(0.0)
    assert out.components["E_flux"] == pytest.approx(0.0)
    assert out.components["E_dist"] == pytest.approx(0.0)
    assert out.components["E_len"] == pytest.approx(0.0)


def test_network_shifted_by_one_cell_has_distance_error_near_one() -> None:
    centroids, _ = _grid_5x5()
    ref_grid = np.zeros((5, 5), dtype=float)
    ref_grid[:, 2] = 1.0
    sim = np.roll(ref_grid, shift=1, axis=1).reshape(-1)

    err = network_distance_error(sim, ref_grid.reshape(-1), centroids, d_tol=1.0)

    assert err == pytest.approx(1.0)


def test_empty_simulated_network_gets_finite_distance_penalty() -> None:
    centroids, cell_area = _grid_5x5()
    ref = _reference_network()
    sim = np.zeros_like(ref)

    err = network_distance_error(sim, ref, centroids, d_tol=1.0, empty_distance_penalty=7.0)
    out = network_cost(
        sim,
        ref,
        centroids,
        cell_area,
        d_tol=1.0,
        empty_distance_penalty=7.0,
    )

    assert err == pytest.approx(7.0)
    assert out.components["E_dist"] == pytest.approx(7.0)
    assert np.isfinite(out.total)
    assert out.total > 0.0


def test_missing_main_axis_penalizes_more_than_missing_side_branch() -> None:
    ref = _reference_network()
    missing_main = ref.reshape(5, 5).copy()
    missing_main[:, 2] = 0.0
    missing_branch = ref.reshape(5, 5).copy()
    missing_branch[2, 3] = 0.0

    main_error = network_flux_error(missing_main.reshape(-1), ref)
    branch_error = network_flux_error(missing_branch.reshape(-1), ref)

    assert main_error > branch_error
    assert main_error == pytest.approx(5.0 / 5.2)
    assert branch_error == pytest.approx(0.2 / 5.2)


def test_double_width_network_has_unit_length_error() -> None:
    _, cell_area = _grid_5x5()
    ref = np.zeros((5, 5), dtype=bool)
    ref[:, 2] = True
    sim = ref.copy()
    sim[:, 1] = True

    err = network_length_error(sim.reshape(-1), ref.reshape(-1), cell_area, d_tol=1.0)

    assert err == pytest.approx(1.0)


def test_empty_reference_network_is_invalid() -> None:
    centroids, cell_area = _grid_5x5()
    ref = np.zeros(25, dtype=float)
    sim = np.zeros(25, dtype=float)

    with pytest.raises(ValueError, match="q_ref_steady"):
        network_flux_error(sim, ref)
    with pytest.raises(ValueError, match="q_ref_steady"):
        network_cost(sim, ref, centroids, cell_area, d_tol=1.0)


def test_component_weights_are_normalized() -> None:
    centroids, cell_area = _grid_5x5()
    ref = _reference_network()
    sim = np.zeros_like(ref)

    out = network_cost(
        sim,
        ref,
        centroids,
        cell_area,
        d_tol=1.0,
        weight_flux=4.0,
        weight_dist=4.0,
        weight_len=2.0,
        empty_distance_penalty=1.0,
    )

    assert out.components["weight_flux"] == pytest.approx(0.4)
    assert out.components["weight_dist"] == pytest.approx(0.4)
    assert out.components["weight_len"] == pytest.approx(0.2)
