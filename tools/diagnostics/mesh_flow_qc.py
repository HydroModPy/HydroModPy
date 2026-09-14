"""Mesh flow QC: channel continuity, monotonicity, accumulation, fill-raise stats.

Measures whether the current mesh-top conditioning (bilinear DEM sample at the
DISV cell centers + network-blind priority-flood epsilon fill) carries a usable
drainage structure on an irregular Voronoi mesh:

  Q1  Broken channels: consecutive channel cells (mapped from the delineated
      stream-network vector) that are NOT face-adjacent on the mesh.
  Q2  Channel monotonicity: elevation inversions along each channel chain in
      downstream order, on the conditioned AND the unconditioned top (the raw
      DEM re-sampled on the same mesh), to see whether the fill created them.
  Q3  Flow concentration: steepest-descent single-flow-direction accumulation
      on the cell adjacency graph (slope = dz / centroid distance; sinks = lake
      cells and boundary-exiting cells). Does the accumulated area concentrate
      on the mapped channel cells (departures, false thalwegs, raster check)?
  Q4  Fill raise: conditioned minus unconditioned top, split channel/hillslope
      (hypothesis: the fill raises exactly the valley-floor channel cells).

Outputs a JSON metrics file and a self-contained interactive HTML map
(pan/zoom canvas, in the style of cheze_interactive_mesh.py).

Example (Cheze 75 m):
    python tools/diagnostics/mesh_flow_qc.py \
        examples/projects/19_cheze_reservoir/.solver_scratch/cheze_reservoir_preretenue_75m.v7 \
        --streams examples/projects/19_cheze_reservoir/simulations/<sim>.parquet/geographic_hydrographic_network_generated.parquet \
        --raw-dem examples/data/dem/DEM_armorican_massif.tif \
        --zarr examples/projects/19_cheze_reservoir/simulations/<sim>.zarr.zip \
        --exclude-corridor examples/data/cutoff_wall/injection_cheze.gpkg \
        --out /tmp/qc_out
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

TOL = 1e-6  # elevation tolerance in meters (flats, inversions, raises)


# --------------------------------------------------------------------------- mesh loading


@dataclass
class Mesh:
    """Layer-0 view of a DISV model: geometry, adjacency, lake cells."""

    ncpl: int
    xc: np.ndarray
    yc: np.ndarray
    top: np.ndarray  # conditioned top carried by the model
    active: np.ndarray  # bool, idomain[0] == 1
    iverts: list
    verts: np.ndarray
    adj: dict  # active-active face adjacency
    boundary: set  # active cells with >=1 edge not shared with an active cell
    lake_cells: set
    polys: dict = field(default_factory=dict)  # active cell id -> shapely Polygon
    areas: np.ndarray | None = None  # m2, shoelace (0 for inactive)


def load_mesh(solver_dir: str) -> Mesh:
    """Load the DISV grid, active mask, face adjacency and LAK cells."""
    import flopy
    from shapely.geometry import Polygon

    sim = flopy.mf6.MFSimulation.load(sim_ws=solver_dir, verbosity_level=0)
    gwf = sim.get_model()
    mg = gwf.modelgrid
    ncpl = int(mg.ncpl)
    xc = np.asarray(mg.xcellcenters).reshape(-1)
    yc = np.asarray(mg.ycellcenters).reshape(-1)
    top = np.asarray(mg.top).reshape(-1).astype(float)
    idom = np.asarray(mg.idomain).reshape(mg.nlay, -1)
    active = idom[0] == 1
    iverts = mg.iverts
    verts = np.asarray(mg.verts)

    # Face adjacency: consecutive vertex pairs shared by exactly 2 cells.
    edge_cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i in range(ncpl):
        vs = [int(v) for v in iverts[i] if v is not None]
        n = len(vs)
        for a in range(n):
            v1, v2 = vs[a], vs[(a + 1) % n]
            if v1 == v2:
                continue
            edge_cells[(v1, v2) if v1 < v2 else (v2, v1)].append(i)
    adj: dict[int, set[int]] = defaultdict(set)
    boundary: set[int] = set()
    for cells in edge_cells.values():
        if len(cells) == 2:
            i, j = cells
            if active[i] and active[j]:
                adj[i].add(j)
                adj[j].add(i)
            elif active[i]:
                boundary.add(i)
            elif active[j]:
                boundary.add(j)
        elif len(cells) == 1 and active[cells[0]]:
            boundary.add(cells[0])

    lake_cells: set[int] = set()
    lak = gwf.get_package("lak")
    if lak is not None:
        for rec in lak.connectiondata.get_data():
            cid = rec["cellid"]
            lake_cells.add(int(cid[1]) if isinstance(cid, (tuple, np.void)) else int(cid))

    polys: dict[int, Polygon] = {}
    areas = np.zeros(ncpl)
    for i in range(ncpl):
        if not active[i]:
            continue
        ring = [(float(verts[int(v), 0]), float(verts[int(v), 1])) for v in iverts[i]]
        p = Polygon(ring)
        polys[i] = p
        areas[i] = p.area

    return Mesh(ncpl, xc, yc, top, active, iverts, verts, adj, boundary, lake_cells, polys, areas)


# --------------------------------------------------------------------------- raster sampling


def sample_bilinear(
    z: np.ndarray, transform: list[float], nodata: float | None, xs: np.ndarray, ys: np.ndarray
) -> np.ndarray:
    """Bilinear sample with pixel-center convention and NaN-aware renormalization."""
    a, _, c, _, e, f = transform
    dx, dy = float(a), float(-e)
    col = (np.asarray(xs, float) - c) / dx - 0.5
    row = (f - np.asarray(ys, float)) / dy - 0.5
    c0 = np.floor(col).astype(int)
    r0 = np.floor(row).astype(int)
    wx = col - c0
    wy = row - r0
    nrow, ncol = z.shape
    out = np.full(col.shape, np.nan)
    num = np.zeros(col.shape)
    den = np.zeros(col.shape)
    for dr, dc, w in (
        (0, 0, (1 - wy) * (1 - wx)),
        (0, 1, (1 - wy) * wx),
        (1, 0, wy * (1 - wx)),
        (1, 1, wy * wx),
    ):
        rr = r0 + dr
        cc = c0 + dc
        ok = (rr >= 0) & (rr < nrow) & (cc >= 0) & (cc < ncol)
        val = np.where(ok, z[np.clip(rr, 0, nrow - 1), np.clip(cc, 0, ncol - 1)], np.nan)
        good = ok & np.isfinite(val)
        if nodata is not None:
            good &= val != nodata
        num = np.where(good, num + w * val, num)
        den = np.where(good, den + w, den)
    got = den > 1e-12
    out[got] = num[got] / den[got]
    return out


def sample_raw_dem(path: str, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilinear sample of a GeoTIFF at world coordinates (windowed read)."""
    import rasterio
    from rasterio.windows import Window

    with rasterio.open(path) as src:
        tr = src.transform
        dx, dy = tr.a, -tr.e
        col = (xs - tr.c) / dx - 0.5
        row = (tr.f - ys) / dy - 0.5
        c0 = max(int(np.floor(col.min())) - 2, 0)
        c1 = min(int(np.ceil(col.max())) + 3, src.width)
        r0 = max(int(np.floor(row.min())) - 2, 0)
        r1 = min(int(np.ceil(row.max())) + 3, src.height)
        z = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(float)
        win_transform = [dx, 0.0, tr.c + c0 * dx, 0.0, -dy, tr.f - r0 * dy]
        return sample_bilinear(z, win_transform, src.nodata, xs, ys)


