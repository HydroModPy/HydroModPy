"""Anti-regression unit tests for ``analysis.comparison.visuals_payloads``.

Covers extent estimation, payload extent/samples extraction, difference
payload construction, and the fine-grid bounds/build/regrid helpers.
"""

from __future__ import annotations

import math

import numpy as np

from hydromodpy.analysis.comparison.config import ComparisonFineRaster
from hydromodpy.analysis.comparison.visuals_payloads import (
    MapPayload,
    _build_difference_payload,
    _build_fine_grid,
    _estimate_extent_from_centroids,
    _payload_extent,
    _payload_samples,
    _regrid_payload,
    _resolve_fine_grid_bounds,
)

from ._test_visuals_helpers_builders import _scatter_payload, _structured_payload

# -- extent ---------------------------------------------------------------


def test_estimate_extent_returns_none_when_inputs_none() -> None:
    assert _estimate_extent_from_centroids(x_values=None, y_values=None) is None


def test_estimate_extent_returns_none_when_no_finite_pair() -> None:
    extent = _estimate_extent_from_centroids(
        x_values=np.array([np.nan, np.inf]),
        y_values=np.array([np.nan, -np.inf]),
    )
    assert extent is None


def test_estimate_extent_basic_grid() -> None:
    extent = _estimate_extent_from_centroids(
        x_values=np.array([0.0, 1.0, 2.0, 0.0, 1.0, 2.0]),
        y_values=np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0]),
    )
    assert extent is not None
    xmin, xmax, ymin, ymax = extent
    assert math.isclose(xmin, -0.5)
    assert math.isclose(xmax, 2.5)
    assert math.isclose(ymin, -0.5)
    assert math.isclose(ymax, 1.5)


def test_estimate_extent_single_unique_value_uses_unit_spacing() -> None:
    extent = _estimate_extent_from_centroids(
        x_values=np.array([5.0, 5.0]),
        y_values=np.array([2.0, 2.0]),
    )
    assert extent == (4.5, 5.5, 1.5, 2.5)


def test_payload_extent_returns_payload_extent_directly() -> None:
    payload = _structured_payload(extent=(0.0, 1.0, 0.0, 1.0))
    assert _payload_extent(payload) == (0.0, 1.0, 0.0, 1.0)


def test_payload_extent_falls_back_to_centroids() -> None:
    payload = _scatter_payload(
        x=np.array([0.0, 1.0, 0.0, 1.0]),
        y=np.array([0.0, 0.0, 1.0, 1.0]),
        extent=None,
    )
    extent = _payload_extent(payload)
    assert extent is not None
    assert math.isclose(extent[0], -0.5)
    assert math.isclose(extent[3], 1.5)


# -- samples --------------------------------------------------------------


def test_payload_samples_none_when_xy_missing() -> None:
    payload = _structured_payload()
    payload_no_xy = MapPayload(
        simulation_id=payload.simulation_id,
        simulation_label=payload.simulation_label,
        solver=payload.solver,
        mesh_mode=payload.mesh_mode,
        observable_name=payload.observable_name,
        resolved_variable=payload.resolved_variable,
        unit=payload.unit,
        time_label=payload.time_label,
        values=payload.values,
        geometry_kind=payload.geometry_kind,
        structured_shape=payload.structured_shape,
        x=None,
        y=None,
    )
    assert _payload_samples(payload_no_xy) is None


def test_payload_samples_returns_finite_values_only() -> None:
    payload = _scatter_payload(
        values=np.array([1.0, np.nan, 3.0, -9999.0]),
        x=np.array([0.0, 1.0, 2.0, 3.0]),
        y=np.array([0.0, 1.0, 2.0, 3.0]),
    )
    samples = _payload_samples(payload)
    assert samples is not None
    sample_x, sample_y, sample_values = samples
    assert sample_values.tolist() == [1.0, 3.0]
    assert sample_x.tolist() == [0.0, 2.0]
    assert sample_y.tolist() == [0.0, 2.0]


