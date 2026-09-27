"""Build domain support polygons from one catchment boundary.

Purpose
-------
Generate the geometric supports required by domain preprocessing from a
single catchment polygon.

Produced supports
-----------------
- buffered catchment (transition ring support),
- catchment bounding box,
- buffered rectangular box used as raster clipping/gridding reference.

Buffer semantics
----------------
``buff_area`` reaches this module in the form the config validator wrote. The
form of the value, not its magnitude, says what it means:

- a string ending in ``%`` (``"10%"``) is an area increase: the buffered
  catchment covers ``1 + 10/100`` times the catchment area. This is the rule
  Abherve et al. (2023, HESS 27, p. 3224) state, "increasing the modeled domain
  by 10 %". The distance is solved on the real polygon;
- any other string (``"150.0 m"``) is an explicit distance in metres;
- a bare number (``10.0``) is the historical v1 rule, ``sqrt(area in km2) *
  10 / 100`` km. It enlarges a real catchment by about 50 %, not 10 %. It is
  kept, with a warning, so a sealed run replays the domain it was built on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import box

from hydromodpy.core.io.crs import ensure_crs
from hydromodpy.core.logging import get_logger
from hydromodpy.core.units import UREG

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

logger = get_logger(__name__)

BufferRule = Literal["area_percent", "distance", "legacy_sqrt_percent"]

BUFFER_QUAD_SEGS = 16
"""Segments per quarter circle of every buffer this module builds.

