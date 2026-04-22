"""Particle pathlines drawn over the mesh footprint."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


def _read_pathlines(sim: "Run") -> list[np.ndarray]:
    """Return one (n_steps, 3) array per particle from the Zarr store.

    The Zarr layout follows ``simulations/<id>.zarr/pathlines/`` with one
    array per particle (named ``p_<idx>``) whose columns are ``x, y, z``.
    """
    sz = sim._catalog.open_zarr(sim.sim_id)
    grp = sz.root.get("pathlines")
    if grp is None:
        return []
    tracks: list[np.ndarray] = []
    for key in grp:
        arr = np.asarray(grp[key])
        if arr.ndim == 2 and arr.shape[1] >= 2:
            tracks.append(arr)
    return tracks


@register
class ParticleTracks(BaseFigure):
    """Plan view of particle pathlines."""

    spec = FigureSpec(
        name="particle_tracks",
        title="Particle pathlines",
        kind="particles",
        required_fields=("pathlines",),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: "Run",
        ax: "Axes",
        *,
        color: str = "magma",
        lw: float = 0.6,
        **_,
    ) -> "Axes":
        tracks = _read_pathlines(sim)
        if not tracks:
            ax.text(0.5, 0.5, "no pathlines", ha="center", va="center", transform=ax.transAxes)
            return ax

        import matplotlib.cm as cm

        cmap = cm.get_cmap(color, max(len(tracks), 2))
        for i, track in enumerate(tracks):
            ax.plot(track[:, 0], track[:, 1], lw=lw, color=cmap(i))
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_title(f"Pathlines — {sim.name or sim.sim_id}")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        return ax
