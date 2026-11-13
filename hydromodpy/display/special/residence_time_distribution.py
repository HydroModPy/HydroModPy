"""Survival function of the particle travel times against the exponential of the turnover time.

A run that drains as one well-mixed store gives an exponential residence time whose mean
is the turnover time, the pore volume divided by the outflow. The pore volume is the
sum over cells of the stored porosity times the saturated thickness and the area, at the
last period, so a layered porosity weighs each layer by its water. The figure draws the share of particles still in the aquifer after each time, as
a step on a log axis, beside that exponential and beside the exponential of the mean
travel time. A particle that never left its release cell has no time and is left out.
Every particle counts once, whatever its release weight.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.core.scope import DOMAIN
from hydromodpy.display import static
from hydromodpy.display.subject import FigureNotApplicable, read_mesh
from hydromodpy.display.theme import Theme, unit_text
from hydromodpy.results.derive.porosity import effective_porosity, pore_volume, turnover_years
from hydromodpy.results.run.particles import particle_travel_years


def _travel_years(run: Any) -> np.ndarray:
    """Return the travel time in years of each particle that moved."""
    years = particle_travel_years(run)
    if years.size < 2:
        raise FigureNotApplicable(
            f"Run {run.name!r}: fewer than two particles carry a travel time, so no "
            "distribution can be drawn."
        )
    return years


def _turnover_years(run: Any) -> float:
    """Return the pore volume over the mean outflow of the domain, in years."""
    mesh = read_mesh(run)
    if mesh.interfaces is None:
        raise FigureNotApplicable(f"Run {run.name!r} has no layer interfaces for its volume.")
    try:
        volume = pore_volume(
            effective_porosity(run), run.field("head", time="last"), mesh.interfaces,
            mesh.areas, mesh.zones[DOMAIN],
        )  # fmt: skip
        return turnover_years(volume, run.budget(zone_id=DOMAIN))
    except NothingThereError as error:
        raise FigureNotApplicable(
            f"Run {run.name!r}: {error} Its turnover time is unknown."
        ) from error


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the survival step and both exponentials, with the turnover time in the legend."""
    years = np.sort(_travel_years(subject))
    turnover = _turnover_years(subject)
    count, mean = years.size, float(years.mean())
    survival = 1.0 - np.arange(1, count + 1) / (count + 1)
    grid = np.linspace(0.0, years.max(), 200)
    ax.step(
        years, survival, where="post", label=f"particles (n = {count})",
        **static.line_style(theme, "simulated"),
    )  # fmt: skip
    ax.plot(
        grid, np.exp(-grid / mean), label=f"exponential, mean travel time {mean:.3g}",
        color=theme.roles["reference_law"], linewidth=theme.line_width,
    )  # fmt: skip
    ax.plot(
        grid, np.exp(-grid / turnover), label=f"pore volume / outflow, {turnover:.3g}",
        color=theme.roles["turnover"], linewidth=theme.data_line_width, linestyle="--",
    )  # fmt: skip
    ax.set_yscale("log")
    ax.set_ylim(0.5 / count, 1.3)
    ax.set_xlim(0.0, years.max() * 1.03)
    ax.set_xlabel(f"Residence time ({unit_text('yr')})")
    ax.set_ylabel("Share of particles still in the aquifer")
    static.style_axes(ax, theme)
    static.legend(ax, theme)
