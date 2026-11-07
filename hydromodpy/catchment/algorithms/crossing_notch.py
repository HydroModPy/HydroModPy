"""The notch of the DEM at each road, railway or bridge crossing of the channel.

At each crossing the bed line read upstream and downstream is drawn across the
embankment, and the ground is lowered to it over the embankment span.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from rasterio.transform import rowcol, xy
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from hydromodpy.catchment.terrain.port import D8_WBT_OFFSETS
from hydromodpy.core.fields.nodata import valid_cells

if TYPE_CHECKING:
    import geopandas as gpd


_LOWERING_TOLERANCE_M = 1e-4


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


_BARRIER_KINDS = ("dam", "weir")


_MAX_PLAN_PASSES = 5


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
    lakes: Sequence[BaseGeometry] = (),
) -> tuple[np.ndarray, np.ndarray]:
    """Return *dem* lowered along the channel at each crossing and its footprint.

    The footprint is the mask of the pixels the notch lowered, as the report
    counts them: what a later step reads instead of differencing two rasters.
    *report* is filled.

    The raster half of the notch, free of any file: *streams* is the channel
    mask of the first delineation, *d8* its pointer (WhiteboxTools codes) and
    *acc* its accumulation, all on the grid of *dem*.

    A crossing is left alone when a dam or a weir of *crossings* or a polygon
    of *lakes* lies at it: a dam crest is not a wall to
    cut. Only the embankment span, the run of channel pixels around the crossing
    that stand above the bed line, is lowered.
    """
    out = dem.astype("float64").copy()
    original = out.copy()
    valid = valid_cells(out, nodata)

    crossings = _normalised_kinds(crossings)
    points = _crossing_points(
        crossings, network, kinds=kinds, snap_radius_m=snap_radius_m, report=report
    )
    res_x, res_y = abs(float(transform.a)), abs(float(transform.e))
    sites = _sites(points, streams, transform, snap_radius_m, res_x, res_y, report)
    guard = _guard_of(crossings, lakes)
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

    capped = _lower_along_plans(
        out,
        plans,
        original=original,
        valid=valid,
        notch_width_m=notch_width_m,
        max_depth_m=max_depth_m,
        res_x=res_x,
        res_y=res_y,
        report=report,
    )
    moved = _count_lowering(report, original=original, out=out, valid=valid, capped=capped)
    return out, moved


def _guard_of(crossings: gpd.GeoDataFrame, lakes: Sequence[BaseGeometry]) -> _Guard:
    """The guard of the declared dams and weirs of *crossings* and of the *lakes*."""
    return _Guard(
        [
            geometry
            for kind, geometry in zip(crossings["kind"], crossings.geometry, strict=True)
            if kind in _BARRIER_KINDS and geometry is not None and not geometry.is_empty
        ],
        list(lakes),
    )


def _lower_along_plans(
    out: np.ndarray,
    plans: list[tuple[_Site, _Plan]],
    *,
    original: np.ndarray,
    valid: np.ndarray,
    notch_width_m: float,
    max_depth_m: float,
    res_x: float,
    res_y: float,
    report: NotchReport,
) -> set[tuple[int, int]]:
    """Lower *out* in place to the bed line of each plan, never deeper than *max_depth_m*.

    Counts each crossing notched or left with nothing to lower, and returns the
    pixels the depth cap held up.
    """
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
    return capped


def _count_lowering(
    report: NotchReport,
    *,
    original: np.ndarray,
    out: np.ndarray,
    valid: np.ndarray,
    capped: set[tuple[int, int]],
) -> np.ndarray:
    """Write the lowering statistics into *report*, return the mask of the lowered pixels."""
    lowering = original - out
    moved = valid & (lowering > _LOWERING_TOLERANCE_M)
    report.pixels_lowered = int(moved.sum())
    if report.pixels_lowered:
        report.max_lowering_m = float(lowering[moved].max())
        report.median_lowering_m = float(np.median(lowering[moved]))
    report.capped_pixels = len(capped)
    return moved


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
    """Plan every crossing, moving each bed end past the embankments of its neighbors.

    A first pass reads the ends at *bed_reach_m*. A second reads them again past
    the spans the first found on the other crossings, which moves the spans, and
    so on until they hold still. A crossing whose span does not settle, or whose
    ends cannot get out of its neighbors, is skipped: it would be cut against
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
    chain is read beyond the embankments of the neighboring crossings.
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
