"""Cheze model diagnostic figures, built against the kept MF6 files.

Run: python tools/diagnostics/cheze_mf6_diagnostics.py <solver_dir> <figures_dir>
(the solver dir must keep the MF6 files -- run with `--until RunSolverStep`).

Produces, against the current model:
* diag_sfr_routing      SFR reaches + flow direction + shoreline SFR->LAK entries + spillway
* diag_drn_routing      DRN cells by destination (nearest downslope SFR / direct LAK / out)
* diag_flow_arrows      Voronoi grid + specific-discharge arrows
* diag_hfb_voile        cutoff wall aerial + cross-section (impervious dam band)
* diag_grid_refinement  Voronoi grid coloured by local cell size
* diag_voile_detail     surveyed cutoff-wall trace -> continuous HFB face chain
* diag_sill_exchange    inter-lake sill: adjacency (where flow passes) + weir schematic
* diag_cell_roles       every cell by role: SFR, DRN by destination (1 SFR / 2 lake /
                        3 out of BV), red outlet -> lake, blue outlet -> out of model
* diag_cross_section    vertical section reservoir -> dam -> outlet: aquifer layers,
                        lake water column + bed, and the HFB voile depth
"""

import os
import sys

import flopy
import matplotlib
import numpy as np

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

D, OUT = sys.argv[1], sys.argv[2]
# Optional 3rd arg: the project TOML, so the voile-detail figure overlays the
# cutoff-wall trace ACTUALLY declared in the config (inline `line` or a
# `line_path` file), not a guessed external file.
PROJECT_TOML = sys.argv[3] if len(sys.argv) > 3 else None
os.makedirs(OUT, exist_ok=True)
sim = flopy.mf6.MFSimulation.load(sim_ws=D, verbosity_level=0)
gwf = sim.get_model()
mg = gwf.modelgrid
xc = np.asarray(mg.xcellcenters).reshape(-1)
yc = np.asarray(mg.ycellcenters).reshape(-1)


def config_cutoff_wall_lines(project_toml):
    """Return (label, geometry, kind) cutoff-wall sources declared in the project.

    kind is 'inline' (from `line`) or the source filename (from `line_path`).
    Files resolve against the project dir and the <workspace>/data/cutoff_wall
    directory (projects live at <workspace>/projects/<name>/).
    """
    if project_toml is None:
        return []
    import tomllib

    from shapely.geometry import LineString

    with open(project_toml, "rb") as fh:
        cfg = tomllib.load(fh)
    base = os.path.dirname(os.path.abspath(project_toml))
    ws_data = os.path.normpath(os.path.join(base, "..", "..", "data", "cutoff_wall"))
    lakes = cfg.get("flow", {}).get("sinks_sources", {}).get("lakes", {})
    out = []
    for lid, lake in lakes.items():
        cw = lake.get("cutoff_wall") if isinstance(lake, dict) else None
        if not isinstance(cw, dict):
            continue
        if cw.get("line") is not None:
            out.append((f"ligne config (inline) : {lid}", LineString(cw["line"]), "inline"))
        elif cw.get("line_path"):
            import geopandas as gpd

            p = cw["line_path"]
            for cand in (p, os.path.join(ws_data, p), os.path.join(base, p)):
                if os.path.exists(cand):
                    geom = gpd.read_file(cand).union_all()
                    out.append((f"trace config ({os.path.basename(p)}) : {lid}", geom, p))
                    break
    return out


def c2d(cellid):
    return int(cellid[1]) if isinstance(cellid, (tuple, list, np.void)) else int(cellid)


# ---- parse packages ----
sfr = gwf.get_package("sfr")
spd = sfr.packagedata.get_data()
scon = sfr.connectiondata.get_data()
reach_cell = {int(r["ifno"]): c2d(r["cellid"]) for r in spd}
lak = gwf.get_package("lak")
lcd = lak.connectiondata.get_data()
outl = lak.outlets.get_data()
lake_cells = {0: [], 1: []}
for r in lcd:
    lake_cells[int(r["ifno"])].append(c2d(r["cellid"]))
drn = gwf.get_package("drn")
dcells = [c2d(r["cellid"]) for r in drn.stress_period_data.get_data(0)]
mvr = gwf.get_package("mvr")
mspd = mvr.perioddata.get_data(0)
drn2sfr = {}  # drn provider index -> sfr reach id
drn2lak = {}  # drn provider index -> lake number (direct DRN -> LAK)
sfr2lak = []  # (reach id, lake id)
for r in mspd:
    p1, i1, p2, i2 = str(r["pname1"]), int(r["id1"]), str(r["pname2"]), int(r["id2"])
    if p1 == "drn" and p2 == "sfr":
        drn2sfr[i1] = i2
    if p1 == "drn" and p2 == "lak":
        drn2lak[i1] = i2
    if p1 == "sfr" and p2 == "lak":
        sfr2lak.append((i1, i2))
