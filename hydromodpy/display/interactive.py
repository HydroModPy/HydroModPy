"""Interactive engine: the plotly template, the assembly of a figure and its HTML file.

A frame holds ``draw_interactive(data, theme)`` and returns ``(traces, axes)``. ``axes``
is a dict of plotly axis settings, ``xaxis`` and ``yaxis`` for a plane or ``scene`` for a
3D block, and may hold a ``title`` the panel title takes after its own. ``assemble`` puts
the panels on one plotly figure and ``write`` saves it. The theme gives the same fonts,
colours and ramps as the static figures. plotly is imported only when a figure is built.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib import colormaps
from matplotlib.colors import to_hex, to_rgba

from hydromodpy.display.subject import FigureNotApplicable, MeshView
from hydromodpy.display.theme import Theme

PX_PER_POINT = 1.5
"""The theme sizes are points at print size. A screen figure takes them in pixels at this ratio."""
MAX_CELLS = 100_000
"""Most cells an interactive map or block draws, since the browser keeps every one of them.

Measured on square grids with the hover text of each cell: 21 406 cells (example 04) give
4.3 MB of HTML written in 0.1 s, 100 000 cells give 21 MB in 0.6 s and 500 000 cells give
106 MB in 2.9 s. The first two open in a browser. The third is too large to load, so the
limit sits at the second and a bigger mesh goes to the static engine.
"""


def refuse_large(count: int) -> None:
    """Refuse a panel of more than ``MAX_CELLS`` cells, naming the count, the limit and the static engine."""
    if count > MAX_CELLS:
        raise FigureNotApplicable(
            f"The interactive engine draws up to {MAX_CELLS:,} cells and this panel has "
            f"{count:,}. Use engine = 'static'."
        )


def plain(text: str) -> str:
    """Turn the mathtext of a unit label into HTML, ``m^{3}\\,s^{-1}`` into ``m<sup>3</sup> s<sup>-1</sup>``."""
    text = re.sub(r"\$\\mathregular\{(.*?)\}\$", r"\1", text)
    text = re.sub(r"\^\{(.*?)\}", r"<sup>\1</sup>", text)
    return text.replace("\\,", " ").replace("\\%", "%")


def colorscale(name: str, steps: int = 16) -> list[list[Any]]:
    """Return the matplotlib colormap ``name`` as a plotly colour scale."""
    ramp = colormaps[name]
    return [[t, to_hex(ramp(t))] for t in np.linspace(0, 1, steps)]


def class_colorscale(colors: list[str]) -> list[list[Any]]:
    """Return a stepped plotly colour scale, one flat band per colour."""
    n = len(colors)
    return [[edge, color] for i, color in enumerate(colors) for edge in (i / n, (i + 1) / n)]


def fan(mesh: MeshView, cells: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Return the triangles of the cells, each cell with its own vertices.

    The answer is the x and y of every vertex, the triangles as an ``(n, 3)`` array of
    vertex numbers, the cell row each triangle belongs to, and the number of vertices per
    cell. The vertices of cell ``r`` are ``r * k`` to ``r * k + k - 1``. A polygon with fewer
    corners than the widest repeats its first corner, which gives empty triangles.
    """
    rings = mesh.faces[cells]
    corners = np.where(rings >= 0, rings, rings[:, :1])
    n, k = corners.shape
    xy = mesh.vertices[corners][:, :, :2].reshape(-1, 2)
    base = (np.arange(n) * k)[:, None]
    fanned = np.arange(1, k - 1)
    first, second, third = (
        np.broadcast_to(a, (n, k - 2)).ravel() for a in (base, base + fanned, base + fanned + 1)
    )
    return xy[:, 0], xy[:, 1], np.column_stack([first, second, third]), k