def load_zarr_raster(zarr_path: str, name: str) -> tuple[np.ndarray, list[float], float]:
    """Load a raster array + transform + nodata from the run zarr (zip store)."""
    import zarr

    store = zarr.storage.ZipStore(zarr_path, mode="r")
    arr = zarr.open_group(store, mode="r")["geographic"][name]
    z = np.asarray(arr[:], dtype=float)
    transform = [float(v) for v in arr.attrs["transform"]]
    nodata = float(arr.attrs.get("nodata", -9999.0))
    return z, transform, nodata


# --------------------------------------------------------------------------- classification

CLS_NORMAL, CLS_PIT, CLS_FLAT, CLS_BOUND, CLS_LAKEBED = 0, 1, 2, 3, 4


def classify_surface(mesh: Mesh, top: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    """Template classification: descent > flat > boundary > lake-bed min > pit."""
    cls = np.full(mesh.ncpl, -1, int)
    for i in range(mesh.ncpl):
        if not mesh.active[i] or not np.isfinite(top[i]):
            continue
        best_slope, best_j, eq = 0.0, -1, False
        for j in mesh.adj[i]:
            if not np.isfinite(top[j]):
                continue
            dz = top[i] - top[j]
            if abs(dz) < TOL:
                eq = True
            elif dz > 0:
                dist = max(math.hypot(mesh.xc[i] - mesh.xc[j], mesh.yc[i] - mesh.yc[j]), 1.0)
                if dz / dist > best_slope:
                    best_slope, best_j = dz / dist, j
        if best_j >= 0:
            cls[i] = CLS_NORMAL
        elif eq:
            cls[i] = CLS_FLAT
        elif i in mesh.boundary:
            cls[i] = CLS_BOUND
        elif i in mesh.lake_cells:
            cls[i] = CLS_LAKEBED
        else:
            cls[i] = CLS_PIT
    counts = {
        "pits": int((cls == CLS_PIT).sum()),
        "flats": int((cls == CLS_FLAT).sum()),
        "boundary_sinks": int((cls == CLS_BOUND).sum()),
        "lakebed_minima": int((cls == CLS_LAKEBED).sum()),
    }
    return cls, counts


# --------------------------------------------------------------------------- channel mapping


def _linear_parts(geom) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        return [part for g in geom.geoms for part in _linear_parts(g)]
    return []


def _sample_line_end(line, coords_order, fill, fill_tr, fill_nod) -> float:
    """Fill-DEM elevation at a line end, walking inward past nodata pixels."""
    for x, y in coords_order:
        v = sample_bilinear(fill, fill_tr, fill_nod, np.array([x]), np.array([y]))[0]
        if np.isfinite(v):
            return float(v)
    return math.nan


def map_channel_chains(
    streams_path: str, mesh: Mesh, fill: np.ndarray, fill_tr: list[float], fill_nod: float
) -> list[dict]:
    """Map each stream LineString to a downstream-ordered chain of active cells."""
    import geopandas as gpd
    from shapely.strtree import STRtree

    gdf = gpd.read_parquet(streams_path).explode(index_parts=False)
    cell_ids = sorted(mesh.polys)
    geoms = [mesh.polys[i] for i in cell_ids]
    tree = STRtree(geoms)

    chains = []
    for fid, line in zip(gdf.get("FID", gdf.index), gdf.geometry, strict=True):
        if line.geom_type != "LineString" or line.length < 1e-3:
            continue
        entries: list[tuple[float, int]] = []
        for pi in tree.query(line):
            inter = geoms[int(pi)].intersection(line)
            for part in _linear_parts(inter):
                if part.length < 1e-3:  # drop sub-mm slivers
                    continue
                mid = part.interpolate(0.5, normalized=True)
                entries.append((float(line.project(mid)), cell_ids[int(pi)]))
        entries.sort()
        cells = [c for _, c in entries]
        cells = [c for k, c in enumerate(cells) if k == 0 or c != cells[k - 1]]
        if len(cells) < 2:
            continue

        # Orient downstream: the routing fill DEM decreases toward the outlet.
        coords = list(line.coords)
        z_start = _sample_line_end(line, coords, fill, fill_tr, fill_nod)
        z_end = _sample_line_end(line, coords[::-1], fill, fill_tr, fill_nod)
        if math.isnan(z_start) or math.isnan(z_end) or abs(z_start - z_end) < TOL:
            z_start, z_end = mesh.top[cells[0]], mesh.top[cells[-1]]
        if z_start < z_end:
            cells = cells[::-1]

        # Drop leading lake cells; terminate the chain at the first lake cell.
        start = 0
        while start < len(cells) and cells[start] in mesh.lake_cells:
            start += 1
        out, ends_in_lake = [], False
        for c in cells[start:]:
            out.append(c)
            if c in mesh.lake_cells:
                ends_in_lake = True
                break
        if len(out) >= 2:
            chains.append({"fid": int(fid), "cells": out, "ends_in_lake": ends_in_lake})
    return chains


def gap_analysis(chains: list[dict], mesh: Mesh) -> dict:
    """Q1: consecutive chain cells that are not face-adjacent on the mesh."""
    n_pairs = n_adj = n_gaps = n_one = n_term_gaps = 0
    gaps = []
    for ch in chains:
        cells = ch["cells"]
        for a, b in zip(cells, cells[1:], strict=False):
            if b in mesh.lake_cells:
                # Terminal pair: reaching any lake cell face counts as arrived.
                if b not in mesh.adj[a] and not any(n in mesh.lake_cells for n in mesh.adj[a]):
                    n_term_gaps += 1
                    gaps.append(_gap_record(mesh, ch, a, b, terminal=True))
                continue
            n_pairs += 1
            if b in mesh.adj[a]:
                n_adj += 1
                continue
            n_gaps += 1
            one = bool(mesh.adj[a] & mesh.adj[b])
            n_one += one
            gaps.append(_gap_record(mesh, ch, a, b, one_cell=one))
    return {
        "n_pairs": n_pairs,
        "n_adjacent": n_adj,
        "n_gaps": n_gaps,
        "n_gaps_one_cell": n_one,
        "n_terminal_gaps": n_term_gaps,
        "gaps": gaps,
    }


def _gap_record(mesh: Mesh, ch: dict, a: int, b: int, one_cell=False, terminal=False) -> dict:
    return {
        "fid": ch["fid"],
        "cells": [a, b],
        "x": round((mesh.xc[a] + mesh.xc[b]) / 2, 1),
        "y": round((mesh.yc[a] + mesh.yc[b]) / 2, 1),
        "x1": round(float(mesh.xc[a]), 1),
        "y1": round(float(mesh.yc[a]), 1),
        "x2": round(float(mesh.xc[b]), 1),
        "y2": round(float(mesh.yc[b]), 1),
        "one_cell": int(one_cell),
        "terminal": int(terminal),
    }


def monotonicity(chains: list[dict], mesh: Mesh, top: np.ndarray) -> dict:
    """Q2: uphill steps along the downstream-ordered chains (non-lake cells)."""
    inversions = []
    for ch in chains:
        cells = [c for c in ch["cells"] if c not in mesh.lake_cells]
        for a, b in zip(cells, cells[1:], strict=False):
            if not (np.isfinite(top[a]) and np.isfinite(top[b])):
                continue
            dz = float(top[b] - top[a])
            if dz > TOL:
                inversions.append(
                    {
                        "fid": ch["fid"],
                        "cells": [a, b],
                        "x": round(float(mesh.xc[b]), 1),
                        "y": round(float(mesh.yc[b]), 1),
                        "m": round(dz, 3),
                    }
                )
    mags = [r["m"] for r in inversions]
    return {
        "n": len(inversions),
        "max_m": round(max(mags), 3) if mags else 0.0,
        "mean_m": round(float(np.mean(mags)), 3) if mags else 0.0,
        "inversions": inversions,
    }


# --------------------------------------------------------------------------- accumulation


def flow_accumulation(mesh: Mesh, top: np.ndarray) -> dict:
    """Q3 routing: steepest-descent SFD accumulation of cell areas (m2)."""
    succ = np.full(mesh.ncpl, -1, int)
    sink_kind = {}  # cell -> 'lake' | 'boundary' | 'pit' | 'flat'
    n_flat_tie = 0
    for i in range(mesh.ncpl):
        if not mesh.active[i]:
            continue
        if i in mesh.lake_cells:
            sink_kind[i] = "lake"
            continue
        best_slope, best_j = 0.0, -1
        eq_lower_id = -1
        for j in mesh.adj[i]:
            dz = top[i] - top[j]
            if abs(dz) < TOL:
                if j < i and (eq_lower_id < 0 or j < eq_lower_id):
                    eq_lower_id = j
            elif dz > 0:
                dist = max(math.hypot(mesh.xc[i] - mesh.xc[j], mesh.yc[i] - mesh.yc[j]), 1.0)
                if dz / dist > best_slope:
                    best_slope, best_j = dz / dist, j
        if best_j >= 0:
            succ[i] = best_j
        elif eq_lower_id >= 0:
            # Deterministic acyclic tie-break: equal-top neighbor with lower id.
            succ[i] = eq_lower_id
            n_flat_tie += 1
        elif i in mesh.boundary:
            sink_kind[i] = "boundary"
        else:
            sink_kind[i] = "flat" if any(abs(top[i] - top[j]) < TOL for j in mesh.adj[i]) else "pit"

    acc = mesh.areas.copy()
    order = sorted(np.flatnonzero(mesh.active), key=lambda i: (top[i], i), reverse=True)
    for i in order:
        s = succ[i]
        if s >= 0:
            acc[s] += acc[i]
    return {"succ": succ, "acc": acc, "sink_kind": sink_kind, "n_flat_tie": n_flat_tie}


def raster_d8_accumulation(z: np.ndarray, nodata: float) -> np.ndarray:
    """D8 SFD accumulation (pixel counts * pixel area) on a filled routing DEM."""
    nrow, ncol = z.shape
    valid = np.isfinite(z) & (z != nodata)
    nb = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    diag = [False, True, False, True, False, True, False, True]
    succ = np.full((nrow, ncol), -1, int)
    for r in range(nrow):
        for c in range(ncol):
            if not valid[r, c]:
                continue
            zc = z[r, c]
            best_s, best_k, eq_low = 0.0, -1, -1
            for k, (dc, dr) in enumerate(nb):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < nrow and 0 <= cc < ncol and valid[rr, cc]):
                    continue
                dz = zc - z[rr, cc]
                flat_idx = rr * ncol + cc
                if abs(dz) < TOL:
                    if flat_idx < r * ncol + c and (eq_low < 0 or flat_idx < eq_low):
                        eq_low = flat_idx
                elif dz > 0:
                    s = dz / (math.sqrt(2) if diag[k] else 1.0)
                    if s > best_s:
                        best_s, best_k = s, flat_idx
            succ[r, c] = best_k if best_k >= 0 else eq_low
    zr = z.ravel()
    sr = succ.ravel()
    ar = np.where(valid, 1.0, 0.0).ravel()
    vr = valid.ravel()
    order = sorted(np.flatnonzero(vr), key=lambda i: (zr[i], i), reverse=True)
    for i in order:
        s = sr[i]
        if s >= 0:
            ar[s] += ar[i]
    return ar.reshape(nrow, ncol)


