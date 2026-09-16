"""Recession rate against discharge, on the Brutsaert-Nieber log-log plane.

A draining aquifer sets how fast its own baseflow falls, so plotting ``-dQ/dt``
against ``Q`` collapses every recession of a chronicle onto one cloud whose
slope is the drainage law. The late-time solution of the non-linear Boussinesq
(1904) equation predicts ``-dQ/dt = a Q^b`` with ``b = 3/2`` and

    a = 4.804 K^(1/2) L / (f A^(3/2))

for an aquifer of area ``A`` drained through a stream reach of length ``L``,
hydraulic conductivity ``K`` and drainable porosity ``f``. A cloud lying on a
3/2 line is the model reproducing that solution, and the offset to the
analytical line is the only number left to read.

Everything is computed on a volume-per-day clock: a discharge in m3/s is
converted to m3/day first, so ``K`` is read in m/day and ``a`` comes out in
``day^-1 (m3/day)^-1/2``, the system the coefficient above is written in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.legend_placement import place_legend

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

SECONDS_PER_DAY = 86400.0
BOUSSINESQ_LATE_TIME_CONSTANT = 4.804
"""Brutsaert-Nieber coefficient of the late-time non-linear Boussinesq solution."""


def brutsaert_nieber_coefficient(
    *, k: float, porosity: float, stream_length: float, area: float, sides: int = 2
) -> float:
    """Return ``a`` of ``-dQ/dt = a Q^(3/2)`` for one aquifer geometry.

    ``k`` in m/day, ``stream_length`` and ``area`` in m and m2, ``porosity``
    dimensionless. The result applies to a discharge expressed in m3/day and a
    time in days.

    The published coefficient is written for a reach drained from both banks,
    with ``area`` the aquifer on both of them. A hillslope draining into one
    bank only carries half the discharge of that symmetric pair for the same
    breadth, which halves the coefficient: declare ``sides = 1`` and give the
    area of the single flank.
    """
    symmetric = BOUSSINESQ_LATE_TIME_CONSTANT * k**0.5 * stream_length / (porosity * area**1.5)
    return symmetric * sides / 2.0


def _days_since_start(index: pd.Index) -> np.ndarray:
    """Return the series index as days elapsed since its first entry."""
    if isinstance(index, pd.DatetimeIndex):
        return np.asarray((index - index[0]).total_seconds(), dtype="float64") / SECONDS_PER_DAY
    return np.asarray(index, dtype="float64")


def budget_outflow_per_day(sim: Run, component: str) -> pd.Series:
    """Return what leaves the domain through one budget component, in m3/day.

    A lateral fixed head is not a stream, so the catchment aggregation never
    turns it into a ``discharge`` series: on a hillslope closed by a fixed head
    the recession is only readable in the budget itself. Rows are taken on the
    whole-domain zone and indexed by the run's own time axis.
    """
    rows = sim.budget(component=component)
    if rows.empty:
        raise ValueError(f"budget component '{component}' is empty for sim {sim.sim_id}")
    zone = "0" if (rows["zone_id"] == "0").any() else rows["zone_id"].iloc[0]
    zoned = rows.loc[rows["zone_id"] == zone]
    steps = np.asarray(zoned["timestep"], dtype="int64")
    values = np.asarray(zoned["flux_out"], dtype="float64") * SECONDS_PER_DAY
    order = np.argsort(steps)
    steps, values = steps[order], values[order]
    index = sim.time_index
    return pd.Series(values, index=index[steps] if len(index) > steps.max() else steps)


def recession_cloud(discharge: pd.Series, *, skip: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(Q, -dQ/dt)`` over the falling limbs of ``discharge``.

    A centred difference would mix a rise and a fall inside one estimate, so
    the rate is the step difference taken at the midpoint of the step, kept
    only where it is negative: a rising limb carries no recession. ``skip``
    drops the head of the chronicle, where the forcing that built the mound is
    still acting and the aquifer is not yet the only thing draining.
    """
    values = np.asarray(discharge.to_numpy(), dtype="float64")[skip:]
    days = _days_since_start(discharge.index)[skip:]
    if values.size < 3:
        return np.empty(0), np.empty(0)

    dt = np.diff(days)
    rate = np.divide(np.diff(values), dt, out=np.full(values.size - 1, np.nan), where=dt > 0.0)
    mid = 0.5 * (values[:-1] + values[1:])
    keep = np.isfinite(rate) & np.isfinite(mid) & (rate < 0.0) & (mid > 0.0)
    return mid[keep], -rate[keep]


