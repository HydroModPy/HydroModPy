"""The soil columns: capacity classes inside each SAFRAN cell, and their catchment weights.

There is one column per SAFRAN cell, or one per capacity class inside each cell when
``[data.soil_capacity]`` gives a raster. Each column is weighed by its share of the catchment.
``[data.impervious]``, ``[data.curve_number]`` and ``[data.infiltration_ratio]`` give each
column the sealed share, the curve number and the infiltration ratio of the part of its cell
that lies inside the catchment.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np
from pyproj import CRS, Transformer
from shapely import contains_xy
from shapely.geometry import box

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.units.physical_bounds import PHYSICAL_BOUNDS
from hydromodpy.model.contracts import FieldRecordProto, LoadResultProto

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
    impervious: np.ndarray | None = None  # (N,) sealed share from [data.impervious], None without
    curve_number: np.ndarray | None = (
        None  # (N,) curve number from [data.curve_number], None without
    )
    infiltration_ratio: np.ndarray | None = (
        None  # (N,) infiltration ratio from [data.infiltration_ratio], None without
    )


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


# ---------------------------------------------------------------------------
# Sealed share and curve number: one value per SAFRAN cell, inside the catchment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SoilMap:
    """A raster of ``[data.<name>]`` that gives one value of the soil section cell by cell."""

    soil_field: str  # the key of [flow.sinks_sources.recharge.soil] the map replaces
    bound: str  # key of PHYSICAL_BOUNDS the cell means must respect
    hint: str  # what to check when they do not


SOIL_MAPS: dict[str, SoilMap] = {
    "impervious": SoilMap(
        "impervious_fraction",
        "soil_impervious_fraction",
        "a column sealed over the upper bound leaves the soil nothing to hold; "
        "a raster in percent is divided by 100 first",
    ),
    "curve_number": SoilMap("curve_number", "soil_curve_number", "it is an AMC II curve number"),
    "infiltration_ratio": SoilMap(
        "infiltration_ratio",
        "soil_infiltration_ratio",
        "it is the share of the soil excess that reaches the aquifer, between 0 and 1",
    ),
}
"""The soil maps, by data family. The planner, the checks, the data step and the
calibration read this table."""


def _nearest_center(values: np.ndarray, centers: np.ndarray, step: float) -> np.ndarray:
    """Index in ``centers`` (regular, either order) of the center nearest each value."""
    order = np.argsort(centers)
    k = np.rint((values - centers[order[0]]) / step).astype(np.int64)
    return order[np.clip(k, 0, centers.size - 1)]


def catchment_cell_means(
    record: FieldRecordProto,
    *,
    name: str,
    x: np.ndarray,
    y: np.ndarray,
    crs: str,
    bbox: tuple[float, float, float, float],
    catchment: gpd.GeoDataFrame | None,
) -> np.ndarray:
    """Mean of the raster over the part of each SAFRAN cell inside the catchment, flat (y, x).

    A town beside the catchment does not seal it, so only the pixels inside the
    polygon count. A cell the catchment does not reach takes the catchment mean:
    it carries no weight in the budget. Without a polygon, every pixel of the cell
    counts. The curve number is averaged like the sealed share, which gives the
    composite curve number of the cell; the SCS law is not linear, so this mean
    runs off a little less than the pixels would one by one.
    """
    section = f"[data.{name}]"
    soil_map = SOIL_MAPS[name]
    bound = PHYSICAL_BOUNDS[soil_map.bound]
    px, py, values = _read_raster_pixels(record, model_crs=crs)
    dx, dy = _grid_steps(x, y, bbox)
    # The forcing grid is regular, so the cell of a pixel is a division: a 10 m map
    # of a large catchment holds millions of pixels, too many for a pixel-by-cell table.
    ix = _nearest_center(px, x, dx)
    iy = _nearest_center(py, y, dy)
    keep = (np.abs(px - x[ix]) <= dx / 2) & (np.abs(py - y[iy]) <= dy / 2)
    if catchment is not None:
        frame = catchment if catchment.crs is None else catchment.to_crs(crs)
        keep &= contains_xy(frame.geometry.union_all(), px, py)
    if not keep.any():
        raise DataContractViolation(
            f"{section} has no pixel inside the catchment and the forcing grid: extend "
            "the raster over the catchment."
        )
    n_cells = x.size * y.size
    cell = iy[keep] * x.size + ix[keep]
    counts = np.bincount(cell, minlength=n_cells)
    sums = np.bincount(cell, weights=values[keep], minlength=n_cells)
    means = np.full(n_cells, float(values[keep].mean()))
    means[counts > 0] = sums[counts > 0] / counts[counts > 0]
    if means.min() < bound.lo or means.max() > bound.hi:
        raise DataContractViolation(
            f"{section} averages {means.min():g} to {means.max():g} over the SAFRAN cells, "
            f"outside {bound.lo:g} to {bound.hi:g} for the {bound.label}: {soil_map.hint}. Check the "
            "raster and its nodata value."
        )
    return means


def with_surface_maps(columns: SoilColumns, maps: dict[str, np.ndarray | None]) -> SoilColumns:
    """``columns`` with the cell values of each map of ``SOIL_MAPS`` handed to its columns."""
    return replace(
        columns,
        **{
            name: None if values is None else values[columns.cell_index]
            for name, values in maps.items()
        },
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
