"""Hydro-enforce lakes into the ROUTING DEM before D8 flow routing.

A pure topographic breach/fill is lake-blind: on a dammed reservoir it carves a
least-cost thalweg that misses the flat water body, so the delineated streams
dead-end short of the lake and the catchment (delineated from the below-dam
outlet) excludes the reservoir. This module carves the lake footprints into a
SEPARATE routing DEM so D8 converges INTO the lakes and drains to the outlet
through a punched notch. The model grid top is left on the raw DEM (two-surface
separation), so the lake-aquifer geometry is untouched.

The carve is a gentle monotonic RAMP toward the outlet (never a flat sink, which
would make the breach crawl) plus a descending outlet notch. It uses only the lake
footprint polygons already supplied for LAK cell selection -- no river data source.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import rowcol, xy
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, unary_union

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.geographic.core.d8 import WBT_D8_OFFSETS

logger = get_logger(__name__)


@dataclass(frozen=True)
class LakeEnforcementReport:
    """What the carve did, for logging and QC figures."""

    lake_cells: int
    notch_cells: int
    outlet_elev: float
    ramp_min: float
    ramp_max: float
    routing_dem_path: str


@dataclass(frozen=True)
class StreamCaptureReport:
    """What the second-pass stream-gap capture carved."""

    near_misses: int
    channel_cells: int
    routing_dem_path: str


def carve_routing_dem(
    *,
    dem_in_path: str | Path,
    dem_out_path: str | Path,
    lake_polygons: list,
    outlet_xy: tuple[float, float] | None,
    slope: float = 0.003,
    buffer_m: float = 15.0,
) -> LakeEnforcementReport:
    """Write a routing DEM with the lakes carved as sinks that drain to the outlet.

    Parameters
    ----------
    dem_in_path:
        Raw regional DEM (untouched; this is also the model-top source).
    dem_out_path:
        Where to write the carved routing DEM (fed only to D8 delineation).
    lake_polygons:
        Lake footprint polygons in the DEM CRS (shapely geometries).
    outlet_xy:
        Model outlet (x, y) in the DEM CRS; the ramp descends toward it and the
        notch is punched to it. When ``None`` the lakes are carved as sinks with
        no notch (they must then be the domain outlet themselves).
    slope:
        Ramp gradient (m per m of distance to the outlet). Small and positive so
        the lakes slope gently toward the outlet with no flat depression.
    buffer_m:
        Buffer applied to each lake footprint (metres) to bridge inter-lake sills
        and knit the shoreline into the carve.
    """
    dem_in_path = str(dem_in_path)
    dem_out_path = str(dem_out_path)

    with rasterio.open(dem_in_path) as src:
        dem = src.read(1).astype("float32")
        transform = src.transform
        profile = src.profile
        nodata = float(src.nodata) if src.nodata is not None else -9999.0

    valid = dem != nodata
    lakes = [g for g in lake_polygons if g is not None and not g.is_empty]
    if not lakes:
        raise ValueError("carve_routing_dem: no lake polygon to enforce.")

    shapes = [(g.buffer(buffer_m), 1) for g in lakes]
    lake_mask = rasterize(
        shapes, out_shape=dem.shape, transform=transform, fill=0, dtype="uint8"
    ).astype(bool)
    lake_mask &= valid
    if not lake_mask.any():
        raise ValueError(
            "carve_routing_dem: the lake footprints rasterize to no valid DEM cell; "
            "check the lake CRS and the DEM extent."
        )

    # Drainage anchor: the outlet cell, or the lowest lake cell if no outlet is set.
    if outlet_xy is not None:
        r_out, c_out = rowcol(transform, outlet_xy[0], outlet_xy[1])
        r_out = int(np.clip(r_out, 0, dem.shape[0] - 1))
        c_out = int(np.clip(c_out, 0, dem.shape[1] - 1))
        anchor_xy = (float(outlet_xy[0]), float(outlet_xy[1]))
        outlet_elev = float(dem[r_out, c_out])
    else:
        rows, cols = np.where(lake_mask)
        k = int(np.argmin(dem[rows, cols]))
        anchor_xy = tuple(float(v) for v in xy(transform, rows[k], cols[k]))
        outlet_elev = float(dem[rows[k], cols[k]])

    # Ramp every lake cell toward the anchor: z = outlet + slope * distance. Lower
    # only (min with existing) so the terrain is never raised.
    rows, cols = np.where(lake_mask)
    xs, ys = xy(transform, rows, cols)
    dist = np.hypot(np.asarray(xs) - anchor_xy[0], np.asarray(ys) - anchor_xy[1])
    ramp = (outlet_elev + slope * dist).astype("float32")
    dem[rows, cols] = np.minimum(dem[rows, cols], ramp)

    # Outlet notch: punch a descending channel from the lake nearest the anchor to
    # the anchor, so the lake system drains OUT to the outlet (else it is a terminal
    # sink and the outlet's watershed would exclude the lakes).
    notch_cells = 0
    if outlet_xy is not None:
        merged = unary_union(lakes)
        near = nearest_points(merged.boundary, Point(*anchor_xy))[0]
        channel = LineString([(near.x, near.y), anchor_xy]).buffer(max(buffer_m * 0.6, 6.0))
        notch_mask = (
            rasterize(
                [(channel, 1)],
                out_shape=dem.shape,
                transform=transform,
                fill=0,
                all_touched=True,  # a thin channel must capture every cell it crosses
                dtype="uint8",
            ).astype(bool)
            & valid
        )
        nr, nc = np.where(notch_mask)
        if nr.size:
            nxs, nys = xy(transform, nr, nc)
            nd = np.hypot(np.asarray(nxs) - anchor_xy[0], np.asarray(nys) - anchor_xy[1])
            dem[nr, nc] = np.minimum(dem[nr, nc], (outlet_elev + slope * nd).astype("float32"))
            notch_cells = int(notch_mask.sum())

    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    profile.update(dtype="float32", compress="lzw", tiled=False, nodata=nodata)
    Path(dem_out_path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dem_out_path, "w", **profile) as dst:
        dst.write(dem, 1)

    report = LakeEnforcementReport(
        lake_cells=int(lake_mask.sum()),
        notch_cells=notch_cells,
        outlet_elev=outlet_elev,
        ramp_min=float(ramp.min()),
        ramp_max=float(ramp.max()),
        routing_dem_path=dem_out_path,
    )
    logger.info(
        "Lake enforcement: carved %d lake cells (ramp %.1f-%.1f m) + %d notch cells "
        "to outlet at %.1f m into the routing DEM.",
        report.lake_cells,
        report.ramp_min,
        report.ramp_max,
        report.notch_cells,
        report.outlet_elev,
    )
    return report


def capture_stream_gaps(
    *,
    dem_path: str | Path,
    out_path: str | Path,
    link_id_tif: str | Path,
    d8_tif: str | Path,
    lake_polygons: list,
    capture_radius_m: float,
    acc_tif: str | Path | None = None,
    min_acc_fraction: float = 0.3,
    max_streams: int = 8,
    slope: float = 0.003,
    buffer_m: float = 15.0,
) -> StreamCaptureReport:
    """Carve a channel from each NEAR-MISS stream terminal to the nearest lake.

    A near-miss is a stream cell whose D8 downstream is neither a stream nor a lake:
    its flow disperses over a flat forebay short of the lake, so the extracted
    channel dead-ends. Carving a descending channel to the nearest lake cell (within
    ``capture_radius_m``) lets the SECOND delineation pass extend the stream to the
    shoreline. Operates on the already lake-carved routing DEM; the model top is
    untouched (a separate raster). Rasters must share the corrected-DEM / D8 grid.
    """
    dem_path = str(dem_path)
    out_path = str(out_path)
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype("float32")
        transform = src.transform
        profile = src.profile
        nodata = float(src.nodata) if src.nodata is not None else -9999.0
    with rasterio.open(str(link_id_tif)) as src:
        link = np.nan_to_num(src.read(1), nan=0.0).astype(int)
    with rasterio.open(str(d8_tif)) as src:
        d8 = np.nan_to_num(src.read(1), nan=0.0).astype(int)

    valid = dem != nodata
    lakes = [g for g in lake_polygons if g is not None and not g.is_empty]
    lake_mask = rasterize(
        [(g, 1) for g in lakes], out_shape=dem.shape, transform=transform, fill=0, dtype="uint8"
    ).astype(bool)
    lake_rc = np.argwhere(lake_mask)
    if not lake_rc.size:
        return StreamCaptureReport(0, 0, dem_path)

    nrow, ncol = dem.shape
    stream = link > 0
    sr, sc = np.where(stream)
    if not sr.size:
        return StreamCaptureReport(0, 0, dem_path)

    # Vectorised D8 downstream cell of every stream cell.
    dr = sr.copy()
    dc = sc.copy()
    has_down = np.zeros(sr.shape, dtype=bool)
    codes = d8[sr, sc]
    for code, (odr, odc) in WBT_D8_OFFSETS.items():
        m = codes == code
        dr[m] = sr[m] + odr
        dc[m] = sc[m] + odc
        has_down |= m
    in_bounds = has_down & (dr >= 0) & (dr < nrow) & (dc >= 0) & (dc < ncol)
    # A near-miss terminal: in-domain downstream that is neither stream nor lake.
    is_terminal = np.zeros(sr.shape, dtype=bool)
    idx = np.where(in_bounds)[0]
    down_ok = ~stream[dr[idx], dc[idx]] & ~lake_mask[dr[idx], dc[idx]]
    is_terminal[idx] = down_ok
    tr = sr[is_terminal]
    tc = sc[is_terminal]
    if not tr.size:
        return StreamCaptureReport(0, 0, dem_path)

    # Keep only the SIGNIFICANT near-misses (main rivers), not every small bank
    # tributary end: a large elongated reservoir has dozens of them, and carving all
    # would fragment the network. Rank by upstream accumulation and keep the biggest.
    if acc_tif is not None and Path(str(acc_tif)).exists():
        with rasterio.open(str(acc_tif)) as src:
            acc = np.nan_to_num(src.read(1), nan=0.0)
        acc_t = acc[tr, tc]
        order = np.argsort(acc_t)[::-1]
        keep = acc_t[order] >= float(min_acc_fraction) * float(acc_t.max())
        chosen = order[keep][: int(max_streams)]
    else:
        chosen = np.arange(tr.size)[: int(max_streams)]
    terminals = list(zip(tr[chosen].tolist(), tc[chosen].tolist(), strict=True))
    if not terminals:
        return StreamCaptureReport(0, 0, dem_path)

    lake_x, lake_y = xy(transform, lake_rc[:, 0], lake_rc[:, 1])
    lake_xy = np.column_stack([np.asarray(lake_x), np.asarray(lake_y)])
    n_captured = 0
    channel_cells = 0
    for r, c in terminals:
        tx, ty = xy(transform, r, c)
        d = np.hypot(lake_xy[:, 0] - tx, lake_xy[:, 1] - ty)
        k = int(np.argmin(d))
        if float(d[k]) > capture_radius_m:
            continue
        lr, lc = int(lake_rc[k, 0]), int(lake_rc[k, 1])
        lx, ly = xy(transform, lr, lc)
        lake_elev = float(dem[lr, lc])
        line = LineString([(tx, ty), (lx, ly)]).buffer(max(buffer_m * 0.6, 6.0))
        cm = (
            rasterize(
                [(line, 1)],
                out_shape=dem.shape,
                transform=transform,
                fill=0,
                all_touched=True,
                dtype="uint8",
            ).astype(bool)
            & valid
        )
        cr, cc = np.where(cm)
        if not cr.size:
            continue
        cxs, cys = xy(transform, cr, cc)
        dch = np.hypot(np.asarray(cxs) - lx, np.asarray(cys) - ly)
        dem[cr, cc] = np.minimum(dem[cr, cc], (lake_elev + slope * dch).astype("float32"))
        channel_cells += int(cm.sum())
        n_captured += 1

    if n_captured == 0:
        return StreamCaptureReport(0, 0, dem_path)

    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    profile.update(dtype="float32", compress="lzw", tiled=False, nodata=nodata)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(dem, 1)
    logger.info(
        "Lake enforcement capture: %d near-miss stream(s) carved to a lake (%d channel cells).",
        n_captured,
        channel_cells,
    )
    return StreamCaptureReport(n_captured, channel_cells, out_path)


def _lakes_from_config(enforce: object, setup: object) -> list:
    """Read the enforcement lake polygons, resolving the path against the DEM data dir."""
    import geopandas as gpd

    lgp = getattr(enforce, "lake_geometry_path", None)
    if lgp is None:
        raise ValueError(
            "geographic.enforce_lakes.enabled is true but lake_geometry_path is unset."
        )
    path = Path(lgp)
    if not path.exists():
        # A bare filename (or a mis-resolved one): look under <data>/lake_geometry/,
        # where <data> is the parent of the DEM's family dir (data/dem/x.tif -> data).
        data_dir = Path(str(setup.dem_init_path)).resolve().parent.parent
        candidate = data_dir / "lake_geometry" / path.name
        if candidate.exists():
            path = candidate
    if not path.exists():
        raise FileNotFoundError(
            f"geographic.enforce_lakes.lake_geometry_path not found: {lgp} "
            "(tried as-is and under <data>/lake_geometry/)."
        )
    gdf = gpd.read_file(path)
    if getattr(setup, "crs_project", None) is not None:
        gdf = gdf.to_crs(setup.crs_project)
    return [g for g in gdf.geometry if g is not None and not g.is_empty]


def _outlet_from_config(config: object) -> tuple[float, float] | None:
    x = getattr(config, "x_outlet", None)
    y = getattr(config, "y_outlet", None)
    if x is None or y is None:
        return None
    return (float(x), float(y))


def routing_dem_from_config(config: object, setup: object) -> str:
    """Return the flow-routing DEM: lakes carved if enforcement is on, else the raw DEM.

    Duck-typed on ``config`` (``enforce_lakes``, ``x_outlet``/``y_outlet``) and ``setup``
    (``dem_init_path``, ``paths.correcflow_path``, ``crs_project``), so BOTH geographic
    entry points can share it. The raw DEM (model top) is never modified.
    """
    enforce = getattr(config, "enforce_lakes", None)
    if enforce is None or not getattr(enforce, "enabled", False):
        return str(setup.dem_init_path)
    lakes = _lakes_from_config(enforce, setup)
    out_path = str(Path(setup.paths.correcflow_path) / "dem_routing_enforced.tif")
    carve_routing_dem(
        dem_in_path=setup.dem_init_path,
        dem_out_path=out_path,
        lake_polygons=lakes,
        outlet_xy=_outlet_from_config(config),
        slope=float(enforce.slope),
        buffer_m=float(enforce.buffer_m),
    )
    return out_path


def _dam_lines_from_config(dam_carve: object, setup: object) -> list:
    """Read the dam-carve trace, resolving a bare filename against <data>/cutoff_wall/."""
    import geopandas as gpd

    lp = getattr(dam_carve, "line_path", None)
    if lp is None:
        raise ValueError("geographic.dam_carve.enabled is true but line_path is unset.")
    path = Path(lp)
    if not path.exists():
        data_dir = Path(str(setup.dem_init_path)).resolve().parent.parent
        for cand in (data_dir / "cutoff_wall" / path.name, data_dir / path.name):
            if cand.exists():
                path = cand
                break
    if not path.exists():
        raise FileNotFoundError(
            f"geographic.dam_carve.line_path not found: {lp} "
            "(tried as-is and under <data>/cutoff_wall/)."
        )
    if str(path).lower().endswith(".csv"):
        import pandas as pd

        df = pd.read_csv(path)
        cols = list(df.columns)
        coords = list(zip(df[cols[0]].to_numpy(), df[cols[1]].to_numpy(), strict=False))
        return [LineString(coords)]
    gdf = gpd.read_file(path)
    if getattr(setup, "crs_project", None) is not None and gdf.crs is not None:
        gdf = gdf.to_crs(setup.crs_project)
    return [g for g in gdf.geometry if g is not None and not g.is_empty]


def carve_dam_into_top_dem(
    *,
    dem_in_path: str,
    dem_out_path: str,
    dam_lines: list,
    buffer_m: float,
    search_radius_m: float | None = None,
) -> tuple[int, float]:
    """Lower the model-top DEM along a dam trace to the local valley floor.

    A raw DEM samples the concrete dam crest as terrain, lifting the aquifer
    column under the dam. This sets every DEM cell within ``buffer_m`` of the dam
    trace to the minimum valid elevation found in a wider neighborhood (the
    valley floor around the dam, excluding the crest corridor), so a cutoff-wall
    HFB band lands in the aquifer at the true dam. Returns (n_cells_carved,
    valley_floor_elevation).
    """
    line = unary_union(list(dam_lines))
    if line.is_empty:
        raise ValueError("carve_dam_into_top_dem: no dam line to carve.")
    with rasterio.open(dem_in_path) as src:
        arr = src.read(1).astype("float64")
        prof = src.profile.copy()
        transform = src.transform
        nodata = src.nodata
    res = (abs(transform.a) + abs(transform.e)) / 2.0
    search_r = float(search_radius_m) if search_radius_m else max(3.0 * float(buffer_m), 3.0 * res)

    corridor_mask = rasterize(
        [(line.buffer(float(buffer_m)), 1)],
        out_shape=arr.shape,
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)
    search_mask = rasterize(
        [(line.buffer(search_r), 1)],
        out_shape=arr.shape,
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)

    valid = np.isfinite(arr)
    if nodata is not None:
        valid &= arr != nodata
    floor_cells = search_mask & valid & ~corridor_mask
    if not floor_cells.any():
        floor_cells = search_mask & valid
    if not floor_cells.any():
        raise ValueError("carve_dam_into_top_dem: no valid DEM cell around the dam trace.")
    floor = float(np.min(arr[floor_cells]))

    carve = corridor_mask & valid & (arr > floor)
    n_carved = int(carve.sum())
    arr[carve] = floor
    with rasterio.open(dem_out_path, "w", **prof) as dst:
        dst.write(arr.astype(prof["dtype"]), 1)
    logger.info(
        "Dam top-carve: lowered %d cells to the valley floor (%.1f m) along the dam trace.",
        n_carved,
        floor,
    )
    return n_carved, floor


def top_dem_from_config(config: object, setup: object) -> str:
    """Return the model-top DEM: the dam carved to the valley floor if configured, else raw.

    Mirror of :func:`routing_dem_from_config` on the model TOP. Duck-typed on
    ``config.dam_carve`` and ``setup`` (``dem_init_path``, ``paths.correcflow_path``,
    ``crs_project``). The routing DEM (delineation) is never modified here.
    """
    dc = getattr(config, "dam_carve", None)
    if dc is None or not getattr(dc, "enabled", False):
        return str(setup.dem_init_path)
    lines = _dam_lines_from_config(dc, setup)
    out_path = str(Path(setup.paths.correcflow_path) / "dem_top_dam_carved.tif")
    carve_dam_into_top_dem(
        dem_in_path=str(setup.dem_init_path),
        dem_out_path=out_path,
        dam_lines=lines,
        buffer_m=float(dc.buffer_m),
        search_radius_m=None if dc.search_radius_m is None else float(dc.search_radius_m),
    )
    return out_path


def capture_from_config(
    config: object, setup: object, *, flow_direc: str, link_id_tif: str | None
) -> str | None:
    """Carve near-miss streams to the lakes; return the captured routing DEM or None.

    The caller re-delineates on the returned DEM. Returns None when capture is off or
    no near-miss was found.
    """
    enforce = getattr(config, "enforce_lakes", None)
    if enforce is None or not getattr(enforce, "enabled", False):
        return None
    radius = float(getattr(enforce, "capture_radius_m", 0.0) or 0.0)
    if radius <= 0.0:
        return None
    link_tif = link_id_tif or str(Path(setup.paths.correcflow_path) / "dem_stream_link_id_full.tif")
    if not Path(link_tif).exists():
        logger.warning(
            "enforce_lakes.capture_radius_m is set but the stream link-id raster is "
            "missing (%s); enable geographic.river_network.compute_stream_links.",
            link_tif,
        )
        return None
    routing = str(Path(setup.paths.correcflow_path) / "dem_routing_enforced.tif")
    src = routing if Path(routing).exists() else str(setup.dem_init_path)
    out_path = str(Path(setup.paths.correcflow_path) / "dem_routing_captured.tif")
    acc_tif = str(Path(setup.paths.correcflow_path) / "dem_acc_cells.tif")
    report = capture_stream_gaps(
        dem_path=src,
        out_path=out_path,
        link_id_tif=link_tif,
        d8_tif=flow_direc,
        lake_polygons=_lakes_from_config(enforce, setup),
        capture_radius_m=radius,
        acc_tif=acc_tif if Path(acc_tif).exists() else None,
        slope=float(enforce.slope),
        buffer_m=float(enforce.buffer_m),
    )
    return report.routing_dem_path if report.near_misses > 0 else None
