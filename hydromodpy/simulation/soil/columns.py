"""The soil columns: capacity classes inside each SAFRAN cell, and their catchment weights."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import box

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.physics.contracts import FieldRecordProto, LoadResultProto

if TYPE_CHECKING:
    import geopandas as gpd


# On a SoilGrids capacity raster of the Nancon, 1985-2020, ten classes stay within
# 1 mm/year of fifty on the mean recharge.
RU_CLASSES_PER_CELL: int = 10


@dataclass(frozen=True)
class SoilColumns:
    """Where each soil column sits and what it holds."""

    cell_index: np.ndarray  # (N,) int, flat (y, x) index of its SAFRAN cell
    class_index: np.ndarray  # (N,) int, capacity class inside the cell, 0 without raster
    x: np.ndarray  # (N,) cell center, CRS of the run
    y: np.ndarray  # (N,)
    ru_shape: np.ndarray  # (N,) class capacity / mean capacity, 1.0 without raster
    cell_fraction: np.ndarray  # (N,) share of its cell the column covers, sums to 1 per cell
    basin_weight: np.ndarray  # (N,) cell_fraction / number of cells, sums to 1
    raster_mean_mm: float | None = None  # basin mean of [data.soil_capacity], None without raster


# ---------------------------------------------------------------------------
# RU raster: capacity classes inside each SAFRAN cell (spec section 1.7)
# ---------------------------------------------------------------------------


def _read_raster_pixels(
    record: FieldRecordProto, *, model_crs: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Valid pixel centers, reprojected to ``model_crs``, and their values."""
    import rasterio
    from rasterio.transform import xy as pixel_xy

    with rasterio.open(str(record.data)) as src:
        band = src.read(1, masked=True)
        rows, cols = np.where(~np.ma.getmaskarray(band))
        values = np.asarray(band)[rows, cols].astype(np.float64)
        raw_x, raw_y = pixel_xy(src.transform, rows, cols)
    px = np.asarray(raw_x, dtype=np.float64)
    py = np.asarray(raw_y, dtype=np.float64)
    if CRS.from_user_input(record.crs) != CRS.from_user_input(model_crs):
        transformer = Transformer.from_crs(record.crs, model_crs, always_xy=True)
        px, py = (np.asarray(v, dtype=np.float64) for v in transformer.transform(px, py))
    return px, py, values


def _grid_steps(
    x: np.ndarray, y: np.ndarray, bbox: tuple[float, float, float, float]
) -> tuple[float, float]:
    """(dx, dy) of the P grid: the other axis' step when one axis has a single cell,
    or the bbox span on both axes for a 1x1 grid."""
    dx = float(abs(x[1] - x[0])) if x.size > 1 else None
    dy = float(abs(y[1] - y[0])) if y.size > 1 else None
    if dx is None and dy is None:
        return float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1])
    if dx is None:
        return dy, dy
    if dy is None:
        return dx, dx
    return dx, dy


def catchment_cell_weights(
    x: np.ndarray,
    y: np.ndarray,
    *,
    bbox: tuple[float, float, float, float],
    catchment: gpd.GeoDataFrame | None,
    crs: str,
) -> np.ndarray:
    """Weight of each SAFRAN cell in the basin mean, row by row, summing to 1.

    The printed budget is read against the gauge, so a cell counts by the share of
    the catchment it holds. Without a polygon, or on a grid that misses it, the
    cells count the same, since nothing then says which one the catchment reads.
    """
    equal = np.full(y.size * x.size, 1.0 / (y.size * x.size))
    if catchment is None:
        return equal
    dx, dy = _grid_steps(x, y, bbox)
    frame = catchment if catchment.crs is None else catchment.to_crs(crs)
    outline = frame.geometry.union_all()
    areas = np.array(
        [
            box(cx - dx / 2, cy - dy / 2, cx + dx / 2, cy + dy / 2).intersection(outline).area
            for cy in y
            for cx in x
        ]
    )
    total = float(areas.sum())
    return areas / total if total > 0.0 else equal