@register
class RecessionPowerLaw(BaseFigure):
    """``-dQ/dt`` against ``Q`` in log-log, against a power law of exponent ``b``."""

    spec = FigureSpec(
        name="recession_power_law",
        title="Recession rate against discharge",
        kind="timeseries",
        required_tables=("budgets",),
        default_figsize=(7.5, 5.0),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        station: str = "_catchment",
        variable: str = "discharge",
        component: str | None = None,
        a: float | None = None,
        b: float = 1.5,
        k: float | None = None,
        porosity: float | None = None,
        stream_length: float | None = None,
        area: float | None = None,
        sides: int = 2,
        skip: int = 0,
        show_residuals: bool = True,
        **_,
    ) -> Axes:
        if component is None:
            series = sim.timeseries(variable, station=station) * SECONDS_PER_DAY
            source = f"'{variable}' @ '{station}'"
        else:
            series = budget_outflow_per_day(sim, component)
            source = f"budget component '{component}'"

        flow, rate = recession_cloud(series, skip=skip)
        if flow.size < 2:
            raise ValueError(
                f"recession_power_law: no falling limb in {source} for sim {sim.sim_id}"
            )

        if a is None and None not in (k, porosity, stream_length, area):
            a = brutsaert_nieber_coefficient(
                k=float(k),  # type: ignore[arg-type]
                porosity=float(porosity),  # type: ignore[arg-type]
                stream_length=float(stream_length),  # type: ignore[arg-type]
                area=float(area),  # type: ignore[arg-type]
                sides=int(sides),
            )

        ax.plot(flow, rate, lw=1.6, color="#b3202c", label="Simulated", zorder=3)

        grid = np.logspace(np.log10(flow.min()), np.log10(flow.max()), 200)
        # At a fixed exponent the offset is the mean log-distance to the cloud.
        a_fit = float(10.0 ** np.mean(np.log10(rate) - b * np.log10(flow)))
        reference = a_fit if a is None else a
        ax.plot(
            grid,
            reference * grid**b,
            lw=2.5,
            color="0.45" if a is None else "#1f6fb4",
            zorder=1,
            label=(
                rf"Fitted $-dQ/dt = {a_fit:.3g}\,Q^{{{b:g}}}$"
                if a is None
                else rf"Boussinesq 1904 $-dQ/dt = {a:.3g}\,Q^{{{b:g}}}$"
            ),
        )

        residual = np.log10(rate) - np.log10(reference * flow**b)
        if show_residuals:
            from matplotlib.ticker import LogLocator, NullFormatter

            inset = ax.inset_axes((0.62, 0.10, 0.34, 0.24))
            inset.plot(flow, residual, lw=1.0, color="#d2762a")
            inset.axhline(0.0, lw=1.0, color="k")
            inset.set_xscale("log")
            inset.xaxis.set_major_locator(LogLocator(numticks=3))
            inset.xaxis.set_minor_formatter(NullFormatter())
            inset.tick_params(labelsize=5, pad=1)
            inset.set_title("residual (log10)", fontsize=6, pad=2)
            inset.grid(True, which="major", ls=":", lw=0.3)

        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Discharge $Q$ (m³/day)")
        ax.set_ylabel("Recession rate $-dQ/dt$ (m³/day²)")
        ax.grid(True, which="both", ls=":", lw=0.4)
        ax.set_title(
            f"{self.spec.title} - {sim.name or sim.sim_id}\n"
            f"{flow.size} falling steps, mean residual {residual.mean():+.3f} log10"
        )
        place_legend(ax, fontsize=8, framealpha=0.9)
        return ax
