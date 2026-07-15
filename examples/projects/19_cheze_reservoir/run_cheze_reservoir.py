"""Example 19 - Cheze reservoir (EBR), MODFLOW 6 LAK + SFR, weekly transient.

Runs the config-declared Cheze reservoir on the MODFLOW 6 backend and pulls the
per-lake output series (stage, volume, lake-aquifer exchange, the SFR feed
``from_mvr``) plus the per-reach SFR figures from the result store. Recharge is
fetched from the SIM2 Meteo-France API at run time, so a network connection (or
a warm SIM2 cache) is required.

    python run_cheze_reservoir.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt

# Run against this working tree, not whatever 'hydromodpy' a notebook CWD resolves.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import hydromodpy as hmp  # noqa: E402

LAKE = "reservoir_cheze"
HERE = Path(__file__).parent


def main() -> None:
    project = hmp.Project(HERE / "project.toml")
    print(f"Catchment area: {project.geographic.catch_area:.1f} km2")

    result = project.simulate(name="cheze_reservoir_transient")
    print(f"Run completed: {result.name}  (sim_id={result.sim_id})")

    store = project.store
    series = {}
    for quantity in (
        "stage",
        "volume",
        "gwf_exchange",
        "ext_outflow",
        "inflow",
        "withdrawal",
        "from_mvr",
    ):
        try:
            series[quantity] = store.query_timeseries(result.sim_id, f"lake:{LAKE}", quantity)
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] no '{quantity}' series: {exc}")

    if "stage" in series:
        stage = series["stage"]
        print(f"  lake stage: {float(stage.min()):.2f} -> {float(stage.max()):.2f} m NGF")
    if "from_mvr" in series:
        feed = series["from_mvr"]
        print(f"  SFR feed (from_mvr): mean {float(feed.mean()) * 1000.0:.1f} L/s")

    fig_dir = HERE / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    if "stage" in series and "volume" in series:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 5), sharex=True, dpi=150)
        ax1.plot(series["stage"].index, series["stage"].to_numpy(), color="navy", lw=1.5)
        ax1.set_ylabel("Stage [m NGF]")
        ax1.set_title("Cheze reservoir - MODFLOW 6 LAK + SFR (transient 2019)")
        ax2.plot(series["volume"].index, series["volume"].to_numpy() / 1e6, color="teal", lw=1.5)
        ax2.set_ylabel("Volume [Mm3]")
        ax2.set_xlabel("Time")
        fig.tight_layout()
        fig.savefig(fig_dir / "cheze_stage_volume.png", bbox_inches="tight")
        plt.close(fig)
        print(f"  [plot] {fig_dir / 'cheze_stage_volume.png'}")

    # The SFR side, through the registered display figures (read-only on the
    # store): the reach network map, the routed-flow longitudinal profile, and
    # the most-downstream-reach flow chronicle.
    from hydromodpy.display.figure_registry import get as get_figure
    from hydromodpy.results.run import Run

    run = Run(result.sim_id, store)
    for name in ("sfr_reach_network", "sfr_longitudinal_profile", "sfr_reach_timeseries"):
        try:
            figure = get_figure(name).plot(run, save_path=fig_dir / f"cheze_{name}.png")
            plt.close(figure)
            print(f"  [plot] {fig_dir / f'cheze_{name}.png'}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] figure '{name}' skipped: {exc}")


if __name__ == "__main__":
    main()
