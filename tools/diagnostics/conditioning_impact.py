"""Impact analysis of mesh-top conditioning: how much is the DEM modified?

For each conditioned MODFLOW 6 solver directory this samples the RAW DEM at the
cell generators (the naive bilinear projection = the unconditioned reference) and
maps the per-cell delta ``conditioned_top - raw``. It renders a signed error map
(blue = lowered by conditioning, red = raised), a magnitude map, a histogram and
volume/area statistics, so the modification by zonal sampling + priority-flood
fill + channel breach is visible and quantified. Lake cells are excluded from the
aquifer map (their top is the carved bathymetric bed, a large legitimate delta)
and reported separately.

Standalone (no hydromodpy import); reuses the QC tool's mesh loader.

Example:
    python tools/diagnostics/conditioning_impact.py \
        --raw-dem examples/data/dem/DEM_cheze_5m.tif --out /tmp/impact \
        centroid=.../preretenue_5m.v8 zonal=.../v9 breach=.../v11
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib  # noqa: E402
from mesh_flow_qc import load_mesh, sample_raw_dem  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402

_MOD_TOL_M = 0.01  # a cell counts as "modified" above 1 cm


def analyze(solver_dir: str, raw_dem: str) -> dict:
    """Return the per-cell delta and statistics for one conditioned mesh."""
    mesh = load_mesh(solver_dir)
    raw = sample_raw_dem(raw_dem, mesh.xc, mesh.yc)
    delta = mesh.top - raw
    lake = np.zeros(mesh.ncpl, dtype=bool)
    if mesh.lake_cells:
        lake[np.fromiter(mesh.lake_cells, dtype=int)] = True
    aquifer = mesh.active & ~lake & np.isfinite(delta)

    d = delta[aquifer]
    areas = mesh.areas[aquifer]
    up = d > _MOD_TOL_M
    down = d < -_MOD_TOL_M
    stats = {
        "n_active": int(mesh.active.sum()),
        "n_aquifer": int(aquifer.sum()),
        "n_lake": int(lake.sum()),
        "n_raised": int(up.sum()),
        "n_lowered": int(down.sum()),
        "frac_modified": float((up | down).mean()) if d.size else 0.0,
        "mean_abs_delta_m": float(np.abs(d).mean()) if d.size else 0.0,
        "p95_abs_delta_m": float(np.percentile(np.abs(d), 95)) if d.size else 0.0,
        "max_raise_m": float(d.max(initial=0.0)),
        "max_lower_m": float(-d.min(initial=0.0)),
        "mean_raise_m": float(d[up].mean()) if up.any() else 0.0,
        "mean_lower_m": float(-d[down].mean()) if down.any() else 0.0,
        # Signed change of DEM material moved, m3 (raised volume - carved volume).
        "raised_volume_m3": float((d[up] * areas[up]).sum()) if up.any() else 0.0,
        "carved_volume_m3": float((-d[down] * areas[down]).sum()) if down.any() else 0.0,
        "lake_mean_delta_m": float(np.nanmean(delta[lake])) if lake.any() else 0.0,
    }
    return {"mesh": mesh, "delta": delta, "aquifer": aquifer, "lake": lake, "stats": stats}


def _cell_polygons(mesh, cells: np.ndarray) -> list[np.ndarray]:
    out = []
    for i in cells:
        ring = [
            (float(mesh.verts[int(v), 0]), float(mesh.verts[int(v), 1])) for v in mesh.iverts[i]
        ]
        out.append(np.asarray(ring))
    return out


def render_map(res: dict, title: str, vlim: float, out_png: str) -> None:
    """Signed delta map (RdBu) over aquifer cells; lakes greyed; histogram inset."""
    mesh, delta, aquifer, lake = res["mesh"], res["delta"], res["aquifer"], res["lake"]
    fig, ax = plt.subplots(figsize=(9, 8))
    lake_cells = np.flatnonzero(lake & mesh.active)
    if lake_cells.size:
        ax.add_collection(
            PolyCollection(
                _cell_polygons(mesh, lake_cells), facecolors="#9fb3c8", edgecolors="none"
            )
        )
    aq = np.flatnonzero(aquifer)
    pc = PolyCollection(_cell_polygons(mesh, aq), array=delta[aq], cmap="RdBu_r", edgecolors="none")
    pc.set_clim(-vlim, vlim)
    ax.add_collection(pc)
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=12)
    ax.set_xticks([])
    ax.set_yticks([])
    cb = fig.colorbar(pc, ax=ax, shrink=0.7, pad=0.02)
    cb.set_label("conditioned - raw DEM  (m)   red = raised, blue = lowered")

    d = delta[aquifer]
    iax = ax.inset_axes([0.02, 0.02, 0.34, 0.20])
    iax.hist(np.clip(d, -vlim, vlim), bins=60, color="#4a4a4a")
    iax.axvline(0, color="k", lw=0.6)
    iax.set_yticks([])
    iax.tick_params(labelsize=7)
    iax.set_title("delta (m)", fontsize=7)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130, bbox_inches="tight")
    plt.close(fig)


def _b64(path: str) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("variants", nargs="+", help="label=solver_dir pairs")
    p.add_argument("--raw-dem", required=True)
    p.add_argument("--out", default="impact_out")
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)

    results = {}
    for spec in args.variants:
        label, _, sdir = spec.partition("=")
        print(f"[impact] {label}: {sdir}")
        results[label] = analyze(sdir, args.raw_dem)

    # One symmetric colour scale across variants for honest comparison.
    vlim = max(float(np.percentile(np.abs(r["delta"][r["aquifer"]]), 99)) for r in results.values())
    vlim = max(vlim, 0.5)

    pngs = {}
    for label, r in results.items():
        s = r["stats"]
        title = (
            f"{label}  |  {s['frac_modified'] * 100:.1f}% modified  "
            f"(-{s['max_lower_m']:.1f} m .. +{s['max_raise_m']:.1f} m, "
            f"mean|d| {s['mean_abs_delta_m']:.2f} m)"
        )
        out_png = os.path.join(args.out, f"impact_{label}.png")
        render_map(r, title, vlim, out_png)
        pngs[label] = out_png

    stats = {label: r["stats"] for label, r in results.items()}
    with open(os.path.join(args.out, "impact_stats.json"), "w") as fh:
        json.dump({"vlim_m": vlim, "variants": stats}, fh, indent=2)

    # Self-contained HTML report with the maps embedded.
    rows = "".join(
        f"<tr><td>{k}</td>"
        + "".join(
            f"<td>{stats[v].get(k, ''):.3g}</td>"
            if isinstance(stats[v].get(k), float)
            else f"<td>{stats[v].get(k, '')}</td>"
            for v in results
        )
        + "</tr>"
        for k in next(iter(stats.values()))
    )
    header = "".join(f"<th>{v}</th>" for v in results)
    imgs = "".join(
        f'<figure><img src="data:image/png;base64,{_b64(pngs[v])}"/></figure>' for v in results
    )
    html = (
        "<style>body{font-family:system-ui;margin:20px}img{max-width:100%}"
        "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:3px 8px;"
        "font-size:13px}figure{margin:0 0 20px}</style>"
        "<h1>Mesh-top conditioning impact (DEM modification)</h1>"
        f"<p>Common colour scale +/-{vlim:.2f} m. Blue = conditioning lowered the top, "
        "red = raised. Lakes greyed (carved bathymetric bed, reported separately).</p>"
        f"{imgs}<h2>Statistics</h2><table><tr><th>metric</th>{header}</tr>{rows}</table>"
    )
    html_path = os.path.join(args.out, "impact_report.html")
    with open(html_path, "w") as fh:
        fh.write(html)
    print(f"[impact] stats: {os.path.join(args.out, 'impact_stats.json')}")
    print(f"[impact] report: {html_path}")


if __name__ == "__main__":
    main()
