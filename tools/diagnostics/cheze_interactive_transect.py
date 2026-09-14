"""Interactive cross-section: drag the transect on the map, the section updates live.

Run locally (needs a GUI backend / display):
    mamba activate hmp_refact
    python tools/diagnostics/cheze_interactive_transect.py <solver_dir> [project.toml]

Left panel  = map view: aquifer grid, lake cells coloured by their bathymetric BED
              elevation, the dam (HFB), and the draggable transect (two endpoints).
Right panel = vertical section along the transect: the two aquifer layers, the lake
              bed + water column, the simulated water table, and the HFB voile band.

Click one of the two endpoints and drag it; release to redraw. Everything updates.
Pass --static to dump one PNG instead (for a headless check).
"""

import os
import sys

import flopy
import numpy as np

if "--static" in sys.argv:
    import matplotlib

    matplotlib.use("Agg")
    sys.argv.remove("--static")
    _STATIC = True
else:
    _STATIC = False

import matplotlib.pyplot as plt
from flopy.plot import PlotCrossSection
from matplotlib.collections import PolyCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

D = sys.argv[1]
TOML = sys.argv[2] if len(sys.argv) > 2 else None

sim = flopy.mf6.MFSimulation.load(sim_ws=D, verbosity_level=0)
gwf = sim.get_model()
mg = gwf.modelgrid
xc = np.asarray(mg.xcellcenters).reshape(-1)
yc = np.asarray(mg.ycellcenters).reshape(-1)
top = np.asarray(mg.top).reshape(-1)
botm = np.asarray(mg.botm)
verts = np.asarray(mg.verts)
iverts = mg.iverts


def c2d(cid):
    return int(cid[1]) if isinstance(cid, (tuple, list, np.void)) else int(cid)


lak = gwf.get_package("lak")
lcd = lak.connectiondata.get_data()
lake_by = {0: [], 1: []}
for r in lcd:
    lake_by[int(r["ifno"])].append(c2d(r["cellid"]))
res_cells = np.array(sorted(set(lake_by[0])))
hspd = gwf.get_package("hfb").stress_period_data.get_data(0)
hfb_cells = sorted({c2d(h["cellid1"]) for h in hspd} | {c2d(h["cellid2"]) for h in hspd})
dam_x, dam_y = float(np.mean(xc[hfb_cells])), float(np.mean(yc[hfb_cells]))
barred_lay = max(int(h["cellid1"][0]) for h in hspd)

# simulated water table (last head, layer 0)
head = None
try:
    hds = flopy.utils.HeadFile([os.path.join(D, f) for f in os.listdir(D) if f.endswith(".hds")][0])
    head = hds.get_data(kstpkper=hds.get_kstpkper()[-1])
except Exception as e:
    print("head unavailable:", e)

# mean reservoir stage
stage = None
_obs = [f for f in os.listdir(D) if f.endswith(".lak.obs.csv")]
if _obs:
    import pandas as pd

    _df = pd.read_csv(os.path.join(D, _obs[0]))
    _c = [c for c in _df.columns if "STAGE" in c.upper()]
    if _c:
        stage = float(np.nanmean(_df[_c[0]].to_numpy()))

# elevation window (real cells only; nodata reaches -10000)
y_lo = float(np.percentile(botm[botm > 0], 0.2)) - 3
y_hi = float(np.max(top[top > 0])) + 4

# map zoom on the lakes + dam
allc = np.concatenate([res_cells, np.array(lake_by[1] or [0])])
mx0, mx1 = xc[allc].min() - 500, xc[allc].max() + 500
my0, my1 = yc[allc].min() - 500, yc[allc].max() + 500

# --- static map artists (drawn once) ---
fig, (axm, axs) = plt.subplots(1, 2, figsize=(17, 7.5))
# grid (light) in the zoom window only, for speed
inwin = (xc > mx0) & (xc < mx1) & (yc > my0) & (yc < my1)
polys = [verts[[int(k) for k in iverts[i] if k is not None]][:, :2] for i in np.where(inwin)[0]]
axm.add_collection(PolyCollection(polys, facecolor="none", edgecolor="0.85", lw=0.2))
# reservoir cells coloured by BED elevation (bathymetry from above)
sc = axm.scatter(xc[res_cells], yc[res_cells], c=top[res_cells], s=14, cmap="viridis_r", zorder=3)
fig.colorbar(sc, ax=axm, shrink=0.6, label="cote du lit du reservoir (m NGF)")
if lake_by[1]:
    axm.scatter(xc[lake_by[1]], yc[lake_by[1]], s=10, c="#e08e00", alpha=0.5, zorder=2)
for h in hspd:  # dam faces
    a, b = c2d(h["cellid1"]), c2d(h["cellid2"])
    axm.plot([xc[a], xc[b]], [yc[a], yc[b]], "-", color="red", lw=2.5, zorder=4)
axm.set_xlim(mx0, mx1)
axm.set_ylim(my0, my1)
axm.set_aspect("equal")
axm.set_title("Carte : glisse un bout du transect (jaune)")
axm.set_xticks([])
axm.set_yticks([])

# initial transect: the reservoir long axis (PCA), clipped to the zoom
pts = np.column_stack([xc[res_cells], yc[res_cells]])
c = pts.mean(0)
u = np.linalg.svd(pts - c)[2][0]  # principal direction
proj = (pts - c) @ u
P0 = [float(c[0] + u[0] * proj.min()), float(c[1] + u[1] * proj.min())]
P1 = [float(c[0] + u[0] * proj.max()), float(c[1] + u[1] * proj.max())]
(mline,) = axm.plot([P0[0], P1[0]], [P0[1], P1[1]], "-", color="#f1c40f", lw=2.5, zorder=6)
(mpts,) = axm.plot([P0[0], P1[0]], [P0[1], P1[1]], "o", color="#f39c12", ms=11, mec="k", zorder=7)


