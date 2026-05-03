"""Render small mesh-comparison SVGs used by the scientific mesh docs."""

from __future__ import annotations

import html
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "_static" / "scientific" / "mesh"
MESH_GALLERY_DIR = ROOT / "_static" / "capability_gallery" / "mesh"


def _line(x1: float, y1: float, x2: float, y2: float, klass: str = "mesh") -> str:
    return f'<line class="{klass}" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>'


def _text(x: float, y: float, value: str, klass: str = "small") -> str:
    return f'<text class="{klass}" x="{x:.2f}" y="{y:.2f}">{html.escape(value)}</text>'


def _rect(x: float, y: float, w: float, h: float, klass: str = "panel") -> str:
    return f'<rect class="{klass}" x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"/>'


def _point_grid(nx: int, ny: int, x: float, y: float, w: float, h: float) -> list[list[tuple[float, float]]]:
    points: list[list[tuple[float, float]]] = []
    for j in range(ny + 1):
        row: list[tuple[float, float]] = []
        for i in range(nx + 1):
            px = x + w * i / nx
            py = y + h * j / ny
            if 0 < i < nx and 0 < j < ny:
                jitter_x = math.sin(i * 1.9 + j * 0.7) * w / nx * 0.18
                jitter_y = math.cos(i * 1.2 - j * 1.6) * h / ny * 0.18
                px += jitter_x
                py += jitter_y
            row.append((px, py))
        points.append(row)
    return points


def _regular_grid(x: float, y: float, size: float, n: int) -> list[str]:
    lines: list[str] = [_rect(x, y, size, size, "domain")]
    step = size / n
    for i in range(1, n):
        lines.append(_line(x + i * step, y, x + i * step, y + size))
        lines.append(_line(x, y + i * step, x + size, y + i * step))
    return lines


def _irregular_triangles(x: float, y: float, size: float, n: int) -> list[str]:
    nx = n
    ny = n // 2
    points = _point_grid(nx, ny, x, y, size, size)
    lines: list[str] = [_rect(x, y, size, size, "domain")]
    for j in range(ny + 1):
        for i in range(nx):
            lines.append(_line(*points[j][i], *points[j][i + 1]))
    for i in range(nx + 1):
        for j in range(ny):
            lines.append(_line(*points[j][i], *points[j + 1][i]))
    for j in range(ny):
        for i in range(nx):
            if (i + j) % 2:
                lines.append(_line(*points[j][i + 1], *points[j + 1][i]))
            else:
                lines.append(_line(*points[j][i], *points[j + 1][i + 1]))
    return lines


def render_regular_irregular_same_counts() -> str:
    rows = [(4, 16), (8, 64), (12, 144)]
    svg: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="780" viewBox="0 0 1200 780" role="img" aria-labelledby="title desc">',
        '<title id="title">Regular and irregular meshes with identical cell counts</title>',
        '<desc id="desc">Three rows compare structured quadrilateral grids and irregular triangular meshes with identical cell counts.</desc>',
        "<style>",
        ".bg{fill:#f7f8f4}.panel{fill:#fff;stroke:#b7c0ba;stroke-width:2;rx:18}.domain{fill:#edf4f8;stroke:#435d70;stroke-width:2}.mesh{stroke:#334b5b;stroke-width:1.1}.title{font:700 27px Georgia,serif;fill:#21313a}.head{font:700 19px Georgia,serif;fill:#21313a}.small{font:14px Georgia,serif;fill:#41515d}.mono{font:13px Consolas,monospace;fill:#2d3d47}",
        "</style>",
        '<rect class="bg" width="1200" height="780"/>',
        _text(48, 56, "Same cell budget, different topology", "title"),
        _text(48, 84, "Synthetic side-by-side: regular quadrilateral grids versus irregular triangular meshes with exactly the same number of cells.", "small"),
        _text(210, 128, "Regular structured grid", "head"),
        _text(730, 128, "Irregular triangular mesh", "head"),
    ]
    for row_index, (n, cell_count) in enumerate(rows):
        y = 158 + row_index * 190
        svg.append(_rect(52, y - 30, 1096, 170, "panel"))
        svg.append(_text(78, y, f"{cell_count} cells", "head"))
        svg.append(_text(78, y + 28, f"left: {n} x {n} quads", "mono"))
        svg.append(_text(78, y + 52, f"right: {n} x {n // 2} split cells", "mono"))
        svg.extend(_regular_grid(270, y - 16, 136, n))
        svg.extend(_irregular_triangles(780, y - 16, 136, n))
    svg.append(_text(70, 735, "Interpretation: identical cell counts do not imply identical accuracy. Cell shape, topology, boundary alignment, and field transfer also matter.", "small"))
    svg.append("</svg>")
    return "\n".join(svg)


