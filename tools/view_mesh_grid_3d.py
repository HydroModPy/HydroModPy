#!/usr/bin/env python
"""Standalone 3D viewer for a HydroModPy catchment mesh bundle.

Reads ONLY the self-contained mesh bundle CSVs (no hydromodpy import) plus the
lake geometry, extrudes every planar triangle into a prism (z_bottom -> z_top),
exports the 3D grid to VTU (open in ParaView / pyvista) and renders PNG views:
the full prismatic aquifer grid and a zoom on the lakes' unstructured cells.

The bundle is produced next to the mesh under
``<project>/mesh/mesh_catchment_bundle/`` and is documented in its README.md.

Usage:
    python tools/view_mesh_grid_3d.py \
        --bundle examples/projects/19_cheze_reservoir/mesh/mesh_catchment_bundle \
        --lakes  examples/data/lake_geometry/lakes_cheze_preretenue.gpkg \
        --out    /tmp/grid3d --zexag 25
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from shapely.prepared import prep


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", required=True, type=Path, help="mesh_catchment_bundle dir")
    p.add_argument("--lakes", type=Path, default=None, help="lake geometry gpkg (optional)")
    p.add_argument("--out", type=Path, required=True, help="output dir for VTU + PNG")
    p.add_argument("--zexag", type=float, default=25.0, help="vertical exaggeration for the render")
    p.add_argument(
        "--keep-islands",
        action="store_true",
        help="keep enclosed non-lake cells (real islands); default fills them so the lake is contiguous",
    )
    return p.parse_args()


def load_bundle(bundle: Path):
    nodes = pd.read_csv(bundle / "nodes.csv").sort_values("node_id").reset_index(drop=True)
    cells = pd.read_csv(bundle / "cells.csv")
    if not (nodes.node_id.to_numpy() == np.arange(len(nodes))).all():
        raise SystemExit("node_id is not a dense 0..N-1 range; remap needed.")
    tri = cells[["n0", "n1", "n2"]].to_numpy(dtype=np.int64)
    return nodes, cells, tri


def classify_lakes(cells: pd.DataFrame, lakes_path: Path | None):
    """Return (lake_id per cell, {id: name}). 0 = aquifer, 1..K = each lake."""
    lake_id = np.zeros(len(cells), dtype=np.int64)
    names = {0: "aquifer"}
    if lakes_path is None or not lakes_path.exists():
        return lake_id, names
    lk = gpd.read_file(lakes_path).to_crs("EPSG:2154")
    centroids = np.c_[cells.centroid_x.to_numpy(), cells.centroid_y.to_numpy()]
    for k, (_, row) in enumerate(lk.iterrows(), start=1):
        prepared = prep(row.geometry)
        inside = np.fromiter(
            (prepared.covers(Point(px, py)) for px, py in centroids),
            dtype=bool,
            count=len(centroids),
        )
        lake_id[inside] = k
        names[k] = str(row.get("lake_id", f"lake{k}"))
    return lake_id, names


def cell_adjacency(tri: np.ndarray) -> dict:
    """Edge-neighbour lists: cells sharing 2 nodes are adjacent."""
    from collections import defaultdict

    edge2cell = defaultdict(list)
    for ci, (a, b, c) in enumerate(tri):
        for e in ((a, b), (b, c), (a, c)):
            edge2cell[tuple(sorted(e))].append(ci)
    nbr = defaultdict(list)
    for shared in edge2cell.values():
        if len(shared) == 2:
            nbr[shared[0]].append(shared[1])
            nbr[shared[1]].append(shared[0])
    return nbr


def fill_enclosed_holes(lake_id: np.ndarray, tri: np.ndarray) -> tuple[np.ndarray, int]:
    """Reclassify non-lake cells fully surrounded by one lake into that lake.

    Removes the small classification holes / sub-cell islands so a lake footprint
    is contiguous. Iterated to fill multi-cell pockets. A cell touching the
    aquifer (a shoreline cell) or two different lakes is never filled. Real
    islands can be preserved by not calling this (``--keep-islands``).
    """
    nbr = cell_adjacency(tri)
    lake_id = lake_id.copy()
    n_filled = 0
    while True:
        changed = 0
        for ci in np.where(lake_id == 0)[0]:
            neighbours = nbr.get(int(ci), [])
            if neighbours and all(lake_id[n] > 0 for n in neighbours):
                vals = {int(lake_id[n]) for n in neighbours}
                if len(vals) == 1:
                    lake_id[ci] = vals.pop()
                    changed += 1
        n_filled += changed
        if changed == 0:
            return lake_id, n_filled


def build_wedge_grid(nodes: pd.DataFrame, tri: np.ndarray, cells: pd.DataFrame, lake_id):
    """Extrude each triangle into a VTK wedge (true elevations, no exaggeration)."""
    import pyvista as pv

    n = len(nodes)
    x, y = nodes.x.to_numpy(), nodes.y.to_numpy()
    zt, zb = nodes.z_top.to_numpy(), nodes.z_bottom.to_numpy()
    pts = np.empty((2 * n, 3), dtype=float)
    pts[:n, 0], pts[:n, 1], pts[:n, 2] = x, y, zb  # bottom sheet
    pts[n:, 0], pts[n:, 1], pts[n:, 2] = x, y, zt  # top sheet
    n_c = len(tri)
    conn = np.empty((n_c, 7), dtype=np.int64)
    conn[:, 0] = 6
    conn[:, 1:4] = tri
    conn[:, 4:7] = tri + n
    celltypes = np.full(n_c, pv.CellType.WEDGE, dtype=np.uint8)
    grid = pv.UnstructuredGrid(conn.ravel(), celltypes, pts)
    grid.cell_data["z_top"] = cells.z_top_mean.to_numpy()
    grid.cell_data["thickness"] = (cells.z_top_mean - cells.z_bottom_mean).to_numpy()
    grid.cell_data["lake_id"] = lake_id
    return grid


def render_pyvista(grid, lake_id, names, out: Path, zexag: float) -> bool:
    import pyvista as pv

    pv.OFF_SCREEN = True
    try:
        pv.start_xvfb()
    except Exception:
        pass
    lake_colors = ["royalblue", "deepskyblue", "turquoise", "teal"]
    try:
        # Full 3D prismatic grid, aquifer by elevation + lakes highlighted.
        pl = pv.Plotter(off_screen=True, window_size=(1500, 950))
        aqu = grid.extract_cells(np.where(lake_id == 0)[0])
        pl.add_mesh(
            aqu,
            scalars="z_top",
            cmap="terrain",
            show_edges=False,
            scalar_bar_args={"title": "z_top [m]"},
        )
        for k in sorted(set(lake_id) - {0}):
            pl.add_mesh(
                grid.extract_cells(np.where(lake_id == k)[0]),
                color=lake_colors[(k - 1) % len(lake_colors)],
                show_edges=True,
            )
        pl.add_text(f"Cheze catchment - 3D prismatic grid (z x{zexag:g})", font_size=11)
        pl.set_scale(zscale=zexag)
        pl.show_grid()
        pl.view_isometric()
        pl.screenshot(str(out / "grid3d_full.png"))
        pl.close()

        # Zoom on the lakes' unstructured cells.
        if set(lake_id) - {0}:
            pl = pv.Plotter(off_screen=True, window_size=(1500, 950))
            for k in sorted(set(lake_id) - {0}):
                sub = grid.extract_cells(np.where(lake_id == k)[0])
                pl.add_mesh(
                    sub,
                    color=lake_colors[(k - 1) % len(lake_colors)],
                    show_edges=True,
                    label=f"{names[k]} ({int((lake_id == k).sum())} cells)",
                )
            pl.add_legend()
            pl.add_text("Lakes - unstructured triangular cells", font_size=11)
            pl.set_scale(zscale=zexag)
            pl.show_grid()
            pl.view_isometric()
            pl.screenshot(str(out / "grid3d_lakes.png"))
            pl.close()
        return True
    except Exception as exc:  # noqa: BLE001 - rendering backend may lack GL
        print(f"[pyvista render skipped: {exc!r}] VTU export is still written.")
        return False


def render_matplotlib(nodes, tri, cells, lake_id, names, out: Path, zexag: float) -> None:
    """Guaranteed static PNGs via matplotlib (top surface + lake cells)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    x, y = nodes.x.to_numpy(), nodes.y.to_numpy()
    zt = nodes.z_top.to_numpy()
    verts_top = np.stack([x[tri], y[tri], zt[tri] * zexag], axis=-1)  # (ncell,3,3)
    ztc = cells.z_top_mean.to_numpy()
    norm = plt.Normalize(ztc.min(), ztc.max())
    facecol = plt.cm.terrain(norm(ztc))
    is_lake = lake_id > 0
    facecol[is_lake] = plt.cm.tab10(0)  # blue for lakes

    fig = plt.figure(figsize=(13, 8))
    ax = fig.add_subplot(111, projection="3d")
    coll = Poly3DCollection(verts_top, facecolors=facecol, edgecolors="none", linewidths=0)
    ax.add_collection3d(coll)
    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(y.min(), y.max())
    ax.set_zlim((zt.min()) * zexag, (zt.max()) * zexag)
    ax.set_box_aspect((np.ptp(x), np.ptp(y), np.ptp(zt) * zexag))
    ax.set_title(f"Cheze catchment - top surface, {len(tri)} triangular cells (z x{zexag:g})")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.view_init(elev=35, azim=-120)
    sm = ScalarMappable(norm=norm, cmap="terrain")
    fig.colorbar(sm, ax=ax, shrink=0.5, label="z_top [m]")
    fig.tight_layout()
    fig.savefig(out / "grid3d_full_mpl.png", dpi=130)
    plt.close(fig)

    # Lake cells only, top view.
    if is_lake.any():
        fig, ax = plt.subplots(figsize=(11, 7))
        colors = {1: "royalblue", 2: "deepskyblue", 3: "turquoise"}
        for k in sorted(set(lake_id) - {0}):
            m = lake_id == k
            polys = [np.c_[x[t], y[t]] for t in tri[m]]
            from matplotlib.collections import PolyCollection

            ax.add_collection(
                PolyCollection(
                    polys,
                    facecolors=colors.get(k, "teal"),
                    edgecolors="k",
                    linewidths=0.3,
                    label=f"{names[k]} ({int(m.sum())} cells)",
                )
            )
        lm = is_lake
        ax.set_xlim(x[tri[lm]].min(), x[tri[lm]].max())
        ax.set_ylim(y[tri[lm]].min(), y[tri[lm]].max())
        ax.set_aspect("equal")
        ax.set_title("Lakes - unstructured triangular mesh (top view)")
        ax.set_xlabel("x [m]")
        ax.set_ylabel("y [m]")
        ax.legend(loc="upper right")
        fig.tight_layout()
        fig.savefig(out / "grid3d_lakes_mpl.png", dpi=140)
        plt.close(fig)