hfb = gwf.get_package("hfb")
hspd = hfb.stress_period_data.get_data(0)

# dam position = centroid of the HFB (cutoff-wall) cells, not a hard-coded guess.
hfb_cells = sorted({c2d(h["cellid1"]) for h in hspd} | {c2d(h["cellid2"]) for h in hspd})
dam_x, dam_y = float(np.mean(xc[hfb_cells])), float(np.mean(yc[hfb_cells]))

# bbox to zoom on the model (lakes + dam)
allc = sum(lake_cells.values(), []) + list(reach_cell.values())
bx0, bx1 = xc[allc].min() - 400, xc[allc].max() + 400
by0, by1 = yc[allc].min() - 400, yc[allc].max() + 400


def base_ax(ax, title):
    pmv = flopy.plot.PlotMapView(model=gwf, ax=ax, layer=0)
    pmv.plot_grid(lw=0.15, color="0.82")
    ax.set_xlim(bx0, bx1)
    ax.set_ylim(by0, by1)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=11)
    ax.set_xticks([])
    ax.set_yticks([])
    return pmv


RES, PRE = "#0b6e8a", "#e08e00"

# ===================== FIG 1: SFR routing + lake entry + sills =====================
fig, ax = plt.subplots(figsize=(11, 8))
base_ax(ax, "Routage SFR : biefs, sens d'ecoulement, entrees dans les lacs, seuils")
# lakes
for lid, col, name in [(0, RES, "reservoir"), (1, PRE, "pre-retenue")]:
    cc = lake_cells[lid]
    ax.scatter(
        xc[cc], yc[cc], s=8, c=col, alpha=0.5, edgecolors="none", zorder=2, label=f"lac {name}"
    )
# SFR reaches + downstream arrows (negative connection = downstream)
segs = []
for r in scon:
    i = int(r["ifno"])
    for k in list(r)[1:]:
        if k is None:
            continue
        try:
            fk = float(k)
        except (TypeError, ValueError):
            continue
        if np.isnan(fk):
            continue
        j = int(fk)
        if j < 0:  # downstream connection (MF6 sign convention)
            a = reach_cell.get(i)
            b = reach_cell.get(abs(j))
            if a is not None and b is not None:
                segs.append([(xc[a], yc[a]), (xc[b], yc[b])])
# reaches coloured by streambed elevation: the flow goes from LIGHT (high, upstream)
# to DARK (low, downstream), so the direction reads at a glance.
rtp = {int(r["ifno"]): float(r["rtp"]) for r in spd}
rc_ids = list(reach_cell.keys())
rc_cells = [reach_cell[i] for i in rc_ids]
# thin arrows first (drawn UNDER the dots) so the elevation gradient stays readable.
for p, q in segs:
    dlen = ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5
    props = (
        dict(arrowstyle="->", color="0.35", lw=0.5, alpha=0.7)
        if dlen < 300
        else dict(arrowstyle="->", color="0.6", lw=0.6, alpha=0.4, linestyle="dashed")
    )
    ax.annotate("", xy=q, xytext=p, zorder=3, arrowprops=props)
sc = ax.scatter(
    xc[rc_cells],
    yc[rc_cells],
    s=22,
    c=[rtp[i] for i in rc_ids],
    cmap="viridis",
    zorder=4,
    edgecolors="none",
)
fig.colorbar(
    sc, ax=ax, shrink=0.5, label="cote du lit SFR (m NGF) : flux du clair (amont) au fonce (aval)"
)
# SFR -> LAK entry points (the shoreline movers)
for ri, li in sfr2lak:
    rc = reach_cell.get(ri)
    if rc is None:
        continue
    ax.scatter(xc[rc], yc[rc], s=140, marker="*", c="#c1272d", edgecolors="k", lw=0.4, zorder=6)
