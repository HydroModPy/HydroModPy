"""The ground: the DEM plus the corrections the project declares, each bounded and logged.

The routing chain (burn, lake carve, conditioning, D8) and the model top both
start from the ground, in both geographic entry points. Without a declared
correction the ground is the raw DEM path itself: no copy, no new file.

The corrections, in order:

1. ``[geographic.dam_carve]``: the dam footprint lowered to the valley floor.
2. ``[geographic.crossings]``: the embankments of roads, railways and bridges
   lowered, along the channel, to the bed level read on both sides.

The notch needs a channel to follow, so it runs after a first delineation: the
caller builds the ground without a channel (dam only), delineates, hands the
channel it found back here, and delineates again on the notched ground.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import rasterio
from rasterio.transform import rowcol, xy
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.geographic.core.lake_enforcement import (
    carve_dam_into_top_dem,
    dam_lines_from_config,
    lakes_from_config,
)
from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS

if TYPE_CHECKING:
    import geopandas as gpd

logger = get_logger(__name__)

GROUND_DAM_FILENAME = "dem_ground_dam_carved.tif"
"""The ground with the dam carved, written when ``dam_carve`` is enabled."""

GROUND_FILENAME = "dem_ground.tif"
"""The ground with the crossings notched, written when ``crossings`` is enabled."""

CROSSINGS_REPORT_FILENAME = "dem_ground_crossings.json"
"""What the notch did, next to the corrected DEM."""

# The channel raster of the first delineation, on the full DEM grid. Named in
# ``river_network.build_river_network_products``, which writes them; the
# products object only carries the clipped copies.
_STREAMS_FULL_NAME = "dem_streams_full.tif"
_STREAMS_PRUNED_FULL_NAME = "dem_streams_pruned_full.tif"

_LOWERING_TOLERANCE_M = 1e-4
"""A pixel moved by less than this is not counted as lowered."""

_REASONS = {
    "off_channel": "point farther than snap_radius from the channel tree",
    "no_channel_pixel": "no channel pixel within snap_radius",
    "no_upstream_reach": "the channel starts at the crossing",
    "no_downstream_reach": "the channel ends at the crossing",
    "nodata": "a bed level is nodata",
    "nothing_to_lower": "the ground is already at or below the bed line",
    "unsupported_geometry": "a polygon structure has no line to cross",
    "dam_or_weir": "a declared dam, weir or lake lies at the crossing",
    "no_bed_end": "a bed end could not be read beyond the neighbouring structures",
}

_KINDS = ("road", "railway", "bridge", "weir", "dam", "other")
"""The kinds of the crossings data variable. Spatial cannot import data, so the
list is written here, and a test pins it to the variable's."""

_BARRIER_KINDS = ("dam", "weir")
"""Declared barriers: a crossing next to one of them is a dam crest, not a wall."""

_MAX_PLAN_PASSES = 5
"""Passes that move the bed ends past the neighbouring embankments."""


@dataclass(frozen=True)
class FirstPassChannel:
    """What the first delineation says about the channel, read by the notch."""

    streams_tif: str
    d8_tif: str
    acc_tif: str
    network_shp: str | None
    catchment_area_km2: float


@dataclass(frozen=True)
class _CrossingPoint:
    kind: str
    name: str
    x: float
    y: float
    feature: int