def _summary_metrics(filename: str) -> dict[str, float | int | str]:
    data = json.loads((MESH_GALLERY_DIR / filename).read_text(encoding="utf-8"))
    metrics = {metric["key"]: metric["value"] for metric in data.get("metrics", [])}
    return {
        "title": data["title"],
        "cells": int(metrics["cell_count"]),
        "nodes": int(metrics["node_count"]),
        "river_edges": int(metrics["river_edge_count"]),
        "geology_edges": int(metrics["geology_interface_edge_count"]),
    }


def render_real_mesh_cell_budget() -> str:
    cases = [
        ("10 km2", "mesh_s3_10km2_outlet_1_geology_rivers_buffer30_summary.json"),
        ("100 km2 floor 340", "mesh_headwater_100km2_outlet_27_geology_rivers_buffer30_floor340_target200_summary.json"),
        ("100 km2 floor 200", "mesh_headwater_100km2_outlet_27_geology_rivers_buffer30_floor200_target200_summary.json"),
        ("100 km2 default", "mesh_headwater_100km2_outlet_27_geology_rivers_buffer30_summary.json"),
        ("1000 km2", "mesh_1000km2_outlet_2_geology_rivers_buffer30_summary.json"),
    ]
    rows = [(label, _summary_metrics(path)) for label, path in cases]
    max_cells = max(row[1]["cells"] for row in rows)
    svg: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520" role="img" aria-labelledby="title desc">',
        '<title id="title">Cell-count balance for versioned catchment meshes</title>',
        '<desc id="desc">Horizontal bar chart comparing cell counts for selected versioned HydroModPy catchment meshes.</desc>',
        "<style>",
        ".bg{fill:#f7f8f4}.bar{fill:#6f8fa8}.bar2{fill:#b38447}.axis{stroke:#52616b;stroke-width:1}.title{font:700 27px Georgia,serif;fill:#21313a}.small{font:14px Georgia,serif;fill:#41515d}.mono{font:13px Consolas,monospace;fill:#2d3d47}.label{font:700 16px Georgia,serif;fill:#21313a}",
        "</style>",
        '<rect class="bg" width="1200" height="520"/>',
        _text(48, 56, "Cell-count balance for committed irregular catchment meshes", "title"),
        _text(48, 84, "Counts are read from the capability-gallery summary JSON files; all cases shown here are triangular Gmsh-style catchment meshes.", "small"),
    ]
    x0, y0, max_w = 280, 132, 720
    for i, (label, metrics) in enumerate(rows):
        y = y0 + i * 68
        w = max_w * metrics["cells"] / max_cells
        svg.append(_text(60, y + 22, label, "label"))
        svg.append(f'<rect class="bar" x="{x0}" y="{y}" width="{w:.2f}" height="28" rx="6"/>')
        svg.append(_text(x0 + w + 14, y + 21, f'{metrics["cells"]:,} cells'.replace(",", " "), "mono"))
        svg.append(_text(x0, y + 48, f'nodes={metrics["nodes"]:,}  river_edges={metrics["river_edges"]:,}  geology_edges={metrics["geology_edges"]:,}'.replace(",", " "), "small"))
    svg.append(_text(60, 486, "Use this as a mesh-budget view, not as a quality ranking: a larger cell count is only useful if the added cells resolve relevant constraints.", "small"))
    svg.append("</svg>")
    return "\n".join(svg)


def main() -> None:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    (STATIC_DIR / "regular_irregular_same_cell_counts.svg").write_text(
        render_regular_irregular_same_counts(),
        encoding="utf-8",
    )
    (STATIC_DIR / "real_mesh_cell_count_balance.svg").write_text(
        render_real_mesh_cell_budget(),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
