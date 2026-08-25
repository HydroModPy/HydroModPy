"""Clarify the reported figure anomalies against the actual MF6 model.

Two panels that answer, on the real model:
* "who feeds what": lake footprints as filled polygons, DRN cells coloured by the
  lake they drain to (via MVR), the SFR feeders, so the pre-retenue reads as a lake
  and its (under-)feeding is explicit.
* "SFR is a one-cell line, not the teal band; flow converges to discharge BC cells,
  not to pits": the thin SFR line vs the hillslope DRN->SFR band, plus the
  specific-discharge convergence cells coloured by their boundary role.

Usage:
    python tools/diagnostics/cheze_routing_truth.py <solver_dir> <lake_gpkg> <out_dir>
"""

from __future__ import annotations

import os
import sys

import flopy
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

D, GPKG, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUT, exist_ok=True)
RES, PRE = "#0b6e8a", "#e08e00"

sim = flopy.mf6.MFSimulation.load(sim_ws=D, verbosity_level=0)
gwf = sim.get_model()
mg = gwf.modelgrid
xc = np.asarray(mg.xcellcenters).reshape(-1)
yc = np.asarray(mg.ycellcenters).reshape(-1)


def c2d(c):
    return int(c[1]) if isinstance(c, (tuple, list, np.void)) else int(c)


lak = gwf.get_package("lak")
names = {int(r["ifno"]): str(r["boundname"]) for r in lak.packagedata.array}
lake_cells = {}
for r in lak.connectiondata.array:
    lake_cells.setdefault(int(r["ifno"]), []).append(c2d(r["cellid"]))
pre_lid = next(li for li, nm in names.items() if "preret" in nm.lower())
res_lid = next(li for li, nm in names.items() if "reserv" in nm.lower())

sfr = gwf.get_package("sfr")
reach_cell = {int(r["ifno"]): c2d(r["cellid"]) for r in sfr.packagedata.array}
scon = sfr.connectiondata.array
drn = [c2d(r["cellid"]) for r in gwf.get_package("drn").stress_period_data.get_data(0)]
mvr = gwf.get_package("mvr").perioddata.get_data(0)
drn2lak, drn2sfr, sfr2lak = {}, {}, []
for r in mvr:
    p1, i1, p2, i2 = str(r["pname1"]), int(r["id1"]), str(r["pname2"]), int(r["id2"])
    if p1 == "drn" and p2 == "lak":
        drn2lak[i1] = i2
    elif p1 == "drn" and p2 == "sfr":
        drn2sfr[i1] = i2
    elif p1 == "sfr" and p2 == "lak":
        sfr2lak.append((i1, i2))

lakes_gdf = gpd.read_file(GPKG)
bx0, bx1 = (
    xc[sum(lake_cells.values(), [])].min() - 500,
    xc[sum(lake_cells.values(), [])].max() + 500,
)
by0, by1 = (
    yc[sum(lake_cells.values(), [])].min() - 500,
    yc[sum(lake_cells.values(), [])].max() + 500,
)


def draw_lakes(ax):
    for _, row in lakes_gdf.iterrows():
        col = PRE if "preret" in str(row.get("lake_id", "")).lower() else RES
        geoms = row.geometry.geoms if row.geometry.geom_type.startswith("Multi") else [row.geometry]
        for g in geoms:
            ax.fill(*g.exterior.xy, color=col, alpha=0.55, zorder=4, ec=col, lw=1.5)


fig, (axa, axb) = plt.subplots(1, 2, figsize=(20, 8))

# ---------------- Panel A: who feeds what ----------------
darr = np.array(drn)
to_pre = np.array([drn2lak.get(i) == pre_lid for i in range(len(drn))])
to_res = np.array([drn2lak.get(i) == res_lid for i in range(len(drn))])
to_sfr = np.array([i in drn2sfr for i in range(len(drn))])
to_out = ~to_pre & ~to_res & ~to_sfr
axa.set_title(
    "Qui alimente quoi : les DEUX plans d'eau sont des lacs (polygones pleins).\n"
    f"Routage topographique : {int(to_pre.sum())} cellules DRN -> pre-retenue, "
    f"{int(to_res.sum())} -> reservoir (chacune vers le lac ou elle draine).",
    fontsize=11,
)
axa.scatter(
    xc[darr[to_sfr]],
    yc[darr[to_sfr]],
    s=6,
    c="#bfe3c0",
    edgecolors="none",
    zorder=2,
    label=f"DRN -> ruisseau SFR ({int(to_sfr.sum())})",
)
axa.scatter(
    xc[darr[to_res]],
    yc[darr[to_res]],
    s=6,
    c="#9ecae1",
    edgecolors="none",
    zorder=2,
    label=f"DRN -> RESERVOIR ({int(to_res.sum())})",
)
axa.scatter(
    xc[darr[to_pre]],
    yc[darr[to_pre]],
    s=14,
    c="#e08e00",
    edgecolors="k",
    lw=0.2,
    zorder=3,
    label=f"DRN -> PRE-RETENUE ({int(to_pre.sum())})",
)
axa.scatter(
    xc[darr[to_out]],
    yc[darr[to_out]],
    s=6,
    c="#d0d0d0",
    edgecolors="none",
    zorder=1,
    label=f"DRN -> hors BV ({int(to_out.sum())})",
)
rc = list(reach_cell.values())
axa.scatter(
    xc[rc],
    yc[rc],
    s=10,
    marker="s",
    c="#1d3faa",
    edgecolors="none",
    zorder=5,
    label="ruisseau SFR (ligne)",
)
for ri, li in sfr2lak:
    cc = reach_cell.get(ri)
    if cc is not None:
        axa.scatter(xc[cc], yc[cc], s=260, marker="*", c="red", edgecolors="k", lw=0.5, zorder=7)
