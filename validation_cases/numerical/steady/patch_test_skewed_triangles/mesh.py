"""Skewed triangle strip of the patch test.

A 100 x 40 m strip of 10 m squares. The nodes of the inner columns are moved
by up to 3 m in x and 2.5 m in y, then every quad is cut along the same
diagonal: the triangles are skewed and not isosceles, so the line between two
centroids is not normal to the edge they share. The columns at x = 0, 10, 90
and 100 m stay straight: every triangle that owns a west edge has its centroid
at x = 10 / 3 m, every one that owns an east edge at x = 100 - 10 / 3 m.

Run as a module to rewrite the committed bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from validation_cases.shared.gmsh_irregular_strip import write_gmsh22_triangle_mesh_from_bundle_csv

LENGTH_X_M = 100.0
WIDTH_Y_M = 40.0
NX = 10
NY = 4
Z_TOP_M = 1000.0
Z_BOTTOM_M = -1000.0
HYDRAULIC_CONDUCTIVITY_M_S = 1.0e-4
STORAGE_COEFFICIENT = 0.1
MAX_SHIFT_X_M = 3.0
MAX_SHIFT_Y_M = 2.5
BUNDLE_DIR = (
    Path(__file__).resolve().parents[3]
    / "shared"
    / "mesh_bundles"
    / "patch_test_skewed_triangles_100x40"
)


def _shift(i: int, j: int, a: int, b: int) -> float:
    """Return a fixed shift in [-1, 1] for node (i, j)."""
    return float(((a * i + b * j) % 5) - 2) / 2.0


def skewed_strip_nodes_and_triangles() -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """Return the node coordinates and the triangles of the strip."""
    dx = LENGTH_X_M / NX
    dy = WIDTH_Y_M / NY
    nodes = np.zeros(((NX + 1) * (NY + 1), 2), dtype=float)
    for j in range(NY + 1):
        for i in range(NX + 1):
            x_m = i * dx
            y_m = j * dy
            if 2 <= i <= NX - 2:
                x_m += MAX_SHIFT_X_M * _shift(i, j, 3, 5)
                if 1 <= j <= NY - 1:
                    y_m += MAX_SHIFT_Y_M * _shift(i, j, 2, 3)
            nodes[j * (NX + 1) + i] = (x_m, y_m)
    triangles: list[tuple[int, int, int]] = []
    for j in range(NY):
        for i in range(NX):
            n00 = j * (NX + 1) + i
            n10, n01, n11 = n00 + 1, n00 + NX + 1, n00 + NX + 2
            triangles += [(n00, n10, n11), (n00, n11, n01)]
    return nodes, triangles


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def write_skewed_strip_bundle(bundle_dir: Path = BUNDLE_DIR) -> Path:
    """Write the mesh bundle of the strip and return its folder."""
    bundle_dir = Path(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    nodes, triangles = skewed_strip_nodes_and_triangles()
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": "EPSG:2154",
                "files": {
                    "mesh": "mesh_2d.msh",
                    "nodes": "nodes.csv",
                    "cells": "cells.csv",
                    "edges": "edges.csv",
                    "cell_geology_fractions": "cell_geology_fractions.csv",
                    "metadata": "metadata.json",
                    "mesh_summary": "mesh_summary.json",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "mesh_summary.json").write_text(
        json.dumps(
            {
                "constraints_mode": "geology_only",
                "generator": "patch_test_skewed_triangles",
                "n_cells": len(triangles),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        bundle_dir / "nodes.csv",
        "node_id,x,y,z_top,z_bottom",
        [
            f"{node_id},{x_m:.6f},{y_m:.6f},{Z_TOP_M:.6f},{Z_BOTTOM_M:.6f}"
            for node_id, (x_m, y_m) in enumerate(nodes)
        ],
    )
    cell_rows: list[str] = []
    edges: dict[tuple[int, int], list[int]] = {}
    for cell_id, triangle in enumerate(triangles):
        points = nodes[list(triangle)]
        centroid = points.mean(axis=0)
        area = 0.5 * abs(
            (points[1, 0] - points[0, 0]) * (points[2, 1] - points[0, 1])
            - (points[2, 0] - points[0, 0]) * (points[1, 1] - points[0, 1])
        )
        cell_rows.append(
            f"{cell_id},triangle,{triangle[0]},{triangle[1]},{triangle[2]},,"
            f"{centroid[0]:.6f},{centroid[1]:.6f},{area:.6f},"
            f"{Z_TOP_M:.6f},{Z_TOP_M:.6f},{Z_BOTTOM_M:.6f},{Z_BOTTOM_M:.6f},1,zone_1,"
            f"{HYDRAULIC_CONDUCTIVITY_M_S:.12g},{STORAGE_COEFFICIENT:.12g}"
        )
        for a, b in ((0, 1), (1, 2), (2, 0)):
            key = tuple(sorted((triangle[a], triangle[b])))
            edges.setdefault(key, []).append(cell_id)
    _write_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,"
        "z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,"
        "hydraulic_conductivity_m_s,storage_coefficient",
        cell_rows,
    )
    _write_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        [f"{cell_id},zone_1,1.0" for cell_id in range(len(triangles))],
    )
    edge_rows = []
    for edge_id, ((node_a, node_b), owners) in enumerate(edges.items()):
        length_m = float(np.linalg.norm(nodes[node_b] - nodes[node_a]))
        cell_b = "" if len(owners) == 1 else str(owners[1])
        kind = "boundary" if len(owners) == 1 else "internal"
        geology_b = "" if len(owners) == 1 else "zone_1"
        edge_rows.append(
            f"{edge_id},{node_a},{node_b},{owners[0]},{cell_b},{length_m:.6f},{kind},false,"
            f"zone_1,{geology_b}"
        )
    _write_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,"
        "geology_a_key,geology_b_key",
        edge_rows,
    )
    write_gmsh22_triangle_mesh_from_bundle_csv(bundle_dir)
    return bundle_dir


if __name__ == "__main__":
    print(write_skewed_strip_bundle())