def zonal_raster_max(
    mesh: Mesh, cells: list[int], grid: np.ndarray, transform: list[float], nodata_mask: np.ndarray
) -> dict[int, float]:
    """Max raster value over the pixels whose centers fall inside each cell."""
    from shapely.geometry import Point

    a, _, c0, _, e, f0 = transform
    dx, dy = float(a), float(-e)
    nrow, ncol = grid.shape
    out: dict[int, float] = {}
    for cell in cells:
        poly = mesh.polys[cell]
        x0, y0, x1, y1 = poly.bounds
        cmin = max(int((x0 - c0) / dx - 0.5), 0)
        cmax = min(int((x1 - c0) / dx + 0.5), ncol - 1)
        rmin = max(int((f0 - y1) / dy - 0.5), 0)
        rmax = min(int((f0 - y0) / dy + 0.5), nrow - 1)
        best = -np.inf
        for r in range(rmin, rmax + 1):
            for c in range(cmin, cmax + 1):
                if nodata_mask[r, c]:
                    continue
                px, py = c0 + (c + 0.5) * dx, f0 - (r + 0.5) * dy
                if poly.contains(Point(px, py)):
                    best = max(best, grid[r, c])
        if not np.isfinite(best):
            # Fallback: nearest pixel under the centroid.
            r = int((f0 - mesh.yc[cell]) / dy - 0.5 + 0.5)
            c = int((mesh.xc[cell] - c0) / dx - 0.5 + 0.5)
            if 0 <= r < nrow and 0 <= c < ncol and not nodata_mask[r, c]:
                best = grid[r, c]
        out[cell] = float(best) if np.isfinite(best) else math.nan
    return out


# --------------------------------------------------------------------------- corridor


def corridor_mask(mesh: Mesh, vector_path: str, buffer_m: float) -> set[int]:
    """Cells whose centroid lies within buffer_m of the excluded corridor line."""
    import geopandas as gpd
    from shapely.geometry import Point
    from shapely.ops import unary_union

    zone = unary_union(list(gpd.read_file(vector_path).geometry)).buffer(buffer_m)
    return {i for i in mesh.polys if zone.contains(Point(float(mesh.xc[i]), float(mesh.yc[i])))}


# --------------------------------------------------------------------------- HTML map


