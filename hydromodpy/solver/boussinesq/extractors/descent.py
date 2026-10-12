"""The descent D of a Boussinesq run, from the Whitebox D8 pointer of its top.

A Boussinesq store has no mesh topology, so a reader cannot rebuild D from it.
The extractor builds D once per run instead: the top is laid out as a raster,
Whitebox fills its depressions, and the D8 pointer of the filled raster becomes
``mesh/descent_receiver``. The filled raster is ``mesh/descent_surface``. The
accumulation fluxes are then routed on read on this D, as on MODFLOW.

This is the graph the per-step ``d8_mass_flux`` routing walked, with an
efficiency of 1 and no absorption: the same filled DEM, the same pointer.

The raster lives in cell-index space: one unit square per cell, row-major, the
first row on top. Whitebox refuses a GeoTIFF without geokeys, so the raster
carries a fixed projected CRS that nothing reads.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS

_NODATA = -99999.0
_VALID_FLOOR = -9000.0
_RASTER_EPSG = 2154
# Relative spread of the cell areas below which the cells are one raster's.
_UNIFORM_AREA_RTOL = 1.0e-6


def raster_grid_shape(
    metadata: Mapping[str, object],
    n_cells: int,
    cell_area_m2: np.ndarray | None,
) -> tuple[tuple[int, int] | None, str]:
    """Return the raster shape of the run's cells, or None and the reason.

    The shape is the ``nrow`` and ``ncol`` of the geographic metadata. It is
    accepted only when it holds exactly ``n_cells`` cells and every cell has
    the same area: a triangle mesh whose cell count happens to match is not a
    raster.
    """
    try:
        nrow = int(str(metadata.get("nrow", "0")))
        ncol = int(str(metadata.get("ncol", "0")))
    except ValueError:
        return None, "its grid metadata holds no integer nrow and ncol"
    if nrow <= 0 or ncol <= 0:
        return None, "its grid metadata holds no nrow and ncol"
    if nrow * ncol != int(n_cells):
        return None, (
            f"its {int(n_cells)} cells are not the {nrow} x {ncol} raster of its grid metadata"
        )
    if cell_area_m2 is not None:
        area = np.asarray(cell_area_m2, dtype=float).reshape(-1)
        finite = area[np.isfinite(area)]
        if finite.size != area.size or finite.size == 0:
            return None, "its cell areas are not all finite"
        spread = float(np.max(finite) - np.min(finite))
        if spread > _UNIFORM_AREA_RTOL * float(np.max(np.abs(finite))):
            return None, "its cells do not share one area, so they are not a raster"
    return (nrow, ncol), ""


def decode_d8_pointer(pointer: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Turn a Whitebox D8 pointer raster (``d8_wbt`` codes) into receivers.

    Cells are numbered row-major. A valid cell whose code is 0, or whose
    receiver is off the raster or invalid, is an outlet: -1, as in
    :func:`hydromodpy.core.descent.descent_graph`. Invalid cells get -1 too.
    """
    codes = np.asarray(pointer).astype(np.int64, copy=False)
    mask = np.asarray(valid, dtype=bool)
    if codes.shape != mask.shape or codes.ndim != 2:
        raise ValueError(f"pointer {codes.shape} and mask {mask.shape} must be one 2-D shape.")
    nrow, ncol = codes.shape
    rows, cols = np.indices(codes.shape)
    receiver = np.full(codes.shape, -1, dtype=np.int64)
    for code, (d_row, d_col) in D8_WBT_OFFSETS.items():
        target_row = rows + d_row
        target_col = cols + d_col
        hit = (
            mask
            & (codes == code)
            & (target_row >= 0)
            & (target_row < nrow)
            & (target_col >= 0)
            & (target_col < ncol)
        )
        hit[hit] &= mask[target_row[hit], target_col[hit]]
        receiver[hit] = target_row[hit] * ncol + target_col[hit]
    return receiver.reshape(-1)


