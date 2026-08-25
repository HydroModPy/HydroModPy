"""Cheze reservoir water-balance diagnostic from a MF6 LAK obs file.

Reads a native MODFLOW 6 ``.lak.obs.csv`` (time in days from the run start) and
draws the reservoir stage trajectory vs the observed level plus the mean LAK
budget terms, so an out-of-balance managed reservoir (withdrawal >> catchment
feed -> the lake drains) reads at a glance. This is the "why it does not
simulate well" figure when the balance, not a parameter, is the problem.

Usage:
    python tools/diagnostics/cheze_water_balance.py \
        <lak_obs.csv> <start_date> <out_dir> [--observed observed.csv] [--lake RESERVOIR_CHEZE]
"""

from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RES = "#0b6e8a"
OBSC = "#111111"
# LAK budget columns that are gains (+) or losses (-) for the lake volume.
GAINS = [
    ("FROM_MVR", "#2a9d8f", "apport bassin (SFR/DRN via MVR)"),
    ("RAINFALL", "#5aa5d6", "pluie sur le lac"),
    ("RUNOFF", "#8fce00", "ruissellement littoral"),
    ("INFLOW", "#7b2fbe", "transfert gere (Meu/Canut)"),
]
LOSSES = [("WITHDRAWAL", "#c1272d", "prelevement gere"), ("EVAPORATION", "#e08e00", "evaporation")]


def _lake_series(df, lake, term):
    col = f"{lake}_{term}"
    if col not in df.columns:
        return None
    return df[col].replace([3e30, -3e30], np.nan)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lak_obs_csv")
    ap.add_argument("start_date")
    ap.add_argument("out_dir")
    ap.add_argument("--observed", default=None)
    ap.add_argument("--lake", default="RESERVOIR_CHEZE")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    df = pd.read_csv(args.lak_obs_csv)
    start = pd.Timestamp(args.start_date)
    # MF6 obs "time" is elapsed model time. Infer the unit from its magnitude: a
    # daily run has ~N rows, so time >> N means the model unit is seconds (fluxes
    # in m3/s), otherwise it is already days.
    tvals = df["time"].to_numpy(dtype=float)
    unit = "s" if np.nanmax(tvals) > 10.0 * len(df) else "D"
    dates = start + pd.to_timedelta(tvals, unit=unit)
    stage = _lake_series(df, args.lake, "STAGE")

    fig, (ax, axb) = plt.subplots(2, 1, figsize=(15, 9), gridspec_kw={"height_ratios": [1.35, 1]})
    # --- stage trajectory vs observed ---
    ax.plot(dates, stage.to_numpy(), color=RES, lw=1.4, label="reservoir simule (LAK)")
    if args.observed:
        obs = pd.read_csv(args.observed)
        tcol = obs.columns[0]
        vcol = "value" if "value" in obs.columns else obs.columns[1]
        ot = pd.to_datetime(obs[tcol])
        m = (ot >= dates.min()) & (ot <= dates.max())
        ax.plot(ot[m], obs[vcol][m], color=OBSC, lw=1.1, label="reservoir observe")
    lakebed = float(np.nanmin(stage))
    ax.axhline(lakebed, color="0.5", ls=":", lw=1)
    ax.text(
        dates[len(dates) // 2],
        lakebed + 0.4,
        f"fond atteint ~{lakebed:.1f} m",
        fontsize=8,
        color="0.4",
    )
    ax.set_ylabel("cote du plan d'eau (m NGF)")
    ax.set_title(
        "Reservoir Cheze : le niveau simule s'effondre alors que l'observe reste tenu\n"
        "(desequilibre du bilan, pas un probleme de calage)",
        fontsize=13,
    )
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(alpha=0.25)

    # --- mean budget terms (annualised Mm3/yr) ---
    n = min(300, len(df))  # first ~year, lake still near full
    labels, values, colors = [], [], []
    for term, col, lab in GAINS:
        s = _lake_series(df, args.lake, term)
        if s is None:
            continue
        labels.append(lab)
        values.append(float(np.nanmean(s.iloc[:n])) * 86400 * 365 / 1e6)
        colors.append(col)
    for term, col, lab in LOSSES:
        s = _lake_series(df, args.lake, term)
        if s is None:
            continue
        labels.append(lab)
        values.append(float(np.nanmean(s.iloc[:n])) * 86400 * 365 / 1e6)
        colors.append(col)
    # aquifer exchange = sum of per-connection LAK_i terms
    lakcols = [c for c in df.columns if c.startswith(f"{args.lake}_LAK_")]
    if lakcols:
        gwf = df[lakcols].replace([3e30, -3e30], np.nan).iloc[:n].sum(axis=1)
        labels.append("echange aquifere (GWF)")
        values.append(float(np.nanmean(gwf)) * 86400 * 365 / 1e6)
        colors.append("#1d4ed8")
    y = np.arange(len(labels))
    axb.barh(y, values, color=colors)
    axb.set_yticks(y)
    axb.set_yticklabels(labels, fontsize=9)
    axb.axvline(0, color="k", lw=0.8)
    for yi, v in zip(y, values):
        axb.text(
            v + (0.1 if v >= 0 else -0.1),
            yi,
            f"{v:+.2f}",
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=8,
        )
    net = sum(values)
    axb.set_xlabel("flux moyen annualise (Mm3/an), 1re annee lac ~plein")
    axb.set_title(
        f"Bilan du reservoir : le prelevement ecrase les apports (net = {net:+.2f} Mm3/an)",
        fontsize=11,
    )
    axb.grid(alpha=0.25, axis="x")

    fig.tight_layout()
    p = os.path.join(args.out_dir, "diag_water_balance.png")
    fig.savefig(p, dpi=140)
    plt.close(fig)
    print("diag_water_balance.png | net balance =", round(net, 2), "Mm3/yr")


if __name__ == "__main__":
    main()