def _hex_ramp(stops: list[str], t: float) -> str:
    t = min(max(t, 0.0), 1.0) * (len(stops) - 1)
    k = min(int(t), len(stops) - 2)
    f = t - k
    c1 = [int(stops[k][i : i + 2], 16) for i in (1, 3, 5)]
    c2 = [int(stops[k + 1][i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a + (b - a) * f):02x}" for a, b in zip(c1, c2, strict=True))


TERRAIN = ["#41694f", "#6d8f5c", "#a3ac72", "#c3ab7a", "#b78e6c", "#c9c2b6"]
ACCMAP = ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"]


def write_html(path: str, mesh: Mesh, ref_top, flow, channel, chains, gaps, invs_c, deps, fts, k):
    """Emit the self-contained interactive map (ref_top = pre-fill or raw sample)."""
    acc = flow["acc"]
    tvals = mesh.top[mesh.active & np.isfinite(mesh.top)]
    tmin, tmax = float(np.percentile(tvals, 1)), float(np.percentile(tvals, 99))
    la_min = math.log10(5e3)
    la_max = math.log10(max(float(acc.max()), 1e6))
    vmap: dict[int, int] = {}
    vx: list[float] = []
    vy: list[float] = []

    def vid(v: int) -> int:
        if v not in vmap:
            vmap[v] = len(vx)
            vx.append(round(float(mesh.verts[v, 0]), 1))
            vy.append(round(float(mesh.verts[v, 1]), 1))
        return vmap[v]

    ft_set = {r["cell"] for r in fts}
    cells = []
    for i in sorted(mesh.polys):
        if i in mesh.lake_cells:
            kind, col = 2, "#1e40af"
        elif i in channel:
            kind = 1
            t = (math.log10(max(acc[i], 5e3)) - la_min) / max(la_max - la_min, 1e-9)
            col = _hex_ramp(ACCMAP, t)
        else:
            kind = 0
            t = (mesh.top[i] - tmin) / max(tmax - tmin, 1e-9)
            col = _hex_ramp(TERRAIN, t)
        rec = {
            "p": [vid(int(v)) for v in mesh.iverts[i] if v is not None],
            "x": round(float(mesh.xc[i]), 1),
            "y": round(float(mesh.yc[i]), 1),
            "t": round(float(mesh.top[i]), 2),
            "u": round(float(ref_top[i]), 2) if np.isfinite(ref_top[i]) else None,
            "a": round(float(acc[i]) / 1e6, 4),
            "c": col,
            "k": kind,
            "ft": 1 if i in ft_set else 0,
        }
        s = int(flow["succ"][i])
        if s >= 0:
            rec["tx"] = round(float(mesh.xc[s]), 1)
            rec["ty"] = round(float(mesh.yc[s]), 1)
        cells.append(rec)

    data = {
        "cells": cells,
        "vx": vx,
        "vy": vy,
        "xmin": min(vx),
        "xmax": max(vx),
        "ymin": min(vy),
        "ymax": max(vy),
        "gaps": gaps["gaps"],
        "invs": invs_c["inversions"],
        "deps": deps[:200],
        "fts": [{"x": r["x"], "y": r["y"], "a": r["a"]} for r in fts][:400],
        "k": k,
    }
    html = _HTML_TEMPLATE.replace("__DATA__", json.dumps(data))
    with open(path, "w") as f:
        f.write(html)


# --------------------------------------------------------------------------- main


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("solver_dir", help="MODFLOW 6 simulation workspace (DISV grid)")
    p.add_argument("--streams", required=True, help="stream network GeoParquet (LineStrings)")
    p.add_argument("--raw-dem", required=True, help="raw source DEM GeoTIFF (unconditioned top)")
    p.add_argument("--zarr", required=True, help="run zarr.zip with geographic/watershed_fill")
    p.add_argument("--out", default="qc_out", help="output directory (JSON + HTML)")
    p.add_argument(
        "--threshold-km2", type=float, default=1.0, help="stream initiation threshold [km2]"
    )
    p.add_argument(
        "--exclude-corridor",
        default=None,
        help="vector line of a structure carve (e.g. dam) to exclude from raise stats",
    )
    p.add_argument(
        "--corridor-buffer",
        type=float,
        default=150.0,
        help="corridor exclusion half-width [m] (carve buffer + bilinear smear margin)",
    )
    p.add_argument(
        "--prefill-name",
        default="watershed_dem",
        help="zarr geographic/ array holding the pre-fill model-top DEM clip "
        "(raw DEM + structure carves, before the priority-flood fill); 'none' disables",
    )
    p.add_argument("--max-report", type=int, default=10, help="rows in console worst-of lists")
    return p.parse_args()


def _raise_stats(prefix: str, delta: np.ndarray, groups: dict[str, list[int]]) -> dict:
    """Raised-cell statistics per group at TOL and at a 1 cm materiality bar."""
    out: dict[str, float | int] = {}
    for name, ids in groups.items():
        d = np.array([delta[i] for i in ids if np.isfinite(delta[i])])
        raised = d > TOL
        out[f"{prefix}_n_{name}_cells"] = int(d.size)
        out[f"{prefix}_n_raised_{name}"] = int(raised.sum())
        out[f"{prefix}_frac_raised_{name}"] = round(float(raised.mean()), 4) if d.size else 0.0
        big = d > 0.01
        out[f"{prefix}_n_raised_gt_1cm_{name}"] = int(big.sum())
        out[f"{prefix}_frac_raised_gt_1cm_{name}"] = round(float(big.mean()), 4) if d.size else 0.0
        out[f"{prefix}_mean_raise_gt_1cm_{name}_m"] = (
            round(float(d[big].mean()), 3) if big.any() else 0.0
        )
        out[f"{prefix}_max_raise_{name}_m"] = (
            round(float(d[raised].max()), 3) if raised.any() else 0.0
        )
    return out


def _violations(delta: np.ndarray, ids: list[int]) -> list[tuple[int, float]]:
    """Cells where the conditioned top sits below the reference (delta < -TOL)."""
    viol = [(i, float(delta[i])) for i in ids if np.isfinite(delta[i]) and delta[i] < -TOL]
    viol.sort(key=lambda t: t[1])
    return viol


def main() -> None:
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)
    thr_m2 = args.threshold_km2 * 1e6

    print(f"Loading model from {args.solver_dir} ...")
    mesh = load_mesh(args.solver_dir)
    n_active = int(mesh.active.sum())
    active_ids = np.flatnonzero(mesh.active)
    print(f"  ncpl={mesh.ncpl} active={n_active} lake_cells={len(mesh.lake_cells)}")

    # Unconditioned top: bilinear re-sample of the raw DEM at the same centers.
    uncond = np.full(mesh.ncpl, np.nan)
    uncond[active_ids] = sample_raw_dem(args.raw_dem, mesh.xc[active_ids], mesh.yc[active_ids])
    n_nan_uncond = int(np.isnan(uncond[active_ids]).sum())

    # Pre-fill top: the surface the fill actually operated on (the model-top DEM
    # clip = raw DEM + structure carves, watershed-masked). When available it is
    # the exact pre/post reference for the fill; the raw-DEM sample additionally
    # differs by the carves and by mask-edge bilinear support.
    prefill = None
    if args.prefill_name and args.prefill_name != "none":
        try:
            pz, ptr, pnod = load_zarr_raster(args.zarr, args.prefill_name)
            prefill = np.full(mesh.ncpl, np.nan)
            prefill[active_ids] = sample_bilinear(
                pz, ptr, pnod, mesh.xc[active_ids], mesh.yc[active_ids]
            )
        except KeyError:
            print(f"  note: no '{args.prefill_name}' array in the zarr; raw DEM only")

    # Depression classification on every top (ties to the known baseline).
    _, cnt_cond = classify_surface(mesh, mesh.top)
    _, cnt_uncond = classify_surface(mesh, uncond)
    cnt_prefill = classify_surface(mesh, prefill)[1] if prefill is not None else None

    # Channel chains from the delineated network.
    fill, fill_tr, fill_nod = load_zarr_raster(args.zarr, "watershed_fill")
    chains = map_channel_chains(args.streams, mesh, fill, fill_tr, fill_nod)
    channel = {c for ch in chains for c in ch["cells"] if c not in mesh.lake_cells}
    n_chain_lake_end = sum(ch["ends_in_lake"] for ch in chains)

    # Q1 gaps, Q2 monotonicity (conditioned / pre-fill / raw tops).
    gaps = gap_analysis(chains, mesh)
    invs_c = monotonicity(chains, mesh, mesh.top)
    invs_u = monotonicity(chains, mesh, uncond)
    invs_p = monotonicity(chains, mesh, prefill) if prefill is not None else invs_u
    pairs_c = {tuple(r["cells"]) for r in invs_c["inversions"]}
    pairs_p = {tuple(r["cells"]) for r in invs_p["inversions"]}
    created = pairs_c - pairs_p
    removed = pairs_p - pairs_c

    # Q3 accumulation on the conditioned top.
    flow = flow_accumulation(mesh, mesh.top)
    acc, succ, sink_kind = flow["acc"], flow["succ"], flow["sink_kind"]
    acc_lakes = sum(acc[i] for i, kind in sink_kind.items() if kind == "lake")
    acc_boundary = sum(acc[i] for i, kind in sink_kind.items() if kind == "boundary")
    acc_stranded = sum(acc[i] for i, kind in sink_kind.items() if kind in ("pit", "flat"))
    n_ch_routed = n_ch_good = 0
    deps = []
    for i in sorted(channel):
        s = int(succ[i])
        if s < 0:
            continue
        n_ch_routed += 1
        if s in channel or s in mesh.lake_cells:
            n_ch_good += 1
        else:
            deps.append(
                {
                    "cell": i,
                    "x": round(float(mesh.xc[i]), 1),
                    "y": round(float(mesh.yc[i]), 1),
                    "a": round(float(acc[i]) / 1e6, 4),
                }
            )
    deps.sort(key=lambda r: -r["a"])
    # Where does departing flow go: walk successors until it re-enters the
    # network (channel or lake) or dies in a sink.
    targets = channel | mesh.lake_cells
    for r in deps:
        c, steps, re = r["cell"], 0, -1
        while steps < mesh.ncpl:
            c = int(succ[c])
            if c < 0:
                break
            steps += 1
            if c in targets:
                re = steps
                break
        r["reenter_steps"] = re
    n_dep_reenter = sum(1 for r in deps if r["reenter_steps"] > 0)
    n_dep_reenter_le3 = sum(1 for r in deps if 0 < r["reenter_steps"] <= 3)
    fts = [
        {
            "cell": int(i),
            "x": round(float(mesh.xc[i]), 1),
            "y": round(float(mesh.yc[i]), 1),
            "a": round(float(acc[i]) / 1e6, 4),
            "adj_channel": int(any(n in channel or n in mesh.lake_cells for n in mesh.adj[i])),
        }
        for i in active_ids
        if acc[i] > thr_m2 and i not in channel and i not in mesh.lake_cells
    ]
    fts.sort(key=lambda r: -r["a"])
    n_ft_adj = sum(r["adj_channel"] for r in fts)

    # Raster cross-check: D8 accumulation on the routing fill DEM.
    px_area = abs(fill_tr[0] * fill_tr[4])
    r_acc = raster_d8_accumulation(fill, fill_nod) * px_area
    r_valid = np.isfinite(fill) & (fill != fill_nod)
    zonal = zonal_raster_max(mesh, sorted(channel), r_acc, fill_tr, ~r_valid)
    ratios = {i: acc[i] / v for i, v in zonal.items() if np.isfinite(v) and v >= thr_m2}
    n_ch_below = sum(1 for r in ratios.values() if r < 0.5)

    # Q4 raise statistics. Primary: conditioned - pre-fill (the fill's own effect,
    # carves cancel out). Secondary: conditioned - raw (total conditioning delta,
    # structure-carve corridor excluded).
    corridor = (
        corridor_mask(mesh, args.exclude_corridor, args.corridor_buffer)
        if args.exclude_corridor
        else set()
    )
    nonlake = [int(i) for i in active_ids if int(i) not in mesh.lake_cells]
    nonlake_nocorr = [i for i in nonlake if i not in corridor]
    groups_all = {
        "channel": [i for i in nonlake if i in channel],
        "hillslope": [i for i in nonlake if i not in channel],
    }
    groups_nocorr = {
        "channel": [i for i in nonlake_nocorr if i in channel],
        "hillslope": [i for i in nonlake_nocorr if i not in channel],
    }
    delta_raw = mesh.top - uncond
    viol_raw = _violations(delta_raw, nonlake_nocorr)
    q4_raw = _raise_stats("q4raw", delta_raw, groups_nocorr)
    if prefill is not None:
        delta_fill = mesh.top - prefill
        viol_fill = _violations(delta_fill, nonlake)
        q4 = _raise_stats("q4", delta_fill, groups_all)
    else:
        delta_fill = delta_raw
        viol_fill = viol_raw
        q4 = _raise_stats("q4", delta_raw, groups_nocorr)

    metrics = {
        "n_active": n_active,
        "n_lake_cells": len(mesh.lake_cells),
        "n_boundary_cells": len(mesh.boundary),
        "active_area_km2": round(float(mesh.areas.sum()) / 1e6, 3),
        "n_uncond_nan": n_nan_uncond,
        "cond_n_pits": cnt_cond["pits"],
        "cond_n_flats": cnt_cond["flats"],
        "cond_n_boundary_sinks": cnt_cond["boundary_sinks"],
        "cond_n_lakebed_minima": cnt_cond["lakebed_minima"],
        "uncond_n_pits": cnt_uncond["pits"],
        "uncond_n_flats": cnt_uncond["flats"],
        "uncond_n_lakebed_minima": cnt_uncond["lakebed_minima"],
        "prefill_n_pits": cnt_prefill["pits"] if cnt_prefill else None,
        "prefill_n_flats": cnt_prefill["flats"] if cnt_prefill else None,
        "q1_n_chains": len(chains),
        "q1_n_chains_ending_in_lake": n_chain_lake_end,
        "q1_n_channel_cells": len(channel),
        "q1_n_pairs": gaps["n_pairs"],
        "q1_n_adjacent_pairs": gaps["n_adjacent"],
        "q1_n_gaps": gaps["n_gaps"],
        "q1_n_gaps_one_cell": gaps["n_gaps_one_cell"],
        "q1_n_terminal_gaps": gaps["n_terminal_gaps"],
        "q1_frac_pairs_adjacent": round(gaps["n_adjacent"] / max(gaps["n_pairs"], 1), 4),
        "q2_cond_n_inversions": invs_c["n"],
        "q2_cond_max_inversion_m": invs_c["max_m"],
        "q2_cond_mean_inversion_m": invs_c["mean_m"],
        "q2_uncond_n_inversions": invs_u["n"],
        "q2_uncond_max_inversion_m": invs_u["max_m"],
        "q2_uncond_mean_inversion_m": invs_u["mean_m"],
        "q2_prefill_n_inversions": invs_p["n"] if prefill is not None else None,
        "q2_prefill_max_inversion_m": invs_p["max_m"] if prefill is not None else None,
        "q2_n_inversions_created_by_fill": len(created),
        "q2_n_inversions_removed_by_fill": len(removed),
        "q3_n_channel_routed": n_ch_routed,
        "q3_frac_channel_succ_channel_or_lake": round(n_ch_good / max(n_ch_routed, 1), 4),
        "q3_n_channel_departures": len(deps),
        "q3_n_departures_reentering_network": n_dep_reenter,
        "q3_n_departures_reentering_within_3_cells": n_dep_reenter_le3,
        "q3_n_false_thalwegs": len(fts),
        "q3_n_false_thalwegs_adjacent_to_network": n_ft_adj,
        "q3_false_thalweg_max_acc_km2": fts[0]["a"] if fts else 0.0,
        "q3_acc_into_lakes_km2": round(acc_lakes / 1e6, 3),
        "q3_acc_boundary_exit_km2": round(acc_boundary / 1e6, 3),
        "q3_acc_stranded_km2": round(acc_stranded / 1e6, 3),
        "q3_max_cell_acc_km2": round(float(acc.max()) / 1e6, 3),
        "q3_n_flat_tie_broken": flow["n_flat_tie"],
        "q3_n_flat_sinks": sum(1 for v in sink_kind.values() if v == "flat"),
        "q3_n_pit_sinks": sum(1 for v in sink_kind.values() if v == "pit"),
        "q3_n_channel_with_raster_ref": len(ratios),
        "q3_n_channel_below_half_raster_acc": n_ch_below,
        "q3_channel_raster_acc_ratio_median": (
            round(float(np.median(list(ratios.values()))), 3) if ratios else math.nan
        ),
        "q4_reference": args.prefill_name if prefill is not None else "raw_dem",
        "q4_n_corridor_cells_excluded": len(corridor),
        "q4_n_negative_delta_violations_vs_prefill": len(viol_fill),
        "q4_n_negative_gt_1cm_vs_prefill": sum(1 for _, d in viol_fill if d < -0.01),
        "q4_max_negative_delta_vs_prefill_m": round(viol_fill[0][1], 3) if viol_fill else 0.0,
        "q4raw_n_negative_delta_violations": len(viol_raw),
        "q4raw_n_negative_gt_1cm": sum(1 for _, d in viol_raw if d < -0.01),
        "q4raw_max_negative_delta_m": round(viol_raw[0][1], 3) if viol_raw else 0.0,
        **q4,
        **q4_raw,
    }

    details = {
        "gaps": gaps["gaps"],
        "inversions_conditioned": invs_c["inversions"],
        "inversions_prefill": invs_p["inversions"] if prefill is not None else None,
        "inversions_unconditioned": invs_u["inversions"],
        "departures": deps,
        "false_thalwegs": fts[:200],
        "negative_delta_violations_vs_prefill": [
            {
                "cell": i,
                "x": round(float(mesh.xc[i]), 1),
                "y": round(float(mesh.yc[i]), 1),
                "delta_m": round(d, 3),
            }
            for i, d in viol_fill[:50]
        ],
        "negative_delta_violations_vs_raw": [
            {
                "cell": i,
                "x": round(float(mesh.xc[i]), 1),
                "y": round(float(mesh.yc[i]), 1),
                "delta_m": round(d, 3),
            }
            for i, d in viol_raw[:50]
        ],
        "chains": [
            {"fid": ch["fid"], "n_cells": len(ch["cells"]), "ends_in_lake": ch["ends_in_lake"]}
            for ch in chains
        ],
    }
    json_path = os.path.join(args.out, "mesh_flow_qc.json")
    with open(json_path, "w") as f:
        json.dump({"metrics": metrics, "details": details}, f, indent=2)

    kpi = {
        "gaps": gaps["n_gaps"],
        "inv_c": invs_c["n"],
        "inv_u": invs_u["n"],
        "fts": len(fts),
        "cont": metrics["q3_frac_channel_succ_channel_or_lake"],
        "nch": len(channel),
        "acc_lakes": metrics["q3_acc_into_lakes_km2"],
    }
    html_path = os.path.join(args.out, "mesh_flow_qc.html")
    ref_top = prefill if prefill is not None else uncond
    write_html(html_path, mesh, ref_top, flow, channel, chains, gaps, invs_c, deps, fts, kpi)

    print("\n=== Q1 channel continuity ===")
    print(f"  chains={len(chains)} channel_cells={len(channel)} pairs={gaps['n_pairs']}")
    print(
        f"  gaps={gaps['n_gaps']} (one-cell={gaps['n_gaps_one_cell']}) "
        f"terminal_gaps={gaps['n_terminal_gaps']} adjacent={metrics['q1_frac_pairs_adjacent']:.1%}"
    )
    print("=== Q2 monotonicity (downstream) ===")
    print(
        f"  conditioned: {invs_c['n']} inversions (max {invs_c['max_m']} m, "
        f"mean {invs_c['mean_m']} m)"
    )
    print(f"  raw unconditioned: {invs_u['n']} inversions (max {invs_u['max_m']} m)")
    if prefill is not None:
        print(f"  pre-fill: {invs_p['n']} inversions (max {invs_p['max_m']} m)")
    print(f"  created_by_fill={len(created)} removed_by_fill={len(removed)}")
    print("=== Q3 accumulation ===")
    print(
        f"  channel successor in channel/lake: {metrics['q3_frac_channel_succ_channel_or_lake']:.1%}"
        f" ({n_ch_good}/{n_ch_routed}); departures={len(deps)} "
        f"(re-enter network: {n_dep_reenter}, within 3 cells: {n_dep_reenter_le3})"
    )
    print(
        f"  false thalwegs (> {args.threshold_km2} km2 off-network): {len(fts)} "
        f"({n_ft_adj} face-adjacent to the network); max acc {metrics['q3_max_cell_acc_km2']} km2"
    )
    print(
        f"  area to lakes {metrics['q3_acc_into_lakes_km2']} km2, boundary "
        f"{metrics['q3_acc_boundary_exit_km2']} km2, stranded {metrics['q3_acc_stranded_km2']} km2"
    )
    print(
        f"  raster check: {n_ch_below}/{len(ratios)} channel cells < 0.5x raster acc "
        f"(median ratio {metrics['q3_channel_raster_acc_ratio_median']})"
    )
    for r in deps[: args.max_report]:
        back = f"re-enters after {r['reenter_steps']}" if r["reenter_steps"] > 0 else "never back"
        print(f"    departure at X={r['x']} Y={r['y']} carrying {r['a']} km2 ({back})")
    ref = metrics["q4_reference"]
    print(f"=== Q4 fill raise (cond - {ref}, lakes excluded) ===")
    for g in ("channel", "hillslope"):
        print(
            f"  {g}: {q4[f'q4_n_raised_gt_1cm_{g}']}/{q4[f'q4_n_{g}_cells']} raised > 1 cm "
            f"({q4[f'q4_frac_raised_gt_1cm_{g}']:.1%}, mean of those "
            f"{q4[f'q4_mean_raise_gt_1cm_{g}_m']} m, max {q4[f'q4_max_raise_{g}_m']} m)"
        )
    print(
        f"  violations vs pre-fill > 1 cm: {metrics['q4_n_negative_gt_1cm_vs_prefill']} "
        f"(max {metrics['q4_max_negative_delta_vs_prefill_m']} m); vs raw (corridor of "
        f"{len(corridor)} cells excluded): {metrics['q4raw_n_negative_gt_1cm']} > 1 cm "
        f"(max {metrics['q4raw_max_negative_delta_m']} m)"
    )
    print("=== depressions (baseline tie-out) ===")
    pre_pits = cnt_prefill["pits"] if cnt_prefill else "n/a"
    print(
        f"  conditioned: pits={cnt_cond['pits']} flats={cnt_cond['flats']} "
        f"lakebed={cnt_cond['lakebed_minima']} | pre-fill pits={pre_pits} | "
        f"raw-sample pits={cnt_uncond['pits']}"
    )
    print(f"\nJSON: {json_path}\nHTML: {html_path}")


