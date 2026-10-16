"""Distribution of one column across the sites of a cohort.

Registered as ``distribution``, the name ``[sites.summary] figures`` writes.
``hmp project collect`` draws it under
``summary/figures/distribution_<variable>.png`` for each name of
``[sites.summary] variables``: how the best K or the NSE spreads over the
catchments of a project. A box gives the quartiles, every site is a point on
top of it, and the sites without a value are counted in the title.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_options import Opt
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures.cohort_table import (
    COHORT_SITE_COLUMN,
    cohort_refusal,
    column_values,
    wants_log,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

LABELLED_SITES_MAX = 12
"""Most sites whose name is written next to their point."""

_JITTER_SEED = 0
"""Seed of the vertical spread of the points, so a figure redraws the same."""


@register
class CohortDistribution(BaseFigure):
    """How a metric or a parameter spreads over the sites of a project."""

    spec = FigureSpec(
        name="distribution",
        title="Cohort distribution",
        kind="table",
        default_figsize=(7.0, 3.5),
    )

    def unavailable_reason(self, sim: Any) -> str | None:
        """Refuse anything but a cohort table."""
        return cohort_refusal(sim)

    def render(
        self,
        sim: Any,
        ax: Axes,
        *,
        variable: Annotated[
            str,
            Opt("Column of the cohort table whose spread is drawn, a metric or a parameter."),
        ] = "nse",
        log: Annotated[
            bool | None,
            Opt(
                "Force a log axis on or off. Left out, a log axis when the positive "
                "values span more than one decade."
            ),
        ] = None,
        **_,
    ) -> Axes:
        refusal = cohort_refusal(sim)
        if refusal is not None:
            raise ValueError(f"distribution: {refusal}")
        values = column_values(sim, variable, figure="distribution")
        finite = np.isfinite(values)
        if not finite.any():
            raise ValueError(f"distribution: no site of the cohort table has a {variable}")
        kept = values[finite]
        ax.boxplot(kept, orientation="horizontal", widths=0.5, showfliers=False)
        spread = np.random.default_rng(_JITTER_SEED).uniform(-0.12, 0.12, kept.size)
        ax.scatter(kept, 1.0 + spread, s=24, color="black", alpha=0.7, zorder=3)
        if kept.size <= LABELLED_SITES_MAX:
            names = np.asarray(sim[COHORT_SITE_COLUMN].astype(str))[finite]
            for name, x, y in zip(names, kept, 1.0 + spread, strict=True):
                ax.annotate(name, (x, y), xytext=(3, 3), textcoords="offset points", fontsize=7)
        if wants_log(values, log):
            ax.set_xscale("log")
        ax.set_yticks([])
        ax.set_xlabel(variable)
        missing = int((~finite).sum())
        suffix = f", {missing} without a value" if missing else ""
        ax.set_title(f"{variable} over {kept.size} sites{suffix}")
        return ax


__all__ = ["CohortDistribution"]