# outlets / sills
for o in outl:
    inv = float(o["invert"])
    lin = int(o["lakein"])
    lout = int(o["lakeout"])
    if lout == -1:  # spillway leaves model
        ax.scatter(dam_x, dam_y + 60, s=200, marker="v", c="red", edgecolors="k", zorder=7)
        ax.annotate(
            f"deversoir {inv:.2f} m -> hors modele",
            (dam_x, dam_y + 60),
            xytext=(dam_x - 1500, dam_y + 500),
            fontsize=8,
            color="red",
            arrowprops=dict(arrowstyle="->", color="red"),
        )
    else:  # sill between lakes
        ax.annotate(
            f"seuil {inv:.2f} m (lac{lin + 1}<->lac{lout + 1})",
            (dam_x, dam_y),
            xytext=(dam_x - 2600, dam_y - 300),
            fontsize=8,
            color="#8a5a00",
            arrowprops=dict(arrowstyle="->", color="#8a5a00"),
        )
h = [
    Line2D(
        [],
        [],
        marker="*",
        ls="",
        mfc="#c1272d",
        mec="k",
        ms=13,
        label=f"entree SFR->lac ({len(sfr2lak)})",
    ),
    Line2D([], [], marker="v", ls="", mfc="red", mec="k", ms=9, label="deversoir (hors modele)"),
    Line2D([], [], marker="o", ls="", mfc=RES, ms=7, label="reservoir"),
    Line2D([], [], marker="o", ls="", mfc=PRE, ms=7, label="pre-retenue"),
]
ax.legend(handles=h, loc="upper left", fontsize=8, framealpha=0.9)
fig.tight_layout()
fig.savefig(f"{OUT}/diag_sfr_routing.png", dpi=130)
plt.close()
print("diag_sfr_routing.png")

# ===================== FIG 2: DRN routing by destination =====================
fig, ax = plt.subplots(figsize=(11, 8))
base_ax(ax, "Cellules DRN : destination du drainage (SFR aval / LAK / hors modele)")
dcells_arr = np.array(dcells)
to_sfr = np.array([i in drn2sfr for i in range(len(dcells))])
to_lak = np.array([i in drn2lak for i in range(len(dcells))])
plain = ~to_sfr & ~to_lak
ax.scatter(
    xc[dcells_arr[plain]],
    yc[dcells_arr[plain]],
    s=7,
    c="#b0b0b0",
    edgecolors="none",
    zorder=2,
    label=f"DRN plain -> hors modele ({int(plain.sum())})",
)
ax.scatter(
    xc[dcells_arr[to_sfr]],
    yc[dcells_arr[to_sfr]],
    s=7,
    c="#2a9d8f",
    edgecolors="none",
    zorder=3,
    label=f"DRN -> bief SFR aval par MVR ({int(to_sfr.sum())})",
)
ax.scatter(
    xc[dcells_arr[to_lak]],
    yc[dcells_arr[to_lak]],
    s=7,
    c="#c1272d",
    edgecolors="none",
    zorder=3,
    label=f"DRN -> LAK direct ({int(to_lak.sum())})",
)
# a subsample of DRN->SFR arrows
idx = list(drn2sfr.items())[::40]
for di, ri in idx:
    a = dcells[di]
    b = reach_cell.get(ri)
    if b is None:
        continue
    ax.annotate(
        "",
        xy=(xc[b], yc[b]),
        xytext=(xc[a], yc[a]),
        zorder=4,
        arrowprops=dict(arrowstyle="->", color="#177a6c", lw=0.5, alpha=0.5),
    )
for lid, col in [(0, RES), (1, PRE)]:
    ax.scatter(xc[lake_cells[lid]], yc[lake_cells[lid]], s=6, c=col, alpha=0.35, zorder=1)
ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
fig.tight_layout()
fig.savefig(f"{OUT}/diag_drn_routing.png", dpi=130)
plt.close()
print("diag_drn_routing.png")

# ===================== FIG 3: grid + flow arrows (specific discharge) =====================
fig, ax = plt.subplots(figsize=(11, 8))
base_ax(ax, "Grille Voronoi + fleches d'ecoulement (debit specifique, couche 0)")
try:
    from flopy.utils import CellBudgetFile
    from flopy.utils.postprocessing import get_specific_discharge

    cbc = CellBudgetFile(
        [
            os.path.join(D, f)
            for f in os.listdir(D)
            if f.endswith(".cbc") and "lak" not in f and "sfr" not in f
        ][0]
    )
    spdis = cbc.get_data(text="DATA-SPDIS")[-1]
    # Map SPDIS to the model grid: with a partial idomain the record count is the
    # active-node count (not nlay * ncpl), so a bare reshape breaks. This helper
    # scatters the records back onto the full (nlay, ncpl) grid with NaN elsewhere.
    qx3, qy3, _ = get_specific_discharge(spdis, gwf)
    qx = np.asarray(qx3).reshape(mg.nlay, -1)[0]
    qy = np.asarray(qy3).reshape(mg.nlay, -1)[0]
    mag = np.hypot(qx, qy)
    m = np.isfinite(mag) & (mag > 0)
    sub = np.where(m)[0][::3]
    ax.quiver(
        xc[sub],
        yc[sub],
        qx[sub],
        qy[sub],
        mag[sub],
        cmap="viridis",
        scale=None,
        width=0.002,
        zorder=4,
    )
    print("  flow arrows: SPDIS ok, n=", m.sum())