_HTML_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mesh flow QC - channels, gaps, inversions, accumulation</title>
<style>
  :root{--bg:#0f1115;--pan:#171a21;--ink:#e8eaed;--mut:#9aa3af;--line:#2a2f3a}
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
    font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
  #wrap{display:flex;height:100%}
  #cv{flex:1;display:block;cursor:grab;background:#0b0d11}
  #cv.grabbing{cursor:grabbing}
  #side{width:320px;flex:none;background:var(--pan);border-left:1px solid var(--line);
    padding:14px 16px;overflow:auto}
  h1{font-size:15px;margin:0 0 4px}
  .sub{color:var(--mut);font-size:12px;margin-bottom:10px}
  .kpi{display:flex;gap:6px;margin:8px 0;flex-wrap:wrap}
  .card{flex:1;min-width:80px;background:#0f1219;border:1px solid var(--line);
    border-radius:8px;padding:7px 5px;text-align:center}
  .card b{display:block;font-size:17px;line-height:1.1}
  .card.ok b{color:#34d399}.card.bad b{color:#f87171}.card span{font-size:10px;color:var(--mut)}
  .leg{margin:10px 0;border-top:1px solid var(--line);padding-top:10px}
  .leg div{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:12px}
  .sw{width:18px;height:11px;border-radius:3px;flex:none}
  .btn{background:#1f2430;border:1px solid var(--line);color:var(--ink);border-radius:6px;
    padding:5px 10px;font-size:12px;cursor:pointer;margin:4px 4px 0 0}
  #read{margin-top:10px;font-size:12px;background:#0f1219;border:1px solid var(--line);
    border-radius:8px;padding:8px 10px;min-height:64px;white-space:pre-line}
  .list{margin-top:10px}
  .list h2{font-size:12px;margin:8px 0 4px;color:var(--mut)}
  .list button{display:block;width:100%;text-align:left;border-radius:6px;padding:4px 8px;
    margin:3px 0;font-size:11px;cursor:pointer;border:1px solid}
  .g button{background:#241318;color:#fca5a5;border-color:#7f1d1d}
  .i button{background:#231a10;color:#fcd34d;border-color:#78560f}
  .d button{background:#101a24;color:#7dd3fc;border-color:#0c4a6e}
  #hint{color:var(--mut);font-size:11px;margin-top:10px;border-top:1px solid var(--line);
    padding-top:8px}
  #tip{position:fixed;pointer-events:none;background:#0b0d11ee;border:1px solid var(--line);
    border-radius:6px;padding:6px 9px;font-size:12px;display:none;z-index:9;white-space:pre-line}
</style></head><body>
<div id="wrap">
  <canvas id="cv"></canvas>
  <div id="side">
    <h1>Mesh flow QC</h1>
    <div class="sub">Channel cells colored by mesh accumulation (log). Markers: chain gaps,
      downstream inversions, false thalwegs, network departures.</div>
    <div class="kpi">
      <div class="card" id="c_gap"><b id="k_gap">0</b><span>chain gaps</span></div>
      <div class="card" id="c_inv"><b id="k_inv">0</b><span>inversions</span></div>
      <div class="card" id="c_ft"><b id="k_ft">0</b><span>false thalwegs</span></div>
    </div>
    <div class="kpi">
      <div class="card"><b id="k_cont">0</b><span>channel continuity</span></div>
      <div class="card"><b id="k_nch">0</b><span>channel cells</span></div>
      <div class="card"><b id="k_lak">0</b><span>km2 to lakes</span></div>
    </div>
    <div class="leg">
      <div><span class="sw" style="background:linear-gradient(90deg,#440154,#21918c,#fde725)">
        </span> channel cell, mesh accumulation</div>
      <div><span class="sw" style="background:linear-gradient(90deg,#41694f,#c9c2b6)"></span>
        hillslope cell, conditioned top</div>
      <div><span class="sw" style="background:#1e40af"></span> lake cell (sink)</div>
      <div><span class="sw" style="background:#ef4444"></span> chain gap (not face-adjacent)</div>
      <div><span class="sw" style="background:#f59e0b"></span> inversion (uphill downstream)</div>
      <div><span class="sw" style="background:#e879f9"></span> false thalweg (off-network)</div>
      <div><span class="sw" style="background:#38bdf8"></span> departure (flow leaves network)</div>
    </div>
    <div>
      <button class="btn" id="fit">Fit</button>
      <button class="btn" id="toggleArrows">Arrows</button>
      <button class="btn" id="toggleMarks">Markers</button>
    </div>
    <div id="read">Hover a cell.</div>
    <div class="list g" id="gaps"><h2>Gaps</h2></div>
    <div class="list i" id="invs"><h2>Inversions (conditioned)</h2></div>
    <div class="list d" id="deps"><h2>Departures (by accumulation)</h2></div>
    <div id="hint">Drag = pan, wheel = zoom. Arrows appear when zoomed in.</div>
  </div>
</div>
<div id="tip"></div>
<script>
const D = __DATA__;
const cv=document.getElementById('cv'), ctx=cv.getContext('2d'), tip=document.getElementById('tip');
let showArrows=false, showMarks=true;
const K=D.k;
document.getElementById('k_gap').textContent=K.gaps;
document.getElementById('k_inv').textContent=K.inv_c;
document.getElementById('k_ft').textContent=K.fts;
document.getElementById('k_cont').textContent=(K.cont*100).toFixed(1)+'%';
document.getElementById('k_nch').textContent=K.nch;
document.getElementById('k_lak').textContent=K.acc_lakes.toFixed(1);
document.getElementById('c_gap').classList.add(K.gaps?'bad':'ok');
document.getElementById('c_inv').classList.add(K.inv_c?'bad':'ok');
document.getElementById('c_ft').classList.add(K.fts?'bad':'ok');

let scale=1, ox=0, oy=0;
function resize(){cv.width=cv.clientWidth*devicePixelRatio;cv.height=cv.clientHeight*devicePixelRatio;
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);}
const sx=(x)=>ox+(x-D.xmin)*scale, sy=(y)=>oy+(D.ymax-y)*scale;
function fit(){const w=cv.clientWidth,h=cv.clientHeight,pad=24;
  scale=Math.min((w-2*pad)/(D.xmax-D.xmin),(h-2*pad)/(D.ymax-D.ymin));
  ox=(w-(D.xmax-D.xmin)*scale)/2; oy=(h-(D.ymax-D.ymin)*scale)/2; draw();}

