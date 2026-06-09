"""Example 19 - Cheze reservoir (EBR), MODFLOW 6 LAK, weekly transient.

Runs the config-declared Cheze reservoir on the MODFLOW 6 backend and pulls the
per-lake output series (stage, volume, lake-aquifer exchange) from the result
store. Recharge is fetched from the SIM2 Meteo-France API at run time, so a
network connection (or a warm SIM2 cache) is required.

    python run_cheze_reservoir.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

import hydromodpy as hmp

LAKE = "reservoir_cheze"
HERE = Path(__file__).parent


def main() -> None:
    project = hmp.Project(HERE / "project.toml")
    print(f"Catchment area: {project.geographic.catch_area:.1f} km2")

    result = project.simulate(name="cheze_reservoir_transient")
    print(f"Run completed: {result.name}  (sim_id={result.sim_id})")

    store = project.store
    series = {}
    for quantity in ("stage", "volume", "gwf_exchange", "ext_outflow", "inflow", "withdrawal"):
        try:
            series[quantity] = store.query_timeseries(result.sim_id, f"lake:{LAKE}", quantity)
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] no '{quantity}' series: {exc}")

    if "stage" in series:
        stage = series["stage"]
        print(f"  lake stage: {float(stage.min()):.2f} -> {float(stage.max()):.2f} m NGF")

    fig_dir = HERE / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    if "stage" in series and "volume" in series:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 5), sharex=True, dpi=150)
        ax1.plot(series["stage"].index, series["stage"].to_numpy(), color="navy", lw=1.5)
        ax1.set_ylabel("Stage [m NGF]")
        ax1.set_title("Cheze reservoir - MODFLOW 6 LAK (transient 2019)")
        ax2.plot(series["volume"].index, series["volume"].to_numpy() / 1e6, color="teal", lw=1.5)
        ax2.set_ylabel("Volume [Mm3]")
        ax2.set_xlabel("Time")
        fig.tight_layout()
        fig.savefig(fig_dir / "cheze_stage_volume.png", bbox_inches="tight")
        plt.close(fig)
        print(f"  [plot] {fig_dir / 'cheze_stage_volume.png'}")


if __name__ == "__main__":
    main()