except Exception as e:
    print("  SPDIS unavailable:", e)
fig.tight_layout()
fig.savefig(f"{OUT}/diag_flow_arrows.png", dpi=130)
plt.close()
print("diag_flow_arrows.png")

# ===================== FIG 4: HFB voile aerial + cross-section =====================
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.5, 1]})
base_ax(ax, "Voile HFB (vue aerienne) : faces barrees")
# zoom near dam
ax.set_xlim(dam_x - 600, dam_x + 600)
ax.set_ylim(dam_y - 500, dam_y + 500)
for lid, col in [(0, RES), (1, PRE)]:
    ax.scatter(xc[lake_cells[lid]], yc[lake_cells[lid]], s=30, c=col, alpha=0.4, zorder=1)
for h in hspd:
    a, b = c2d(h["cellid1"]), c2d(h["cellid2"])
    ax.plot([xc[a], xc[b]], [yc[a], yc[b]], "-", color="k", lw=3, zorder=5)
    mx, my = (xc[a] + xc[b]) / 2, (yc[a] + yc[b]) / 2
    ax.plot(mx, my, "s", color="red", ms=7, zorder=6)
ax.scatter([], [], c="k", marker="_", s=100, label=f"face HFB voile ({len(hspd)})")
ax.legend(loc="upper right", fontsize=9)
# cross-section at the deepest HFB column: aquifer layers + the impervious dam band
top = np.asarray(mg.top).reshape(-1)
botm = np.asarray(mg.botm)
ca = c2d(min(hspd, key=lambda h: botm[-1, c2d(h["cellid1"])])["cellid1"])
for lay in range(mg.nlay):
    lt = top[ca] if lay == 0 else botm[lay - 1, ca]
    ax2.axhspan(
        botm[lay, ca],
        lt,
        color=plt.cm.Blues(0.25 + 0.18 * lay),
        alpha=0.6,
        label=f"couche {lay} (aquifere)",
    )
barred_lay = sorted({int(h["cellid1"][0]) for h in hspd if c2d(h["cellid1"]) == ca})
crest = float(top[ca])
foot = float(botm[max(barred_lay), ca])
ax2.axhspan(
    foot,
    crest,
    color="none",
    ec="red",
    hatch="///",
    lw=2.5,
    label=f"barrage impermeable\n(HFB couches {barred_lay})",
)
ax2.axhline(crest, color="k", ls=":", lw=0.8)
ax2.axhline(foot, color="red", ls="--", lw=0.9)
ax2.annotate(
    f"crete ~{crest:.0f} m (beton)",
    (0.03, crest),
    xycoords=("axes fraction", "data"),
    fontsize=7,
    va="bottom",
)
ax2.annotate(
    f"pied voile {foot:.0f} m",
    (0.03, foot),
    xycoords=("axes fraction", "data"),
    fontsize=7,
    va="top",
    color="red",
)
ax2.set_ylabel("elevation (m NGF)")
ax2.set_xticks([])
ax2.set_title(
    f"Coupe au barrage : aucun flux horizontal de\nla crete ({crest:.0f} m) au pied ({foot:.0f} m) = {crest - foot:.0f} m barres",
    fontsize=9,
)
ax2.legend(fontsize=7, loc="lower left")
fig.tight_layout()
fig.savefig(f"{OUT}/diag_hfb_voile.png", dpi=130)
plt.close()
print("diag_hfb_voile.png")

# ===================== FIG 5: grid + local refinement (cell size) =====================
verts = np.asarray(mg.verts)
iverts = mg.iverts


def cell_diam(i):
    p = verts[[int(k) for k in iverts[i] if k is not None]][:, :2]
    a = 0.5 * abs(np.dot(p[:, 0], np.roll(p[:, 1], 1)) - np.dot(p[:, 1], np.roll(p[:, 0], 1)))
    return 2.0 * np.sqrt(a / np.pi)


