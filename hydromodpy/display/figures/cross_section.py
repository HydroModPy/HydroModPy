"""Vertical cross-section of head along a row or column of cells.

The figure plots head versus cell index for one column (DIS) or one slice of
faces (DISV) at a single timestep. Layers are stacked along the y-axis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display._ugrid import last_timestep
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class CrossSection(BaseFigure):
    """Vertical head profile across one column / face slice."""

    spec = FigureSpec(
        name="cross_section",
        title="Head cross-section",
        kind="section",
        required_fields=("head",),
        default_figsize=(7.0, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        timestep: int | None = None,
        face_index: int | None = None,
        **_,
    ) -> Axes:
        ts = last_timestep(sim) if timestep is None else timestep
        head = np.asarray(sim.field("head", timestep=ts))
        if head.ndim == 1:
            ax.plot(head, label="head")
            ax.set_xlabel("Face")
        else:
            n_layers, n_faces = head.shape
            idx = face_index if face_index is not None else n_faces // 2
            ax.plot(head[:, idx], np.arange(n_layers), marker="o", label=f"face {idx}")
            ax.invert_yaxis()
            ax.set_ylabel("Layer (top = 0)")
            ax.set_xlabel("Head (m)")
        ax.set_title(f"Cross-section — {sim.name or sim.sim_id}")
        ax.grid(True, ls=":", lw=0.4)
        ax.legend()
        return ax