@dataclass
class NotchReport:
    """What the notch found and did, as the JSON document and the INFO line."""

    parameters: dict[str, Any]
    features: dict[str, int] = field(default_factory=dict)
    crossing_points: dict[str, int] = field(default_factory=dict)
    notched: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    skipped_detail: list[dict[str, Any]] = field(default_factory=list)
    pixels_lowered: int = 0
    max_lowering_m: float = 0.0
    median_lowering_m: float = 0.0
    capped_pixels: int = 0
    catchment_area_km2_before: float | None = None
    catchment_area_km2_after: float | None = None

    def skip(self, point: _CrossingPoint, reason: str) -> None:
        """Count one crossing left alone, with where and why."""
        self.skipped[reason] = self.skipped.get(reason, 0) + 1
        self.skipped_detail.append(
            {
                "kind": point.kind,
                "name": point.name,
                "x": point.x,
                "y": point.y,
                "reason": reason,
                "meaning": _REASONS[reason],
            }
        )

    def to_document(self) -> dict[str, Any]:
        """The JSON form."""
        return {
            "parameters": self.parameters,
            "features": self.features,
            "crossing_points": self.crossing_points,
            "notched": self.notched,
            "skipped": self.skipped,
            "skipped_detail": self.skipped_detail,
            "pixels_lowered": self.pixels_lowered,
            "max_lowering_m": self.max_lowering_m,
            "median_lowering_m": self.median_lowering_m,
            "capped_pixels": self.capped_pixels,
            "catchment_area_km2_before": self.catchment_area_km2_before,
            "catchment_area_km2_after": self.catchment_area_km2_after,
        }

    def info_line(self) -> str:
        """The one line the log carries."""
        before, after = self.catchment_area_km2_before, self.catchment_area_km2_after
        area = (
            ""
            if before is None or after is None
            else f"; catchment {before:.3f} -> {after:.3f} km2"
        )
        return (
            f"Crossing notch: {sum(self.crossing_points.values())} crossing(s) on the channel "
            f"tree {_counts(self.crossing_points)}, {sum(self.notched.values())} notched "
            f"{_counts(self.notched)}, {sum(self.skipped.values())} skipped "
            f"{_counts(self.skipped)}; {self.pixels_lowered} pixel(s) lowered, max "
            f"{self.max_lowering_m:.2f} m, median {self.median_lowering_m:.2f} m, "
            f"{self.capped_pixels} capped{area}."
        )


def _counts(counts: dict[str, int]) -> str:
    return "(" + ", ".join(f"{key} {value}" for key, value in sorted(counts.items())) + ")"


class _GroundSetup:
    """A setup whose DEM is the ground, for the helpers that read ``dem_init_path``.

    ``source_dem_path`` keeps the DEM the project declared: the data folder a
    bare filename is looked up in is the one around it, not the one around the
    corrected copy.
    """

    def __init__(self, setup: Any, ground: str) -> None:
        self._setup = setup
        self.dem_init_path = ground
        self.source_dem_path = str(setup.dem_init_path)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._setup, name)


def on_ground(setup: Any, ground: str | Path) -> Any:
    """The setup reading *ground* as its DEM, or the setup itself when it already does."""
    if str(ground) == str(setup.dem_init_path):
        return setup
    return _GroundSetup(setup, str(ground))


def notch_enabled(config: object) -> bool:
    """Whether ``[geographic.crossings]`` is on."""
    return bool(getattr(getattr(config, "crossings", None), "enabled", False))


def _dam_enabled(config: object) -> bool:
    return bool(getattr(getattr(config, "dam_carve", None), "enabled", False))


def ground_dem_path_from_config(config: object, setup: object) -> str:
    """Return the path of the final ground without building anything.

    The cache branch needs it and must not redo a correction. It is the raw DEM
    when nothing is declared, the notched file when the notch is on, else the
    dam-carved one.
    """
    correcflow = Path(setup.paths.correcflow_path)
    if notch_enabled(config):
        return str(correcflow / GROUND_FILENAME)
    if _dam_enabled(config):
        return str(correcflow / GROUND_DAM_FILENAME)
    return str(setup.dem_init_path)


def ground_dem_from_config(
    config: object,
    setup: object,
    *,
    channel: FirstPassChannel | None = None,
) -> Path:
    """Build the ground and return its path.

    Without ``channel`` the ground carries the dam only (the raw DEM path when
    that is off too). With the channel of a first delineation and the notch
    enabled, the crossings are notched into it and the report is written.
    """
    base = _dam_carved(config, setup)
    if channel is None or not notch_enabled(config):
        return Path(base)
    return _notched(config, setup, base=base, channel=channel)