def render_top2d(nodes, tri, cells, lake_id, names, out: Path) -> None:
    """Plain 2D top view of the full unstructured triangular mesh."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from matplotlib.collections import PolyCollection

    x, y = nodes.x.to_numpy(), nodes.y.to_numpy()
    polys = [np.c_[x[t], y[t]] for t in tri]
    ztc = cells.z_top_mean.to_numpy()
    norm = plt.Normalize(ztc.min(), ztc.max())

    fig, ax = plt.subplots(figsize=(13, 7))
    # All cells: terrain fill + thin edges so the triangulation is visible.
    ax.add_collection(
        PolyCollection(
            polys,
            array=ztc,
            cmap="terrain",
            norm=norm,
            edgecolors="0.35",
            linewidths=0.12,
        )
    )
    # Lakes overlaid with a solid colour + crisper edges.
    lake_colors = {1: "royalblue", 2: "deepskyblue", 3: "turquoise"}
    for k in sorted(set(lake_id) - {0}):
        m = lake_id == k
        ax.add_collection(
            PolyCollection(
                [polys[i] for i in np.where(m)[0]],
                facecolors=lake_colors.get(k, "teal"),
                edgecolors="k",
                linewidths=0.25,
                label=f"{names[k]} ({int(m.sum())} cells)",
            )
        )
    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(y.min(), y.max())
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_title(f"Unstructured triangular mesh - top view ({len(tri)} cells)")
    sm = ScalarMappable(norm=norm, cmap="terrain")
    fig.colorbar(sm, ax=ax, shrink=0.7, label="z_top [m]")
    if set(lake_id) - {0}:
        ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "grid2d_top.png", dpi=160)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    nodes, cells, tri = load_bundle(args.bundle)
    lake_id, names = classify_lakes(cells, args.lakes)
    if not args.keep_islands and (lake_id > 0).any():
        lake_id, n_filled = fill_enclosed_holes(lake_id, tri)
        if n_filled:
            print(
                f"filled {n_filled} enclosed lake hole cell(s); use --keep-islands to preserve them"
            )
    print(f"mesh: {len(nodes)} nodes, {len(cells)} triangular cells")
    for k in sorted(set(lake_id)):
        print(f"  {names[k]:16s}: {int((lake_id == k).sum())} cells")

    try:
        grid = build_wedge_grid(nodes, tri, cells, lake_id)
        grid.save(args.out / "cheze_grid3d.vtu")
        if (lake_id > 0).any():
            grid.extract_cells(np.where(lake_id > 0)[0]).save(args.out / "cheze_lakes3d.vtu")
        print(f"VTU written to {args.out} (open in ParaView / pyvista)")
        render_pyvista(grid, lake_id, names, args.out, args.zexag)
    except Exception as exc:  # noqa: BLE001
        print(f"[pyvista path failed: {exc!r}] falling back to matplotlib only.")

    render_matplotlib(nodes, tri, cells, lake_id, names, args.out, args.zexag)
    render_top2d(nodes, tri, cells, lake_id, names, args.out)
    print(f"PNG views written to {args.out}")


if __name__ == "__main__":
    main()
