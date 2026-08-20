#!/usr/bin/env python
"""Publication-ready 2D top view of the cheze catchment unstructured mesh.

Reads the self-contained mesh bundle CSVs (no hydromodpy import) plus the lake,
watershed and river vector layers, and renders one clean figure: the triangular
mesh coloured by surface elevation (lakes highlighted), the watershed boundary,
the stream network, a scale bar, a north arrow and an elevation colour bar.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.cm import ScalarMappable  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from shapely.geometry import Point  # noqa: E402
from shapely.prepared import prep  # noqa: E402

_LAKE_STYLE = {
    "reservoir_cheze": ("#08306b", "Reservoir"),
    "preretenue_cheze": ("#41b6c4", "Forebay (pre-retenue)"),
}


def _land_cmap():
    """Terrain colormap with the blue low-end removed, so land reads green->brown
    ->white and the blue lakes stay unambiguous."""
    import matplotlib.colors as mcolors

    base = plt.cm.terrain(np.linspace(0.25, 1.0, 256))
    return mcolors.LinearSegmentedColormap.from_list("land_terrain", base)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", required=True, type=Path)
    p.add_argument("--lakes", required=True, type=Path)
    p.add_argument("--watershed", type=Path, default=None, help="watershed polygon parquet/gpkg")
    p.add_argument("--rivers", type=Path, default=None, help="river network parquet/gpkg")
    p.add_argument("--out", required=True, type=Path)
    return p.parse_args()


def _plot_line(ax, geom, **kw):
    parts = geom.geoms if geom.geom_type.startswith("Multi") else [geom]
    for part in parts:
        xs, ys = part.xy
        ax.plot(np.asarray(xs) / 1000.0, np.asarray(ys) / 1000.0, **kw)
        kw.pop("label", None)  # label once


def _scale_bar(ax, length_km: float, xy_axes=(0.06, 0.08)) -> None:
    """Horizontal scale bar in km, placed in axes fraction coords."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    px = x0 + xy_axes[0] * (x1 - x0)
    py = y0 + xy_axes[1] * (y1 - y0)
    ax.plot([px, px + length_km], [py, py], color="k", lw=2.4, solid_capstyle="butt", zorder=8)
    ax.plot([px, px], [py - 0.03 * (y1 - y0), py + 0.03 * (y1 - y0)], color="k", lw=1.2, zorder=8)
    ax.plot(
        [px + length_km, px + length_km],
        [py - 0.03 * (y1 - y0), py + 0.03 * (y1 - y0)],
        color="k",
        lw=1.2,
        zorder=8,
    )
    ax.text(
        px + length_km / 2.0,
        py + 0.045 * (y1 - y0),
        f"{length_km:g} km",
        ha="center",
        va="bottom",
        fontsize=10,
        zorder=8,
    )


def _north_arrow(ax, xy_axes=(0.95, 0.86)) -> None:
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    px = x0 + xy_axes[0] * (x1 - x0)
    py = y0 + xy_axes[1] * (y1 - y0)
    dy = 0.08 * (y1 - y0)
    ax.annotate(
        "",
        xy=(px, py + dy),
        xytext=(px, py),
        arrowprops=dict(arrowstyle="-|>", color="k", lw=1.8),
        zorder=8,
    )
    ax.text(px, py + dy + 0.01 * (y1 - y0), "N", ha="center", va="bottom", fontsize=12, zorder=8)