function draw(){
  const w=cv.clientWidth,h=cv.clientHeight; ctx.clearRect(0,0,w,h);
  const cellpx=scale*75;
  for(const c of D.cells){
    const p=c.p; ctx.beginPath();
    ctx.moveTo(sx(D.vx[p[0]]),sy(D.vy[p[0]]));
    for(let a=1;a<p.length;a++) ctx.lineTo(sx(D.vx[p[a]]),sy(D.vy[p[a]]));
    ctx.closePath();
    ctx.fillStyle=c.c; ctx.fill();
    if(cellpx>4){ctx.lineWidth=0.3;ctx.strokeStyle='rgba(0,0,0,0.35)';ctx.stroke();}
  }
  if(showArrows&&cellpx>10){
    ctx.strokeStyle='rgba(10,12,18,0.85)'; ctx.lineWidth=Math.max(0.7,cellpx*0.05);
    ctx.beginPath();
    for(const c of D.cells){
      if(c.tx===undefined) continue;
      const x=sx(c.x),y=sy(c.y);
      if(x<-20||y<-20||x>w+20||y>h+20) continue;
      let ex=sx(c.tx),ey=sy(c.ty);
      const dx=ex-x,dy=ey-y,L=Math.hypot(dx,dy)||1,f=Math.min(1,(cellpx*0.5)/L);
      ex=x+dx*f; ey=y+dy*f;
      const hd=Math.min(cellpx*0.2,5), a=Math.atan2(ey-y,ex-x);
      ctx.moveTo(x,y);ctx.lineTo(ex,ey);
      ctx.moveTo(ex,ey);ctx.lineTo(ex-hd*Math.cos(a-0.5),ey-hd*Math.sin(a-0.5));
      ctx.moveTo(ex,ey);ctx.lineTo(ex-hd*Math.cos(a+0.5),ey-hd*Math.sin(a+0.5));
    }
    ctx.stroke();
  }
  if(!showMarks) return;
  for(const r of D.fts){
    const x=sx(r.x),y=sy(r.y);
    if(x<-10||y<-10||x>w+10||y>h+10) continue;
    ctx.strokeStyle='#e879f9';ctx.lineWidth=1.4;
    ctx.beginPath();ctx.arc(x,y,Math.max(3,cellpx*0.3),0,7);ctx.stroke();
  }
  for(const r of D.deps){
    const x=sx(r.x),y=sy(r.y);
    if(x<-10||y<-10||x>w+10||y>h+10) continue;
    const s=Math.max(3.5,cellpx*0.25);
    ctx.fillStyle='#38bdf8';ctx.strokeStyle='#000';ctx.lineWidth=1;
    ctx.save();ctx.translate(x,y);ctx.rotate(Math.PI/4);
    ctx.fillRect(-s/2,-s/2,s,s);ctx.strokeRect(-s/2,-s/2,s,s);ctx.restore();
  }
  for(const r of D.invs){
    const x=sx(r.x),y=sy(r.y);
    if(x<-10||y<-10||x>w+10||y>h+10) continue;
    const s=Math.max(4,Math.min(cellpx*0.4,6+r.m*2));
    ctx.fillStyle='#f59e0b';ctx.strokeStyle='#000';ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(x,y-s);ctx.lineTo(x-s*0.87,y+s*0.5);
    ctx.lineTo(x+s*0.87,y+s*0.5);ctx.closePath();ctx.fill();ctx.stroke();
  }
  for(const r of D.gaps){
    const x1=sx(r.x1),y1=sy(r.y1),x2=sx(r.x2),y2=sy(r.y2);
    if(Math.min(x1,x2)>w+20||Math.max(x1,x2)<-20) continue;
    ctx.strokeStyle='#ef4444';ctx.lineWidth=2;ctx.setLineDash([4,3]);
    ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();ctx.setLineDash([]);
    const x=sx(r.x),y=sy(r.y),s=Math.max(4.5,cellpx*0.3);
    ctx.fillStyle=r.terminal?'#fb923c':'#ef4444';ctx.strokeStyle='#000';ctx.lineWidth=1.2;
    ctx.fillRect(x-s/2,y-s/2,s,s);ctx.strokeRect(x-s/2,y-s/2,s,s);
  }
}

