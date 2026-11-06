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

from typing import TYPE_CHECKING, Annotated

import numpy as np

from hydromodpy.core.scope import CATCHMENT
from hydromodpy.display.figure import BaseFigure, FigureSpec, run_suffix
from hydromodpy.display.figure_options import Opt, Station
from hydromodpy.display.figure_registry import register
from hydromodpy.display.style import place_legend
from hydromodpy.results.derive.recession import (
    SECONDS_PER_DAY,
    brutsaert_nieber_coefficient,
    budget_outflow_per_day,
    recession_cloud,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


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
        station: Station = CATCHMENT,
        variable: Annotated[
            str, Opt('Stored discharge series read, in m3/s, for example "discharge".')
        ] = "discharge",
        component: Annotated[
            str | None,
            Opt(
                "Budget component whose outflow is read instead of the series, for a "
                'boundary that is not a stream, such as "constant_head". Left out, the '
                "series of station and variable."
            ),
        ] = None,
        a: Annotated[
            float | None,
            Opt(
                "Coefficient of the reference law -dQ/dt = a Q^b, for Q in m3/day and t "
                "in days. Left out, computed from k, porosity, stream_length and area "
                "when all four are given, else fitted to the cloud at exponent b."
            ),
        ] = None,
        b: Annotated[float, Opt("Exponent of the reference law -dQ/dt = a Q^b.", unit="-")] = 1.5,
        k: Annotated[
            float | None,
            Opt("Hydraulic conductivity of the Brutsaert-Nieber coefficient.", unit="m/day"),
        ] = None,
        porosity: Annotated[
            float | None,
            Opt("Drainable porosity of the Brutsaert-Nieber coefficient.", unit="-"),
        ] = None,
        stream_length: Annotated[
            float | None,
            Opt("Length of the draining stream of the Brutsaert-Nieber coefficient.", unit="m"),
        ] = None,
        area: Annotated[
            float | None,
            Opt(
                "Area of the aquifer drained, on both banks when sides is 2, of the "
                "Brutsaert-Nieber coefficient.",
                unit="m2",
            ),
        ] = None,
        sides: Annotated[
            int,
            Opt(
                "Banks that drain into the stream: 2 for a reach drained from both "
                "sides, 1 for a single hillslope, which halves the coefficient."
            ),
        ] = 2,
        skip: Annotated[
            int,
            Opt(
                "Values dropped at the head of the series, where the forcing that "
                "built the mound still acts."
            ),
        ] = 0,
        show_residuals: Annotated[
            bool, Opt("Draw the log10 residual to the reference law in an inset.")
        ] = True,
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
            f"{self.spec.title}{run_suffix(sim)}\n"
            f"{flow.size} falling steps, mean residual {residual.mean():+.3f} log10"
        )
        place_legend(ax, fontsize=8, framealpha=0.9)
        return ax
