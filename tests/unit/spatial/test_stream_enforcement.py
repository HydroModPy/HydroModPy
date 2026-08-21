"""Burn the observed stream network into the routing DEM before D8 routing."""

from __future__ import annotations

import logging

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from hydromodpy.spatial.geographic.core.stream_enforcement import (
    burn_streams_into_routing_dem,
    check_catchment_area_drift,
)

_N = 20
_RES = 10.0
_TRANSFORM = from_origin(0.0, _N * _RES, _RES, _RES)  # top-left (0, 200), 10 m cells
# Plane sloping from 100 m (north) to 60 m (south): one row step is 40/19 m, which
# is the drop a trench along a north-south line has to clear.
_ROW_DROP = 40.0 / (_N - 1)
_DEM = np.tile((100.0 - 40.0 * np.arange(_N) / (_N - 1))[:, None], (1, _N)).astype("float32")
# Down the middle of column 10, from the north edge to the south edge.
_STREAM = LineString([(105.0, 195.0), (105.0, 5.0)])


def _write_dem(path: str) -> None:
    profile = {
        "driver": "GTiff",
        "height": _N,
        "width": _N,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": _TRANSFORM,
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(_DEM, 1)


def _burn(tmp_path, **kwargs):
    raw = str(tmp_path / "raw.tif")
    out = str(tmp_path / "routing.tif")
    _write_dem(raw)
    report = burn_streams_into_routing_dem(
        dem_in_path=raw,
        dem_out_path=out,
        stream_lines=kwargs.pop("stream_lines", [_STREAM]),
        **kwargs,
    )
    with rasterio.open(out) as src:
        return report, src.read(1), src.crs


def test_constant_burn_lowers_only_the_mapped_cells(tmp_path) -> None:
    report, burned, crs = _burn(tmp_path, mode="constant", depth_m=30.0)

    trench = np.isclose(burned, _DEM - 30.0)
    assert report.stream_cells == _N
    assert report.depth_m == pytest.approx(30.0)
    # Exactly one column, all its rows, and nothing else moved.
    assert trench.sum() == _N
    assert np.array_equal(np.unique(np.where(trench)[1]), np.array([10]))
    assert np.allclose(burned[~trench], _DEM[~trench])
    assert str(crs) == "EPSG:2154"


def test_raw_dem_is_never_modified(tmp_path) -> None:
    raw = str(tmp_path / "raw.tif")
    _write_dem(raw)

    burn_streams_into_routing_dem(
        dem_in_path=raw,
        dem_out_path=str(tmp_path / "routing.tif"),
        stream_lines=[_STREAM],
        depth_m=30.0,
    )

    with rasterio.open(raw) as src:
        assert np.allclose(src.read(1), _DEM)


def test_an_oblique_trace_keeps_every_cell_it_clips(tmp_path) -> None:
    # all_touched: a one-cell-wide trace must not lose the cells it only clips.
    # This one spans 20 columns while dropping 4 rows, so it grazes many corners.
    oblique = LineString([(5.0, 195.0), (195.0, 155.0)])

    report, burned, _ = _burn(tmp_path, stream_lines=[oblique], depth_m=5.0)

    lowered = np.isclose(burned, _DEM - 5.0)
    assert report.stream_cells == lowered.sum()
    # One cell per column would be 20; the clipped corners bring more.
    assert report.stream_cells > _N


def test_adaptive_depth_comes_from_the_measured_relief(tmp_path) -> None:
    report, burned, _ = _burn(tmp_path, mode="adaptive", adaptive_percentile=95.0)

    # Every stream cell but the southernmost sits exactly one row step above its
    # lowest off-stream neighbour, so the 95th percentile is that row step.
    assert report.relief_p95_m == pytest.approx(_ROW_DROP, rel=1e-5)
    assert report.depth_m == pytest.approx(_ROW_DROP, rel=1e-5)
    assert np.isclose(burned, _DEM - report.depth_m).sum() == _N


def test_relief_is_reported_even_in_constant_mode(tmp_path) -> None:
    # The measurement is what tells the user whether their depth is deep enough.
    report, _, _ = _burn(tmp_path, mode="constant", depth_m=30.0)

    assert report.relief_p95_m == pytest.approx(_ROW_DROP, rel=1e-5)
    assert report.relief_max_m == pytest.approx(_ROW_DROP, rel=1e-5)


def test_a_depth_below_the_local_relief_warns(tmp_path, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        _burn(tmp_path, mode="constant", depth_m=0.5)

    assert "shallower than the 95th percentile" in caplog.text


def test_unknown_mode_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="Unknown stream burn mode"):
        _burn(tmp_path, mode="fill_burn")


def test_no_geometry_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="no stream geometry"):
        _burn(tmp_path, stream_lines=[])


def test_geometry_outside_the_dem_raises(tmp_path) -> None:
    far_away = LineString([(50_000.0, 50_000.0), (50_100.0, 50_100.0)])

    with pytest.raises(ValueError, match="rasterize to no valid DEM cell"):
        _burn(tmp_path, stream_lines=[far_away])


class _Enforce:
    def __init__(self, *, enabled: bool = True, max_catchment_area_drift: float = 0.05):
        self.enabled = enabled
        self.max_catchment_area_drift = max_catchment_area_drift


class _Config:
    def __init__(self, enforce):
        self.enforce_streams = enforce


def test_area_drift_within_the_limit_passes() -> None:
    check_catchment_area_drift(
        config=_Config(_Enforce()),
        reference_area_km2=100.0,
        burned_area_km2=103.0,
    )


def test_area_drift_above_the_limit_raises() -> None:
    with pytest.raises(ValueError, match="moved the delineated"):
        check_catchment_area_drift(
            config=_Config(_Enforce()),
            reference_area_km2=100.0,
            burned_area_km2=180.0,
        )


def test_area_drift_is_not_checked_without_a_reference() -> None:
    # Burning off: nothing was measured, so nothing is claimed.
    check_catchment_area_drift(
        config=_Config(_Enforce(enabled=False)),
        reference_area_km2=None,
        burned_area_km2=180.0,
    )


def test_an_empty_reference_catchment_raises() -> None:
    with pytest.raises(ValueError, match="empty catchment"):
        check_catchment_area_drift(
            config=_Config(_Enforce()),
            reference_area_km2=0.0,
            burned_area_km2=100.0,
        )
