"""Burn the observed stream network into the ROUTING DEM before D8 flow routing.

Twin of :mod:`~hydromodpy.spatial.geographic.core.lake_enforcement`, on the
linework instead of the water bodies. A mapped stream network is surveyed
independently of the DEM, so its trace rarely sits in the thalwegs the DEM
computes: on five Armorican catchments at 75 m, following D8 from the mapped
cells leaves that network within the first step over a quarter to a third of it.
Every length measured along those paths then mixes a DEM-versus-map disagreement
into what is supposed to be hydrogeology. Lowering the mapped cells before the
fill/breach pass forces the two to agree.

The trench is cut into the SEPARATE routing DEM used for delineation. The model
grid top stays on the raw DEM (two-surface separation), which matters more here
than for lakes: a top lowered along the observed network would make a model that
agrees with that network by construction.

The depth is not a free knob. It has to exceed the local drop between a stream
cell and its lowest non-stream neighbour, which the report measures and prints
whatever mode is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.geographic.core.catchment_metrics import compute_catchment_area_km2
from hydromodpy.spatial.geographic.core.flow_products import build_regional_flow_products
from hydromodpy.spatial.geographic.core.lake_enforcement import routing_dem_from_config
from hydromodpy.spatial.geographic.core.pipeline_steps import build_standard_catchment

logger = get_logger(__name__)

# (drow, dcol) of the eight neighbours, used for the local-relief measurement.
_NEIGHBOURS = ((0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1))


@dataclass(frozen=True)
class StreamEnforcementReport:
    """What the burn cut, and whether it was deep enough."""

    stream_cells: int
    mode: str
    depth_m: float
    relief_p95_m: float
    """95th percentile of ``z(stream) - min z(non-stream neighbour)``: the drop a
    trench must clear to keep the flow inside the mapped network."""

    relief_max_m: float
    routing_dem_path: str


def burn_streams_into_routing_dem(
    *,
    dem_in_path: str | Path,
    dem_out_path: str | Path,
    stream_lines: list,
    mode: str = "constant",
    depth_m: float = 30.0,
    adaptive_percentile: float = 95.0,
) -> StreamEnforcementReport:
    """Write a routing DEM with the mapped stream network cut into it.

    Parameters
    ----------
    dem_in_path:
        DEM to burn (the raw regional DEM, or an already conditioned routing DEM).
    dem_out_path:
        Where to write the burned routing DEM (fed only to D8 delineation).
    stream_lines:
        Observed network geometries in the DEM CRS (shapely geometries).
    mode:
        ``"constant"`` lowers every stream cell by ``depth_m``. ``"adaptive"``
        derives one depth from ``adaptive_percentile`` of the measured local
        relief instead.
    depth_m:
        Trench depth in metres, used by ``mode="constant"``.
    adaptive_percentile:
        Percentile of the local relief used by ``mode="adaptive"``.

    A single depth is applied over the whole network, never a per-cell one: a
    depth that varies along a reach rewrites its own downstream gradient, which
    is the thing the trench exists to preserve.
    """
    dem_in_path = str(dem_in_path)
    dem_out_path = str(dem_out_path)
    if mode not in ("constant", "adaptive"):
        raise ValueError(f"Unknown stream burn mode={mode!r}. Expected 'constant' or 'adaptive'.")

    with rasterio.open(dem_in_path) as src:
        dem = src.read(1).astype("float32")
        transform = src.transform
        profile = src.profile
        nodata = float(src.nodata) if src.nodata is not None else -9999.0

    valid = dem != nodata
    lines = [g for g in stream_lines if g is not None and not g.is_empty]
    if not lines:
        raise ValueError("burn_streams_into_routing_dem: no stream geometry to burn.")

    stream_mask = (
        rasterize(
            ((g, 1) for g in lines),
            out_shape=dem.shape,
            transform=transform,
            fill=0,
            all_touched=True,  # a one-cell-wide trace must capture every cell it crosses
            dtype="uint8",
        ).astype(bool)
        & valid
    )
    if not stream_mask.any():
        raise ValueError(
            "burn_streams_into_routing_dem: the stream geometries rasterize to no valid "
            "DEM cell; check the network CRS and the DEM extent."
        )

    relief = _local_relief_along_streams(dem, stream_mask, valid)
    relief_p95 = float(np.percentile(relief, 95.0)) if relief.size else 0.0
    relief_max = float(relief.max()) if relief.size else 0.0

    if mode == "adaptive":
        if not relief.size:
            raise ValueError(
                "burn_streams_into_routing_dem: adaptive mode found no stream cell with a "
                "non-stream neighbour, so no depth can be derived; use mode='constant'."
            )
        depth = max(float(np.percentile(relief, float(adaptive_percentile))), 0.0)
    else:
        depth = float(depth_m)
    if depth <= 0.0:
        raise ValueError(f"burn_streams_into_routing_dem: derived depth {depth} m is not positive.")

    dem[stream_mask] = (dem[stream_mask] - depth).astype("float32")

    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    profile.update(dtype="float32", compress="lzw", tiled=False, nodata=nodata)
    Path(dem_out_path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dem_out_path, "w", **profile) as dst:
        dst.write(dem, 1)

    report = StreamEnforcementReport(
        stream_cells=int(stream_mask.sum()),
        mode=mode,
        depth_m=depth,
        relief_p95_m=relief_p95,
        relief_max_m=relief_max,
        routing_dem_path=dem_out_path,
    )
    if depth < relief_p95:
        logger.warning(
            "Stream burn: %.1f m is shallower than the 95th percentile of the local relief "
            "along the network (%.1f m), so the trench will not hold the flow everywhere.",
            depth,
            relief_p95,
        )
    logger.info(
        "Stream enforcement: burned %d network cells by %.1f m (%s mode) into the routing "
        "DEM; local relief along the network p95 %.1f m, max %.1f m.",
        report.stream_cells,
        report.depth_m,
        report.mode,
        report.relief_p95_m,
        report.relief_max_m,
    )
    return report


def streams_from_config(enforce: object, setup: object) -> list:
    """Read the observed network geometries, resolving the path against the DEM data dir."""
    import geopandas as gpd

    declared = getattr(enforce, "stream_geometry_path", None)
    if declared is None:
        raise ValueError("geographic.enforce_streams.stream_geometry_path is unset.")
    path = Path(declared)
    if not path.exists():
        # A bare filename (or a mis-resolved one): look under <data>/hydrography/,
        # where <data> is the parent of the DEM's family dir (data/dem/x.tif -> data).
        data_dir = Path(str(setup.dem_init_path)).resolve().parent.parent
        candidate = data_dir / "hydrography" / path.name
        if candidate.exists():
            path = candidate
    if not path.exists():
        raise FileNotFoundError(
            f"geographic.enforce_streams.stream_geometry_path not found: {declared} "
            "(tried as-is and under <data>/hydrography/)."
        )
    gdf = gpd.read_file(path)
    if getattr(setup, "crs_project", None) is not None:
        gdf = gdf.to_crs(setup.crs_project)
    return [g for g in gdf.geometry if g is not None and not g.is_empty]


def burned_dem_from_config(config: object, setup: object) -> str:
    """Return the stream-burned routing DEM, or the raw DEM when burning is off.

    Duck-typed on ``config.enforce_streams`` and ``setup`` (``dem_init_path``,
    ``paths.correcflow_path``, ``crs_project``), like its lake twin, so both
    geographic entry points share it. Runs FIRST in the routing chain: the lake
    carve then overwrites the trench inside a water body, which is right, a lake
    is not a channel.
    """
    enforce = getattr(config, "enforce_streams", None)
    if enforce is None or not getattr(enforce, "enabled", False):
        return str(setup.dem_init_path)
    out_path = str(Path(setup.paths.correcflow_path) / "dem_routing_stream_burned.tif")
    burn_streams_into_routing_dem(
        dem_in_path=setup.dem_init_path,
        dem_out_path=out_path,
        stream_lines=streams_from_config(enforce, setup),
        mode=str(enforce.mode),
        depth_m=float(enforce.depth_m),
        adaptive_percentile=float(enforce.adaptive_percentile),
    )
    return out_path


def catchment_area_without_burn(
    *,
    config: object,
    setup: object,
    backend: object | None = None,
) -> float | None:
    """Delineate on the un-burned routing DEM and return its catchment area, in km2.

    Returns ``None`` when burning is off, or when the domain is not outlet- or
    polygon-delineated (nothing to compare). Otherwise it costs one extra
    delineation pass, which is the price of the divide guard: a trench that
    crosses a divide reconnects two catchments and the delineated area is the
    only thing that says so. The catchment artifacts it writes are overwritten by
    the real delineation that follows.
    """
    enforce = getattr(config, "enforce_streams", None)
    if enforce is None or not getattr(enforce, "enabled", False):
        return None
    if str(getattr(config, "catch_def", "")) == "dem":
        return None

    flow = build_regional_flow_products(
        dem_init_path=routing_dem_from_config(config, setup, dem_in_path=setup.dem_init_path),
        dem_out_dir_path=setup.paths.correcflow_path,
        dem_correc_type=str(config.dem_correc_type),
        crs_project=setup.crs_project,
        backend=backend,
    )
    build_standard_catchment(
        config=config,
        paths=setup.paths,
        direc_path=flow.direc,
        acc_path=flow.acc,
        direc_data=flow.direc_data,
        acc_data=flow.acc_data,
        crs_project=setup.crs_project,
        backend=backend,
        unsupported_mode="ignore",
    )
    return float(compute_catchment_area_km2(setup.paths.watershed_shp))


def check_catchment_area_drift(
    *,
    config: object,
    reference_area_km2: float | None,
    burned_area_km2: float,
) -> None:
    """Raise when the stream burn moved the delineated catchment area too far.

    ``reference_area_km2`` is the area delineated without the burn, or ``None``
    when burning is off (then nothing is checked). A drift means the trench
    re-plumbed the drainage, most often by crossing a divide.
    """
    if reference_area_km2 is None:
        return
    enforce = getattr(config, "enforce_streams", None)
    if enforce is None or not getattr(enforce, "enabled", False):
        return
    if reference_area_km2 <= 0.0:
        raise ValueError(
            "geographic.enforce_streams: the un-burned delineation produced an empty "
            "catchment, so the burn cannot be checked against it."
        )
    drift = abs(burned_area_km2 - reference_area_km2) / reference_area_km2
    limit = float(enforce.max_catchment_area_drift)
    logger.info(
        "Stream enforcement: catchment area %.3f km2 before the burn, %.3f km2 after "
        "(drift %.2f%%, limit %.2f%%).",
        reference_area_km2,
        burned_area_km2,
        100.0 * drift,
        100.0 * limit,
    )
    if drift > limit:
        raise ValueError(
            f"geographic.enforce_streams: burning the network moved the delineated "
            f"catchment area from {reference_area_km2:.3f} km2 to {burned_area_km2:.3f} km2 "
            f"({100.0 * drift:.1f}% > {100.0 * limit:.1f}%). The trench re-plumbed the "
            "drainage, most likely by crossing a divide; check the network trace against "
            "the DEM, or lower depth_m."
        )


def _local_relief_along_streams(
    dem: np.ndarray,
    stream_mask: np.ndarray,
    valid: np.ndarray,
) -> np.ndarray:
    """Return ``z(stream) - min z(non-stream neighbour)`` over the stream cells.

    A positive value is the drop a constant trench must exceed at that cell for
    the flow to stay on the mapped network. Cells with no valid non-stream
    neighbour are dropped rather than counted as zero.
    """
    off_stream = np.where(valid & ~stream_mask, dem.astype(float), np.inf)
    lowest = np.full(dem.shape, np.inf)
    nrow, ncol = dem.shape
    for drow, dcol in _NEIGHBOURS:
        shifted = np.full(dem.shape, np.inf)
        rows_src = slice(max(0, -drow), nrow - max(0, drow))
        cols_src = slice(max(0, -dcol), ncol - max(0, dcol))
        rows_dst = slice(max(0, drow), nrow - max(0, -drow))
        cols_dst = slice(max(0, dcol), ncol - max(0, -dcol))
        shifted[rows_src, cols_src] = off_stream[rows_dst, cols_dst]
        lowest = np.minimum(lowest, shifted)
    drop = dem.astype(float) - lowest
    return drop[stream_mask & valid & np.isfinite(drop)]
