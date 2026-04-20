"""UGRID mesh rendering helper shared by spatial figures.

Reads ``mesh.vertices`` and ``mesh.face_node_connectivity`` from the
:class:`~hydromodpy.results.simulation.Simulation` and draws a per-face scalar
field as a :class:`~matplotlib.collections.PolyCollection`. Works identically
on DIS (rectangular cells) and DISV (arbitrary polygons) layouts because both
solver families serialize their mesh in the same UGRID schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.collections import PolyCollection

    from hydromodpy.results.simulation import Simulation


def render_face_field(
    ax: "Axes",
    sim: "Simulation",
    values: np.ndarray,
    *,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    cbar_label: str | None = None,
) -> "PolyCollection":
    """Draw ``values`` (one scalar per face) as colored polygons on ``ax``."""
    from matplotlib.collections import PolyCollection

    mesh = sim.mesh
    vertices = np.asarray(mesh["vertices"])
    fnc = np.asarray(mesh["face_node_connectivity"])

    polygons = []
    for row in fnc:
        nodes = row[row >= 0] if row.dtype.kind in "iu" else row[~np.isnan(row)]
        polygons.append(vertices[nodes.astype(int)][:, :2])

    flat = np.asarray(values).ravel()
    if flat.size != len(polygons):
        raise ValueError(
            f"face field has {flat.size} values but mesh has {len(polygons)} faces"
        )

    coll = PolyCollection(
        polygons,
        array=flat,
        cmap=cmap,
        edgecolors="none",
    )
    if vmin is not None or vmax is not None:
        coll.set_clim(vmin=vmin, vmax=vmax)
    ax.add_collection(coll)
    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()
    cbar = ax.figure.colorbar(coll, ax=ax, fraction=0.046, pad=0.04)
    if cbar_label:
        cbar.set_label(cbar_label)
    return coll


def last_timestep(sim: "Simulation") -> int:
    """Return the index of the last timestep, or 0 if not declared."""
    n_ts = sim.n_timesteps or 1
    return n_ts - 1
