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


def test_binary_reference_is_refused_where_a_flux_is_required() -> None:
    centroids, cell_area = _grid_5x5()
    mask_ref = np.zeros((5, 5), dtype=float)
    mask_ref[:, 2] = 1.0
    ref = mask_ref.reshape(-1)
    sim = _reference_network()

    with pytest.raises(ValueError, match="binary 0/1 mask"):
        network_flux_error(sim, ref)
    with pytest.raises(ValueError, match="per-cell drainage outflow"):
        network_cost(sim, ref, centroids, cell_area, d_tol=1.0)


def test_binary_reference_message_reports_what_it_got_and_what_it_needed() -> None:
    ref = np.array([0.0, 1.0, 0.0, 1.0])
    sim = np.array([0.0, 2.5, 0.0, 1.5])

    with pytest.raises(ValueError) as excinfo:
        network_flux_error(sim, ref)

    message = str(excinfo.value)
    assert "4 cells" in message
    assert "2 active" in message
    assert "per-cell drainage outflow" in message


def test_natural_observation_package_writes_no_flux_named_mask(tmp_path) -> None:
    from hydromodpy.calibration.observations.natural_observations import (
        write_natural_observation_package,
    )

    centroids = np.column_stack([np.arange(5, dtype=float), np.zeros(5)])
    write_natural_observation_package(
        tmp_path,
        observed_q_total_release=np.array([1.0, 1.2, 0.9]),
        observed_network_mask=np.array([False, True, True, False, False]),
        observed_network_distance_by_cell=np.array([1.0, 0.0, 0.0, 1.0, 2.0]),
        centroids=centroids,
        cell_area=np.ones(5),
        d_tol=1.0,
    )

    assert not (tmp_path / "steady_network_drain_by_cell.npz").exists()
    assert (tmp_path / "steady_network_active_mask.npz").is_file()
    assert (tmp_path / "observed_network_active_mask.npz").is_file()
