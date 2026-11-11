"""Residence-time distribution of the particles a run tracked.

Puts the travel-time density of the tracked particles next to the exponential
distribution a single well-mixed reservoir produces, ``p(u) = exp(-u)`` with
``u = t / tau``. An aquifer that drains as one store follows the line; a
departure from it is the signature of a structure the flow field imposes
(layering, a depth-decaying conductivity, a boundary that short-circuits part
of the domain).

Every particle counts once. The extractors write no release weight on the
``particles`` group, so the density is the distribution of the release the run
asked for, not a recharge-weighted one: read it as such when the release zone
does not cover the domain uniformly.

The travel times come from ``results/run/particles.py``, because a figure never computes
a hydrological quantity itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec, run_suffix
from hydromodpy.display.figure_options import Opt
from hydromodpy.display.style import place_legend
from hydromodpy.results.run.particles import has_particle_tracks, particle_travel_years

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run.view import Run


def _log_spaced_density(values: np.ndarray, n_bins: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (bin centers, density) of ``values`` over log-spaced bins.

    A travel-time distribution spans decades, so equal-width bins waste every
    one of them on the tail. The bins span the 1st to the 99th percentile,
    which keeps a single outlying particle from setting the whole support.
    """
    low, high = np.percentile(values, (1.0, 99.0))
    low = max(low, values.min())
    if not np.isfinite(low) or low <= 0.0:
        low = values.min()
    if high <= low:
        high = values.max()
    edges = np.logspace(np.log10(low), np.log10(high), n_bins + 1)
    density, edges = np.histogram(values, bins=edges, density=True)
    centres = np.sqrt(edges[:-1] * edges[1:])
    return centres, density


class ResidenceTimeDistribution(BaseFigure):
    """Travel-time density of the tracked particles, against the exponential law."""

    spec = FigureSpec(
        name="residence_time_distribution",
        title="Residence-time distribution",
        kind="particles",
        required_fields=("particles",),
        default_figsize=(7.0, 5.0),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Require a timed pathline, not only the ``particles`` group."""
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        if not has_particle_tracks(sim, timed=True):
            return "run holds no timed particle pathline"
        return None

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        normalize: Annotated[
            bool,
            Opt("Divide the residence times by their mean, so the axis reads t/tau."),
        ] = True,
        bins: Annotated[
            int | None,
            Opt("Number of log-spaced bins. Left out, 2 n^(2/5) for n particles, at least 5."),
        ] = None,
        show_model: Annotated[
            bool,
            Opt("Draw the exponential law of a well-mixed aquifer for comparison."),
        ] = True,
        **_,
    ) -> Axes:
        years = particle_travel_years(sim)
        if years.size < 2:
            raise ValueError(f"no timed particle pathline stored for sim {sim.sim_id}")

        tau = float(years.mean())
        # Scott's rule on the sample size, the count the legacy analysis used.
        n_bins = int(bins) if bins else max(5, int(2 * years.size ** (2 / 5)))
        values = years / tau if normalize else years
        centres, density = _log_spaced_density(values, n_bins)

        drawn = density > 0.0
        ax.plot(
            centres[drawn],
            density[drawn],
            marker="o",
            ms=4,
            lw=1.2,
            color="#1f6fb4",
            label=f"Simulated ({years.size} particles)",
        )

        if show_model and normalize:
            grid = np.logspace(np.log10(centres[0]), np.log10(centres[-1]), 200)
            ax.plot(
                grid,
                np.exp(-grid),
                lw=2.5,
                color="0.45",
                zorder=0,
                label=r"Exponential, $p(t/\tau)=e^{-t/\tau}$",
            )
        elif show_model:
            grid = np.logspace(np.log10(centres[0]), np.log10(centres[-1]), 200)
            ax.plot(
                grid,
                np.exp(-grid / tau) / tau,
                lw=2.5,
                color="0.45",
                zorder=0,
                label=r"Exponential, $p(t)=\tau^{-1}e^{-t/\tau}$",
            )

        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel(r"Residence time $t/\tau$ (-)" if normalize else "Residence time (years)")
        ax.set_ylabel("Probability density (-)")
        ax.grid(True, which="both", ls=":", lw=0.4)
        ax.set_title(
            f"{self.spec.title}{run_suffix(sim)}\n"
            rf"mean residence time $\tau$ = {tau:.3g} years"
        )
        place_legend(ax, fontsize=8, framealpha=0.9)
        return ax
