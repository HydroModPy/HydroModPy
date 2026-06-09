"""Example 19 - Cheze reservoir: daily full-chronicle run + simulated-vs-observed.

Runs ``project_chronicle.toml`` (daily 2007-2025) and compares the simulated LAK
lake stage to the observed Cheze level. v1 has no declarative forward
sim-vs-observed lake wiring (the ``lake_levels`` family loads but has no
consumer), so the comparison is scripted here from existing parts:
``query_timeseries`` for the simulated series, the observed CSV
(``data/lake_levels``), the stage-volume abacus, and the goodness-of-fit
metrics. This mirrors the legacy EBR overlay + NSE/RMSE/R2.

A ~19-year daily run is ~6940 stress periods and fetches SIM2 over the full
window on the first run, so expect a multi-minute (network + solve) wall time.

    python compare_chronicle.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import hydromodpy as hmp
from hydromodpy.core.metrics.goodness_of_fit import bias, correlation, mae, nse, rmse

LAKE = "reservoir_cheze"
HERE = Path(__file__).parent
DATA = HERE / ".." / ".." / "data"
OBS_LEVELS = DATA / "lake_levels" / "lake_levels_custom_reservoir_cheze.csv"
ABACUS = DATA / "lake_abacus" / "reservoir_cheze.csv"
SPILLWAY_CREST_M = 87.3


def _observed_stage() -> pd.Series:
    """Observed Cheze level (m NGF), daily, datetime-indexed."""
    df = pd.read_csv(OBS_LEVELS, parse_dates=["datetime"]).set_index("datetime")
    return df["value"].astype(float)


def _stage_to_volume(stage: pd.Series) -> pd.Series:
    """Convert a stage series to volume (m3) through the lake abacus."""
    ab = pd.read_csv(ABACUS).sort_values("stage")
    vol = np.interp(
        stage.to_numpy(float), ab["stage"].to_numpy(float), ab["volume"].to_numpy(float)
    )
    return pd.Series(vol, index=stage.index)


def _scores(sim: pd.Series, obs: pd.Series) -> dict[str, float]:
    """NSE / RMSE / MAE / bias / R2 on the common (inner-joined) dates."""
    pair = pd.concat([sim.rename("sim"), obs.rename("obs")], axis=1, join="inner").dropna()
    s, o = pair["sim"].to_numpy(float), pair["obs"].to_numpy(float)
    return {
        "n": float(len(pair)),
        "NSE": nse(s, o),
        "RMSE": rmse(s, o),
        "MAE": mae(s, o),
        "bias": bias(s, o),
        "R2": correlation(s, o) ** 2,
    }


def main() -> None:
    project = hmp.Project(HERE / "project_chronicle.toml")
    result = project.simulate(name="cheze_reservoir_chronicle")
    print(f"Run completed: sim_id={result.sim_id}")

    store = project.store
    # Drop the steady warm-up (first period) from the comparison.
    sim_stage = store.query_timeseries(result.sim_id, f"lake:{LAKE}", "stage").iloc[1:]
    sim_volume = store.query_timeseries(result.sim_id, f"lake:{LAKE}", "volume").iloc[1:]

    obs_stage = _observed_stage()
    obs_volume = _stage_to_volume(obs_stage)

    stage_scores = _scores(sim_stage, obs_stage)
    volume_scores = _scores(sim_volume, obs_volume)
    print("Lake STAGE (m NGF) simulated vs observed:")
    for key, val in stage_scores.items():
        print(f"  {key:5s} = {val:.4g}")
    print("Lake VOLUME (m3) simulated vs observed (obs stage -> abacus):")
    for key, val in volume_scores.items():
        print(f"  {key:5s} = {val:.4g}")

    fig_dir = HERE / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True, dpi=150)
    ax1.plot(obs_stage.index, obs_stage.to_numpy(), color="black", lw=0.7, label="observed")
    ax1.plot(sim_stage.index, sim_stage.to_numpy(), color="crimson", lw=0.7, label="simulated")
    ax1.axhline(SPILLWAY_CREST_M, color="grey", ls=":", lw=0.8, label="spillway crest")
    ax1.set_ylabel("Stage [m NGF]")
    ax1.legend(loc="best", fontsize=8)
    ax1.set_title(
        "Cheze reservoir - MODFLOW 6 LAK, daily 2007-2025  "
        f"(stage NSE={stage_scores['NSE']:.2f}, RMSE={stage_scores['RMSE']:.2f} m)"
    )
    ax2.plot(obs_volume.index, obs_volume.to_numpy() / 1e6, color="black", lw=0.7, label="observed")
    ax2.plot(sim_volume.index, sim_volume.to_numpy() / 1e6, color="teal", lw=0.7, label="simulated")
    ax2.set_ylabel("Volume [Mm3]")
    ax2.set_xlabel("Time")
    ax2.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig_path = fig_dir / "cheze_chronicle_obs_vs_sim.png"
    fig.savefig(fig_path, bbox_inches="tight")
    plt.close(fig)
    print(f"[plot] {fig_path}")

    metrics_path = fig_dir / "cheze_chronicle_metrics.csv"
    pd.DataFrame({"stage": stage_scores, "volume": volume_scores}).to_csv(metrics_path)
    print(f"[metrics] {metrics_path}")


if __name__ == "__main__":
    main()
