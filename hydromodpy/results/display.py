from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.results.simulation import Simulation

logger = logging.getLogger(__name__)

_NO_DISPLAY = os.environ.get("HYDROMODPY_NO_DISPLAY", "0") == "1"
_NO_SAVE = os.environ.get("HYDROMODPY_NO_SAVE", "0") == "1"


def render_figure(
    figure_name: str,
    sim: Simulation,
    *,
    save: str | Path | None = None,
) -> None:
    renderer = _RENDERERS.get(figure_name)
    if renderer is None:
        raise ValueError(f"No renderer registered for '{figure_name}'")
    renderer(sim, save=save)


def _render_watertable_map(sim: Simulation, *, save=None) -> None:
    import matplotlib.pyplot as plt

    n_ts = sim.n_timesteps or 1
    data = sim.field("head", timestep=n_ts - 1, layer=0)

    fig, ax = plt.subplots()
    im = ax.imshow(data.reshape(-1), aspect="auto")
    ax.set_title(f"Watertable — {sim.name or sim.id}")
    fig.colorbar(im, ax=ax, label="head (m)")
    _finish(fig, save, "watertable_map")


def _render_budget_chart(sim: Simulation, *, save=None) -> None:
    import matplotlib.pyplot as plt

    df = sim.budget()
    if df.empty:
        logger.info("No budget data for %s", sim.id)
        return

    components = df.groupby("component")[["flux_in", "flux_out"]].sum()
    fig, ax = plt.subplots()
    components.plot.bar(ax=ax)
    ax.set_title(f"Budget — {sim.name or sim.id}")
    ax.set_ylabel("Flux (m3/d)")
    _finish(fig, save, "budget_chart")


def _render_streamflow(sim: Simulation, *, save=None) -> None:
    import matplotlib.pyplot as plt

    try:
        ts = sim.timeseries("outflow_drain", station="_catchment")
    except KeyError:
        try:
            ts = sim.timeseries("discharge", station="_catchment")
        except KeyError:
            logger.info("No streamflow data for %s", sim.id)
            return

    fig, ax = plt.subplots()
    ts.plot(ax=ax)
    ax.set_title(f"Streamflow — {sim.name or sim.id}")
    ax.set_ylabel("Discharge")
    _finish(fig, save, "streamflow")


def _render_head_timeseries(sim: Simulation, *, save=None) -> None:
    import matplotlib.pyplot as plt

    metrics_df = sim.metrics
    if metrics_df.empty:
        return
    stations = metrics_df["station_id"].unique()

    fig, ax = plt.subplots()
    for station in stations[:5]:
        try:
            ts = sim.timeseries("head", station=station)
            ts.plot(ax=ax, label=station)
        except KeyError:
            continue
    ax.set_title(f"Head timeseries — {sim.name or sim.id}")
    ax.set_ylabel("Head (m)")
    ax.legend()
    _finish(fig, save, "head_timeseries")


def _render_cross_section(sim: Simulation, *, save=None) -> None:
    import matplotlib.pyplot as plt

    n_ts = sim.n_timesteps or 1
    data = sim.field("head", timestep=n_ts - 1)

    fig, ax = plt.subplots()
    if data.ndim == 2:
        mid_col = data.shape[1] // 2
        ax.plot(data[:, mid_col], label="mid-column")
    ax.set_title(f"Cross section — {sim.name or sim.id}")
    ax.set_xlabel("Layer")
    ax.set_ylabel("Head (m)")
    _finish(fig, save, "cross_section")


def _render_stub(name: str):
    def _render(sim: Simulation, *, save=None) -> None:
        logger.info("Renderer '%s' not yet implemented for sim %s", name, sim.id)
    return _render


def _finish(fig, save, name: str) -> None:
    import matplotlib.pyplot as plt

    if save is not None and not _NO_SAVE:
        out = Path(save)
        out.mkdir(parents=True, exist_ok=True)
        fig.savefig(out / f"{name}.png", dpi=150, bbox_inches="tight")

    if not _NO_DISPLAY:
        plt.show()
    plt.close(fig)


_RENDERERS = {
    "watertable_map": _render_watertable_map,
    "budget_chart": _render_budget_chart,
    "streamflow": _render_streamflow,
    "head_timeseries": _render_head_timeseries,
    "cross_section": _render_cross_section,
    "drainage_density": _render_stub("drainage_density"),
    "concentration_map": _render_stub("concentration_map"),
    "pathlines": _render_stub("pathlines"),
}