function pick(px,py){
  let best=-1,bd=1e18;
  for(let i=0;i<D.cells.length;i++){
    const c=D.cells[i], dx=sx(c.x)-px, dy=sy(c.y)-py, d=dx*dx+dy*dy;
    if(d<bd){bd=d;best=i;}
  }
  return (bd < (scale*75*0.9)**2 || bd<400) ? best : -1;
}
const KIND=['hillslope','CHANNEL','lake (sink)'];
function hover(e){
  const r=cv.getBoundingClientRect(), i=pick(e.clientX-r.left,e.clientY-r.top);
  if(i<0){tip.style.display='none';document.getElementById('read').textContent='Hover a cell.';return;}
  const c=D.cells[i];
  let s=`X=${c.x.toFixed(0)}  Y=${c.y.toFixed(0)}\\n${KIND[c.k]}`;
  s+=`\\ntop cond = ${c.t} m`;
  if(c.u!==null){s+=`\\npre-fill top = ${c.u} m  (fill raise ${(c.t-c.u).toFixed(2)} m)`;}
  s+=`\\naccumulation = ${c.a} km2`;
  if(c.ft) s+='\\nFALSE THALWEG (off-network concentration)';
  document.getElementById('read').textContent=s;
  tip.textContent=s;tip.style.display='block';
  tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';
}
cv.addEventListener('mouseleave',()=>{tip.style.display='none';});