def draw_section():
    axs.clear()
    line = [(P0[0], P0[1]), (P1[0], P1[1])]
    xs = PlotCrossSection(model=gwf, ax=axs, line={"line": line}, geographic_coords=False)
    lay = np.repeat(np.arange(mg.nlay).reshape(-1, 1), mg.ncpl, axis=1).astype(float)
    lay[:, ~np.isfinite(top) | (top < -9000)] = np.nan
    xs.plot_array(np.ma.masked_invalid(lay), cmap="Blues", vmin=-0.5, vmax=mg.nlay - 0.5, alpha=0.4)
    xs.plot_grid(lw=0.3, color="0.55")
    lm = np.full((mg.nlay, mg.ncpl), np.nan)
    for cc in res_cells:
        lm[0, cc] = 1.0
    xs.plot_array(np.ma.masked_invalid(lm), cmap="autumn", alpha=0.85)
    projp = xs.projpts
    if stage is not None:
        for cid in res_cells:
            key = cid if cid in projp else (0, cid)
            if key in projp:
                a = np.asarray(projp[key])
                bed = float(top[cid])
                if stage > bed:
                    axs.fill_between(
                        [a[:, 0].min(), a[:, 0].max()],
                        bed,
                        stage,
                        color="#2b8cbe",
                        alpha=0.4,
                        zorder=5,
                    )
        axs.axhline(stage, color="#08519c", ls="--", lw=1.5, zorder=8)
    if head is not None:
        try:
            xs.plot_array(
                np.where(head > -1e3, head, np.nan), head=head, masked_values=[1e30], alpha=0
            )  # ensure wet mask; then draw the surface
        except Exception:
            pass
        try:
            xs.plot_surface(head, color="#117733", lw=1.6)  # water table (layer 0 head)
        except Exception:
            pass
    # HFB band where the section passes near the dam
    dp = np.hypot((P1[0] - P0[0]), (P1[1] - P0[1]))
    if dp > 0:
        t = ((dam_x - P0[0]) * (P1[0] - P0[0]) + (dam_y - P0[1]) * (P1[1] - P0[1])) / dp**2
        if -0.05 <= t <= 1.05:
            dd = t * dp
            b_top = float(np.nanmax([top[cc] for cc in hfb_cells]))
            b_bot = float(np.nanmin([botm[barred_lay, cc] for cc in hfb_cells]))
            axs.add_patch(
                plt.Rectangle(
                    (dd - 40, b_bot),
                    80,
                    b_top - b_bot,
                    fill=False,
                    ec="red",
                    hatch="///",
                    lw=2,
                    zorder=9,
                )
            )
    axs.set_ylim(y_lo, y_hi)
    axs.autoscale(False)
    axs.set_ylabel("elevation (m NGF)")
    axs.set_xlabel("distance le long du transect (m)")
    axs.set_title("Coupe (lit rouge, lame d'eau bleue, nappe verte, voile rouge)")
    axs.legend(
        handles=[
            Patch(fc=plt.cm.autumn(0.2), alpha=0.85, label="cellules-lac (lit)"),
            Patch(fc="#2b8cbe", alpha=0.4, label="lame d'eau (lit->niveau)"),
            Patch(fc=plt.cm.Blues(0.4), alpha=0.4, label="aquifere (2 couches)"),
            Line2D([], [], color="#08519c", ls="--", label="niveau lac"),
            Line2D([], [], color="#117733", label="nappe (charge simulee)"),
            Patch(fc="none", ec="red", hatch="///", label="voile HFB"),
        ],
        loc="lower right",
        fontsize=7,
        framealpha=0.9,
    )
    fig.canvas.draw_idle()


draw_section()

# --- dragging ---
_drag = {"i": None}


def _near(ev):
    for i, p in enumerate((P0, P1)):
        if (
            ev.xdata
            and abs(ev.xdata - p[0]) < (mx1 - mx0) * 0.03
            and abs(ev.ydata - p[1]) < (my1 - my0) * 0.03
        ):
            return i
    return None


def on_press(ev):
    if ev.inaxes is axm:
        _drag["i"] = _near(ev)


def on_move(ev):
    if _drag["i"] is not None and ev.inaxes is axm and ev.xdata:
        (P0 if _drag["i"] == 0 else P1)[0] = ev.xdata
        (P0 if _drag["i"] == 0 else P1)[1] = ev.ydata
        mline.set_data([P0[0], P1[0]], [P0[1], P1[1]])
        mpts.set_data([P0[0], P1[0]], [P0[1], P1[1]])
        fig.canvas.draw_idle()


def on_release(ev):
    if _drag["i"] is not None:
        _drag["i"] = None
        draw_section()


fig.canvas.mpl_connect("button_press_event", on_press)
fig.canvas.mpl_connect("motion_notify_event", on_move)
fig.canvas.mpl_connect("button_release_event", on_release)
fig.tight_layout()

if _STATIC:
    out = os.path.join(os.path.dirname(D), "interactive_transect_static.png")
    fig.savefig(out, dpi=130)
    print("wrote", out)
else:
    print("Glisse un bout du transect jaune sur la carte ; relache pour redessiner la coupe.")
    plt.show()
