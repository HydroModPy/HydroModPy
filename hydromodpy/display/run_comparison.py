"""Figures of a comparison of sealed runs: their series and their maps against a reference."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from hydromodpy.core.scope import OBSERVED
from hydromodpy.display.maps.ugrid import render_face_field

if TYPE_CHECKING:
    from hydromodpy.results.run.view import Run


def draw_series(
    frame: pd.DataFrame, reference: Run, variable: str, station: str, path: Path
) -> None:
    """Plot one column per run of *frame* and, for discharge, the gauge of *reference*."""
    figure = Figure(figsize=(10, 4))
    axes = figure.subplots()
    for name in frame.columns:
        axes.plot(frame.index, frame[name], label=name)
    if variable == "discharge" and reference.stations(variable, source=OBSERVED):
        observed = reference.observed(variable)
        observed = observed[observed["datetime"].between(frame.index[0], frame.index[-1])]
        axes.plot(observed["datetime"], observed["value"], "k:", label="observed")
    axes.set(title=f"{variable}, {station}", ylabel=variable)
    axes.legend()
    figure.savefig(path, dpi=150, bbox_inches="tight")


def draw_maps(
    values: list[np.ndarray], runs: Sequence[Run], variable: str, when: str, path: Path
) -> None:
    """Plot the reference map, then each other run minus the reference on a symmetric scale."""
    panels = [(runs[0].name, values[0], "viridis", None)]
    for run, value in zip(runs[1:], values[1:], strict=True):
        difference = value - values[0]
        limit = np.nanmax(np.abs(difference), initial=0.0)
        panels.append((f"{run.name} minus reference", difference, "RdBu_r", limit))
    figure = Figure(figsize=(5 * len(panels), 4), layout="constrained")
    for axes, (title, value, cmap, limit) in zip(
        figure.subplots(1, len(panels)), panels, strict=True
    ):
        bounds = {} if limit is None else {"vmin": -limit, "vmax": limit}
        render_face_field(axes, runs[0], value, cmap=cmap, **bounds)
        axes.set_title(title)
    figure.suptitle(f"{variable}, {when}")
    figure.savefig(path, dpi=150, bbox_inches="tight")
