"""Anti-regression rendering smoke tests for ``visuals_render_maps``.

Exercises the map figure entry points end-to-end against a ``tmp_path``:
map comparison, difference figure, regridded map/difference, and GeoTIFF
export.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.analysis.comparison import visuals_render_maps
from hydromodpy.analysis.comparison.visuals_payloads import DifferencePayload
from hydromodpy.analysis.comparison.visuals_render_maps import (
    _write_difference_figure,
    _write_geotiff,
    _write_map_comparison_figure,
    _write_regridded_difference_figure,
    _write_regridded_map_figure,
)

from ._test_visuals_helpers_builders import _structured_payload


def test_write_map_comparison_figure_creates_png(tmp_path: Path) -> None:
    payloads = [
        _structured_payload(simulation_id="ref", shape=(3, 3), values=np.arange(9, dtype=float)),
        _structured_payload(
            simulation_id="cand", shape=(3, 3), values=np.arange(9, dtype=float) * 2.0
        ),
    ]
    out = tmp_path / "map.png"
    _write_map_comparison_figure(path=out, observable_name="head", payloads=payloads)
    assert out.exists()
    assert out.stat().st_size > 0


def test_write_difference_figure_creates_png(tmp_path: Path) -> None:
    diff = DifferencePayload(
        reference_simulation="ref",
        candidate_simulation="cand",
        observable_name="head",
        unit="m",
        values=np.array([0.0, 0.5, -0.5, 1.0]),
        geometry_kind="structured",
        structured_shape=(2, 2),
        extent=(0.0, 2.0, 0.0, 2.0),
    )
    out = tmp_path / "diff.png"
    _write_difference_figure(path=out, payload=diff)
    assert out.exists()


def test_write_regridded_map_figure_creates_png(tmp_path: Path) -> None:
    array_a = np.arange(16, dtype=float).reshape(4, 4)
    array_b = array_a + 1.0
    arrays = [
        (_structured_payload(simulation_id="a"), array_a),
        (_structured_payload(simulation_id="b"), array_b),
    ]
    out = tmp_path / "fine.png"
    ok = _write_regridded_map_figure(
        path=out, observable_name="head", arrays=arrays, extent=(0.0, 4.0, 0.0, 4.0)
    )
    assert ok is True
    assert out.exists()


def test_write_regridded_difference_figure_creates_png(tmp_path: Path) -> None:
    array = np.linspace(-1.0, 1.0, 16).reshape(4, 4)
    out = tmp_path / "fine_diff.png"
    ok = _write_regridded_difference_figure(
        path=out,
        observable_name="head",
        candidate_simulation="cand",
        reference_simulation="ref",
        array=array,
        unit="m",
        extent=(0.0, 4.0, 0.0, 4.0),
    )
    assert ok is True
    assert out.exists()


def test_write_geotiff_creates_tif(tmp_path: Path) -> None:
    if visuals_render_maps.rasterio is None:
        pytest.skip("rasterio not installed")
    array = np.arange(16, dtype=float).reshape(4, 4)
    out = tmp_path / "raster.tif"
    ok = _write_geotiff(path=out, array=array, extent=(0.0, 4.0, 0.0, 4.0))
    assert ok is True
    assert out.exists()


def test_write_geotiff_returns_false_for_zero_dim(tmp_path: Path) -> None:
    if visuals_render_maps.rasterio is None:
        pytest.skip("rasterio not installed")
    array = np.zeros((0, 0), dtype=float)
    out = tmp_path / "raster.tif"
    assert _write_geotiff(path=out, array=array, extent=(0.0, 1.0, 0.0, 1.0)) is False