def test_payload_samples_size_mismatch_returns_none() -> None:
    payload = MapPayload(
        simulation_id="vid",
        simulation_label="lab",
        solver="s",
        mesh_mode="structured",
        observable_name="obs",
        resolved_variable="obs",
        unit="m",
        time_label="t",
        values=np.array([1.0, 2.0, 3.0]),
        geometry_kind="scatter",
        x=np.array([0.0, 1.0]),
        y=np.array([0.0, 1.0]),
    )
    assert _payload_samples(payload) is None


# -- difference payload ---------------------------------------------------


def test_build_difference_payload_unit_mismatch_returns_none() -> None:
    ref = _scatter_payload(unit="m")
    cand = _scatter_payload(unit="m3/s")
    assert _build_difference_payload(reference=ref, candidate=cand) is None


def test_build_difference_payload_scatter_match_subtracts() -> None:
    ref = _scatter_payload(values=np.array([1.0, 2.0, 3.0, 4.0]))
    cand = _scatter_payload(values=np.array([2.0, 4.0, 6.0, 8.0]))
    diff = _build_difference_payload(reference=ref, candidate=cand)
    assert diff is not None
    np.testing.assert_array_equal(diff.values, np.array([1.0, 2.0, 3.0, 4.0]))
    assert diff.geometry_kind == "scatter"


def test_build_difference_payload_scatter_size_mismatch_returns_none() -> None:
    ref = _scatter_payload(values=np.array([1.0, 2.0, 3.0]))
    cand = _scatter_payload(values=np.array([2.0, 4.0]))
    assert _build_difference_payload(reference=ref, candidate=cand) is None


def test_build_difference_payload_scatter_cellid_mismatch_returns_none() -> None:
    ref = _scatter_payload(cell_ids=np.array([0, 1, 2, 3]))
    cand = _scatter_payload(cell_ids=np.array([10, 11, 12, 13]))
    assert _build_difference_payload(reference=ref, candidate=cand) is None


def test_build_difference_payload_structured_match() -> None:
    ref = _structured_payload(values=np.arange(4, dtype=float))
    cand = _structured_payload(values=np.arange(4, dtype=float) * 2.0)
    diff = _build_difference_payload(reference=ref, candidate=cand)
    assert diff is not None
    assert diff.geometry_kind == "structured"
    np.testing.assert_array_equal(diff.values, np.arange(4, dtype=float))


def test_build_difference_payload_structured_shape_mismatch_returns_none() -> None:
    ref = _structured_payload(shape=(2, 2), values=np.arange(4, dtype=float))
    cand = _structured_payload(shape=(2, 3), values=np.arange(6, dtype=float))
    assert _build_difference_payload(reference=ref, candidate=cand) is None


def test_build_difference_payload_mixed_geometries_returns_none() -> None:
    ref = _scatter_payload()
    cand = _structured_payload()
    assert _build_difference_payload(reference=ref, candidate=cand) is None


# -- fine grid bounds / build_fine_grid ----------------------------------


def test_build_fine_grid_basic_shape() -> None:
    grid = _build_fine_grid(bounds=(0.0, 10.0, 0.0, 5.0), resolution=1.0)
    assert grid is not None
    grid_x, grid_y, extent = grid
    assert grid_x.shape == grid_y.shape
    assert grid_x.shape[0] == 5  # y
    assert grid_x.shape[1] == 10  # x
    assert extent == (0.0, 10.0, 0.0, 5.0)


def test_build_fine_grid_resolution_too_large_returns_none() -> None:
    grid = _build_fine_grid(bounds=(0.0, 1.0, 0.0, 1.0), resolution=10.0)
    assert grid is None


