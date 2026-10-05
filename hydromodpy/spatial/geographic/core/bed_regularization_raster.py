"""The channel bed of the ground G, regularised on the pixels of the channel tree A.

The ground G is read along A, the generated channel network of the run, and
fitted by :func:`~hydromodpy.core.bed_regularization.regularize_bed_on_tree`:
the bed closest to G that never rises downstream. The fit runs on the whole
DEM grid, every A pixel with its receiver on the D8 pointer of the routing
DEM R, and writes the regularised copy of G next to it
(:data:`GROUND_BED_FILENAME`). The model-top clips and the SFR bed both read
that copy, so DRN and SFR see one bed. The routing DEM, A, the catchment and
the mesh are built before and never read it.

The pixel tree: every A pixel of the grid, its receiver the D8 pointer of R, a
root where the pointer leaves A or the grid. The pixels inside a declared lake
are left out: they keep G, the edge entering a lake is a root and the reach
below its outlet is a tree of its own. The pixels a crossing notch lowered
(the footprint the notch wrote) are gaps. A declared weir or dam of the
crossings file, snapped to the nearest A pixel within the crossings
``snap_radius`` and not inside a declared lake, cuts both edges of that pixel.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import shapely
from rasterio.features import geometry_mask
from rasterio.transform import xy
from rasterio.windows import Window
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.bed_regularization import BedRegularization, regularize_bed_on_tree
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.geographic.core.ground_corrections import (
    ground_dem_path_from_config,
    notch_enabled,
    notch_footprint_path,
)
from hydromodpy.spatial.geographic.core.lake_enforcement import lakes_from_config
from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS

logger = get_logger(__name__)

GROUND_BED_FILENAME = "dem_ground_bed.tif"
"""The ground with its channel bed regularised, next to the ground."""

GROUND_BED_REPORT_FILENAME = "dem_ground_bed.json"
"""What the fit found and did, next to the regularised ground."""

BED_SUFFIX = "_bed"
"""A clip of the regularised ground is the clip of G's file name with this before the extension."""

_BARRIER_KINDS = ("weir", "dam")

_ALIGN_TOL_PX = 1.0e-3
"""Largest misalignment, in pixels, between two rasters read on one grid."""

_STREAMS_FULL_NAME = "dem_streams_full.tif"
_STREAMS_PRUNED_FULL_NAME = "dem_streams_pruned_full.tif"


def bed_regularization_enabled(config: object) -> bool:
    """Whether ``[geographic.bed_regularization]`` is on."""
    return bool(getattr(getattr(config, "bed_regularization", None), "enabled", False))


def bed_dem_path(clip_path: str | Path) -> Path:
    """Where the clip of the regularised ground matching the clip *clip_path* of G is written."""
    path = Path(clip_path)
    return path.with_name(f"{path.stem}{BED_SUFFIX}{path.suffix}")


def ground_bed_path(setup: object) -> Path:
    """Where the regularised ground is written."""
    return Path(setup.paths.correcflow_path) / GROUND_BED_FILENAME


def ground_bed_report_path(setup: object) -> Path:
    """Where the report of the fit is written."""
    return Path(setup.paths.correcflow_path) / GROUND_BED_REPORT_FILENAME


def top_dem_path_from_config(config: object, setup: object) -> str:
    """The full-extent DEM the model top and the SFR bed read, without building anything.

    The regularised ground when the option is on, else the ground G.
    """
    if bed_regularization_enabled(config):
        return str(ground_bed_path(setup))
    return ground_dem_path_from_config(config, setup)


@dataclass(frozen=True)
class PixelTree:
    """The channel pixels of a grid as a tree: one receiver per pixel, ``-1`` at a root."""

    rows: np.ndarray
    cols: np.ndarray
    receiver: np.ndarray
    edge_length: np.ndarray

    @property
    def size(self) -> int:
        return int(self.rows.size)