def _dam_carved(config: object, setup: object) -> str:
    """The raw DEM, with the dam carved to the valley floor when ``dam_carve`` is on."""
    if not _dam_enabled(config):
        return str(setup.dem_init_path)
    dam = config.dam_carve
    out_path = str(Path(setup.paths.correcflow_path) / GROUND_DAM_FILENAME)
    carve_dam_into_top_dem(
        dem_in_path=str(setup.dem_init_path),
        dem_out_path=out_path,
        dam_lines=dam_lines_from_config(dam, setup),
        buffer_m=float(dam.buffer_m),
        search_radius_m=None if dam.search_radius_m is None else float(dam.search_radius_m),
    )
    return out_path


def first_pass_channel(
    config: object,
    setup: object,
    *,
    flow: object,
    river_products: object,
    catchment_area_km2: float,
) -> FirstPassChannel:
    """Gather what the notch reads from the first delineation."""
    full_name = (
        _STREAMS_PRUNED_FULL_NAME
        if bool(config.river_network.prune_short_streams)
        else _STREAMS_FULL_NAME
    )
    return FirstPassChannel(
        streams_tif=str(Path(setup.paths.correcflow_path) / full_name),
        d8_tif=str(flow.direc),
        acc_tif=str(flow.acc),
        network_shp=getattr(river_products, "hydrographic_network_generated_shp", None),
        catchment_area_km2=float(catchment_area_km2),
    )


def notch_report_path(setup: object) -> Path:
    """Where the JSON report of the notch is written."""
    return Path(setup.paths.correcflow_path) / CROSSINGS_REPORT_FILENAME


def notch_lowered_pixels(setup: object) -> int:
    """How many pixels the last notch lowered, 0 when it did not run."""
    path = notch_report_path(setup)
    if not path.exists():
        return 0
    return int(json.loads(path.read_text(encoding="utf-8"))["pixels_lowered"])


def close_notch_report(setup: object, *, catchment_area_km2_after: float) -> NotchReport:
    """Add the catchment area after the second delineation, log the line, rewrite the JSON."""
    path = notch_report_path(setup)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["catchment_area_km2_after"] = float(catchment_area_km2_after)
    report = NotchReport(
        **{key: value for key, value in document.items() if key in NotchReport.__dataclass_fields__}
    )
    path.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    logger.info(report.info_line())
    return report