diam = np.array([cell_diam(i) for i in range(mg.ncpl)])
patches = [verts[[int(k) for k in iverts[i] if k is not None]][:, :2] for i in range(mg.ncpl)]
fig, ax = plt.subplots(figsize=(11, 8))
pc = PolyCollection(patches, array=diam, cmap="viridis_r", edgecolors="0.7", lw=0.1)
pc.set_clim(float(np.percentile(diam, 2)), float(np.percentile(diam, 98)))
ax.add_collection(pc)
for lid, col in [(0, RES), (1, PRE)]:
    ax.scatter(xc[lake_cells[lid]], yc[lake_cells[lid]], s=4, c=col, alpha=0.35, zorder=2)
for h in hspd:
    a, b = c2d(h["cellid1"]), c2d(h["cellid2"])
    ax.plot([xc[a], xc[b]], [yc[a], yc[b]], "-", color="red", lw=2, zorder=5)
ax.set_xlim(bx0, bx1)
ax.set_ylim(by0, by1)
ax.set_aspect("equal")
ax.set_xticks([])
ax.set_yticks([])
ax.set_title(
    f"Grille Voronoi + raffinage local (diametre cellule, m)\nmedian {np.median(diam):.0f} m, "
    f"voile ~{np.median(diam[hfb_cells]):.0f} m",
    fontsize=11,
)
fig.colorbar(pc, ax=ax, shrink=0.6, label="diametre cellule (m)")
fig.tight_layout()
fig.savefig(f"{OUT}/diag_grid_refinement.png", dpi=130)
plt.close()
print("diag_grid_refinement.png")

# ===================== FIG 6: voile detail on the surveyed trace =====================
fig, ax = plt.subplots(figsize=(9, 8))
pmv = flopy.plot.PlotMapView(model=gwf, ax=ax, layer=0)
pmv.plot_grid(lw=0.4, color="0.8")
ax.scatter(
    xc[lake_cells[0]], yc[lake_cells[0]], s=10, c=RES, alpha=0.5, zorder=2, label="reservoir"
)
# barred faces as a continuous chain (edges shared by the two HFB cells)
be = set()
for h in hspd:
    ca_, cb_ = c2d(h["cellid1"]), c2d(h["cellid2"])
    ea = {
        tuple(sorted((int(iverts[ca_][k]), int(iverts[ca_][(k + 1) % len(iverts[ca_])]))))
        for k in range(len(iverts[ca_]))
    }
    eb = {
        tuple(sorted((int(iverts[cb_][k]), int(iverts[cb_][(k + 1) % len(iverts[cb_])]))))
        for k in range(len(iverts[cb_]))
    }
    be |= ea & eb
for a, b in be:
    ax.plot(
        [verts[a][0], verts[b][0]], [verts[a][1], verts[b][1]], "-", color="red", lw=4, zorder=6
    )
# The trace ACTUALLY used by the model (from the project config), so the figure
# matches where the HFB was built instead of a guessed external file.
config_sources = config_cutoff_wall_lines(PROJECT_TOML)
uses_survey = any(str(kind).endswith("injection_cheze.gpkg") for _, _, kind in config_sources)
for label, geom, _kind in config_sources:
    parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
    for i, part in enumerate(parts):
        ax.plot(*part.xy, "--", color="#0a7d00", lw=2.4, zorder=5, label=label if i == 0 else None)
# The surveyed grout-curtain axis: drawn as a reference ONLY when the config uses
# a different (inline, shifted) trace. When the config already uses this survey
# file, the green overlay above is it, so we do not draw it twice.
if not uses_survey:
    try:
        import geopandas as gpd
        from shapely.ops import linemerge

        inj = gpd.read_file("examples/data/cutoff_wall/injection_cheze.gpkg").union_all()
        inj = linemerge(inj) if inj.geom_type == "MultiLineString" else inj
        ax.plot(
            *inj.xy, ":", color="orange", lw=1.8, zorder=4, label="axe leve (gpkg, non utilise ici)"
        )
    except Exception as e:
        print("  injection gpkg overlay skipped:", e)
ax.plot([], [], "r-", lw=4, label=f"faces HFB voile ({len(hspd)} rows, {len(be)} faces)")
ax.set_xlim(dam_x - 350, dam_x + 350)
ax.set_ylim(dam_y - 350, dam_y + 350)
ax.set_aspect("equal")
ax.set_xticks([])
ax.set_yticks([])
ax.legend(fontsize=8, loc="lower left")
ax.set_title("Voile d'injection : ligne config -> chaine continue de faces HFB", fontsize=11)
fig.tight_layout()
fig.savefig(f"{OUT}/diag_voile_detail.png", dpi=140)
plt.close()
print("diag_voile_detail.png")

