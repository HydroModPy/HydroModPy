"""Display theme presets.

A :class:`Theme` bundles a few matplotlib ``rcParams`` knobs (palette,
fonts, grid, background) so the whole figure corpus looks consistent.
The registry exposes three presets: ``default``, ``print`` and ``dark``.
Call :func:`apply_theme` at the start of a display session; figures do
not have to opt-in individually.
"""

from __future__ import annotations

from dataclasses import dataclass


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


__all__ = ["Theme", "THEMES", "get_theme", "apply_theme"]