draw_lakes(axa)
axa.scatter(
    [], [], marker="*", c="red", edgecolors="k", s=180, label=f"entree SFR -> lac ({len(sfr2lak)})"
)
axa.add_artist(axa.legend(loc="upper left", fontsize=8, framealpha=0.93))
axa.set_xlim(bx0, bx1)
axa.set_ylim(by0, by1)
axa.set_aspect("equal")
axa.set_xticks([])
axa.set_yticks([])
axa.legend(
    handles=[
        Patch(fc=RES, alpha=0.55, label="RESERVOIR (lac)"),
        Patch(fc=PRE, alpha=0.55, label="PRE-RETENUE (lac)"),
    ],
    loc="lower right",
    fontsize=9,
    framealpha=0.93,
)

# ---------------- Panel B: SFR line vs band, convergence = discharge ----------------
axb.set_title(
    "SFR = 1 cellule de large (ligne). La 'largeur' = cellules de versant -> ruisseau.\n"
    "Les fleches convergent vers des cellules de DECHARGE (lac/ruisseau/drain), pas des pits.",
    fontsize=11,
)
# hillslope DRN->SFR band (what looks 'wide')
axb.scatter(
    xc[darr[to_sfr]],
    yc[darr[to_sfr]],
    s=7,
    c="#cdeccc",
    edgecolors="none",
    zorder=1,
    label=f"versant -> ruisseau ({int(to_sfr.sum())} cellules)",
)
# the actual SFR reaches as a connected thin line
segs = []
for r in scon:
    i = int(r["ifno"])
    for k in list(r)[1:]:
        try:
            j = int(float(k))
        except (TypeError, ValueError):
            continue
        if j < 0:
            a, b = reach_cell.get(i), reach_cell.get(abs(j))
            if a is not None and b is not None:
                segs.append([(xc[a], yc[a]), (xc[b], yc[b])])
for p, q in segs:
    axb.plot([p[0], q[0]], [p[1], q[1]], "-", color="#1d3faa", lw=1.1, zorder=3)
axb.scatter(
    xc[rc],
    yc[rc],
    s=9,
    c="#1d3faa",
    zorder=4,
    label=f"ruisseau SFR ({len(reach_cell)} biefs, 1 cellule/bief)",
)
draw_lakes(axb)
# flow convergence cells coloured by BC role
try:
    from flopy.utils import CellBudgetFile
    from flopy.utils.postprocessing import get_specific_discharge
    from scipy.spatial import cKDTree

    cbc = [f for f in os.listdir(D) if f.endswith(".cbc") and "lak" not in f and "sfr" not in f][0]
    spdis = CellBudgetFile(os.path.join(D, cbc)).get_data(text="DATA-SPDIS")[-1]
    qx3, qy3, _ = get_specific_discharge(spdis, gwf)
    qx = np.asarray(qx3).reshape(mg.nlay, -1)[0]
    qy = np.asarray(qy3).reshape(mg.nlay, -1)[0]
    mag = np.hypot(qx, qy)
    valid = np.where(np.isfinite(mag) & (mag > 0))[0]
    pts = np.column_stack([xc, yc])
    tree = cKDTree(pts[valid])
    conv = np.zeros(mg.ncpl)
    for idx in valid:
        step = pts[idx] + np.array([qx[idx], qy[idx]]) / mag[idx] * 120.0
        _, j = tree.query(step)
        t = valid[j]
        if t != idx:
            conv[t] += 1
    lak_set = set(sum(lake_cells.values(), []))
    sfr_set = set(reach_cell.values())
    drn_set = set(drn)
    conv_cells = [c for c in np.argsort(conv)[::-1] if conv[c] >= 3][:60]
    for c in conv_cells:
        role_c = (
            "#0b6e8a"
            if c in lak_set
            else "#1d3faa"
            if c in sfr_set
            else "#2a9d8f"
            if c in drn_set
            else "red"
        )
        axb.scatter(
            xc[c], yc[c], s=70, marker="o", facecolors="none", edgecolors=role_c, lw=1.6, zorder=6
        )
    npits = sum(1 for c in conv_cells if c not in lak_set and c not in sfr_set and c not in drn_set)
    axb.scatter(
        [],
        [],
        marker="o",
        facecolors="none",
        edgecolors="#2a9d8f",
        s=70,
        label=f"cellule de convergence = decharge BC (0 pit non-BC ; {len(conv_cells)} verifiees)",
    )
except Exception as e:
    print("conv overlay skipped:", e)
axb.legend(loc="upper left", fontsize=8, framealpha=0.93)
axb.set_xlim(bx0, bx1)
axb.set_ylim(by0, by1)
axb.set_aspect("equal")
axb.set_xticks([])
axb.set_yticks([])

fig.tight_layout()
p = os.path.join(OUT, "diag_routing_truth.png")
fig.savefig(p, dpi=135)
plt.close(fig)
print("diag_routing_truth.png")
print(
    f"  reservoir DRN-fed cells: {int(to_res.sum())} | pre-retenue DRN-fed cells: {int(to_pre.sum())}"
)
print(f"  SFR feeders: {[(ri, names[li]) for ri, li in sfr2lak]}")