def pixel_tree(channel: np.ndarray, d8: np.ndarray, *, res_x: float, res_y: float) -> PixelTree:
    """The tree of the *channel* pixels along the *d8* pointer (WhiteboxTools codes).

    A pixel whose pointer leaves the channel, the grid, or carries no code is a
    root. The edge length is the pointer step in metres. Receivers are found
    by a search on the sorted flat indices of the channel pixels, so a DEM
    grid of any size costs memory on its channel pixels only.
    """
    n_rows, n_cols = channel.shape
    rows, cols = np.nonzero(channel)
    flat = rows.astype(np.int64) * n_cols + cols  # sorted: np.nonzero is row-major
    receiver = np.full(rows.size, -1, dtype=np.int64)
    length = np.zeros(rows.size)
    codes = d8[rows, cols]
    for code, (d_row, d_col) in D8_WBT_OFFSETS.items():
        sel = np.flatnonzero(codes == code)
        if sel.size == 0:
            continue
        to_row, to_col = rows[sel] + d_row, cols[sel] + d_col
        inside = (to_row >= 0) & (to_row < n_rows) & (to_col >= 0) & (to_col < n_cols)
        to_flat = to_row.astype(np.int64) * n_cols + to_col
        pos = np.minimum(np.searchsorted(flat, to_flat), max(flat.size - 1, 0))
        found = inside & (flat[pos] == to_flat)
        receiver[sel] = np.where(found, pos, -1)
        length[sel] = math.hypot(d_row * res_y, d_col * res_x)
    length[receiver < 0] = 0.0
    return PixelTree(rows, cols, receiver, length)


@dataclass
class BedReport:
    """What the fit found and did, as the JSON document and the INFO line."""

    parameters: dict[str, Any]
    channel_pixels: int = 0
    lake_pixels: int = 0
    gap_pixels: int = 0
    cuts: list[dict[str, Any]] = field(default_factory=list)
    barriers_skipped: dict[str, int] = field(default_factory=dict)
    raised: int = 0
    lowered: int = 0
    median_change_m: float = 0.0
    max_change_m: float = 0.0
    mean_bias_m: float = 0.0
    violations_before: int = 0
    rises_after_fit: int = 0
    violations_after: int = 0
    min_drop_max_lift_m: float = 0.0
    closing_raised: int = 0
    closing_max_raise_m: float = 0.0
    climbs_at_cuts: int = 0
    confluence_blocks: list[dict[str, Any]] = field(default_factory=list)

    def to_document(self) -> dict[str, Any]:
        """The JSON form."""
        return {
            "parameters": self.parameters,
            "channel_pixels": self.channel_pixels,
            "lake_pixels": self.lake_pixels,
            "gap_pixels": self.gap_pixels,
            "cut_pixels": len(self.cuts),
            "cuts": self.cuts,
            "barriers_skipped": self.barriers_skipped,
            "raised": self.raised,
            "lowered": self.lowered,
            "median_change_m": self.median_change_m,
            "max_change_m": self.max_change_m,
            "mean_bias_m": self.mean_bias_m,
            "violations_before": self.violations_before,
            "rises_after_fit": self.rises_after_fit,
            "violations_after": self.violations_after,
            "min_drop_max_lift_m": self.min_drop_max_lift_m,
            "closing_raised": self.closing_raised,
            "closing_max_raise_m": self.closing_max_raise_m,
            "climbs_at_cuts": self.climbs_at_cuts,
            "confluence_blocks": self.confluence_blocks,
        }

    def info_line(self) -> str:
        """The one line the log carries."""
        largest = (
            f", largest {self.confluence_blocks[0]['amplitude_m']:.2f} m"
            if self.confluence_blocks
            else ""
        )
        return (
            f"Bed regularisation: {self.channel_pixels} channel pixel(s) "
            f"({self.gap_pixels} gap(s), {len(self.cuts)} cut(s), {self.lake_pixels} in "
            f"lakes left out); {self.raised} raised, {self.lowered} lowered, median "
            f"{self.median_change_m:.2f} m, max {self.max_change_m:.2f} m, bias "
            f"{self.mean_bias_m:+.3f} m; rises {self.violations_before} -> "
            f"{self.rises_after_fit}; minimum drop lifts up to "
            f"{self.min_drop_max_lift_m:.3f} m and leaves {self.violations_after} edge(s) "
            f"short, closing pass raised {self.closing_raised} node(s) by up to "
            f"{self.closing_max_raise_m:.3f} m; {self.climbs_at_cuts} climb(s) left at "
            f"cuts; {len(self.confluence_blocks)} pooled block(s) at confluences{largest}."
        )


