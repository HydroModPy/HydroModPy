"""Where a legend goes, and why it is not always left to matplotlib.

``loc="best"`` asks matplotlib to score every candidate corner against every
artist already on the axes. On a scatter of a few hundred points that is free
and the result is better than any fixed corner. On a per-cell map it is not:
measured on the Nancon at 25 m, one legend entry over a 243 552-polygon
collection took 99.3 s to place, against 1.1 s for an explicit corner, and that
was the single largest cost of the whole gallery.

So the placement is chosen by how much is on the axes, and the threshold is a
declared number rather than a literal in a figure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.legend import Legend


class LegendPlacementDefaults(HydroModelBase):
    """How dense an axes has to be before the legend stops looking for a spot."""

    best_placement_limit: Annotated[int, Profile.EXPERT] = Field(
        default=5000,
        gt=0,
        description=(
            "Number of drawable elements on the axes above which the legend is "
            "pinned to a fixed corner instead of being placed by matplotlib. "
            "Placement scores every candidate position against every element, so "
            "the cost grows with the map: one entry over a 243 552-cell "
            "collection took 99.3 s against 1.1 s pinned."
        ),
    )
    dense_location: Annotated[str, Profile.EXPERT] = Field(
        default="upper right",
        description=(
            "Corner the legend takes once the axes is denser than "
            "best_placement_limit. Any matplotlib location string."
        ),
    )


LEGEND_PLACEMENT = LegendPlacementDefaults()
"""The one instance every figure reads."""


def axes_element_count(ax: Axes) -> int:
    """Count what a legend placement would have to be scored against.

    A collection counts for the paths it holds, not for one: that is the whole
    difference between a scatter and a per-cell map.
    """
    total = len(ax.lines) + len(ax.patches) + len(ax.images) + len(ax.texts)
    for collection in ax.collections:
        try:
            total += len(collection.get_paths())
        except (AttributeError, TypeError):
            total += 1
    return total


def place_legend(ax: Axes, **kwargs: Any) -> Legend | None:
    """Draw the legend of ``ax``, choosing its location from how dense it is.

    Returns ``None`` when the axes carries nothing to put in a legend, which is
    what every caller already tested for by hand.
    """
    handles, _labels = ax.get_legend_handles_labels()
    if not handles and "handles" not in kwargs:
        return None
    if "loc" not in kwargs:
        kwargs["loc"] = (
            "best"
            if axes_element_count(ax) <= LEGEND_PLACEMENT.best_placement_limit
            else LEGEND_PLACEMENT.dense_location
        )
    return ax.legend(**kwargs)


__all__ = ["LEGEND_PLACEMENT", "LegendPlacementDefaults", "axes_element_count", "place_legend"]
