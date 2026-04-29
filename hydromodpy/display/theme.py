"""Display theme presets.

A :class:`Theme` bundles a few matplotlib ``rcParams`` knobs (palette,
fonts, grid, background) so the whole figure corpus looks consistent.
The registry exposes three presets: ``default``, ``print`` and ``dark``.
Call :func:`apply_theme` at the start of a display session; figures do
not have to opt-in individually.

The :func:`plot_params` helper is a legacy hook used by the MODFLOW-NWT
and Boussinesq notebooks to apply the historical "classic" matplotlib
rcParams in one call.
"""

from __future__ import annotations

from dataclasses import dataclass

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties


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


def plot_params(small: int, interm: int, medium: int, large: int) -> FontProperties:
    """Apply the classic matplotlib rcParams style and return a FontProperties."""
    mpl.style.use("classic")
    mpl.rcParams["figure.facecolor"] = "white"
    mpl.rcParams["grid.color"] = "darkgrey"
    mpl.rcParams["grid.linestyle"] = "-"
    mpl.rcParams["grid.alpha"] = 0.8
    mpl.rcParams["axes.axisbelow"] = True
    mpl.rcParams["axes.linewidth"] = 1.5
    mpl.rcParams["figure.dpi"] = 300
    mpl.rcParams["savefig.dpi"] = 300
    mpl.rcParams["patch.force_edgecolor"] = True
    mpl.rcParams["image.interpolation"] = "nearest"
    mpl.rcParams["image.resample"] = True
    mpl.rcParams["axes.autolimit_mode"] = "data"
    mpl.rcParams["axes.xmargin"] = 0.05
    mpl.rcParams["axes.ymargin"] = 0.05
    mpl.rcParams["xtick.direction"] = "in"
    mpl.rcParams["ytick.direction"] = "in"
    mpl.rcParams["xtick.major.size"] = 5
    mpl.rcParams["xtick.minor.size"] = 3
    mpl.rcParams["xtick.major.width"] = 1.5
    mpl.rcParams["xtick.minor.width"] = 1
    mpl.rcParams["ytick.major.size"] = 5
    mpl.rcParams["ytick.minor.size"] = 1.5
    mpl.rcParams["ytick.major.width"] = 1.5
    mpl.rcParams["ytick.minor.width"] = 1
    mpl.rcParams["xtick.top"] = True
    mpl.rcParams["ytick.right"] = True
    mpl.rcParams["legend.numpoints"] = 1
    mpl.rcParams["legend.scatterpoints"] = 1
    mpl.rcParams["legend.edgecolor"] = "grey"
    mpl.rcParams["date.autoformatter.year"] = "%Y"
    mpl.rcParams["date.autoformatter.month"] = "%Y-%m"
    mpl.rcParams["date.autoformatter.day"] = "%Y-%m-%d"
    mpl.rcParams["date.autoformatter.hour"] = "%H:%M"
    mpl.rcParams["date.autoformatter.minute"] = "%H:%M:%S"
    mpl.rcParams["date.autoformatter.second"] = "%H:%M:%S"
    mpl.rcParams.update({"mathtext.default": "regular"})

    plt.rc("font", size=small)
    plt.rc("figure", titlesize=large)
    plt.rc("legend", fontsize=small)
    plt.rc("axes", titlesize=medium, labelpad=10)
    plt.rc("axes", labelsize=medium, labelpad=12)
    plt.rc("xtick", labelsize=interm)
    plt.rc("ytick", labelsize=interm)
    plt.rc("font", family="sans serif")

    fontprop = FontProperties()
    fontprop.set_family("sans serif")
    return fontprop


__all__ = ["Theme", "THEMES", "get_theme", "apply_theme", "plot_params"]
