"""Delineate an SFR trace from full DEM-grid raster products (rasterio round-trip)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.spatial.geographic.core.sfr_network import build_sfr_reach_trace_from_products

_RES = 10.0
_N = 8


def _write_raster(path: Path, data: np.ndarray, *, west: float = 0.0, north: float = 80.0) -> str:
    import rasterio
    from rasterio.transform import from_origin

    transform = from_origin(west, north, _RES, _RES)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float64",
        crs="EPSG:32630",
        transform=transform,
    ) as dataset:
        dataset.write(np.asarray(data, dtype="float64"), 1)
    return str(path)


def _write_products(tmp_path: Path) -> dict[str, str]:
    """A straight south-flowing stream in column 3, two links, lake at the foot."""
    dem = np.zeros((_N, _N))
    for row in range(_N):
        dem[row, :] = 100.0 - row
    d8 = np.full((_N, _N), 8.0)  # everything flows south (WBT code 8)
    link = np.zeros((_N, _N))
    link[1:4, 3] = 1.0
    link[4:7, 3] = 2.0
    acc = np.ones((_N, _N))
    for row in range(_N):
        acc[row, 3] = 5.0 * (row + 1)
    strahler = np.where(link > 0, 1.0, 0.0)
    return {
        "link": _write_raster(tmp_path / "link_full.tif", link),
        "d8": _write_raster(tmp_path / "d8.tif", d8),
        "acc": _write_raster(tmp_path / "acc_cells.tif", acc),
        "dem": _write_raster(tmp_path / "dem_correc.tif", dem),
        "strahler": _write_raster(tmp_path / "strahler_full.tif", strahler),
    }


def test_trace_from_products_flags_terminal_to_lake(tmp_path: Path) -> None:
    paths = _write_products(tmp_path)
    # Row 7 (y in [0, 10]) around column 3 is lake: the link-2 outlet (6, 3)
    # drains into it.
    lake = box(20.0, 0.0, 60.0, 12.0)
    trace = build_sfr_reach_trace_from_products(
        stream_link_id_full_tif=paths["link"],
        d8_pointer_tif=paths["d8"],
        flow_acc_cells_tif=paths["acc"],
        dem_correc_tif=paths["dem"],
        dem_res_m=_RES,
        stream_order_strahler_full_tif=paths["strahler"],
        lake_polygons=[lake],
    )
    assert trace.reach_count == 2
    first, second = trace.reaches
    assert first.downstream == (1,)
    assert second.upstream == (0,)
    assert not first.is_terminal_to_lake
    assert second.is_terminal_to_lake
    assert second.rtp < first.rtp
    assert "32630" in trace.crs_wkt or "WGS 84" in trace.crs_wkt


def test_trace_from_products_without_lake_keeps_outlet_external(tmp_path: Path) -> None:
    paths = _write_products(tmp_path)
    trace = build_sfr_reach_trace_from_products(
        stream_link_id_full_tif=paths["link"],
        d8_pointer_tif=paths["d8"],
        flow_acc_cells_tif=paths["acc"],
        dem_correc_tif=paths["dem"],
        dem_res_m=_RES,
    )
    assert trace.reach_count == 2
    assert not any(reach.is_terminal_to_lake for reach in trace.reaches)


def test_trace_from_products_rejects_misaligned_rasters(tmp_path: Path) -> None:
    paths = _write_products(tmp_path)
    shifted_dem = np.zeros((_N, _N))
    paths["dem"] = _write_raster(tmp_path / "dem_shifted.tif", shifted_dem, west=500.0)
    with pytest.raises(ValueError, match="misaligned.*dem_correc"):
        build_sfr_reach_trace_from_products(
            stream_link_id_full_tif=paths["link"],
            d8_pointer_tif=paths["d8"],
            flow_acc_cells_tif=paths["acc"],
            dem_correc_tif=paths["dem"],
            dem_res_m=_RES,
        )
