"""The line families of the mesh of a run: the cells of its rivers, the faces of its lines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.results.errors import FieldNotFoundError

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

__all__ = ["MeshFamilies", "mesh_families"]


@dataclass(frozen=True)
class MeshFamilies:
    """The two family tables of one run, both empty when the mesh holds no family.

    ``cells`` has one row per cell of every chain of a cell family, with the
    columns ``family``, ``chain_id``, ``position`` (0 upstream), ``cell_id`` and
    ``offset_m``. ``faces`` has one row per mesh edge that lies on a face family,
    with ``face_row``, ``family``, ``edge_id``, ``node_a``, ``node_b``, ``cell_a``,
    ``cell_b`` (-1 on the domain boundary), ``zone_left`` and ``zone_right``.
    """

    cells: pd.DataFrame
    faces: pd.DataFrame


def mesh_families(run: Run) -> MeshFamilies:
    """Return the family tables of the mesh of ``run``.

    A module function rather than a ``Run`` attribute: ``Run`` is capped at 50
    public attributes (``tests/unit/results/test_run_surface.py``).

    Raises
    ------
    FieldNotFoundError
        The run was sealed before mesh families were stored, or has no mesh. A run
        that stored its mesh and has no family returns two empty tables.
    """
    if not _stores_families(run):
        raise FieldNotFoundError(
            f"Run '{run.sim_id}' was sealed before mesh families were stored: its mesh group "
            "names no engine, and no family table was written for it.",
            sim_id=run.sim_id,
            variable="mesh_families",
        )
    backend = run._catalog.backend
    cells = backend.query(
        "SELECT * FROM mesh_cell_families WHERE sim_id = ? ORDER BY family, chain_id, position",
        [run.sim_id],
    )
    faces = backend.query(
        "SELECT * FROM mesh_face_families WHERE sim_id = ? ORDER BY face_row", [run.sim_id]
    )
    return MeshFamilies(
        cells=cells.drop(columns="sim_id").reset_index(drop=True),
        faces=faces.drop(columns="sim_id").reset_index(drop=True),
    )


def _stores_families(run: Run) -> bool:
    """Say whether the mesh group of ``run`` carries the cell-mesh layout (it names an engine)."""
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        mesh = sz.root.get("mesh")
        return mesh is not None and mesh.attrs.get("engine") is not None
    finally:
        sz.close()