def _notched(
    config: object,
    setup: object,
    *,
    base: str,
    channel: FirstPassChannel,
) -> Path:
    """Notch the crossings into *base*, write the ground and its report."""
    import geopandas as gpd

    notch = config.crossings
    if notch.path is None:
        raise ValueError(
            "geographic.crossings is enabled without a path, and no "
            "[[data.crossings.sources]] filled one in. Set geographic.crossings.path, or "
            "declare a crossings source."
        )
    path = Path(notch.path)
    if not path.exists():
        raise FileNotFoundError(f"geographic.crossings.path points to nothing: {path}")
    crossings = gpd.read_file(path)
    if crossings.crs is None:
        raise ValueError(
            f"geographic.crossings.path {path} carries no CRS, so its geometries cannot "
            "be placed on the DEM. Save it with a CRS."
        )
    crs_project = getattr(setup, "crs_project", None)
    if crs_project is not None:
        crossings = crossings.to_crs(crs_project)
    dam_lines = dam_lines_from_config(config.dam_carve, setup) if _dam_enabled(config) else []
    lakes = (
        lakes_from_config(config.enforce_lakes, setup)
        if bool(getattr(getattr(config, "enforce_lakes", None), "enabled", False))
        else []
    )
    network = None
    if channel.network_shp is not None and Path(channel.network_shp).exists():
        network = gpd.read_file(channel.network_shp)

    with rasterio.open(base) as src:
        dem = src.read(1).astype("float32")
        profile = src.profile.copy()
        transform = src.transform
        nodata = src.nodata
    streams = _read_int(channel.streams_tif) > 0
    d8 = _read_int(channel.d8_tif)
    with rasterio.open(channel.acc_tif) as src:
        acc = np.nan_to_num(src.read(1), nan=0.0)

    report = NotchReport(
        parameters={
            "kinds": list(notch.kinds),
            "notch_width_m": float(notch.notch_width),
            "bed_reach_m": float(notch.bed_reach),
            "max_depth_m": float(notch.max_depth),
            "snap_radius_m": float(notch.snap_radius),
            "path": str(path),
        },
        catchment_area_km2_before=channel.catchment_area_km2,
    )
    notched_dem = notch_dem(
        dem,
        nodata=nodata,
        transform=transform,
        streams=streams,
        d8=d8,
        acc=acc,
        crossings=crossings,
        network=network,
        kinds=list(notch.kinds),
        notch_width_m=float(notch.notch_width),
        bed_reach_m=float(notch.bed_reach),
        max_depth_m=float(notch.max_depth),
        snap_radius_m=float(notch.snap_radius),
        report=report,
        dam_lines=dam_lines,
        lakes=lakes,
    )

    out_path = Path(setup.paths.correcflow_path) / GROUND_FILENAME
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    profile.update(dtype="float32", compress="lzw", tiled=False)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(notched_dem.astype("float32"), 1)
    notch_report_path(setup).write_text(
        json.dumps(report.to_document(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return out_path


def _read_int(path: str) -> np.ndarray:
    with rasterio.open(path) as src:
        return np.nan_to_num(src.read(1), nan=0.0).astype(int)


def notch_dem(
    dem: np.ndarray,
    *,
    nodata: float | None,
    transform: Any,
    streams: np.ndarray,
    d8: np.ndarray,
    acc: np.ndarray,
    crossings: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame | None,
    kinds: list[str],
    notch_width_m: float,
    bed_reach_m: float,
    max_depth_m: float,
    snap_radius_m: float,
    report: NotchReport,
    dam_lines: Sequence[BaseGeometry] = (),
    lakes: Sequence[BaseGeometry] = (),
) -> np.ndarray:
    """Return *dem* lowered along the channel at each crossing, and fill *report*.

    The raster half of the notch, free of any file: *streams* is the channel
    mask of the first delineation, *d8* its pointer (WhiteboxTools codes) and
    *acc* its accumulation, all on the grid of *dem*.

    A crossing is left alone when a dam or a weir of *crossings*, a line of
    *dam_lines* or a polygon of *lakes* lies at it: a dam crest is not a wall to
    cut. Only the embankment span, the run of channel pixels around the crossing
    that stand above the bed line, is lowered.
    """
    out = dem.astype("float64").copy()
    original = out.copy()
    valid = np.isfinite(out)
    if nodata is not None:
        valid &= out != nodata

    crossings = _normalised_kinds(crossings)
    points = _crossing_points(
        crossings, network, kinds=kinds, snap_radius_m=snap_radius_m, report=report
    )
    res_x, res_y = abs(float(transform.a)), abs(float(transform.e))
    sites = _sites(points, streams, transform, snap_radius_m, res_x, res_y, report)
    guard = _Guard(
        [
            geometry
            for kind, geometry in zip(crossings["kind"], crossings.geometry, strict=True)
            if kind in _BARRIER_KINDS and geometry is not None and not geometry.is_empty
        ]
        + list(dam_lines),
        list(lakes),
    )
    plans = _plan_all(
        sites,
        guard=guard,
        original=original,
        valid=valid,
        streams=streams,
        d8=d8,
        acc=acc,
        transform=transform,
        bed_reach_m=bed_reach_m,
        snap_radius_m=snap_radius_m,
        res_x=res_x,
        res_y=res_y,
        report=report,
    )

    capped: set[tuple[int, int]] = set()
    for site, plan in plans:
        targets = _notch_targets(
            plan,
            half_width_m=notch_width_m / 2.0,
            res_x=res_x,
            res_y=res_y,
            shape=out.shape,
        )
        changed = False
        for (row, col), target in targets.items():
            if not valid[row, col]:
                continue
            floor = original[row, col] - max_depth_m
            if target < floor - _LOWERING_TOLERANCE_M and out[row, col] > floor:
                capped.add((row, col))
            new = max(min(out[row, col], target), floor)
            changed |= out[row, col] - new > _LOWERING_TOLERANCE_M
            out[row, col] = new
        if changed:
            report.notched[site.point.kind] = report.notched.get(site.point.kind, 0) + 1
        else:
            report.skip(site.point, "nothing_to_lower")

    lowering = original - out
    moved = valid & (lowering > _LOWERING_TOLERANCE_M)
    report.pixels_lowered = int(moved.sum())
    if report.pixels_lowered:
        report.max_lowering_m = float(lowering[moved].max())
        report.median_lowering_m = float(np.median(lowering[moved]))
    report.capped_pixels = len(capped)
    return out


@dataclass(frozen=True)
class _Site:
    """One crossing: where it meets the channel, as the nearest channel pixel."""

    point: _CrossingPoint
    pixel: tuple[int, int]


@dataclass(frozen=True)
class _Plan:
    """The chain around a crossing, its bed line and the embankment span on it."""

    chain: list[tuple[int, int, float]]
    levels: list[float]
    span: frozenset[int]

    @property
    def pixels(self) -> frozenset[tuple[int, int]]:
        return frozenset((self.chain[i][0], self.chain[i][1]) for i in self.span)


class _Guard:
    """The declared dams, weirs and lakes a crossing must not be cut through."""

    def __init__(self, barriers: list[BaseGeometry], lakes: list[BaseGeometry]) -> None:
        self._barriers = STRtree(barriers) if barriers else None
        self._lakes = STRtree(lakes) if lakes else None

    def barrier_near(self, point: _CrossingPoint, radius_m: float) -> bool:
        if self._barriers is None:
            return False
        hits = self._barriers.query(Point(point.x, point.y), predicate="dwithin", distance=radius_m)
        return len(hits) > 0

    def lake_touches(self, line: BaseGeometry) -> bool:
        return self._lakes is not None and len(self._lakes.query(line, predicate="intersects")) > 0


def _normalised_kinds(crossings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """The frame with ``kind`` stripped and lower case, refusing a kind that is not one of ours."""
    if "kind" not in crossings.columns:
        raise ValueError(
            f"geographic.crossings.path holds no 'kind' column; it must hold one of "
            f"{list(_KINDS)} for each feature."
        )
    kind = crossings["kind"].astype(str).str.strip().str.lower()
    unknown = sorted(set(kind) - set(_KINDS))
    if unknown:
        raise ValueError(
            f"geographic.crossings.path: 'kind' value(s) {unknown} are not allowed, "
            f"use {list(_KINDS)}."
        )
    crossings = crossings.copy()
    crossings["kind"] = kind.to_numpy()
    return crossings


def _sites(
    points: list[_CrossingPoint],
    streams: np.ndarray,
    transform: Any,
    snap_radius_m: float,
    res_x: float,
    res_y: float,
    report: NotchReport,
) -> list[_Site]:
    """One site per channel pixel, whatever feature or source the point comes from.

    The channel vector is cut at its junctions, a line through a cut meets both
    pieces, and a bridge of one source and a road of another describe one
    structure: one pixel, one crossing.
    """
    sites: list[_Site] = []
    seen: set[tuple[int, int]] = set()
    for point in points:
        pixel = _channel_pixel(streams, transform, point, snap_radius_m, res_x, res_y)
        key = pixel if pixel is not None else tuple(rowcol(transform, point.x, point.y))
        if key in seen:
            continue
        seen.add(key)
        report.crossing_points[point.kind] = report.crossing_points.get(point.kind, 0) + 1
        if pixel is None:
            report.skip(point, "no_channel_pixel")
            continue
        sites.append(_Site(point, pixel))
    return sites


def _plan_all(
    sites: list[_Site],
    *,
    guard: _Guard,
    original: np.ndarray,
    valid: np.ndarray,
    streams: np.ndarray,
    d8: np.ndarray,
    acc: np.ndarray,
    transform: Any,
    bed_reach_m: float,
    snap_radius_m: float,
    res_x: float,
    res_y: float,
    report: NotchReport,
) -> list[tuple[_Site, _Plan]]:
    """Plan every crossing, moving each bed end past the embankments of its neighbours.

    A first pass reads the ends at *bed_reach_m*. A second reads them again past
    the spans the first found on the other crossings, which moves the spans, and
    so on until they hold still. A crossing whose span does not settle, or whose
    ends cannot get out of its neighbours, is skipped: it would be cut against
    a wall taken for the bed.
    """
    open_sites: list[_Site] = []
    for site in sites:
        if guard.barrier_near(site.point, snap_radius_m):
            report.skip(site.point, "dam_or_weir")
        else:
            open_sites.append(site)

    spans: dict[tuple[int, int], frozenset[tuple[int, int]]] = {}
    previous = spans
    outcomes: dict[tuple[int, int], _Plan | str] = {}
    settled = False
    for _ in range(_MAX_PLAN_PASSES):
        outcomes = {}
        for site in open_sites:
            blocked = {
                pixel for other, span in spans.items() if other != site.pixel for pixel in span
            }
            outcomes[site.pixel] = _plan(
                site,
                blocked=blocked,
                guard=guard,
                original=original,
                valid=valid,
                streams=streams,
                d8=d8,
                acc=acc,
                bed_reach_m=bed_reach_m,
                res_x=res_x,
                res_y=res_y,
                shape=original.shape,
                transform=transform,
            )
        found = {
            pixel: outcome.pixels
            for pixel, outcome in outcomes.items()
            if not isinstance(outcome, str)
        }
        previous, spans = spans, found
        if found == previous:
            settled = True
            break

    plans: list[tuple[_Site, _Plan]] = []
    for site in open_sites:
        outcome = outcomes[site.pixel]
        if isinstance(outcome, str):
            report.skip(site.point, outcome)
        elif not settled and outcome.pixels != previous.get(site.pixel):
            report.skip(site.point, "no_bed_end")
        else:
            plans.append((site, outcome))
    return plans


def _plan(
    site: _Site,
    *,
    blocked: set[tuple[int, int]],
    guard: _Guard,
    original: np.ndarray,
    valid: np.ndarray,
    streams: np.ndarray,
    d8: np.ndarray,
    acc: np.ndarray,
    bed_reach_m: float,
    res_x: float,
    res_y: float,
    shape: tuple[int, ...],
    transform: Any,
) -> _Plan | str:
    """The plan of one crossing, or the reason it is left alone."""
    up = _walk_up(d8, streams, acc, site.pixel, bed_reach_m, res_x, res_y, blocked)
    down = _walk_down(d8, site.pixel, bed_reach_m, res_x, res_y, shape, blocked)
    if not up:
        return "no_upstream_reach"
    if not down:
        return "no_downstream_reach"
    chain = [*reversed([(r, c, -s) for r, c, s in up]), (*site.pixel, 0.0), *down]
    (r_up, c_up, s_up), (r_down, c_down, s_down) = chain[0], chain[-1]
    if (r_up, c_up) in blocked or (r_down, c_down) in blocked:
        return "no_bed_end"
    if not (valid[r_up, c_up] and valid[r_down, c_down]):
        return "nodata"
    centres = [xy(transform, r, c) for r, c, _ in chain]
    if guard.lake_touches(LineString(centres)):
        return "dam_or_weir"
    z_up, z_down = float(original[r_up, c_up]), float(original[r_down, c_down])
    span_m = s_down - s_up
    levels = [z_up + (z_down - z_up) * (s - s_up) / span_m for _, _, s in chain]
    here = len(up)
    span: set[int] = set()
    for direction in (-1, 1):
        index = here
        while 0 < index < len(chain) - 1:
            row, col, _ = chain[index]
            if not valid[row, col] or original[row, col] - levels[index] <= _LOWERING_TOLERANCE_M:
                break
            span.add(index)
            index += direction
    if not span:
        return "nothing_to_lower"
    return _Plan(chain, levels, frozenset(span))


def _line_parts(geometry: BaseGeometry) -> list[BaseGeometry]:
    """The points of an intersection, a collinear overlap giving its midpoint."""
    if geometry.is_empty:
        return []
    if isinstance(geometry, Point):
        return [geometry]
    if isinstance(geometry, LineString):
        return [geometry.interpolate(0.5, normalized=True)]
    return [part for child in getattr(geometry, "geoms", ()) for part in _line_parts(child)]


def _crossing_points(
    crossings: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame | None,
    *,
    kinds: list[str],
    snap_radius_m: float,
    report: NotchReport,
) -> list[_CrossingPoint]:
    """Where the structures of *kinds* meet the channel tree.

    A line structure gives the points where it crosses a channel line (the caller
    merges those that fall in one pixel). A point structure snaps to the nearest channel line
    within *snap_radius_m*. A structure that meets no channel is not a crossing
    and is not reported.
    """
    points: list[_CrossingPoint] = []
    names = crossings["name"] if "name" in crossings.columns else None
    for position, (kind, geometry) in enumerate(
        zip(crossings["kind"], crossings.geometry, strict=True)
    ):
        if kind not in kinds or geometry is None or geometry.is_empty:
            continue
        report.features[kind] = report.features.get(kind, 0) + 1
        name = "" if names is None else str(names.iloc[position])
        if network is None or network.empty:
            continue
        if isinstance(geometry, Point):
            found = _snap_to_network(geometry, network, snap_radius_m)
            if found is None:
                report.skip(
                    _CrossingPoint(kind, name, geometry.x, geometry.y, position), "off_channel"
                )
                continue
            points.append(_CrossingPoint(kind, name, found.x, found.y, position))
        elif isinstance(geometry, LineString | MultiLineString):
            points.extend(_line_crossings(geometry, kind, name, position, network))
        else:
            centre = geometry.representative_point()
            report.skip(
                _CrossingPoint(kind, name, centre.x, centre.y, position), "unsupported_geometry"
            )
    return points


def _snap_to_network(
    geometry: Point, network: gpd.GeoDataFrame, snap_radius_m: float
) -> Point | None:
    candidates = network.sindex.query(geometry.buffer(snap_radius_m), predicate="intersects")
    best: tuple[float, Point] | None = None
    for index in candidates:
        line = network.geometry.iloc[index]
        distance = line.distance(geometry)
        if distance <= snap_radius_m and (best is None or distance < best[0]):
            best = (distance, nearest_points(line, geometry)[0])
    return None if best is None else best[1]


def _line_crossings(
    geometry: BaseGeometry, kind: str, name: str, feature: int, network: gpd.GeoDataFrame
) -> list[_CrossingPoint]:
    found: list[_CrossingPoint] = []
    for index in network.sindex.query(geometry, predicate="intersects"):
        for point in _line_parts(geometry.intersection(network.geometry.iloc[index])):
            found.append(_CrossingPoint(kind, name, point.x, point.y, feature))
    return found


def _channel_pixel(
    streams: np.ndarray,
    transform: Any,
    point: _CrossingPoint,
    snap_radius_m: float,
    res_x: float,
    res_y: float,
) -> tuple[int, int] | None:
    """The channel pixel nearest to *point* within the snap radius, else ``None``."""
    row, col = rowcol(transform, point.x, point.y)
    reach_r = int(math.ceil(snap_radius_m / res_y)) + 1
    reach_c = int(math.ceil(snap_radius_m / res_x)) + 1
    r0, r1 = max(row - reach_r, 0), min(row + reach_r + 1, streams.shape[0])
    c0, c1 = max(col - reach_c, 0), min(col + reach_c + 1, streams.shape[1])
    if r0 >= r1 or c0 >= c1:
        return None
    rows, cols = np.nonzero(streams[r0:r1, c0:c1])
    if rows.size == 0:
        return None
    rows, cols = rows + r0, cols + c0
    xs, ys = xy(transform, rows, cols)
    distance = np.hypot(np.asarray(xs) - point.x, np.asarray(ys) - point.y)
    best = int(np.argmin(distance))
    if float(distance[best]) > snap_radius_m:
        return None
    return int(rows[best]), int(cols[best])


def _step_m(d_row: int, d_col: int, res_x: float, res_y: float) -> float:
    return math.hypot(d_row * res_y, d_col * res_x)


def _walk_down(
    d8: np.ndarray,
    start: tuple[int, int],
    reach_m: float,
    res_x: float,
    res_y: float,
    shape: tuple[int, ...],
    blocked: set[tuple[int, int]],
) -> list[tuple[int, int, float]]:
    """Follow the D8 pointer from *start* until *reach_m* is covered or the pointer ends.

    The walk goes on while it stands on a pixel of *blocked*: the end of the
    chain is read beyond the embankments of the neighbouring crossings.
    """
    row, col = start
    walked = 0.0
    seen = {start}
    chain: list[tuple[int, int, float]] = []
    while walked < reach_m or (row, col) in blocked:
        step = D8_WBT_OFFSETS.get(int(d8[row, col]))
        if step is None:
            break
        row, col = row + step[0], col + step[1]
        if not (0 <= row < shape[0] and 0 <= col < shape[1]) or (row, col) in seen:
            break
        seen.add((row, col))
        walked += _step_m(step[0], step[1], res_x, res_y)
        chain.append((row, col, walked))
    return chain


def _walk_up(
    d8: np.ndarray,
    streams: np.ndarray,
    acc: np.ndarray,
    start: tuple[int, int],
    reach_m: float,
    res_x: float,
    res_y: float,
    blocked: set[tuple[int, int]],
) -> list[tuple[int, int, float]]:
    """Climb the channel from *start*, taking the largest accumulation at each fork.

    Like :func:`_walk_down`, the walk goes on while it stands on a *blocked* pixel.
    """
    row, col = start
    walked = 0.0
    seen = {start}
    chain: list[tuple[int, int, float]] = []
    while walked < reach_m or (row, col) in blocked:
        best: tuple[float, int, int, tuple[int, int]] | None = None
        for code, (d_row, d_col) in D8_WBT_OFFSETS.items():
            up_row, up_col = row - d_row, col - d_col
            if not (0 <= up_row < d8.shape[0] and 0 <= up_col < d8.shape[1]):
                continue
            if (up_row, up_col) in seen or not streams[up_row, up_col]:
                continue
            if int(d8[up_row, up_col]) != code:
                continue
            if best is None or acc[up_row, up_col] > best[0]:
                best = (float(acc[up_row, up_col]), up_row, up_col, (d_row, d_col))
        if best is None:
            break
        _, row, col, step = best
        seen.add((row, col))
        walked += _step_m(step[0], step[1], res_x, res_y)
        chain.append((row, col, walked))
    return chain


def _notch_targets(
    plan: _Plan,
    *,
    half_width_m: float,
    res_x: float,
    res_y: float,
    shape: tuple[int, ...],
) -> dict[tuple[int, int], float]:
    """The bed line over the embankment span and the pixels beside it.

    A pixel within *half_width_m* of the span takes the level of the chain pixel
    nearest to it, and only when that pixel is on the span: the width is applied
    across the embankment, never along the channel past it. The two end pixels
    are the bed and are never touched.
    """
    chain, levels, span = plan.chain, plan.levels, plan.span
    rows = np.array([row for row, _, _ in chain])
    cols = np.array([col for _, col, _ in chain])
    off_span = np.array([index not in span for index in range(len(chain))])
    ends = {(chain[0][0], chain[0][1]), (chain[-1][0], chain[-1][1])}
    reach_r = int(math.floor(half_width_m / res_y))
    reach_c = int(math.floor(half_width_m / res_x))
    targets: dict[tuple[int, int], float] = {}
    for index in span:
        row, col, _ = chain[index]
        for d_row in range(-reach_r, reach_r + 1):
            for d_col in range(-reach_c, reach_c + 1):
                if _step_m(d_row, d_col, res_x, res_y) > half_width_m + 1e-9:
                    continue
                r, c = row + d_row, col + d_col
                if not (0 <= r < shape[0] and 0 <= c < shape[1]) or (r, c) in targets:
                    continue
                if (r, c) in ends:
                    continue
                distance = np.round(np.hypot((rows - r) * res_y, (cols - c) * res_x), 6)
                nearest = int(np.lexsort((off_span, distance))[0])
                if nearest in span:
                    targets[(r, c)] = levels[nearest]
    return targets
