"""Lake stage and lake storage, simulated against the gauged record.

A reservoir model is judged on the lake level, so these two figures carry the
comparison the rest of the gallery has no place for. Storage is the same
comparison in the unit that matters for management: the observed stage is turned
into a volume through the REFERENCE abacus, never through the carved bed, so a
grid whose cuvette is off does not quietly rescale the observation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.metrics import bias, kge, nse, rmse
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.map_axes import style_date_axis
from hydromodpy.results.derive.time_alignment import (
    normalize_datetime_series,
    observed_on_simulation_index,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

# Canonical variable names the gauged lake level may carry. ``Run.observed``
# strips the ``_obs`` suffix the ingestion adds, so query WITHOUT it; the data
# family is ``lake_levels`` but a record may name its variable in the singular.
_OBS_VARIABLES: tuple[str, ...] = ("lake_level", "lake_levels", "stage")

_STATION_PREFIX = "lake:"


def _default_lake(sim: Run) -> str:
    """The lake holding the most water at full pool, as the abacus figure picks."""
    from hydromodpy.results.run.lake_abacus_view import run_lake_abacus

    return str(run_lake_abacus(sim)["lake_id"])


def _observed_stage(sim: Run, lake_id: str):
    """Gauged stage for one lake, or ``None`` when the run carries none."""
    for variable in _OBS_VARIABLES:
        try:
            frame = sim.observed(variable)
        except (ValueError, KeyError):
            continue
        if frame is None or frame.empty:
            continue
        stations = frame["station_id"].astype(str)
        match = frame[stations.str.removeprefix(_STATION_PREFIX) == lake_id]
        if match.empty:
            match = frame if stations.nunique() == 1 else match
        if match.empty:
            continue
        return normalize_datetime_series(match.set_index("datetime")["value"])
    return None


def _metrics_box(ax: Axes, sim_values: np.ndarray, obs_values: np.ndarray, unit: str) -> None:
    """Write KGE / NSE / RMSE / bias for the aligned pair."""
    if sim_values.size < 2:
        return
    # kge() returns the decomposition, not a scalar: r, alpha (variance ratio) and
    # beta (mean ratio) say WHERE a mediocre KGE comes from, which a single number
    # hides. A respectable KGE carrying an alpha far from one is a model whose
    # amplitude is wrong, not one that is nearly right.
    decomposition = kge(sim_values, obs_values)
    lines = [
        f"KGE   {decomposition['kge']:+.4f}",
        f"  r   {decomposition['r']:+.4f}",
        f"  a   {decomposition['alpha']:.4f}   (ecart-type sim/obs)",
        f"  b   {decomposition['beta']:.4f}   (moyenne sim/obs)",
        f"NSE   {nse(sim_values, obs_values):+.4f}",
        f"RMSE  {rmse(sim_values, obs_values):.4g} {unit}",
        f"biais {bias(sim_values, obs_values):+.4g} {unit}",
        f"n     {sim_values.size}",
    ]
    ax.text(
        0.985,
        0.04,
        "\n".join(lines),
        transform=ax.transAxes,
        va="bottom",
        ha="right",
        fontsize=8.5,
        family="monospace",
        bbox={
            "boxstyle": "round,pad=0.45",
            "facecolor": "white",
            "alpha": 0.85,
            "edgecolor": "#d0d0d0",
        },
    )


def _plot_pair(ax: Axes, sim_ts, obs_ts, *, sim_label: str, obs_label: str):
    """Draw the simulated and observed series and return the aligned arrays."""
    ax.plot(sim_ts.index, sim_ts.values, label=sim_label, color="#b3352c", lw=1.3)
    aligned = observed_on_simulation_index(obs_ts, sim_ts.index).dropna()
    if aligned.empty:
        return None, None
    ax.plot(
        aligned.index,
        aligned.values,
        label=obs_label,
        color="#111111",
        lw=1.0,
        ls="--",
        alpha=0.9,
    )
    paired = sim_ts.reindex(aligned.index)
    keep = paired.notna().to_numpy()
    return paired.to_numpy()[keep], aligned.to_numpy()[keep]


@register
class LakeStageSimObs(BaseFigure):
    """Simulated lake stage over the gauged record."""

    spec = FigureSpec(
        name="lake_stage_sim_obs",
        title="Lake stage (sim vs obs)",
        kind="comparison",
        required_tables=("timeseries",),
        default_figsize=(9.0, 4.6),
    )

    def render(self, sim: Run, ax: Axes, *, lake_id: str | None = None, **_: Any) -> Axes:
        lake = lake_id or _default_lake(sim)
        sim_ts = normalize_datetime_series(
            sim.timeseries("stage", station=f"{_STATION_PREFIX}{lake}")
        )
        obs_ts = _observed_stage(sim, lake)
        if obs_ts is None:
            raise ValueError(
                f"no gauged lake level ingested for {lake!r}; declare [data.lake_levels] "
                "so the observation reaches the run store"
            )
        sim_v, obs_v = _plot_pair(ax, sim_ts, obs_ts, sim_label="sim", obs_label="obs")
        if sim_v is None:
            raise ValueError(f"gauged lake level for {lake!r} does not overlap the simulation")
        _metrics_box(ax, sim_v, obs_v, "m")
        ax.set_xlabel("Date")
        ax.set_ylabel("Stage [m]")
        ax.set_title(f"Lake stage sim vs obs - {lake} ({sim.name or sim.sim_id})")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend(fontsize=10, framealpha=0.94, loc="upper left")
        style_date_axis(ax)
        return ax


@register
class LakeVolumeSimObs(BaseFigure):
    """Simulated lake storage over the storage implied by the gauged stage."""

    spec = FigureSpec(
        name="lake_volume_sim_obs",
        title="Lake storage (sim vs obs)",
        kind="comparison",
        required_tables=("timeseries",),
        default_figsize=(9.0, 4.6),
    )

    def render(self, sim: Run, ax: Axes, *, lake_id: str | None = None, **_: Any) -> Axes:
        from hydromodpy.results.run.lake_abacus_view import run_lake_abacus

        lake = lake_id or _default_lake(sim)
        abacus = run_lake_abacus(sim, lake)
        stage_axis = np.asarray(abacus["stage"], dtype=float)
        reference_volume = np.asarray(abacus["real_volume"], dtype=float)

        sim_ts = normalize_datetime_series(
            sim.timeseries("volume", station=f"{_STATION_PREFIX}{lake}")
        )
        obs_stage = _observed_stage(sim, lake)
        if obs_stage is None:
            raise ValueError(
                f"no gauged lake level ingested for {lake!r}; declare [data.lake_levels] "
                "so the observation reaches the run store"
            )
        # The gauged STAGE becomes a volume through the reference abacus, so the
        # observation stays independent of whatever cuvette the grid carved.
        obs_volume = obs_stage.copy()
        obs_volume[:] = np.interp(obs_stage.to_numpy(dtype=float), stage_axis, reference_volume)

        scale = 1e6
        sim_v, obs_v = _plot_pair(
            ax,
            sim_ts / scale,
            obs_volume / scale,
            sim_label="sim (MF6)",
            obs_label="obs (stage through the reference abacus)",
        )
        if sim_v is None:
            raise ValueError(f"gauged lake level for {lake!r} does not overlap the simulation")
        _metrics_box(ax, sim_v, obs_v, "Mm3")
        ax.set_xlabel("Date")
        ax.set_ylabel("Storage [Mm3]")
        ax.set_title(f"Lake storage sim vs obs - {lake} ({sim.name or sim.sim_id})")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend(fontsize=9, framealpha=0.94, loc="upper left")
        style_date_axis(ax)
        return ax