# ===================== FIG 7: inter-lake sill (reciprocal weir exchange) =====================
if lake_cells.get(0) and lake_cells.get(1):
    res_xy = np.column_stack([xc[lake_cells[0]], yc[lake_cells[0]]])
    pre_xy = np.column_stack([xc[lake_cells[1]], yc[lake_cells[1]]])
    dmat = np.hypot(
        res_xy[:, None, 0] - pre_xy[None, :, 0], res_xy[:, None, 1] - pre_xy[None, :, 1]
    )
    order = np.argsort(dmat.min(axis=1))[:14]  # the closest reservoir cells = the sill throat
    sill_res = [lake_cells[0][k] for k in order]
    sill_pre = [lake_cells[1][int(np.argmin(dmat[k]))] for k in order]
    sx = float(np.mean(xc[sill_res + sill_pre]))
    sy = float(np.mean(yc[sill_res + sill_pre]))
    # the reciprocal inter-lake weirs (lakeout is another lake, not -1)
    weirs = [o for o in outl if int(o["lakeout"]) >= 0]
    crest = float(weirs[0]["invert"]) if weirs else 86.93
    width = float(weirs[0]["width"]) if weirs else 0.0
    strt = {int(r["ifno"]): float(r["strt"]) for r in lak.packagedata.get_data()}

    fig, (axa, axb) = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.5, 1]})
    pmv = flopy.plot.PlotMapView(model=gwf, ax=axa, layer=0)
    pmv.plot_grid(lw=0.3, color="0.85")
    axa.scatter(xc[lake_cells[0]], yc[lake_cells[0]], s=16, c=RES, alpha=0.5, label="reservoir")
    axa.scatter(xc[lake_cells[1]], yc[lake_cells[1]], s=16, c=PRE, alpha=0.65, label="pre-retenue")
    for cr, cp in zip(sill_res, sill_pre):
        axa.plot([xc[cr], xc[cp]], [yc[cr], yc[cp]], "-", color="red", lw=1.0, alpha=0.5, zorder=5)
    axa.scatter(
        xc[sill_res + sill_pre],
        yc[sill_res + sill_pre],
        s=55,
        facecolors="none",
        edgecolors="red",
        lw=1.8,
        zorder=6,
        label="seuil (cellules mitoyennes)",
    )
    axa.set_xlim(sx - 450, sx + 450)
    axa.set_ylim(sy - 450, sy + 450)
    axa.set_aspect("equal")
    axa.set_xticks([])
    axa.set_yticks([])
    axa.legend(fontsize=8, loc="upper left")
    axa.set_title("Seuil reservoir <-> pre-retenue : ou passe le flux", fontsize=11)
    # schematic cross-section: two water bodies separated by the sill crest
    axb.add_patch(Rectangle((0, 78), 4, strt.get(0, 82) - 78, color=RES, alpha=0.4))
    axb.add_patch(Rectangle((6, 78), 4, strt.get(1, 82) - 78, color=PRE, alpha=0.45))
    axb.plot([4, 4, 6, 6], [78, crest, crest, 78], "k-", lw=2)  # the sill wall up to the crest
    axb.text(
        5, crest + 0.15, f"seuil {crest:.2f} m\n(2 weirs, l={width:.0f} m)", ha="center", fontsize=8
    )
    axb.text(
        2, 78.4, f"reservoir\n{strt.get(0, 82):.1f} m", ha="center", fontsize=8, color="#063d4d"
    )
    axb.text(
        8, 78.4, f"pre-retenue\n{strt.get(1, 82):.1f} m", ha="center", fontsize=8, color="#8a5a00"
    )
    axb.annotate(
        "",
        xy=(6.3, crest + 0.6),
        xytext=(3.7, crest + 0.6),
        arrowprops=dict(arrowstyle="<->", color="blue", lw=2),
    )
    axb.text(
        5,
        crest + 1.1,
        "echange quand un\nniveau depasse le seuil",
        ha="center",
        fontsize=8,
        color="blue",
    )
    axb.set_xlim(0, 10)
    axb.set_ylim(78, max(crest + 2.5, strt.get(0, 82), strt.get(1, 82)) + 1)
    axb.set_xticks([])
    axb.set_ylabel("elevation (m NGF)")
    axb.set_title("Fonctionnement du seuil (coupe schematique)", fontsize=10)
    fig.tight_layout()
    fig.savefig(f"{OUT}/diag_sill_exchange.png", dpi=140)
    plt.close()
    print("diag_sill_exchange.png")


