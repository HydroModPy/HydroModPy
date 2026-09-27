"""How every figure looks: the theme, the colormaps, where the legend goes.

**Theme.** A :class:`Theme` bundles a few matplotlib ``rcParams`` knobs (palette,
fonts, grid, background) so the whole figure corpus looks consistent.
The registry exposes three presets: ``default``, ``print`` and ``dark``.
Call :func:`apply_theme` at the start of a display session; figures do
not have to opt-in individually.

**Colormaps.** A short list of perceptually-broken colormaps is banned across the whole
display corpus. :func:`get_cmap` is the single entry point - it rejects
a banned name up-front so misuse fails loudly at figure construction
time, not later in a CI pipeline.

**Legend placement.** ``loc="best"`` asks matplotlib to score every candidate corner against every
artist already on the axes. On a scatter of a few hundred points that is free
and the result is better than any fixed corner. On a per-cell map it is not:
measured on the Nancon at 25 m, one legend entry over a 243 552-polygon
collection took 99.3 s to place, against 1.1 s for an explicit corner, and that
was the single largest cost of the whole gallery.

So the placement is chosen by how much is on the axes, and the threshold is a
declared number rather than a literal in a figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.legend import Legend

__all__ = [
    "BANNED_CMAPS",
    "HIGH_CONTRAST_TRIPLET",
    "LEGEND_PLACEMENT",
    "PREFERRED_CMAPS",
    "THEMES",
    "LegendPlacementDefaults",
    "Theme",
    "apply_theme",
    "axes_element_count",
    "get_cmap",
    "get_theme",
    "place_legend",
]


# -- theme ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Theme:
    name: str
    palette: list[str]
    grid_alpha: float
    font_family: str
    font_size_base: int
    title_weight: str
    background: str
    foreground: str


THEMES: dict[str, Theme] = {
    "default": Theme(
        name="default",
        palette=[
            "#1f77b4",
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
            "#9467bd",
            "#8c564b",
            "#e377c2",
            "#7f7f7f",
            "#bcbd22",
            "#17becf",
        ],
        grid_alpha=0.3,
        font_family="sans-serif",
        font_size_base=10,
        title_weight="bold",
        background="white",
        foreground="black",
    ),
    "print": Theme(
        name="print",
        palette=[
            "#000000",
            "#555555",
            "#888888",
            "#333333",
            "#aaaaaa",
            "#222222",
            "#666666",
            "#444444",
        ],
        grid_alpha=0.5,
        font_family="serif",
        font_size_base=9,
        title_weight="normal",
        background="white",
        foreground="black",
    ),
    "dark": Theme(
        name="dark",
        palette=[
            "#8ab4f8",
            "#f28b82",
            "#81c995",
            "#fdd663",
            "#c58af9",
            "#ff8bcb",
            "#78d9ec",
            "#fcad70",
        ],
        grid_alpha=0.3,
        font_family="sans-serif",
        font_size_base=10,
        title_weight="bold",
        background="#1e1e1e",
        foreground="#eeeeee",
    ),
}


def get_theme(name: str) -> Theme:
    try:
        return THEMES[name]
    except KeyError as exc:
        available = ", ".join(sorted(THEMES))
        raise KeyError(f"unknown theme '{name}' (available: {available})") from exc


def apply_theme(name: str) -> Theme:
    """Configure ``matplotlib.rcParams`` from the named preset.

    Safe to call repeatedly. Returns the resolved :class:`Theme` so callers
    can pick up the palette to feed into figure-level color cycles.
    """
    import matplotlib as mpl
    from cycler import cycler

    theme = get_theme(name)
    mpl.rcParams.update(
        {
            "axes.prop_cycle": cycler(color=theme.palette),
            "axes.grid": True,
            "grid.alpha": theme.grid_alpha,
            "font.family": theme.font_family,
            "font.size": theme.font_size_base,
            "axes.titleweight": theme.title_weight,
            "figure.facecolor": theme.background,
            "axes.facecolor": theme.background,
            "axes.edgecolor": theme.foreground,
            "axes.labelcolor": theme.foreground,
            "text.color": theme.foreground,
            "xtick.color": theme.foreground,
            "ytick.color": theme.foreground,
        }
    )
    return theme


# -- colormaps -----------------------------------------------------------------


BANNED_CMAPS: frozenset[str] = frozenset(
    {
        "jet",
        "rainbow",
        "hsv",
        "nipy_spectral",
        "gist_rainbow",
    }
)

PREFERRED_CMAPS: dict[str, str] = {
    "sequential": "viridis",
    "diverging": "RdBu_r",
    "cyclic": "twilight",
    "categorical": "tab10",
}

HIGH_CONTRAST_TRIPLET: tuple[str, str, str] = ("#004488", "#DDAA33", "#BB5566")
"""Blue, sand and red, for at most three classes drawn side by side.

The three hues stay separable under every common colour-vision deficiency,
and their lightnesses are far enough apart (roughly 33, 73 and 50 in L*) that
the classes survive a greyscale print. A red-versus-green pair has neither
property, which is why no figure encodes a class with one.
"""


def get_cmap(name: str | None = None, kind: str = "sequential"):
    """Return a matplotlib colormap.

    ``name`` may be ``None``; in that case the preferred cmap for ``kind``
    is used. Any banned name is rejected.
    """
    import matplotlib as mpl

    if name is None:
        name = PREFERRED_CMAPS.get(kind, "viridis")
    if name in BANNED_CMAPS:
        raise ValueError(
            f"colormap '{name}' is banned (non-perceptual). "
            f"Use one of the preferred cmaps: {sorted(PREFERRED_CMAPS.values())}."
        )
    return mpl.colormaps.get_cmap(name)


# -- legend placement -----------------------------------------------------------


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
