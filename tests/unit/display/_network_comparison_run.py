"""A run whose stream comparison is known cell by cell, before it is computed.

The three network maps read the partition the calibration criterion scores,
rebuilt from what a run persisted. Asserting on them therefore needs a run and
not three masks, and it needs one whose answer is written down here rather than
read back from the same function the figure called.

The mesh is a ``5 x 3`` grid of square cells carrying a V-shaped valley whose
axis is the middle column and whose floor falls to the south. The drop across
one column is ten times the drop across one row, so every cell descends toward
the axis first and then down it: the descent of a cell is its Manhattan path to
the axis and then to the outlet, one cell width per step. The mapped network is
the axis column, and the outlet is its southern end.

Putting a release flux on one cell therefore names the simulated network
exactly: that cell, plus every cell its water flows through on the way out.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

import numpy as np

NX = 5
NY = 3
AXIS_COLUMN = 2
CELL_M = 100.0
CRS = "EPSG:2154"

COLUMN_DROP_M = 20.0
"""Drop from one column to the next toward the axis."""

ROW_DROP_M = 2.0
"""Drop from one row to the next toward the outlet, ten times the smaller."""

CELL_RECHARGE_M3_S = 1.0e-4
"""Recharge of every cell, so a threshold is a fraction of something real."""

RELEASE_M3_S = 1.0
"""Release of a seeping cell: far above any threshold a test asks for."""


def cell(column: int, row: int) -> int:
    """Return the index of one grid cell, row-major from the southern row."""
    return row * NX + column


def column_cells(column: int) -> list[int]:
    """Return every cell of one grid column."""
    return [cell(column, row) for row in range(NY)]


def valley_topography() -> np.ndarray:
    """Return the V-shaped valley the mesh is routed on."""
    return np.asarray(
        [
            abs(column - AXIS_COLUMN) * COLUMN_DROP_M + row * ROW_DROP_M
            for row in range(NY)
            for column in range(NX)
        ],
        dtype=float,
    )


def comparison_run(
    *,
    seepage_cells: Sequence[int] = (),
    cell_m: float = CELL_M,
    topography: np.ndarray | None = None,
    relief: np.ndarray | None = None,
    with_relief: bool = True,
    with_release: bool = True,
    catchment_columns: Sequence[int] | None = None,
    name: str = "nancon",
) -> SimpleNamespace:
    """Return a run the stream comparison can be rebuilt from.

    ``seepage_cells`` are the cells releasing water to the surface; every other
    cell releases nothing, so the simulated network is the downslope closure of
    exactly those. ``topography`` replaces the routing surface, and ``relief``
    the elevation the run persisted as a field: they are the same array unless
    a test drives the hillshade on its own.
    """
    import geopandas as gpd
    from shapely.geometry import LineString, box

    vertices, faces = _grid(cell_m)
    surface = valley_topography() if topography is None else np.asarray(topography, dtype=float)
    mesh = SimpleNamespace(
        vertices=vertices,
        face_node_connectivity=faces,
        topography=surface,
        crs=CRS,
    )

    axis_x = (AXIS_COLUMN + 0.5) * cell_m
    network = gpd.GeoDataFrame(
        geometry=[LineString([(axis_x, 0.1 * cell_m), (axis_x, (NY - 0.1) * cell_m)])],
        crs=CRS,
    )
    columns = range(NX) if catchment_columns is None else catchment_columns
    watershed = gpd.GeoDataFrame(
        geometry=[
            box(
                min(columns) * cell_m,
                -0.1 * cell_m,
                (max(columns) + 1) * cell_m,
                (NY + 0.1) * cell_m,
            )
        ],
        crs=CRS,
    )

    release = np.zeros(NX * NY, dtype=float)
    release[list(seepage_cells)] = RELEASE_M3_S
    fields: dict[str, np.ndarray] = {"recharge": np.full(NX * NY, CELL_RECHARGE_M3_S)}
    if with_release:
        fields["release_flux"] = release
    if with_relief:
        fields["topography"] = surface if relief is None else np.asarray(relief, dtype=float)

    return SimpleNamespace(
        sim_id="sim-network",
        name=name,
        mesh=mesh,
        outlet=(axis_x, 0.5 * cell_m),
        has_field=lambda variable, **_: variable in fields,
        field=lambda variable, **_: fields[variable],
        has_hydrographic_network=lambda role="generated": role == "reference",
        hydrographic_network=lambda role="generated": network,
        geographic=lambda feature: watershed,
    )


def _grid(cell_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Return the vertices and the face connectivity of the grid."""
    vertices = np.asarray(
        [[column * cell_m, row * cell_m, 0.0] for row in range(NY + 1) for column in range(NX + 1)],
        dtype=float,
    )
    faces = np.asarray(
        [
            [
                row * (NX + 1) + column,
                row * (NX + 1) + column + 1,
                (row + 1) * (NX + 1) + column + 1,
                (row + 1) * (NX + 1) + column,
            ]
            for row in range(NY)
            for column in range(NX)
        ],
        dtype=int,
    )
    return vertices, faces


def drawn_cells(collection, cell_m: float = CELL_M) -> list[int]:
    """Return the grid cells one drawn collection covers, in index order."""
    cells = []
    for path in collection.get_paths():
        corners = path.vertices
        column = int(round(float(corners[:, 0].mean()) / cell_m - 0.5))
        row = int(round(float(corners[:, 1].mean()) / cell_m - 0.5))
        cells.append(cell(column, row))
    return sorted(cells)
