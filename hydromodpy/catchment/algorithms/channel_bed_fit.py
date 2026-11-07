"""Least-change fit of the channel bed along the D8 tree of the channel pixels.

The bed is pooled where it climbs downstream, so that it never rises along the
flow, and cut at the declared barriers so that a weir keeps its step.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import shapely
from rasterio.features import geometry_mask
from rasterio.transform import xy
from shapely.geometry.base import BaseGeometry

from hydromodpy.catchment.algorithms.bed_regularization import (
    BedRegularization,
    regularize_bed_on_tree,
)
from hydromodpy.catchment.terrain.port import D8_WBT_OFFSETS

__all__ = [
    "BedReport",
    "PixelTree",
    "pixel_tree",
    "regularize_channel_bed",
]


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
    root. The edge length is the pointer step in meters. Receivers are found
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
    """Return *top* with its channel pixels regularized, and the report.

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
