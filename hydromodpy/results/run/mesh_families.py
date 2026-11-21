"""The line families of the mesh of a run: the cells of its rivers, the faces of its lines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.mesh.request import RIVER_FAMILY
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run.tables import read_run_table

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.run.view import Run

__all__ = ["MeshFamilies", "mesh_constraint_network", "mesh_families", "stores_river_chains"]


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
        The mesh group names no engine, or the run has no mesh. A run
        that stored its mesh and has no family returns two empty tables.
    """
    if not _stores_families(run):
        raise FieldNotFoundError(
            f"Run '{run.sim_id}' stores no mesh families: its mesh group names no engine, "
            "and no family table was written for it.",
            sim_id=run.sim_id,
            variable="mesh_families",
        )
    cells = read_run_table(run, "mesh_cell_families").sort_values(
        ["family", "chain_id", "position"], kind="stable"
    )
    faces = read_run_table(run, "mesh_face_families").sort_values("face_row", kind="stable")
    return MeshFamilies(
        cells=cells.drop(columns="sim_id").reset_index(drop=True),
        faces=faces.drop(columns="sim_id").reset_index(drop=True),
    )


def stores_river_chains(run: Run) -> bool:
    """Say whether the mesh of ``run`` holds a chain of two cells or more of the ``rivers`` family."""
    if not _stores_families(run):
        return False
    cells = read_run_table(run, "mesh_cell_families")
    sizes = cells[cells["family"] == RIVER_FAMILY].groupby("chain_id").size()
    return bool((sizes >= 2).any())


def mesh_constraint_network(run: Run) -> gpd.GeoDataFrame:
    """Return the river network the mesh carries, one line per chain of the ``rivers`` family.

    Each line joins the solver centers of the cells of one chain, upstream first.
    It is the river as the solver sees it, after the mesh placed it on its cells,
    so it departs from the traced line by the distance of those centers to it. A chain of one cell
    is a point and has no line, so it is left out. The CRS is the one the mesh
    group states.
    """
    import geopandas as gpd
    import shapely

    if not stores_river_chains(run):
        raise FieldNotFoundError(
            f"Run '{run.sim_id}' stores no river chain of two cells in its mesh: the mesh "
            "followed no river, or each river fell in one cell.",
            sim_id=run.sim_id,
            variable="mesh_constraint",
        )
    cells = mesh_families(run).cells
    cells = cells[cells["family"] == RIVER_FAMILY]
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        mesh = sz.root["mesh"]
        x = np.asarray(mesh["face_x"][:], dtype=np.float64)
        y = np.asarray(mesh["face_y"][:], dtype=np.float64)
        crs = str(mesh.attrs["crs"])
    finally:
        sz.close()
    rows, lines = [], []
    for chain_id, chain in cells.groupby("chain_id", sort=True):
        ids = chain["cell_id"].to_numpy()
        if ids.size < 2:
            continue
        rows.append({"family": RIVER_FAMILY, "chain_id": int(chain_id), "n_cells": int(ids.size)})
        lines.append(shapely.linestrings(np.column_stack([x[ids], y[ids]])))
    frame = pd.DataFrame(rows, columns=["family", "chain_id", "n_cells"])
    return gpd.GeoDataFrame(frame, geometry=lines, crs=crs)


def _stores_families(run: Run) -> bool:
    """Say whether the mesh group of ``run`` names an engine, which writes the family tables."""
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        mesh = sz.root.get("mesh")
        return mesh is not None and mesh.attrs.get("engine") is not None
    finally:
        sz.close()
