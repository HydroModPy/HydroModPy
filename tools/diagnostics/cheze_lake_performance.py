"""Cheze lake performance + two-lake dynamics figures from a catalog run.

Reads the simulated lake series straight from the project catalog (the canonical
timeseries source, no export needed) plus the observed reservoir levels, then
draws:

* diag_lake_performance  reservoir simulated vs observed stage + KGE/NSE/RMSE/
                         bias + 1:1 scatter (the "how well does the lake perform"
                         figure). Uses hydromodpy's own goodness_of_fit so the
                         KGE matches the calibration objective.
* diag_two_lake_stage    reservoir + pre-retenue simulated stage vs the sill /
                         spillway crests, plus the reservoir water-balance terms
                         (SFR feed, under-dam seepage, aquifer exchange,
                         withdrawal) so the pre-retenue coupling reads at a glance.

Usage:
    python tools/diagnostics/cheze_lake_performance.py \
        <project_dir> <observed_levels.csv> <out_dir> \
        [--run REF] [--warmup-days N] [--sill 86.93] [--spillway 87.57]
        [--start YYYY-MM-DD]

<project_dir> is the HydroModPy project holding the catalog; --run selects a run
by id, unique prefix or name (default: the latest run). The observed CSV has
columns datetime,value (m NGF). --start clips the plotted/scored window (e.g.
skip the first spin-up year); --warmup-days additionally drops the leading N days
from the metric to exclude the steady warm-up.
"""

from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import hydromodpy as hmp  # noqa: E402
from hydromodpy.core.metrics import (  # noqa: E402
    bias,
    kge,
    nse,
    rmse,
)

RES_STATION = "lake:reservoir_cheze"
PRE_STATION = "lake:preretenue_cheze"
RES, PRE, OBSC = "#0b6e8a", "#e08e00", "#111111"


def _open_run(project_dir: str, ref: str | None):
    """Return the Run to diagnose: an explicit reference, or the latest one."""
    catalog = hmp.open(project_dir)
    return catalog[ref] if ref else catalog.latest()


def _load_series(run, station: str, variable: str) -> pd.Series:
    """Return a datetime-indexed float series for one station/variable."""
    try:
        s = run.timeseries(variable, station=station)
    except KeyError:
        return pd.Series(dtype=float)
    s = s.sort_index()
    return s[~s.index.duplicated(keep="last")]


def _load_observed(obs_csv: str) -> pd.Series:
    df = pd.read_csv(obs_csv)
    tcol = df.columns[0]
    vcol = "value" if "value" in df.columns else df.columns[1]
    t = pd.to_datetime(df[tcol]).dt.tz_localize(None)
    return pd.Series(df[vcol].to_numpy(), index=t.to_numpy()).sort_index()