let drag=null;
cv.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY,ox,oy};cv.classList.add('grabbing');});
window.addEventListener('mouseup',()=>{drag=null;cv.classList.remove('grabbing');});
window.addEventListener('mousemove',e=>{
  if(drag){ox=drag.ox+(e.clientX-drag.x);oy=drag.oy+(e.clientY-drag.y);draw();return;}
  hover(e);
});
cv.addEventListener('wheel',e=>{
  e.preventDefault();
  const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=Math.exp(-e.deltaY*0.0012), wx=(mx-ox)/scale+D.xmin, wy=D.ymax-(my-oy)/scale;
  scale*=f; ox=mx-(wx-D.xmin)*scale; oy=my-(D.ymax-wy)*scale; draw();
},{passive:false});

function flyTo(x,y){scale=Math.max(scale,3.2);
  ox=cv.clientWidth/2-(x-D.xmin)*scale; oy=cv.clientHeight/2-(D.ymax-y)*scale; draw();}
function fillList(id,rows,label){
  const el=document.getElementById(id);
  if(!rows.length){const ok=document.createElement('div');
    ok.style.cssText='color:#34d399;font-size:11.5px;padding:2px 0';
    ok.textContent='none';el.appendChild(ok);return;}
  for(const r of rows.slice(0,40)){
    const b=document.createElement('button');
    b.textContent=label(r);
    b.onclick=()=>flyTo(r.x,r.y);
    el.appendChild(b);
  }
}
fillList('gaps',D.gaps,r=>`${r.terminal?'terminal ':''}gap fid ${r.fid} `+
  `${r.one_cell?'(1 cell) ':''}X=${r.x.toFixed(0)} Y=${r.y.toFixed(0)}`);
fillList('invs',D.invs,r=>`+${r.m} m uphill  fid ${r.fid}  X=${r.x.toFixed(0)} Y=${r.y.toFixed(0)}`);
fillList('deps',D.deps,r=>`${r.a} km2 leaves network  X=${r.x.toFixed(0)} Y=${r.y.toFixed(0)}`);

document.getElementById('fit').onclick=fit;
document.getElementById('toggleArrows').onclick=()=>{showArrows=!showArrows;draw();};
document.getElementById('toggleMarks').onclick=()=>{showMarks=!showMarks;draw();};
window.addEventListener('resize',()=>{resize();draw();});
resize(); fit();
</script></body></html>"""


if __name__ == "__main__":
    main()