def regularize_channel_bed(
    top: np.ndarray,
    *,
    valid: np.ndarray,
    transform: Any,
    channel: np.ndarray,
    d8: np.ndarray,
    gap: np.ndarray | None = None,
    barriers: Sequence[tuple[str, str, float, BaseGeometry]] = (),
    lakes: Sequence[BaseGeometry] = (),
    snap_radius_m: float = 30.0,
    min_slope: float = 1.0e-4,
    report: BedReport | None = None,
) -> tuple[np.ndarray, BedReport]:
    """Return *top* with its channel pixels regularised, and the report.

    The raster half of the fit, free of any file. *channel*, *d8* and *gap* sit
    on the grid of *top*; only pixels both *channel* and *valid*, and outside
    every polygon of *lakes*, enter the tree. *barriers* are the declared weirs
    and dams as ``(kind, name, drop_m, geometry)``.
    """
    report = report if report is not None else BedReport(parameters={})
    res_x, res_y = abs(float(transform.a)), abs(float(transform.e))
    on_tree = channel & valid
    if lakes:
        in_lake = geometry_mask(lakes, out_shape=top.shape, transform=transform, invert=True)
        report.lake_pixels = int(np.count_nonzero(on_tree & in_lake))
        on_tree &= ~in_lake
    tree = pixel_tree(on_tree, d8, res_x=res_x, res_y=res_y)
    out = np.array(top, copy=True)
    report.channel_pixels = tree.size
    if tree.size == 0:
        return out, report

    values = top[tree.rows, tree.cols].astype(float)
    is_gap = (
        np.zeros(tree.size, dtype=bool)
        if gap is None
        else np.asarray(gap[tree.rows, tree.cols], dtype=bool)
    )
    xs, ys = xy(transform, tree.rows, tree.cols)
    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    cut, cut_rows = _cuts(xs, ys, tree.receiver, barriers, lakes, snap_radius_m, report)
    fit = regularize_bed_on_tree(
        values,
        tree.receiver,
        tree.edge_length,
        gap=is_gap,
        cut=cut,
        min_slope=min_slope,
    )
    out[tree.rows, tree.cols] = fit.values.astype(out.dtype)

    report.gap_pixels = int(is_gap.sum())
    _fill_figures(report, fit)
    report.cuts = [
        {
            **row,
            "climb_m": (
                None
                if tree.receiver[node] < 0
                else max(float(fit.values[tree.receiver[node]] - fit.values[node]), 0.0)
            ),
        }
        for node, row in cut_rows
    ]
    report.confluence_blocks = _confluence_blocks(fit, tree, cut, xs, ys)
    return out, report


def _fill_figures(report: BedReport, fit: BedRegularization) -> None:
    report.raised = fit.raised
    report.lowered = fit.lowered
    report.median_change_m = fit.median_change_m
    report.max_change_m = fit.max_change_m
    report.mean_bias_m = fit.mean_bias_m
    report.violations_before = fit.violations_before
    report.rises_after_fit = fit.rises_after_fit
    report.violations_after = fit.violations_after
    report.min_drop_max_lift_m = fit.min_drop_max_lift_m
    report.closing_raised = fit.closing_raised
    report.closing_max_raise_m = fit.closing_max_raise_m
    report.climbs_at_cuts = fit.climbs_at_cuts


def _skip(report: BedReport, reason: str) -> None:
    report.barriers_skipped[reason] = report.barriers_skipped.get(reason, 0) + 1


def _cuts(
    xs: np.ndarray,
    ys: np.ndarray,
    receiver: np.ndarray,
    barriers: Sequence[tuple[str, str, float, BaseGeometry]],
    lakes: Sequence[BaseGeometry],
    snap_radius_m: float,
    report: BedReport,
) -> tuple[np.ndarray, list[tuple[int, dict[str, Any]]]]:
    """Cut the tree around the channel pixel nearest each barrier within the snap radius.

    Both edges of the snapped pixel are cut, the one into it and the one out
    of it, so a snap on the crest or on the pond-side foot leaves the pond its
    own tree and the crest its own value.
    """
    cut = np.zeros(xs.size, dtype=bool)
    rows: list[tuple[int, dict[str, Any]]] = []
    if not barriers:
        return cut, rows
    centres = shapely.points(xs, ys)
    snapped: set[int] = set()
    for kind, name, drop_m, geometry in barriers:
        if any(lake.contains(geometry) for lake in lakes):
            _skip(report, "in_lake")
            continue
        x0, y0, x1, y1 = geometry.bounds
        near = np.flatnonzero(
            (xs >= x0 - snap_radius_m)
            & (xs <= x1 + snap_radius_m)
            & (ys >= y0 - snap_radius_m)
            & (ys <= y1 + snap_radius_m)
        )
        distance = shapely.distance(centres[near], geometry) if near.size else np.empty(0)
        if near.size == 0 or float(distance.min()) > snap_radius_m:
            _skip(report, "off_channel")
            continue
        node = int(near[int(np.argmin(distance))])
        if node in snapped:
            _skip(report, "same_pixel")
            continue
        snapped.add(node)
        cut[node] = True
        cut[receiver == node] = True
        rows.append(
            (
                node,
                {
                    "kind": kind,
                    "name": name,
                    "drop_m": None if not math.isfinite(drop_m) else float(drop_m),
                    "x": float(xs[node]),
                    "y": float(ys[node]),
                },
            )
        )
    return cut, rows