def whitebox_d8_descent(
    top: np.ndarray, grid_shape: tuple[int, int]
) -> tuple[np.ndarray, np.ndarray]:
    """Return the receiver and the filled surface of D for a raster top.

    Whitebox fills the depressions of ``top`` and draws the D8 pointer of the
    filled raster. Non-finite cells of ``top`` are nodata: no receiver and a
    NaN surface. Every link descends strictly on the surface, which the
    receiver graph needs to order its cells.

    Raises
    ------
    ValueError
        ``top`` does not hold the cells of ``grid_shape``, or a link of the
        pointer does not descend.
    """
    import rasterio

    from hydromodpy.spatial.delineation import get_whitebox_backend

    nrow, ncol = (int(grid_shape[0]), int(grid_shape[1]))
    values = np.asarray(top, dtype="float64").reshape(-1)
    if values.size != nrow * ncol:
        raise ValueError(f"the top holds {values.size} cells, the raster {nrow} x {ncol}.")
    dem = np.where(np.isfinite(values), values, _NODATA).reshape(nrow, ncol)

    wb = get_whitebox_backend()
    with tempfile.TemporaryDirectory(prefix="hmp_descent_") as tmp:
        dem_path = str(Path(tmp) / "dem.tif")
        fill_path = str(Path(tmp) / "fill.tif")
        pointer_path = str(Path(tmp) / "pointer.tif")
        write_index_raster(dem_path, dem)
        wb.flow.fill_depressions(dem_path, fill_path)
        wb.flow.d8_pointer(fill_path, pointer_path)
        with rasterio.open(fill_path) as src:
            filled = np.asarray(src.read(1), dtype="float64")
        with rasterio.open(pointer_path) as src:
            pointer = src.read(1)

    valid = np.isfinite(filled) & (filled > _VALID_FLOOR)
    receiver = decode_d8_pointer(pointer, valid)
    surface = np.where(valid, filled, np.nan).reshape(-1)
    linked = receiver >= 0
    if np.any(surface[receiver[linked]] >= surface[linked]):
        raise ValueError("a link of the Whitebox D8 pointer does not descend the filled top.")
    return receiver, surface


def write_index_raster(path: str, data: np.ndarray) -> None:
    """Write a 2-D array as a GeoTIFF in cell-index space for Whitebox."""
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import from_bounds

    nrow, ncol = data.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=nrow,
        width=ncol,
        count=1,
        dtype=data.dtype,
        nodata=_NODATA,
        transform=from_bounds(0, 0, ncol, nrow, ncol, nrow),
        crs=CRS.from_epsg(_RASTER_EPSG),
    ) as dst:
        dst.write(data, 1)


def write_raster_descent(
    sz: Any, *, top: np.ndarray, receiver: np.ndarray, surface: np.ndarray
) -> None:
    """Write a raster D under ``mesh/`` with the store's descent writer.

    A raster D has no channel tree, no pin, no constant-head seed and no lake,
    so those masks are empty. The base level is the valid cells with no
    receiver, where the routing ends. ``raised`` flags the cells the fill
    raised above the top.
    """
    top_values = np.asarray(top, dtype="float64").reshape(-1)
    valid = np.isfinite(surface)
    raise_m = np.where(valid & np.isfinite(top_values), surface - top_values, 0.0)
    raised = raise_m > 0.0
    empty = np.zeros(receiver.size, dtype=bool)
    sz.write_descent(
        receiver=receiver,
        surface=surface,
        base_level=valid & (receiver < 0),
        constant_head=empty,
        raised=raised,
        channel=empty,
        pinned=empty,
        attrs={
            "adjacency": "shared_nodes",
            "source": "whitebox_d8_pointer",
            "n_raised": int(np.count_nonzero(raised)),
            "max_raise_m": float(np.max(raise_m, initial=0.0)),
            "n_lake_flooded": 0,
            "max_lake_flood_m": 0.0,
            "n_pinned_raised": 0,
            "max_pinned_raise_m": 0.0,
        },
    )


__all__ = (
    "decode_d8_pointer",
    "raster_grid_shape",
    "whitebox_d8_descent",
    "write_index_raster",
    "write_raster_descent",
)