def _outlet_xy(project_toml):
    """Catchment outlet (x, y) from the project config, or (nan, nan)."""
    if project_toml is None:
        return float("nan"), float("nan")
    import tomllib

    with open(project_toml, "rb") as fh:
        g = tomllib.load(fh).get("geographic", {}).get("catchment", {})
    return float(g.get("x_outlet", float("nan"))), float(g.get("y_outlet", float("nan")))


xo, yo = _outlet_xy(PROJECT_TOML)

# ===================== FIG 8: cell roles (SFR / DRN destination / outlets) =====================
from matplotlib.patches import Patch  # noqa: E402

fig, ax = plt.subplots(figsize=(11, 8.5))
pmv = flopy.plot.PlotMapView(model=gwf, ax=ax, layer=0)
pmv.plot_grid(lw=0.1, color="0.9")
darr = np.array(dcells)
to_sfr = np.array([i in drn2sfr for i in range(len(dcells))])
to_lak = np.array([i in drn2lak for i in range(len(dcells))])
to_out = ~to_sfr & ~to_lak
ax.scatter(xc[darr[to_sfr]], yc[darr[to_sfr]], s=11, c="#2a9d8f", edgecolors="none", zorder=3)
ax.scatter(xc[darr[to_lak]], yc[darr[to_lak]], s=11, c="#e76f51", edgecolors="none", zorder=3)
ax.scatter(xc[darr[to_out]], yc[darr[to_out]], s=9, c="#c4c8cc", edgecolors="none", zorder=2)
for lid, col in [(0, RES), (1, PRE)]:
    ax.scatter(xc[lake_cells[lid]], yc[lake_cells[lid]], s=8, c=col, alpha=0.35, zorder=1)
rcv = list(reach_cell.values())
ax.scatter(xc[rcv], yc[rcv], s=16, marker="s", c="#1d4ed8", edgecolors="none", zorder=4)
red_pts = [reach_cell[ri] for ri, li in sfr2lak if ri in reach_cell]
if red_pts:
    ax.scatter(
        xc[red_pts], yc[red_pts], s=210, marker="D", c="red", edgecolors="k", lw=0.6, zorder=6
    )
if np.isfinite(xo):
    ax.scatter(xo, yo, s=230, marker="D", c="blue", edgecolors="k", lw=0.6, zorder=6)
ax.set_xlim(bx0, bx1)
ax.set_ylim(by0, by1)
ax.set_aspect("equal")
ax.set_xticks([])
ax.set_yticks([])
ax.set_title("Roles des cellules : reseau SFR, DRN par destination, exutoires", fontsize=12)
ax.legend(
    handles=[
        Line2D([], [], marker="s", ls="", mfc="#1d4ed8", mec="none", ms=8, label="cellule SFR"),
        Line2D(
            [],
            [],
            marker="o",
            ls="",
            mfc="#2a9d8f",
            mec="none",
            ms=8,
            label=f"1 - DRN -> bief SFR ({int(to_sfr.sum())})",
        ),
        Line2D(
            [],
            [],
            marker="o",
            ls="",
            mfc="#e76f51",
            mec="none",
            ms=8,
            label=f"2 - DRN -> lac ({int(to_lak.sum())})",
        ),
        Line2D(
            [],
            [],
            marker="o",
            ls="",
            mfc="#c4c8cc",
            mec="none",
            ms=8,
            label=f"3 - DRN -> hors BV ({int(to_out.sum())})",
        ),
        Line2D([], [], marker="D", ls="", mfc="red", mec="k", ms=11, label="exutoire -> lac"),
        Line2D([], [], marker="D", ls="", mfc="blue", mec="k", ms=11, label="exutoire hors modele"),
        Patch(fc=RES, alpha=0.4, label="reservoir"),
        Patch(fc=PRE, alpha=0.4, label="pre-retenue"),
    ],
    loc="upper left",
    fontsize=8,
    framealpha=0.92,
)
fig.tight_layout()
fig.savefig(f"{OUT}/diag_cell_roles.png", dpi=140)
plt.close()
print("diag_cell_roles.png")

# ===================== FIG 9: vertical cross-section (layers + lake + voile) =====================
from flopy.plot import PlotCrossSection  # noqa: E402