def capacity_classes(
    soil_capacity: LoadResultProto,
    *,
    x: np.ndarray,
    y: np.ndarray,
    crs: str,
    bbox: tuple[float, float, float, float],
    n_classes: int = RU_CLASSES_PER_CELL,
    cell_weights: np.ndarray | None = None,
) -> SoilColumns:
    """Spread each SAFRAN cell into capacity classes from a soil capacity raster."""
    record = soil_capacity.fields[0]
    px, py, values = _read_raster_pixels(record, model_crs=crs)

    ny, nx = y.size, x.size
    n_cells = ny * nx
    dx, dy = _grid_steps(x, y, bbox)
    ix = np.argmin(np.abs(px[:, None] - x[None, :]), axis=1)
    iy = np.argmin(np.abs(py[:, None] - y[None, :]), axis=1)
    inside = (np.abs(px - x[ix]) <= dx / 2) & (np.abs(py - y[iy]) <= dy / 2)

    inside_values = values[inside]
    negative = inside_values < 0
    if negative.any():
        raise DataContractViolation(
            "[data.soil_capacity] holds negative values (down to "
            f"{float(inside_values[negative].min()):g} mm): a soil water capacity "
            "is 0 mm or more. Check the raster and its nodata value."
        )

    cell_of_pixel = np.where(inside, iy * nx + ix, -1)
    order = np.argsort(cell_of_pixel, kind="stable")
    sorted_cells = cell_of_pixel[order]
    sorted_values = values[order]
    boundaries = np.searchsorted(sorted_cells, np.arange(n_cells + 1))

    cell_index: list[int] = []
    class_index: list[int] = []
    col_x: list[float] = []
    col_y: list[float] = []
    cell_fraction: list[float] = []
    class_mean: list[float] = []
    for c in range(n_cells):
        pixels = sorted_values[boundaries[c] : boundaries[c + 1]]
        iy_c, ix_c = divmod(c, nx)
        if pixels.size == 0:
            raise DataContractViolation(
                "[data.soil_capacity] covers no part of the SAFRAN cell centred on "
                f"x = {x[ix_c]:.0f}, y = {y[iy_c]:.0f}: every cell of the forcing "
                "grid needs soil capacity values. Extend the raster, or narrow the "
                "forcing extent."
            )
        groups = [group for group in np.array_split(np.sort(pixels), n_classes) if group.size > 0]
        for j, group in enumerate(groups):
            cell_index.append(c)
            class_index.append(j)
            col_x.append(float(x[ix_c]))
            col_y.append(float(y[iy_c]))
            cell_fraction.append(group.size / pixels.size)
            class_mean.append(float(group.mean()))

    cell_index_arr = np.asarray(cell_index, dtype=np.int64)
    cell_fraction_arr = np.asarray(cell_fraction, dtype=np.float64)
    class_mean_arr = np.asarray(class_mean, dtype=np.float64)
    weights = np.full(n_cells, 1.0 / n_cells) if cell_weights is None else cell_weights
    basin_weight_arr = cell_fraction_arr * weights[cell_index_arr]
    raster_mean = float(np.sum(basin_weight_arr * class_mean_arr))
    if raster_mean == 0.0:
        raise DataContractViolation(
            "[data.soil_capacity] is 0 mm over every SAFRAN cell, so it gives no "
            "shape to spread ru over: check the raster, or remove [data.soil_capacity] "
            "to use a uniform ru."
        )

    return SoilColumns(
        cell_index=cell_index_arr,
        class_index=np.asarray(class_index, dtype=np.int64),
        x=np.asarray(col_x, dtype=np.float64),
        y=np.asarray(col_y, dtype=np.float64),
        ru_shape=class_mean_arr / raster_mean,
        cell_fraction=cell_fraction_arr,
        basin_weight=basin_weight_arr,
        raster_mean_mm=raster_mean,
    )


def aggregate_to_cells(values_tn: np.ndarray, columns: SoilColumns, n_cells: int) -> np.ndarray:
    """Weighted sum of columns back onto their SAFRAN cells, shape ``(T, n_cells)``.

    One ``FieldRecord`` per quantity (spec section 7): several classes of the
    same cell are summed here, weighted by ``cell_fraction``, never averaged
    twice by the discretizer.
    """
    weighted = (values_tn * columns.cell_fraction).T
    out = np.zeros((n_cells, values_tn.shape[0]), dtype=np.float64)
    np.add.at(out, columns.cell_index, weighted)
    return out.T
