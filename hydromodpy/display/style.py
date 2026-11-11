"""How every figure looks: the theme, the colormaps, where the legend goes.

**Theme.** A :class:`Theme` bundles a few matplotlib ``rcParams`` knobs (palette,
fonts, grid, background) so the whole figure corpus looks consistent.
The registry exposes three presets: ``default``, ``print`` and ``dark``.
:func:`theme_rc` turns a preset into the ``rcParams`` it sets, and
:func:`themed` holds those values, under one lock, for the length of one render.
Nothing writes ``rcParams`` for good, so two renders in two threads of one
process never see each other's style.

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

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.legend import Legend

__all__ = [
    "BANNED_CMAPS",
    "HIGH_CONTRAST_TRIPLET",
    "LEGEND_BEST_PLACEMENT_LIMIT",
    "LEGEND_DENSE_LOCATION",
    "PREFERRED_CMAPS",
    "RENDER_LOCK",
    "THEMES",
    "Theme",
    "axes_element_count",
    "get_cmap",
    "get_theme",
    "is_dark",
    "relative_luminance",
    "neutral",
    "place_legend",
    "theme_rc",
    "themed",
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


RENDER_LOCK = threading.RLock()
"""Held for the length of one render, because ``rcParams`` is shared by every thread.

Matplotlib reads its style from ``rcParams`` while an artist is created, so two
renders can only run one after the other. The lock is reentrant: a figure that
sets its own style inside a render that already holds the lock does not wait
for itself.
"""


def theme_rc(name: str) -> dict[str, Any]:
    """Return the ``rcParams`` values of the preset ``name``.

    The mapping is built fresh on each call and nothing is written to
    ``rcParams``; :func:`themed` is what puts it in force.
    """
    from cycler import cycler

    theme = get_theme(name)
    return {
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
        # A legend frame keeps its distance from the background in both themes.
        "legend.edgecolor": neutral(
            "#cccccc", background=theme.background, foreground=theme.foreground
        ),
    }


@contextmanager
def themed(
    name: str | None = None, extra: Mapping[str, Any] | None = None
) -> Iterator[Theme | None]:
    """Hold :data:`RENDER_LOCK` and the style of the preset ``name`` for one render.

    ``extra`` adds ``rcParams`` values on top of the preset, for a figure that
    needs larger fonts. With no ``name`` the style already in force is kept.
    The previous values come back on the way out, and the resolved
    :class:`Theme` (``None`` without a name) is what the block receives, so a
    caller can read its palette.
    """
    import matplotlib as mpl

    with RENDER_LOCK:
        theme = None if name is None else get_theme(name)
        values = {} if name is None else theme_rc(name)
        values.update(extra or {})
        with mpl.rc_context(values):
            yield theme


def _rgb(color: Any) -> tuple[float, float, float]:
    from matplotlib.colors import to_rgb

    return to_rgb(color)


def relative_luminance(color: Any) -> float:
    """Perceived brightness of one color (WCAG), the quantity a grayscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def is_dark(background: Any = None) -> bool:
    """Whether the figures are drawn on a dark background (the ``dark`` preset).

    Read from ``axes.facecolor`` unless ``background`` is given.
    """
    if background is None:
        import matplotlib as mpl

        background = mpl.rcParams["axes.facecolor"]
    red, green, blue = _rgb(background)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue < 0.5


def neutral(color: Any, *, background: Any = None, foreground: Any = None) -> str:
    """Return a gray that keeps its distance from the background in the current theme.

    The light grays of the figures (a cell with nothing to show, a table
    column, a frame) are written for a white page. On a dark page the same
    gray would be the brightest thing drawn. Here a gray is read as a
    distance from white and laid at that distance from the dark background,
    toward the foreground. A color that is not a gray, and any color on a
    light background, comes back unchanged.
    """
    import matplotlib as mpl
    from matplotlib.colors import to_hex

    background = mpl.rcParams["axes.facecolor"] if background is None else background
    foreground = mpl.rcParams["text.color"] if foreground is None else foreground
    if not is_dark(background):
        return to_hex(color)
    red, green, blue = _rgb(color)
    if max(red, green, blue) - min(red, green, blue) > 0.02:
        return to_hex((red, green, blue))
    back, fore = _rgb(background), _rgb(foreground)
    distance = 1.0 - (red + green + blue) / 3.0
    return to_hex(tuple(b + distance * (f - b) for b, f in zip(back, fore, strict=True)))


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

The three hues stay separable under every common color-vision deficiency,
and their lightnesses are far enough apart (roughly 33, 73 and 50 in L*) that
the classes survive a grayscale print. A red-versus-green pair has neither
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


LEGEND_BEST_PLACEMENT_LIMIT = 5000
"""Drawable elements on an axes above which the legend is pinned to a corner.

Placement scores every candidate position against every element, so the cost
grows with the map: one entry over a 243 552-cell collection took 99.3 s
against 1.1 s pinned.
"""

LEGEND_DENSE_LOCATION = "upper right"
"""Corner the legend takes on an axes denser than ``LEGEND_BEST_PLACEMENT_LIMIT``."""


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
            if axes_element_count(ax) <= LEGEND_BEST_PLACEMENT_LIMIT
            else LEGEND_DENSE_LOCATION
        )
    return ax.legend(**kwargs)