def main() -> None:
    args = parse_args()
    nodes = pd.read_csv(args.bundle / "nodes.csv")
    cells = pd.read_csv(args.bundle / "cells.csv")
    x, y = nodes.x.to_numpy(), nodes.y.to_numpy()
    tri = cells[["n0", "n1", "n2"]].to_numpy(int)
    ztc = cells.z_top_mean.to_numpy()
    # triangles in km for a readable axis
    polys = [np.c_[x[t] / 1000.0, y[t] / 1000.0] for t in tri]

    lakes = gpd.read_file(args.lakes).to_crs("EPSG:2154")
    cx, cy = cells.centroid_x.to_numpy(), cells.centroid_y.to_numpy()
    lake_id = np.zeros(len(cells), dtype=int)
    for k, (_, row) in enumerate(lakes.iterrows(), start=1):
        prepared = prep(row.geometry)
        inside = np.fromiter(
            (prepared.covers(Point(a, b)) for a, b in zip(cx, cy, strict=False)),
            bool,
            len(cx),
        )
        lake_id[inside] = k
    names = {k + 1: str(r.lake_id) for k, r in enumerate(lakes.itertuples(index=False))}

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 11,
            "axes.linewidth": 0.8,
            "mathtext.fontset": "cm",
        }
    )
    fig, ax = plt.subplots(figsize=(11.5, 6.4))

    # Elevation colours over LAND cells only, so the colour bar spans the terrain
    # (lakes get their own solid colour and do not skew the ramp).
    land = lake_id == 0
    norm = Normalize(float(np.percentile(ztc[land], 1)), float(ztc[land].max()))
    cmap = _land_cmap()
    facecolors = cmap(norm(ztc))
    for k, (_, row) in enumerate(lakes.iterrows(), start=1):
        colour, _ = _LAKE_STYLE.get(str(row.lake_id), ("#2166ac", str(row.lake_id)))
        facecolors[lake_id == k] = matplotlib.colors.to_rgba(colour)

    ax.add_collection(
        PolyCollection(polys, facecolors=facecolors, edgecolors="0.30", linewidths=0.15, zorder=1)
    )

    if args.rivers is not None and args.rivers.exists():
        riv = (
            gpd.read_parquet(args.rivers)
            if args.rivers.suffix == ".parquet"
            else gpd.read_file(args.rivers)
        ).to_crs("EPSG:2154")
        for i, geom in enumerate(riv.geometry):
            _plot_line(
                ax,
                geom,
                color="#08519c",
                lw=0.9,
                zorder=3,
                label="Stream network" if i == 0 else None,
            )

    if args.watershed is not None and args.watershed.exists():
        ws = (
            gpd.read_parquet(args.watershed)
            if args.watershed.suffix == ".parquet"
            else gpd.read_file(args.watershed)
        ).to_crs("EPSG:2154")
        boundary = ws.geometry.iloc[0]
        boundary = boundary.boundary if boundary.geom_type.endswith("Polygon") else boundary
        _plot_line(ax, boundary, color="k", lw=2.0, zorder=5, label="Watershed boundary")

    ax.set_xlim(x.min() / 1000.0, x.max() / 1000.0)
    ax.set_ylim(y.min() / 1000.0, y.max() / 1000.0)
    ax.set_aspect("equal")
    ax.set_xlabel("Easting [km]  (RGF93 / Lambert-93)")
    ax.set_ylabel("Northing [km]")
    ax.tick_params(direction="out", length=4)

    n_in = int((lake_id == 0).sum())  # placeholder; real inside/outside needs the polygon
    ax.set_title(
        f"Chèze catchment — unstructured triangular mesh ({len(tri)} cells)",
        fontsize=13,
        pad=10,
    )

    _scale_bar(ax, 2.0)
    _north_arrow(ax)

    # Colour bar for land-surface elevation.
    sm = ScalarMappable(norm=norm, cmap=cmap)
    cbar = fig.colorbar(sm, ax=ax, shrink=0.82, pad=0.02, fraction=0.045)
    cbar.set_label("Land-surface elevation $z_{top}$ [m NGF]", fontsize=11)

    # Legend: lakes + boundary + streams.
    handles = [
        Patch(facecolor=_LAKE_STYLE.get(names[k], ("#2166ac", ""))[0], edgecolor="0.3", label=lbl)
        for k in sorted(set(lake_id) - {0})
        for lbl in [_LAKE_STYLE.get(names[k], ("", names[k]))[1]]
    ]
    handles += [
        Line2D([0], [0], color="k", lw=2.0, label="Watershed boundary"),
        Line2D([0], [0], color="#08519c", lw=1.2, label="Stream network"),
    ]
    ax.legend(handles=handles, loc="upper left", framealpha=0.92, fontsize=9.5, borderpad=0.6)

    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=300, bbox_inches="tight")
    print(
        f"wrote {args.out} ({len(tri)} cells, {int(n_in)} land + {int((lake_id > 0).sum())} lake)"
    )


if __name__ == "__main__":
    main()