def _confluence_blocks(
    fit: BedRegularization,
    tree: PixelTree,
    cut: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
) -> list[dict[str, Any]]:
    """The pooled blocks at a confluence, largest change first.

    The position of a block is its confluence pixels (two givers or more, one
    of them in the block) and its exit, the member whose receiver leaves the
    block.
    """
    blocks: list[dict[str, Any]] = []
    down = np.where(cut, -1, tree.receiver)
    edges = np.flatnonzero(down >= 0)
    all_givers = np.bincount(down[edges], minlength=tree.size)
    for block in fit.blocks:
        if not block.holds_confluence:
            continue
        nodes = block.nodes
        member = np.zeros(tree.size, dtype=bool)
        member[nodes] = True
        inner = nodes[(down[nodes] >= 0) & member[np.maximum(down[nodes], 0)]]
        inner_givers = np.bincount(down[inner], minlength=tree.size)
        confluences = nodes[(all_givers[nodes] >= 2) & (inner_givers[nodes] >= 1)]
        exits = nodes[(down[nodes] < 0) | ~member[np.maximum(down[nodes], 0)]]
        exit_node = int(exits[0]) if exits.size else int(nodes[0])
        blocks.append(
            {
                "pixels": int(nodes.size),
                "amplitude_m": block.amplitude_m,
                "max_raise_m": block.max_raise_m,
                "max_lowering_m": block.max_lowering_m,
                "exit": [float(xs[exit_node]), float(ys[exit_node])],
                "confluences": [[float(xs[n]), float(ys[n])] for n in confluences],
            }
        )
    return blocks