top = np.asarray(mg.top).reshape(-1)
botm = np.asarray(mg.botm)
res_c = np.array(lake_cells[0])
far = int(res_c[int(np.argmax(np.hypot(xc[res_c] - dam_x, yc[res_c] - dam_y)))])
end = (
    (xo, yo)
    if np.isfinite(xo)
    else (dam_x + (dam_x - xc[far]) * 0.15, dam_y + (dam_y - yc[far]) * 0.15)
)
line = [(float(xc[far]), float(yc[far])), (dam_x, dam_y), (float(end[0]), float(end[1]))]
y_lo = float(np.percentile(botm[botm > 0], 0.2)) - 3
y_hi = float(np.max(top[top > 0])) + 4
stage = None
_obs = [f for f in os.listdir(D) if f.endswith(".lak.obs.csv")]
if _obs:
    import pandas as pd

    _df = pd.read_csv(os.path.join(D, _obs[0]))
    _col = [c for c in _df.columns if "STAGE" in c.upper()]
    if _col:
        stage = float(np.nanmean(_df[_col[0]].to_numpy()))
fig, ax = plt.subplots(figsize=(15, 6))
xs = PlotCrossSection(model=gwf, ax=ax, line={"line": line}, geographic_coords=False)
lay_arr = np.repeat(np.arange(mg.nlay).reshape(-1, 1), mg.ncpl, axis=1).astype(float)
lay_arr[:, ~np.isfinite(top) | (top < -9000)] = np.nan
xs.plot_array(
    np.ma.masked_invalid(lay_arr), cmap="Blues", vmin=-0.5, vmax=mg.nlay - 0.5, alpha=0.45
)
xs.plot_grid(lw=0.25, color="0.55")
lakemask = np.full((mg.nlay, mg.ncpl), np.nan)
for c in lake_cells[0]:
    lakemask[0, c] = 1.0
xs.plot_array(np.ma.masked_invalid(lakemask), cmap="autumn", alpha=0.8)
if stage is not None:
    pts = xs.projpts
    for cid in lake_cells[0]:
        key = cid if cid in pts else (0, cid)
        if key in pts:
            arr = np.asarray(pts[key])
            bed = float(top[cid])
            if stage > bed:
                ax.fill_between(
                    [float(arr[:, 0].min()), float(arr[:, 0].max())],
                    bed,
                    stage,
                    color="#2b8cbe",
                    alpha=0.45,
                    zorder=5,
                )
    ax.axhline(stage, color="#08519c", ls="--", lw=1.6, zorder=8)
    ax.text(
        0.005,
        stage + 0.6,
        f"niveau lac ~{stage:.1f} m",
        transform=ax.get_yaxis_transform(),
        color="#08519c",
        fontsize=9,
        va="bottom",
    )
barred_lay = sorted({int(h["cellid1"][0]) for h in hspd})
dam_dist = float(np.hypot(xc[far] - dam_x, yc[far] - dam_y))
b_top = float(np.nanmax([top[c] for c in hfb_cells]))
b_bot = float(np.nanmin([botm[max(barred_lay), c] for c in hfb_cells]))
ax.add_patch(
    plt.Rectangle(
        (dam_dist - 40, b_bot), 80, b_top - b_bot, fill=False, ec="red", hatch="///", lw=2, zorder=9
    )
)
ax.annotate(
    "voile HFB\n(barrage)",
    (dam_dist, b_top),
    xytext=(dam_dist + 250, b_top + 2),
    fontsize=9,
    color="red",
    arrowprops=dict(arrowstyle="->", color="red"),
)
ax.set_title(
    "Coupe verticale reservoir -> barrage -> exutoire : couches, lame d'eau, voile HFB", fontsize=11
)
ax.set_ylabel("elevation (m NGF)")
ax.set_xlabel("distance le long de la coupe (m)")
ax.legend(
    handles=[
        Patch(fc="#2b8cbe", alpha=0.45, label="lame d'eau du lac (lit -> niveau)"),
        Patch(fc=plt.cm.autumn(0.2), alpha=0.8, label="cellules-lac (lit, couche 0)"),
        Patch(fc=plt.cm.Blues(0.5), alpha=0.45, label="aquifere (2 couches)"),
        Line2D([], [], color="#08519c", ls="--", lw=1.6, label="niveau du lac"),
        Patch(fc="none", ec="red", hatch="///", label="voile HFB (barre couche 0)"),
    ],
    loc="lower right",
    fontsize=8,
    framealpha=0.92,
)
fig.tight_layout()
ax.set_ylim(y_lo, y_hi)
ax.autoscale(False)
fig.savefig(f"{OUT}/diag_cross_section.png", dpi=140)
plt.close()
print("diag_cross_section.png")
print("DONE")
