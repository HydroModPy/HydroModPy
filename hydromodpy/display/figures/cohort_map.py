"""Map of a cohort: one point per site at its outlet, colored by one column.

Registered as ``map``, the name ``[sites.summary] figures`` writes.
``hmp campaign collect`` draws it under ``summary/figures/map_<variable>.png``
for each name of ``[sites.summary] variables``: the best K or the NSE of every catchment of a
project on one map. A site without a value is drawn hollow, so a reader sees
which catchments the table leaves empty.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_options import Cmap, Opt
from hydromodpy.display.figures._cohort import (
    COHORT_SITE_COLUMN,
    cohort_refusal,
    column_values,
    outlets,
    wants_log,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

LABELLED_SITES_MAX = 40
"""Most sites whose name is written next to their point."""


class CohortMap(BaseFigure):
    """The outlets of a project's sites, colored by a metric or a parameter."""

    spec = FigureSpec(
        name="map",
        title="Cohort map",
        kind="table",
        default_figsize=(7.0, 6.0),
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
            Opt("Column of the cohort table the points are colored by, a metric or a parameter."),
        ] = "nse",
        log: Annotated[
            bool | None,
            Opt(
                "Force a log color scale on or off. Left out, a log scale when the "
                "positive values span more than one decade."
            ),
        ] = None,
        cmap: Cmap = "viridis",
        **_,
    ) -> Axes:
        from matplotlib.colors import LogNorm, Normalize

        refusal = cohort_refusal(sim)
        if refusal is not None:
            raise ValueError(f"map: {refusal}")
        values = column_values(sim, variable, figure="map")
        xs, ys, crs = outlets(sim, figure="map")
        placed = np.isfinite(xs) & np.isfinite(ys)
        if not placed.any():
            raise ValueError("map: no site of the cohort table has an outlet to place")
        valued = placed & np.isfinite(values)
        use_log = wants_log(values, log)
        norm = None
        if valued.any():
            low, high = float(values[valued].min()), float(values[valued].max())
            norm = LogNorm(low, high) if use_log and low > 0 else Normalize(low, high)
            points = ax.scatter(
                xs[valued],
                ys[valued],
                c=values[valued],
                cmap=cmap,
                norm=norm,
                s=60,
                edgecolors="black",
                linewidths=0.5,
                zorder=3,
            )
            ax.figure.colorbar(points, ax=ax, label=variable)
        empty = placed & ~np.isfinite(values)
        if empty.any():
            ax.scatter(
                xs[empty],
                ys[empty],
                facecolors="none",
                edgecolors="grey",
                s=60,
                zorder=2,
                label=f"no {variable}",
            )
            ax.legend(loc="best", fontsize="small")
        if int(placed.sum()) <= LABELLED_SITES_MAX:
            for name, x, y in zip(sim[COHORT_SITE_COLUMN], xs, ys, strict=True):
                if np.isfinite(x) and np.isfinite(y):
                    ax.annotate(
                        str(name), (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7
                    )
        geographic = crs == "EPSG:4326"
        ax.set_xlabel("longitude (°)" if geographic else f"easting ({crs or 'm'})")
        ax.set_ylabel("latitude (°)" if geographic else f"northing ({crs or 'm'})")
        ax.ticklabel_format(style="plain", useOffset=False)
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_title(f"{variable} of the best case of each site ({int(placed.sum())} sites)")
        return ax


__all__ = ["CohortMap"]
