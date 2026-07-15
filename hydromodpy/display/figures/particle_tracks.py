"""Particle pathlines drawn over the mesh footprint."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


def _read_particles(sim: Run) -> list[np.ndarray]:
    """Return one (n_steps, 3) array per particle from the Zarr store.

    The preferred layout stores vectorized ``x``, ``y``, ``z`` and ``time``
    arrays shaped ``(n_particles, max_steps)`` under
    ``simulations/<id>.zarr/particles/``. Older stores may contain one array
    per particle (named ``p_<idx>``) whose columns are ``x, y, z``.
    """
    sz = sim._catalog.open_zarr(sim.sim_id)
    try:
        grp = sz.root.get("particles")
        if grp is None:
            return []
        tracks: list[np.ndarray] = []

        if "x" in grp and "y" in grp:
            x = np.asarray(grp["x"], dtype=float)
            y = np.asarray(grp["y"], dtype=float)
            if x.ndim == 1:
                x = x.reshape(1, -1)
            if y.ndim == 1:
                y = y.reshape(1, -1)
            z = (
                np.asarray(grp["z"], dtype=float)
                if "z" in grp
                else np.full_like(x, np.nan, dtype=float)
            )
            if z.ndim == 1:
                z = z.reshape(1, -1)
            n_particles = min(x.shape[0], y.shape[0], z.shape[0])
            for i in range(n_particles):
                valid = np.isfinite(x[i]) & np.isfinite(y[i])
                if not np.any(valid):
                    continue
                tracks.append(np.column_stack((x[i, valid], y[i, valid], z[i, valid])))
            return tracks

        for key in grp:
            arr = np.asarray(grp[key])
            if arr.ndim == 2 and arr.shape[1] >= 2:
                tracks.append(arr)
        return tracks
    finally:
        sz.close()


@register
class ParticleTracks(BaseFigure):
    """Plan view of particle pathlines."""

    spec = FigureSpec(
        name="particle_tracks",
        title="Particle pathlines",
        kind="particles",
        required_fields=("particles",),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        color: str = "magma",
        lw: float = 0.6,
        **_,
    ) -> Axes:
        tracks = _read_particles(sim)
        if not tracks:
            ax.text(0.5, 0.5, "no pathlines", ha="center", va="center", transform=ax.transAxes)
            return ax

        import matplotlib.pyplot as plt

        cmap = plt.get_cmap(color, max(len(tracks), 2))
        for i, track in enumerate(tracks):
            ax.plot(track[:, 0], track[:, 1], lw=lw, color=cmap(i))
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_title(f"Pathlines - {sim.name or sim.sim_id}")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        return ax
