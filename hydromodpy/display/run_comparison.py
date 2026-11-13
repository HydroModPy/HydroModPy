"""Figures of a comparison of sealed runs: their series and their maps against a reference."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from hydromodpy.core.scope import OBSERVED
from hydromodpy.display import static, variables
from hydromodpy.display.frames import map as map_frame
from hydromodpy.display.subject import read_mesh
from hydromodpy.display.theme import get_theme
from hydromodpy.results.run.view import Run


def draw_series(
    frame: pd.DataFrame, reference: Run, variable: str, station: str, path: Path
) -> None:
    """Plot one column per run of *frame* and, for discharge, the gauge of *reference*."""
    theme = get_theme("default")
    fig = static.new_figure(theme, width="double", height_mm=75.0)
    ax = fig.axes[0]
    colors = theme.class_colors(len(frame.columns))
    for i, name in enumerate(frame.columns):
        ax.plot(frame.index, frame[name], color=colors[i],
                linewidth=theme.data_line_width, label=name)  # fmt: skip
    if variable == "discharge" and reference.stations(variable, source=OBSERVED):
        observed = reference.observed(variable)
        observed = observed[observed["datetime"].between(frame.index[0], frame.index[-1])]
        ax.plot(observed["datetime"], observed["value"], linestyle=":",
                **static.line_style(theme, "observed"), label="observed")  # fmt: skip
    ax.set(title=f"{variable}, {station}", ylabel=variable)
    static.style_axes(ax, theme, dates=True)
    static.legend(ax, theme)
    static.save(fig, path, theme)


def draw_maps(
    values: list[np.ndarray], runs: Sequence[Run], variable: str, when: str, path: Path
) -> None:
    """Plot the reference map, then each other run minus the reference on a symmetric scale.

    Each array holds one value per cell of the mesh of ``runs[0]``, in the stored unit,
    already read at the cells of that mesh when a run has another one. An array of
    another length is refused with a ``ValueError``.
    """
    theme = get_theme("default")
    mesh = read_mesh(runs[0])
    for run, value in zip(runs, values, strict=True):
        if len(value) != len(mesh.faces):
            raise ValueError(
                f"{run.name!r} holds {len(value)} values and the mesh of {runs[0].name!r} "
                f"has {len(mesh.faces)} cells, so the maps cannot be subtracted."
            )
    head, unit = variables.label_parts(variable)
    shown = [variables.to_display(variable, value, area=mesh.areas) for value in values]
    panels = [(runs[0].name, shown[0], variables.label(variable), "sequential", None)]
    for run, value in zip(runs[1:], shown[1:], strict=True):
        difference = value - shown[0]
        limit = float(np.nanmax(np.abs(difference), initial=0.0)) or 1.0
        label = variables.join_unit(f"Difference in {head[:1].lower()}{head[1:]}", unit)
        panels.append((f"{run.name} minus reference", difference, label, "diverging", limit))
    fig = static.new_figure(theme, width="double", height_mm=70.0, ncols=len(panels))
    for ax, (title, value, label, scale, limit) in zip(fig.axes, panels, strict=True):
        table = pd.DataFrame(
            {
                "cell": np.arange(len(value), dtype=np.int64),
                "x": mesh.centres[:, 0],
                "y": mesh.centres[:, 1],
                "value": value,
            }
        )
        limits = None if limit is None else (-limit, limit)
        out = map_frame.MapData(
            table, mesh, variable, label, scale, "", False, False, limits=limits
        )
        ax.set_title(title)
        map_frame.draw(ax, out, theme)
    fig.suptitle(f"{variable}, {when}", **static.text_style(theme, small=False))
    static.save(fig, path, theme)
