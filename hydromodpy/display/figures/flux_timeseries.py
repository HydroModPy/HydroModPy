"""Water-balance components through time, over the whole model domain.

The complement of :class:`~hydromodpy.display.figures.water_budget.WaterBudget`:
that one sums each component over the run, this one shows how they evolve.
Inflows are drawn positive, outflows negative, so the curves visually close
on the storage change.

Components are read from the budget table, whose names are normalized to the
public field vocabulary (``recharge``, ``drain``, ``well``, ...) whatever the
solver, so the figure needs no per-backend knowledge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.map_axes import style_date_axis

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


# Stable colour per physical role, so the same component reads the same way
# across projects and backends. Unlisted components fall back to the cycle.
_COMPONENT_COLORS: dict[str, str] = {
    "recharge": "dodgerblue",
    "drain": "firebrick",
    "well": "darkorange",
    "river": "seagreen",
    "lake": "teal",
    "stream": "olive",
    "evapotranspiration": "goldenrod",
    "constant_head": "slateblue",
    "general_head": "orchid",
}
# Storage is an accounting term, not a flux across the domain boundary.
_STORAGE_PREFIX = "storage"
# Managed point extractions. These are a sparse discrete schedule (pumping
# happens on a few periods), not a distributed flux, so they read as bars,
# not as a step line that flattens to zero between pumping periods.
_BAR_COMPONENTS: frozenset[str] = frozenset({"well"})


@register
class FluxTimeseries(BaseFigure):
    """Signed domain fluxes per stress period.

    Options
    -------
    ``units``
        ``"m3/s"`` (default) or ``"mm/period"``, the depth equivalent over
        the model domain, which is how hydrologists compare a recharge to a
        discharge.
    ``include_storage``
        Draw the storage change as well (default False: it is the residual).
    """

    spec = FigureSpec(
        name="flux_timeseries",
        title="Water-balance components",
        kind="balance",
        required_tables=("budgets",),
        default_figsize=(8.5, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        units: str = "m3/s",
        include_storage: bool = False,
        **_,
    ) -> Axes:
        frame = sim.budget()
        if frame.empty:
            raise ValueError(f"no budget rows stored for sim {sim.sim_id}")

        net = (
            frame.assign(net=frame["flux_in"] - frame["flux_out"])
            .groupby(["component", "timestep"], as_index=False)["net"]
            .sum()
            .pivot(index="timestep", columns="component", values="net")
            .sort_index()
        )
        if not include_storage:
            net = net.drop(columns=[c for c in net.columns if c.startswith(_STORAGE_PREFIX)])
        if net.empty or not len(net.columns):
            raise ValueError("budget holds no boundary flux component to plot")

        index, xlabel = _time_axis(sim, net.index)
        scale, ylabel = _scaling(sim, units, index)

        line_components = [c for c in net.columns if c not in _BAR_COMPONENTS]
        bar_components = [c for c in net.columns if c in _BAR_COMPONENTS]

        # Distributed fluxes hold over each stress period -> step lines.
        for component in line_components:
            values = np.asarray(net[component], dtype="float64") * scale
            ax.step(
                index,
                values,
                where="post",
                lw=1.8,
                color=_COMPONENT_COLORS.get(component),
                label=component.replace("_", " "),
            )
        ax.axhline(0.0, color="0.4", lw=0.8)

        bar_ax = None
        if bar_components:
            # A managed point extraction (pumping) is orders of magnitude
            # smaller than the distributed fluxes; on the shared depth axis it
            # collapses onto zero. A twin axis, zero-aligned with the primary
            # one, shows the pumping schedule as bars at its own scale without
            # distorting the balance (legacy example_00 did the same).
            bar_ax = ax.twinx()
            period = _period_width(index)
            centers = _period_centers(index, period)
            bar_color = _COMPONENT_COLORS.get(bar_components[0], "darkorange")
            for component in bar_components:
                values = np.asarray(net[component], dtype="float64") * scale
                # Centred, half-period bars so the drain/recharge steps stay
                # readable on either side of each pumping bar.
                bar_ax.bar(
                    centers,
                    values,
                    width=0.55 * period,
                    align="center",
                    color=_COMPONENT_COLORS.get(component),
                    alpha=0.85,
                    edgecolor="black",
                    linewidth=0.4,
                    label=" ".join(component.split("_")),
                )
            unit_token = "mm/period" if "mm" in ylabel else "m3/s"
            bar_ax.set_ylabel(f"Managed pumping ({unit_token})", color=bar_color)
            bar_ax.tick_params(axis="y", labelcolor=bar_color)
            _align_zero_axes(ax, bar_ax)

        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, ls=":", lw=0.4, alpha=0.6)
        handles, labels = ax.get_legend_handles_labels()
        if bar_ax is not None:
            extra = bar_ax.get_legend_handles_labels()
            handles += extra[0]
            labels += extra[1]
        ax.legend(handles, labels, fontsize=9, framealpha=0.9, ncols=min(len(labels), 4))
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}\npositive = into the aquifer")
        if isinstance(index, pd.DatetimeIndex):
            style_date_axis(ax)
        return ax


def _time_axis(sim: Run, timesteps: pd.Index) -> tuple[pd.Index, str]:
    """Return the calendar index when the run has one, else the step number."""
    try:
        stamps = sim.time_index
    except Exception:
        return timesteps, "Stress period"
    if len(stamps) != len(timesteps):
        return timesteps, "Stress period"
    return stamps, "Date"


def _scaling(sim: Run, units: str, index: pd.Index) -> tuple[float, str]:
    """Return the multiplicative factor and axis label for the requested units."""
    token = str(units).strip().lower()
    if token in ("m3/s", "m3 s-1", ""):
        return 1.0, "Flux (m3/s)"
    if token not in ("mm/period", "mm"):
        raise ValueError(f"flux_timeseries: unsupported units '{units}' (m3/s or mm/period)")
    from hydromodpy.display.mesh_geometry import domain_area_m2

    # The budget is a domain balance, so the depth equivalent must divide by
    # the ACTIVE domain area. Using the catchment area would inflate every
    # component whenever the grid extends past the catchment (buffered box).
    area = domain_area_m2(sim)
    if not area:
        raise ValueError("mm/period requires a positive model domain area")
    seconds = _period_seconds(index)
    return 1000.0 * seconds / float(area), "Flux (mm/period over model domain)"


def _period_seconds(index: pd.Index) -> float:
    """Return the mean stress-period length in seconds, 1.0 when unknown."""
    if isinstance(index, pd.DatetimeIndex) and len(index) > 1:
        return float(np.median(np.diff(index.astype("int64"))) / 1e9)
    return 1.0


def _period_width(index: pd.Index) -> float:
    """Return one stress period's width in the x-axis data units.

    A matplotlib date axis measures in days, so a datetime index yields the
    median period in days; an integer stress-period axis yields 1.
    """
    if isinstance(index, pd.DatetimeIndex) and len(index) > 1:
        return float(np.median(np.diff(index.astype("int64"))) / 8.64e13)
    if len(index) > 1:
        return float(np.median(np.diff(np.asarray(index, dtype="float64"))))
    return 1.0


def _period_centers(index: pd.Index, period: float) -> np.ndarray:
    """Return the numeric midpoint of each stress period on the shared x-axis.

    ``where="post"`` step segments span ``[x[i], x[i] + period]``; the bar
    centre is half a period to the right of the period start. Datetime labels
    are converted to matplotlib day numbers so bars co-register with the steps.
    """
    if isinstance(index, pd.DatetimeIndex):
        import matplotlib.dates as mdates

        start = mdates.date2num(index.to_pydatetime())
    else:
        start = np.asarray(index, dtype="float64")
    return start + 0.5 * period


def _align_zero_axes(primary: Axes, secondary: Axes) -> None:
    """Rescale ``secondary`` so its zero sits at the same height as ``primary``'s.

    Keeps the secondary data in view while pinning the two zero lines together,
    so a downward pumping bar and a downward drain step read on the same
    baseline even though the axes have different scales.
    """
    p0, p1 = primary.get_ylim()
    if p1 == p0:
        return
    zero_fraction = (0.0 - p0) / (p1 - p0)
    s0, s1 = secondary.get_ylim()
    candidates = [0.0]
    if zero_fraction > 0:
        candidates.append(-s0 / zero_fraction)
    if zero_fraction < 1:
        candidates.append(s1 / (1.0 - zero_fraction))
    span = max(candidates)
    if span <= 0:
        return
    secondary.set_ylim(-zero_fraction * span, (1.0 - zero_fraction) * span)