def _daily_align(sim: pd.Series, obs: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Align sim and obs on a common daily index (nearest-day inner join)."""
    s = sim.resample("1D").mean()
    o = obs.resample("1D").mean()
    j = pd.concat({"sim": s, "obs": o}, axis=1).dropna()
    return j["sim"], j["obs"]


def performance_figure(sim_res, obs, out_dir, warmup_days=0):
    """Reservoir sim-vs-obs stage, scored with hydromodpy's KGE/NSE."""
    s, o = _daily_align(sim_res, obs)
    if warmup_days:
        cutoff = s.index.min() + pd.Timedelta(days=warmup_days)
        m = s.index >= cutoff
        s_sc, o_sc = s[m], o[m]
    else:
        s_sc, o_sc = s, o
    k = kge(s_sc.to_numpy(), o_sc.to_numpy())
    metrics = {
        "KGE": k["kge"],
        "r": k["r"],
        "alpha": k["alpha"],
        "beta": k["beta"],
        "NSE": nse(s_sc.to_numpy(), o_sc.to_numpy()),
        "RMSE": rmse(s_sc.to_numpy(), o_sc.to_numpy()),
        "biais": bias(s_sc.to_numpy(), o_sc.to_numpy()),
    }

    fig = plt.figure(figsize=(15, 8), layout="constrained")
    gs = fig.add_gridspec(2, 3, height_ratios=[1.4, 1])
    axt = fig.add_subplot(gs[0, :])
    axt.plot(o.index, o.to_numpy(), color=OBSC, lw=1.1, label="niveau observe", zorder=3)
    axt.plot(s.index, s.to_numpy(), color=RES, lw=1.1, label="niveau simule (LAK)", zorder=2)
    if warmup_days:
        axt.axvspan(
            s.index.min(),
            s.index.min() + pd.Timedelta(days=warmup_days),
            color="0.85",
            alpha=0.5,
            label="warm-up (hors score)",
        )
    axt.set_ylabel("cote du plan d'eau (m NGF)")
    axt.set_title("Performance du reservoir : niveau simule vs observe", fontsize=13)
    axt.legend(loc="lower left", fontsize=9, ncol=3)
    axt.grid(alpha=0.25)
    txt = "\n".join(
        [
            f"KGE  = {metrics['KGE']:.3f}",
            f"NSE  = {metrics['NSE']:.3f}",
            f"RMSE = {metrics['RMSE']:.3f} m",
            f"biais= {metrics['biais']:+.3f} m",
            f"r={metrics['r']:.2f}  alpha={metrics['alpha']:.2f}  beta={metrics['beta']:.2f}",
            f"n = {len(s_sc)} jours",
        ]
    )
    axt.text(
        0.995,
        0.04,
        txt,
        transform=axt.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        family="monospace",
        bbox=dict(boxstyle="round", fc="white", ec="0.6", alpha=0.9),
    )

    # 1:1 scatter
    axs = fig.add_subplot(gs[1, 0])
    axs.scatter(o_sc.to_numpy(), s_sc.to_numpy(), s=6, c=RES, alpha=0.35, edgecolors="none")
    lo = float(min(o_sc.min(), s_sc.min()))
    hi = float(max(o_sc.max(), s_sc.max()))
    axs.plot([lo, hi], [lo, hi], "k--", lw=1)
    axs.set_xlabel("observe (m)")
    axs.set_ylabel("simule (m)")
    axs.set_title("1:1", fontsize=10)
    axs.set_aspect("equal")
    axs.grid(alpha=0.25)

    # residuals over time
    axr = fig.add_subplot(gs[1, 1:])
    resid = (s_sc - o_sc).to_numpy()
    axr.axhline(0, color="k", lw=0.8)
    axr.plot(s_sc.index, resid, color="#8a5a00", lw=0.8)
    axr.fill_between(s_sc.index, resid, 0, color="#e08e00", alpha=0.3)
    axr.set_ylabel("simule - observe (m)")
    axr.set_title("Residus", fontsize=10)
    axr.grid(alpha=0.25)

    p = os.path.join(out_dir, "diag_lake_performance.png")
    fig.savefig(p, dpi=140)
    plt.close(fig)
    print("diag_lake_performance.png", {k2: round(v, 3) for k2, v in metrics.items()})
    return metrics


def two_lake_figure(run, obs, out_dir, sill=86.93, spillway=87.57):
    """Both lake stages vs the crests + the reservoir water-balance terms."""
    res = _load_series(run, RES_STATION, "stage")
    pre = _load_series(run, PRE_STATION, "stage")
    if res.empty:
        print("two_lake: no reservoir stage, skipped")
        return

    fig, (ax, axf) = plt.subplots(
        2, 1, figsize=(15, 9), sharex=True, gridspec_kw={"height_ratios": [1.3, 1]}
    )
    ax.plot(res.index, res.to_numpy(), color=RES, lw=1.2, label="reservoir (simule)", zorder=3)
    if not pre.empty:
        ax.plot(
            pre.index, pre.to_numpy(), color=PRE, lw=1.2, label="pre-retenue (simule)", zorder=2
        )
    if obs is not None and not obs.empty:
        oo = obs.resample("1D").mean().reindex(res.resample("1D").mean().index).dropna()
        ax.plot(oo.index, oo.to_numpy(), color=OBSC, lw=0.9, alpha=0.7, label="reservoir observe")
    ax.axhline(sill, color="#7a0", ls="--", lw=1, label=f"seuil inter-lac {sill} m")
    ax.axhline(spillway, color="red", ls=":", lw=1, label=f"deversoir {spillway} m")
    ax.set_ylabel("cote (m NGF)")
    ax.set_title(
        "Dynamique deux-lacs : reservoir + pre-retenue vs seuil de la pre-retenue", fontsize=13
    )
    ax.legend(loc="lower left", fontsize=8, ncol=3)
    ax.grid(alpha=0.25)

    # reservoir water-balance terms (m3/s)
    terms = [
        ("from_mvr", "#2a9d8f", "apport SFR/DRN (MVR)"),
        ("seepage_under_dam", "#c1272d", "fuite sous barrage"),
        ("gwf_exchange", "#1d4ed8", "echange aquifere"),
        ("withdrawal", "#8a5a00", "prelevement gere"),
        ("ext_inflow", "#7b2fbe", "apport externe"),
    ]
    for var, col, lab in terms:
        s = _load_series(run, RES_STATION, var)
        if s.empty:
            continue
        s = s.replace([3e30, -3e30], np.nan).resample("7D").mean()
        axf.plot(s.index, s.to_numpy(), color=col, lw=0.9, label=lab)
    axf.axhline(0, color="k", lw=0.6)
    axf.set_ylabel("flux reservoir (m3/s)")
    axf.set_xlabel("date")
    axf.set_title("Termes du bilan du reservoir (moyenne 7 j)", fontsize=11)
    axf.legend(loc="upper right", fontsize=8, ncol=3)
    axf.grid(alpha=0.25)

    fig.tight_layout()
    p = os.path.join(out_dir, "diag_two_lake_stage.png")
    fig.savefig(p, dpi=140)
    plt.close(fig)
    print("diag_two_lake_stage.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir", help="project directory holding the catalog")
    ap.add_argument("observed_csv")
    ap.add_argument("out_dir")
    ap.add_argument("--run", default=None, help="run id, unique prefix or name (default: latest)")
    ap.add_argument("--warmup-days", type=int, default=0)
    ap.add_argument("--sill", type=float, default=86.93)
    ap.add_argument("--spillway", type=float, default=87.57)
    ap.add_argument("--start", default=None, help="clip series to >= this date (YYYY-MM-DD)")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    run = _open_run(args.project_dir, args.run)
    sim_res = _load_series(run, RES_STATION, "stage")
    obs = _load_observed(args.observed_csv)
    if args.start:
        cut = pd.Timestamp(args.start)
        sim_res = sim_res[sim_res.index >= cut]
        obs = obs[obs.index >= cut]
    if sim_res.empty:
        raise SystemExit(f"no simulated reservoir stage for run {run.sim_id}")

    performance_figure(sim_res, obs, args.out_dir, warmup_days=args.warmup_days)
    two_lake_figure(run, obs, args.out_dir, sill=args.sill, spillway=args.spillway)
    print("DONE")


if __name__ == "__main__":
    main()
