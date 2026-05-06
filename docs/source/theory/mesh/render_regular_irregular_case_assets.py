"""Render regular-vs-irregular mesh comparisons from committed mesh bundles."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection, PolyCollection
from shapely import prepared
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union


REPO_ROOT = Path(__file__).resolve().parents[5]
STATIC_DIR = REPO_ROOT / "docs" / "readthedocs" / "source" / "_static" / "scientific" / "mesh" / "regular_irregular_cases"
SUMMARY_PATH = STATIC_DIR / "regular_irregular_case_summary.json"


@dataclass(frozen=True)
class MeshCase:
    slug: str
    title: str
    bundle_path: Path
    max_plot_cells: int | None = None


CASES = (
    MeshCase(
        slug="s3_10km2_outlet_1_rivers_only",
        title="10 km2 Strahler-3 outlet 1, rivers only",
        bundle_path=REPO_ROOT
        / "examples"
        / "projects"
        / "07_mesh_gallery"
        / "10km2"
        / "mesh_s3_10km2_outlet_1_rivers_only_buffer30"
        / "bundle",
    ),
    MeshCase(
        slug="headwater_100km2_outlet_27_rivers_only",
        title="100 km2 headwater outlet 27, rivers only",
        bundle_path=REPO_ROOT
        / "examples"
        / "projects"
        / "07_mesh_gallery"
        / "100km2"
        / "mesh_100km2_outlet_27_rivers_only_buffer30"
        / "bundle",
    ),
    MeshCase(
        slug="s3_10km2_outlet_1",
        title="10 km2 Strahler-3 outlet 1",
        bundle_path=REPO_ROOT
        / "examples"
        / "projects"
        / "07_mesh_gallery"
        / "10km2"
        / "mesh_s3_10km2_outlet_1_geology_rivers_buffer30"
        / "bundle",
    ),
    MeshCase(
        slug="headwater_100km2_outlet_27_floor200",
        title="100 km2 headwater outlet 27, floor 200 m",
        bundle_path=REPO_ROOT
        / "examples"
        / "projects"
        / "07_mesh_gallery"
        / "100km2"
        / "mesh_headwater_100km2_outlet_27_geology_rivers_buffer30_floor200_target200"
        / "bundle",
    ),
    MeshCase(
        slug="headwater_100km2_outlet_27_default",
        title="100 km2 headwater outlet 27, default",
        bundle_path=REPO_ROOT
        / "examples"
        / "projects"
        / "07_mesh_gallery"
        / "100km2"
        / "mesh_headwater_100km2_outlet_27_geology_rivers_buffer30"
        / "bundle",
    ),
)


def _load_nodes(bundle_path: Path) -> pd.DataFrame:
    nodes = pd.read_csv(bundle_path / "nodes.csv")
    return nodes.set_index("node_id")


def _cell_node_ids(row: pd.Series) -> list[int]:
    ids = [int(row["n0"]), int(row["n1"]), int(row["n2"])]
    if "n3" in row and not pd.isna(row["n3"]):
        ids.append(int(row["n3"]))
    return ids


def _cell_polygons(nodes: pd.DataFrame, cells: pd.DataFrame) -> list[np.ndarray]:
    polygons: list[np.ndarray] = []
    for _, row in cells.iterrows():
        ids = _cell_node_ids(row)
        coords = nodes.loc[ids, ["x", "y"]].to_numpy(float)
        polygons.append(coords)
    return polygons


def _domain_from_polygons(polygons: list[np.ndarray]) -> Polygon:
    shapely_polygons = [Polygon(coords) for coords in polygons]
    return unary_union(shapely_polygons).buffer(0)


def _count_regular_cells(domain: Polygon, dx: float) -> int:
    minx, miny, maxx, maxy = domain.bounds
    xs = np.arange(minx + dx / 2, maxx, dx)
    ys = np.arange(miny + dx / 2, maxy, dx)
    prepared_domain = prepared.prep(domain)
    count = 0
    for y in ys:
        for x in xs:
            if prepared_domain.covers(Point(float(x), float(y))):
                count += 1
    return count


def _find_regular_cell_size(domain: Polygon, target_count: int) -> float:
    dx0 = math.sqrt(domain.area / target_count)
    lo = dx0 * 0.35
    hi = dx0 * 2.2
    best_dx = dx0
    best_error = abs(_count_regular_cells(domain, dx0) - target_count)
    for _ in range(28):
        mid = (lo + hi) / 2
        count = _count_regular_cells(domain, mid)
        error = abs(count - target_count)
        if error < best_error:
            best_dx = mid
            best_error = error
        if count > target_count:
            lo = mid
        else:
            hi = mid
    return best_dx


def _regular_cell_polygons(domain: Polygon, dx: float) -> list[np.ndarray]:
    minx, miny, maxx, maxy = domain.bounds
    xs = np.arange(minx, maxx, dx)
    ys = np.arange(miny, maxy, dx)
    prepared_domain = prepared.prep(domain)
    polygons: list[np.ndarray] = []
    for y in ys:
        for x in xs:
            center = Point(float(x + dx / 2), float(y + dx / 2))
            if prepared_domain.covers(center):
                polygons.append(
                    np.array(
                        [
                            [x, y],
                            [x + dx, y],
                            [x + dx, y + dx],
                            [x, y + dx],
                        ],
                        dtype=float,
                    )
                )
    return polygons


def _constraint_segments(nodes: pd.DataFrame, bundle_path: Path) -> tuple[list[np.ndarray], int]:
    edges = pd.read_csv(bundle_path / "edges.csv")
    river_segments: list[np.ndarray] = []
    geology_change_edge_count = 0
    for _, row in edges.iterrows():
        coords = nodes.loc[[int(row["node_a"]), int(row["node_b"])], ["x", "y"]].to_numpy(float)
        is_river = str(row.get("is_river", "")).lower() == "true"
        geology_a = str(row.get("geology_a_key", ""))
        geology_b = str(row.get("geology_b_key", ""))
        if is_river:
            river_segments.append(coords)
        elif geology_b and geology_b != "nan" and geology_a != geology_b:
            geology_change_edge_count += 1
    return river_segments, geology_change_edge_count


def _add_mesh(
    ax: plt.Axes,
    polygons: list[np.ndarray],
    *,
    edgecolor: str,
    linewidth: float,
    max_cells: int | None = None,
) -> None:
    plot_polygons = polygons
    if max_cells is not None and len(polygons) > max_cells:
        step = max(1, len(polygons) // max_cells)
        plot_polygons = polygons[::step]
    collection = PolyCollection(
        plot_polygons,
        facecolors="none",
        edgecolors=edgecolor,
        linewidths=linewidth,
        alpha=0.78,
        zorder=1,
    )
    ax.add_collection(collection)


def _add_constraints(ax: plt.Axes, river_segments: list[np.ndarray]) -> None:
    if river_segments:
        # Draw a light casing first so the river trace remains continuous when
        # it crosses dense mesh edges.
        ax.add_collection(
            LineCollection(
                river_segments,
                colors="#fffdf5",
                linewidths=3.0,
                alpha=0.98,
                zorder=5,
                capstyle="round",
                joinstyle="round",
            )
        )
        ax.add_collection(
            LineCollection(
                river_segments,
                colors="#0072b2",
                linewidths=1.45,
                alpha=0.98,
                zorder=6,
                capstyle="round",
                joinstyle="round",
            )
        )


def _plot_case(case: MeshCase) -> dict[str, object]:
    nodes = _load_nodes(case.bundle_path)
    cells = pd.read_csv(case.bundle_path / "cells.csv")
    irregular_polygons = _cell_polygons(nodes, cells)
    domain = _domain_from_polygons(irregular_polygons)
    target_count = len(irregular_polygons)
    dx = _find_regular_cell_size(domain, target_count)
    regular_polygons = _regular_cell_polygons(domain, dx)
    river_segments, geology_change_edge_count = _constraint_segments(nodes, case.bundle_path)

    fig, axes = plt.subplots(1, 2, figsize=(15, 7.2), constrained_layout=False)
    panels = [
        (axes[0], irregular_polygons, f"Irregular Gmsh mesh\n{target_count:,} triangular cells".replace(",", " "), "#334b5b", 0.32),
        (axes[1], regular_polygons, f"Generated regular grid\n{len(regular_polygons):,} active square cells".replace(",", " "), "#394f36", 0.32),
    ]
    minx, miny, maxx, maxy = domain.bounds
    pad = max(maxx - minx, maxy - miny) * 0.03
    for ax, polygons, title, color, linewidth in panels:
        _add_mesh(ax, polygons, edgecolor=color, linewidth=linewidth, max_cells=case.max_plot_cells)
        _add_constraints(ax, river_segments)
        ax.set_aspect("equal")
        ax.set_xlim(minx - pad, maxx + pad)
        ax.set_ylim(miny - pad, maxy + pad)
        ax.set_title(title, fontsize=12)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_facecolor("#fbfcf9")

    fig.subplots_adjust(left=0.03, right=0.99, top=0.84, bottom=0.08, wspace=0.08)
    fig.suptitle(case.title, fontsize=16, fontweight="bold")
    fig.text(
        0.5,
        0.035,
        "Blue with light casing = river constraints from the irregular bundle. Regular cells are selected by centre inclusion on the same reconstructed support.",
        ha="center",
        fontsize=9,
    )
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    output = STATIC_DIR / f"{case.slug}_regular_vs_irregular.png"
    fig.savefig(output, dpi=190)
    plt.close(fig)
    return {
        "slug": case.slug,
        "title": case.title,
        "figure": output.relative_to(REPO_ROOT).as_posix(),
        "bundle": case.bundle_path.relative_to(REPO_ROOT).as_posix(),
        "irregular_cells": target_count,
        "regular_cells": len(regular_polygons),
        "regular_dx_m": dx,
        "regular_cell_count_error": len(regular_polygons) - target_count,
        "river_edges": len(river_segments),
        "geology_change_edges_from_cells": geology_change_edge_count,
    }


def main() -> None:
    summaries = [_plot_case(case) for case in CASES]
    SUMMARY_PATH.write_text(json.dumps({"cases": summaries}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