def layout(theme: Theme) -> dict[str, Any]:
    """Return the plotly layout of a theme: font, sizes, colours and the grid."""
    font = {
        "family": f"{theme.family}, {theme.fallback}, sans-serif",
        "size": theme.size * PX_PER_POINT,
        "color": theme.ink,
    }
    return {
        "font": font,
        "title": {"font": {"size": theme.title_size * PX_PER_POINT}},
        "paper_bgcolor": theme.face,
        "plot_bgcolor": theme.face,
        "hovermode": "x unified",
        "legend": {"orientation": "h", "y": -0.2},
        "barmode": "relative",
        "margin": {"l": 70, "r": 20, "t": 60, "b": 60},
    }


def _axis(theme: Theme) -> dict[str, Any]:
    red, green, blue, _ = to_rgba(theme.muted)
    grid = f"rgba({red * 255:.0f},{green * 255:.0f},{blue * 255:.0f},{theme.grid_alpha})"
    return {
        "showgrid": True, "gridcolor": grid, "gridwidth": theme.grid_width * PX_PER_POINT,
        "linecolor": theme.muted, "linewidth": theme.line_width * PX_PER_POINT,
        "ticks": "outside", "tickcolor": theme.muted, "ticklen": theme.tick_size * PX_PER_POINT,
        "zeroline": False, "title": {"font": {"color": theme.muted, "size": theme.small * PX_PER_POINT}},
    }  # fmt: skip


def assemble(
    panels: list[tuple[str, list[Any], dict[str, Any]]],
    theme: Theme,
    columns: int,
    title: str | None = None,
) -> Any:
    """Return one plotly figure with one subplot per ``(title, traces, axes)``, in order.

    The subplots sit in rows of ``columns``. A panel of ``scene`` axes is a 3D plot. With
    more than one panel each title starts with its letter, as in the static figure.
    """
    from plotly.subplots import make_subplots

    rows = -(-len(panels) // columns)
    kinds = ["scene" if "scene" in axes else "xy" for _, _, axes in panels]
    specs = [
        [{"type": kind} for kind in kinds[r * columns : (r + 1) * columns]] for r in range(rows)
    ]
    specs = [row + [None] * (columns - len(row)) for row in specs]
    titles = [
        ((f"({chr(97 + i)}) " if len(panels) > 1 else "") + ", ".join(t for t in (name, axes.get("title")) if t)).strip()
        for i, (name, _, axes) in enumerate(panels)
    ]  # fmt: skip
    fig = make_subplots(rows=rows, cols=columns, specs=specs, subplot_titles=titles)
    for i, (_, traces, axes) in enumerate(panels):
        row, col = divmod(i, columns)
        row, col = row + 1, col + 1
        if kinds[i] == "scene":
            fig.update_scenes(**axes["scene"], row=row, col=col)
            area = fig.get_subplot(row, col).domain
            bar = {
                "x": area.x[1] + 0.01,
                "y": sum(area.y) / 2,
                "len": 0.9 * (area.y[1] - area.y[0]),
            }
            for trace in traces:
                if getattr(trace, "intensity", None) is not None:
                    trace.update(
                        colorbar={**bar, "xanchor": "left", "yanchor": "middle", "thickness": 12}
                    )
        else:
            fig.update_xaxes(**{**_axis(theme), **axes.get("xaxis", {})}, row=row, col=col)
            fig.update_yaxes(**{**_axis(theme), **axes.get("yaxis", {})}, row=row, col=col)
        fig.add_traces(traces, rows=[row] * len(traces), cols=[col] * len(traces))
    fig.update_layout(
        **layout(theme), height=450 * rows, showlegend=sum(len(t) for _, t, _ in panels) > 1,
        **({"title": {"text": title}} if title else {}),
    )  # fmt: skip
    fig.update_annotations(font={"size": theme.size * PX_PER_POINT, "color": theme.ink})
    return fig


def write(fig: Any, path: str | Path, *, embed: bool = False) -> Path:
    """Write the figure as one HTML file and return its path.

    The file loads plotly.js from the CDN, which keeps it small. ``embed`` copies the
    library into the file so it opens without a network, at about 4.5 MB more.
    """
    target = Path(path).with_suffix(".html")
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(
        target, include_plotlyjs=True if embed else "cdn", div_id="figure",
        config={"displaylogo": False},
    )  # fmt: skip
    return target