def regularized_ground_from_config(
    config: object,
    setup: object,
    *,
    d8_tif: str | Path,
    river_products: object,
) -> Path:
    """Fit the bed on the whole ground G, write the regularised ground and its report.

    Returns the path of the regularised ground, :func:`ground_bed_path`. It is
    G byte for byte off the channel tree, on G's grid and in G's data type.
    """
    section = config.bed_regularization
    ground = Path(ground_dem_path_from_config(config, setup))
    with rasterio.open(ground) as src:
        top = src.read(1)
        profile = src.profile.copy()
        transform = src.transform
        nodata = src.nodata
        shape = (src.height, src.width)
    valid = _valid(top, nodata)

    channel_tif = _channel_raster(config, setup, river_products)
    channel_raw, channel_nodata = _read_on_grid(channel_tif, transform, shape, fill=0.0)
    channel = _valid(channel_raw, channel_nodata) & (channel_raw > 0)
    del channel_raw
    d8_raw, d8_nodata = _read_on_grid(d8_tif, transform, shape, fill=0.0)
    d8 = np.where(_valid(d8_raw, d8_nodata), d8_raw, 0)
    del d8_raw
    gap = _notch_footprint(config, setup, transform, shape)
    barriers, crossings_path = _barriers_from_config(config, setup)
    lakes = (
        lakes_from_config(config.enforce_lakes, setup)
        if bool(getattr(getattr(config, "enforce_lakes", None), "enabled", False))
        else []
    )
    snap_radius_m = float(config.crossings.snap_radius)
    report = BedReport(
        parameters={
            "min_slope": float(section.min_slope),
            "snap_radius_m": snap_radius_m,
            "ground": str(ground),
            "channel_raster": str(channel_tif),
            "d8_pointer": str(d8_tif),
            "crossings_path": None if crossings_path is None else str(crossings_path),
            "notch_footprint": gap is not None,
            "lakes": len(lakes),
        }
    )
    fitted, report = regularize_channel_bed(
        top,
        valid=valid,
        transform=transform,
        channel=channel,
        d8=d8,
        gap=gap,
        barriers=barriers,
        lakes=lakes,
        snap_radius_m=snap_radius_m,
        min_slope=float(section.min_slope),
        report=report,
    )

    out = ground_bed_path(setup)
    out.parent.mkdir(parents=True, exist_ok=True)
    for key in ("blockxsize", "blockysize"):
        profile.pop(key, None)
    profile.update(driver="GTiff", compress="lzw", tiled=False)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(fitted, 1)
    ground_bed_report_path(setup).write_text(
        json.dumps(report.to_document(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    logger.info(report.info_line())
    return out


def _valid(array: np.ndarray, nodata: float | None) -> np.ndarray:
    valid = np.isfinite(array)
    if nodata is not None and not (isinstance(nodata, float) and math.isnan(nodata)):
        valid &= array != nodata
    return valid


def _channel_raster(config: object, setup: object, river_products: object) -> Path:
    """The full-extent raster of A: its link ids, else its streams (pruned when pruning)."""
    link = getattr(river_products, "stream_link_id_full_tif", None)
    if link and Path(link).exists():
        return Path(link)
    correcflow = Path(setup.paths.correcflow_path)
    name = (
        _STREAMS_PRUNED_FULL_NAME
        if bool(config.river_network.prune_short_streams)
        else _STREAMS_FULL_NAME
    )
    path = correcflow / name
    if not path.exists():
        raise FileNotFoundError(
            f"[geographic.bed_regularization] reads the channel tree A from {path.name} (or "
            f"the full-extent stream-link raster) in {correcflow}, and neither exists."
        )
    return path


def _read_on_grid(
    path: str | Path, transform: Any, shape: tuple[int, int], *, fill: float
) -> tuple[np.ndarray, float | None]:
    """Read *path* on the grid of *transform* and *shape*, *fill* outside its extent.

    The full-extent rasters of one geographic run share the DEM grid, so this
    is a window read; a raster off that grid is refused.
    """
    with rasterio.open(path) as src:
        src_t = src.transform
        if not (
            math.isclose(src_t.a, transform.a, rel_tol=1e-6)
            and math.isclose(src_t.e, transform.e, rel_tol=1e-6)
        ):
            raise ValueError(f"{path} has another cell size than the ground.")
        col = (transform.c - src_t.c) / src_t.a
        row = (transform.f - src_t.f) / src_t.e
        if abs(col - round(col)) > _ALIGN_TOL_PX or abs(row - round(row)) > _ALIGN_TOL_PX:
            raise ValueError(f"{path} is not aligned with the pixels of the ground.")
        window = Window(round(col), round(row), shape[1], shape[0])
        data = src.read(1, window=window, boundless=True, fill_value=fill)
        return data, src.nodata


def _notch_footprint(
    config: object, setup: object, transform: Any, shape: tuple[int, int]
) -> np.ndarray | None:
    """The pixels the crossing notch lowered, as the notch wrote them."""
    if not notch_enabled(config):
        return None
    path = notch_footprint_path(setup)
    if not path.exists():
        return None
    footprint, _ = _read_on_grid(path, transform, shape, fill=0.0)
    return footprint > 0


def _barriers_from_config(
    config: object, setup: object
) -> tuple[list[tuple[str, str, float, BaseGeometry]], Path | None]:
    """The weirs and dams of the crossings file, in the project CRS."""
    raw = getattr(config.crossings, "path", None)
    if raw is None:
        logger.info(
            "Bed regularisation: no crossings file, so no declared weir or dam cuts the "
            "channel tree. Declare [[data.crossings.sources]] or "
            "[geographic.crossings] path to keep their drops."
        )
        return [], None
    path = Path(raw)
    if not path.exists():
        raise FileNotFoundError(f"geographic.crossings.path points to nothing: {path}")
    import geopandas as gpd

    frame = gpd.read_file(path)
    if "kind" not in frame.columns:
        raise ValueError(f"geographic.crossings.path {path} holds no 'kind' column.")
    if frame.crs is None:
        raise ValueError(f"geographic.crossings.path {path} carries no CRS.")
    crs_project = getattr(setup, "crs_project", None)
    if crs_project is not None:
        frame = frame.to_crs(crs_project)
    kinds = frame["kind"].astype(str).str.strip().str.lower()
    names = frame["name"].astype(str) if "name" in frame.columns else None
    drops = frame["drop_m"] if "drop_m" in frame.columns else None
    barriers: list[tuple[str, str, float, BaseGeometry]] = []
    for position, (kind, geometry) in enumerate(zip(kinds, frame.geometry, strict=True)):
        if kind not in _BARRIER_KINDS or geometry is None or geometry.is_empty:
            continue
        name = "" if names is None else str(names.iloc[position])
        drop = math.nan if drops is None else _float_or_nan(drops.iloc[position])
        barriers.append((kind, name, drop, geometry))
    return barriers, path


def _float_or_nan(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan


__all__ = (
    "BED_SUFFIX",
    "GROUND_BED_FILENAME",
    "GROUND_BED_REPORT_FILENAME",
    "BedReport",
    "PixelTree",
    "bed_dem_path",
    "bed_regularization_enabled",
    "ground_bed_path",
    "ground_bed_report_path",
    "pixel_tree",
    "regularize_channel_bed",
    "regularized_ground_from_config",
    "top_dem_path_from_config",
)