The distance is solved with this value and the written buffer uses it too, so
the area the solver reached is the area of the polygon on disk.
"""


def _parse_length_meters(token: str, *, label: str) -> float:
    """Convert a length string (e.g. '500 m', '2 km') to metres.

    A token with no unit is metres: the validator of an older release wrote a
    declared distance back as a bare number in a string, and a sealed config
    still carries that form.
    """
    quantity = UREG(token.strip())
    if not hasattr(quantity, "magnitude"):
        return float(quantity)
    if quantity.dimensionless:
        return float(quantity.magnitude)
    try:
        return float(quantity.to("m").magnitude)
    except Exception as exc:
        raise ValueError(f"{label}: '{token}' is not a length.") from exc


def buffer_rule_of(buff_area: float | str) -> BufferRule:
    """Return which rule a normalized ``buff_area`` value selects."""
    if isinstance(buff_area, str):
        return "area_percent" if buff_area.strip().endswith("%") else "distance"
    return "legacy_sqrt_percent"


@dataclass(frozen=True)
class CatchmentDomainProducts:
    """Output artifacts produced from one catchment polygon.

    ``buffer_rule``, ``buffer_declared`` and ``buffer_area_increase`` say how
    the margin was chosen and what it did. They are ``None`` when no buffer was
    built (a DEM-driven domain) or when the products were read back from a
    cache that does not record them.
    """

    catchment_area_km2: float
    buffer_distance_m: float
    watershed_buff_shp: str
    watershed_box_shp: str
    watershed_box_buff_shp: str
    buffer_rule: BufferRule | None = None
    buffer_declared: float | str | None = None
    buffer_area_increase: float | None = None


def _read_dem_resolution(
    dem_init_path: str | Path | None,
    dem_resolution: float | None,
) -> float | None:
    """Resolve DEM resolution in meters from explicit value or DEM metadata."""
    if dem_resolution is not None:
        if float(dem_resolution) <= 0.0:
            raise ValueError("dem_resolution must be > 0")
        return float(dem_resolution)
    if dem_init_path is None:
        return None
    with rasterio.open(str(dem_init_path)) as dem_src:
        return float(abs(dem_src.transform.a))


def buffer_distance_for_area_increase(
    geom: BaseGeometry,
    fraction: float,
    *,
    xtol_m: float = 0.01,
) -> float:
    """Return the distance whose buffer covers ``(1 + fraction)`` times the area.

    ``g(d) = area(buffer(d)) / A - 1 - fraction`` is strictly increasing, with
    ``g(0) = -fraction``. By the Brunn-Minkowski inequality the buffer of any
    compact set of area A covers at least ``(sqrt(A) + d sqrt(pi))^2``, so
    ``d_max = sqrt((1 + f) A / pi) - sqrt(A / pi)`` brackets the root whatever
    the shape; the disk is the worst case. A buffer drawn with chords falls a
    hair short of that bound on a near-circular polygon, so the bracket is
    widened by one per cent steps in that case only.
    """
    from scipy.optimize import brentq

    area = float(geom.area)
    if not area > 0.0:
        raise ValueError("the catchment has no area to enlarge.")
    f = float(fraction)
    if not f > 0.0:
        raise ValueError("the area increase must be > 0.")

    def excess(distance: float) -> float:
        return float(geom.buffer(distance, quad_segs=BUFFER_QUAD_SEGS).area) / area - 1.0 - f

    upper = math.sqrt((1.0 + f) * area / math.pi) - math.sqrt(area / math.pi)
    for _ in range(10):
        if excess(upper) >= 0.0:
            break
        upper *= 1.01
    else:
        raise ValueError(
            f"no buffer distance up to {upper:.3f} m enlarges the catchment by {100.0 * f:g} %."
        )
    return float(brentq(excess, 0.0, upper, xtol=float(xtol_m)))


def _snap_to_resolution(distance: float, resolution: float | None) -> float:
    """Snap to the closest multiple of the DEM resolution, at least one cell.

    Equidistant values go to the lower multiple, the established Geographic
    tie-breaking.
    """
    if resolution is None:
        return float(distance)
    lower = np.floor(distance / resolution) * resolution
    upper = np.ceil(distance / resolution) * resolution
    snapped = lower if abs(lower - distance) <= abs(upper - distance) else upper
    return float(max(snapped, resolution))


def _compute_buffer_distance(
    *,
    catchment: BaseGeometry,
    buff_area: float | str,
    dem_resolution: float | None,
) -> float:
    """Compute the buffer distance in metres for one normalized ``buff_area``.

    A percentage is solved on ``catchment`` and a bare number read with the v1
    rule, both snapped to the DEM grid. An explicit distance is used as given.
    """
    rule = buffer_rule_of(buff_area)
    if rule == "distance":
        dist = _parse_length_meters(str(buff_area), label="geographic.buff_area")
        if dist <= 0.0:
            raise ValueError("buff_area distance must be > 0")
        return dist

    if rule == "area_percent":
        pct = float(str(buff_area).strip()[:-1].strip())
        if pct <= 0.0:
            raise ValueError("buff_area percentage must be > 0")
        raw = buffer_distance_for_area_increase(catchment, pct / 100.0)
        return _snap_to_resolution(raw, dem_resolution)

    area_km2 = float(catchment.area) / 1_000_000.0
    buff_raw = np.sqrt(area_km2) * (float(buff_area) / 100.0) * 1000.0
    if buff_raw <= 0.0:
        raise ValueError("buff_area percentage must produce a distance > 0")
    return _snap_to_resolution(float(int(round(buff_raw))), dem_resolution)


def buffer_area_increase(catchment: BaseGeometry, distance_m: float) -> float:
    """Return the relative area the buffer adds, ``area(buffer) / area - 1``."""
    area = float(catchment.area)
    buffered = float(catchment.buffer(float(distance_m), quad_segs=BUFFER_QUAD_SEGS).area)
    return buffered / area - 1.0


def _warn_legacy_rule(buff_area: float, distance_m: float, increase: float) -> None:
    """Say that a bare number reads with the v1 rule, and what it did here."""
    logger.warning(
        "buff_area = %g is read with the legacy v1 rule, %g %% of sqrt(area in km2) km, "
        '%g m here, which enlarges the catchment by %.0f %%. Write "%g%%" for the '
        'paper\'s rule, %g %% more area, or an explicit distance such as "%g m" to '
        "keep this domain.",
        buff_area,
        buff_area,
        distance_m,
        100.0 * increase,
        buff_area,
        buff_area,
        distance_m,
    )


def derive_catchment_domain(
    catchment_shp: str | Path,
    output_dir: str | Path,
    *,
    buff_area: float | str,
    dem_init_path: str | Path | None = None,
    dem_resolution: float | None = None,
    crs_project: str | None = None,
    watershed_buff_name: str = "watershed_buff.shp",
    watershed_box_name: str = "watershed_box.shp",
    watershed_box_buff_name: str = "watershed_box_buff.shp",
) -> CatchmentDomainProducts:
    """
    Build catchment-derived polygon products only (no raster processing).

    Parameters
    ----------
    catchment_shp:
        Existing catchment polygon shapefile (e.g. ``watershed.shp``).
    output_dir:
        Directory where output shapefiles are written.
    buff_area:
        Buffer control, in the normalized form of the config validator:
        ``"10%"`` is an area increase, ``"150.0 m"`` a distance, a bare number
        the legacy v1 rule (see the module docstring).
    dem_init_path, dem_resolution:
        Used to derive/supply DEM resolution for distance snapping.
        ``dem_resolution`` overrides ``dem_init_path`` when both are provided.
    crs_project:
        Optional CRS override applied to outputs.
    *_name:
        Filenames for generated shapefiles.
    """
    catchment_path = Path(catchment_shp)
    if not catchment_path.exists():
        raise FileNotFoundError(f"catchment_shp not found: {catchment_path}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    catchment_gdf = gpd.read_file(str(catchment_path))
    catchment_gdf = catchment_gdf.loc[:, ~catchment_gdf.columns.duplicated()]
    if catchment_gdf.empty:
        raise ValueError("catchment_shp is empty")

    if catchment_gdf.crs is not None and catchment_gdf.crs.is_geographic:
        raise ValueError(
            "catchment_shp CRS is geographic (degrees). "
            "Use a projected CRS in meters before buffering."
        )

    catchment_area_km2 = float(np.abs(catchment_gdf.geometry.area.sum()) / 1_000_000.0)
    if catchment_area_km2 <= 0.0:
        raise ValueError("catchment area must be > 0")

    catchment = catchment_gdf.geometry.union_all()
    res = _read_dem_resolution(dem_init_path, dem_resolution)
    rule = buffer_rule_of(buff_area)
    buff_dist = _compute_buffer_distance(
        catchment=catchment,
        buff_area=buff_area,
        dem_resolution=res,
    )
    increase = buffer_area_increase(catchment, buff_dist)
    if rule == "legacy_sqrt_percent":
        _warn_legacy_rule(float(buff_area), buff_dist, increase)

    target_crs = crs_project or (catchment_gdf.crs.to_string() if catchment_gdf.crs else None)

    watershed_buff_path = out_dir / watershed_buff_name
    watershed_box_path = out_dir / watershed_box_name
    watershed_box_buff_path = out_dir / watershed_box_buff_name

    buff_gdf = catchment_gdf.copy()
    buff_gdf["geometry"] = buff_gdf.geometry.buffer(buff_dist, resolution=BUFFER_QUAD_SEGS)
    buff_gdf.to_file(str(watershed_buff_path))
    ensure_crs(watershed_buff_path, target_crs)

    xmin, ymin, xmax, ymax = catchment_gdf.total_bounds
    watershed_box_gdf = gpd.GeoDataFrame(
        data={"id": [1]},
        geometry=[box(xmin, ymin, xmax, ymax)],
        crs=catchment_gdf.crs,
    )
    watershed_box_gdf.to_file(str(watershed_box_path))
    ensure_crs(watershed_box_path, target_crs)

    # Build buffered rectangle from the catchment box envelope.
    box_buff_geom = watershed_box_gdf.geometry.iloc[0].buffer(buff_dist).envelope
    watershed_box_buff_gdf = gpd.GeoDataFrame(
        data={"id": [1]},
        geometry=[box_buff_geom],
        crs=catchment_gdf.crs,
    )
    watershed_box_buff_gdf.to_file(str(watershed_box_buff_path))
    ensure_crs(watershed_box_buff_path, target_crs)

    return CatchmentDomainProducts(
        catchment_area_km2=catchment_area_km2,
        buffer_distance_m=buff_dist,
        watershed_buff_shp=str(watershed_buff_path),
        watershed_box_shp=str(watershed_box_path),
        watershed_box_buff_shp=str(watershed_box_buff_path),
        buffer_rule=rule,
        buffer_declared=buff_area,
        buffer_area_increase=increase,
    )