def test_resolve_fine_grid_bounds_too_few_extents_returns_none() -> None:
    fine = ComparisonFineRaster(enabled=True, resolution=1.0, extent_mode="union")
    payloads = [_scatter_payload(extent=(0.0, 1.0, 0.0, 1.0))]
    assert (
        _resolve_fine_grid_bounds(payloads=payloads, fine_raster=fine, reference_simulation=None)
        is None
    )


def test_resolve_fine_grid_bounds_intersection() -> None:
    fine = ComparisonFineRaster(enabled=True, resolution=1.0, extent_mode="intersection")
    payloads = [
        _scatter_payload(simulation_id="a", extent=(0.0, 4.0, 0.0, 4.0)),
        _scatter_payload(simulation_id="b", extent=(2.0, 6.0, 2.0, 6.0)),
    ]
    bounds = _resolve_fine_grid_bounds(
        payloads=payloads, fine_raster=fine, reference_simulation=None
    )
    assert bounds == (2.0, 4.0, 2.0, 4.0)


def test_resolve_fine_grid_bounds_intersection_disjoint_returns_none() -> None:
    fine = ComparisonFineRaster(enabled=True, resolution=1.0, extent_mode="intersection")
    payloads = [
        _scatter_payload(simulation_id="a", extent=(0.0, 1.0, 0.0, 1.0)),
        _scatter_payload(simulation_id="b", extent=(5.0, 6.0, 5.0, 6.0)),
    ]
    assert (
        _resolve_fine_grid_bounds(payloads=payloads, fine_raster=fine, reference_simulation=None)
        is None
    )


def test_resolve_fine_grid_bounds_union() -> None:
    fine = ComparisonFineRaster(enabled=True, resolution=1.0, extent_mode="union")
    payloads = [
        _scatter_payload(simulation_id="a", extent=(0.0, 4.0, 0.0, 4.0)),
        _scatter_payload(simulation_id="b", extent=(2.0, 6.0, 2.0, 6.0)),
    ]
    bounds = _resolve_fine_grid_bounds(
        payloads=payloads, fine_raster=fine, reference_simulation=None
    )
    assert bounds == (0.0, 6.0, 0.0, 6.0)


def test_resolve_fine_grid_bounds_reference_uses_reference_extent() -> None:
    fine = ComparisonFineRaster(enabled=True, resolution=1.0, extent_mode="reference")
    payloads = [
        _scatter_payload(simulation_id="a", extent=(0.0, 4.0, 0.0, 4.0)),
        _scatter_payload(simulation_id="b", extent=(2.0, 6.0, 2.0, 6.0)),
    ]
    bounds = _resolve_fine_grid_bounds(
        payloads=payloads, fine_raster=fine, reference_simulation="a"
    )
    assert bounds == (0.0, 4.0, 0.0, 4.0)


def test_regrid_payload_linear_against_grid() -> None:
    payload = _scatter_payload(
        values=np.array([0.0, 1.0, 2.0, 3.0]),
        x=np.array([0.0, 1.0, 0.0, 1.0]),
        y=np.array([0.0, 0.0, 1.0, 1.0]),
    )
    grid_x, grid_y = np.meshgrid(np.linspace(0.1, 0.9, 3), np.linspace(0.1, 0.9, 3))
    array = _regrid_payload(payload=payload, grid_x=grid_x, grid_y=grid_y, interpolation="linear")
    assert array is not None
    assert array.shape == (3, 3)
    assert np.all(np.isfinite(array))


def test_regrid_payload_returns_none_when_no_finite_samples() -> None:
    payload = _scatter_payload(
        values=np.array([np.nan, np.nan, np.nan, np.nan]),
        x=np.array([0.0, 1.0, 0.0, 1.0]),
        y=np.array([0.0, 0.0, 1.0, 1.0]),
    )
    grid_x, grid_y = np.meshgrid([0.5], [0.5])
    array = _regrid_payload(payload=payload, grid_x=grid_x, grid_y=grid_y, interpolation="linear")
    assert array is None
