"""The home-grown DISV LAK builder reproduces the ex-gwf-lak-p01 footprint.

``flopy.mf6.utils.get_lak_connections`` on the Merritt & Konikow (2000) test-1
grid (single surface lake, 5x5 cells on layer 0) yields 45 connections: 25
VERTICAL (one per lake cell, to the active cell below) and 20 HORIZONTAL (the
perimeter edges). This test pins the home-grown DISV builder to that exact set
WITHOUT running a solver, isolating the CONNECTIONDATA path that production uses
in place of ``get_lak_connections`` (which does not support DISV lakes).

The expected counts come from the case's documented structural tolerances, so a
drift in either the builder or the published footprint fails here.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.modflow6.builders import apply_lake_idomain_mask
from validation_cases.numerical.steady.lak_merritt_konikow_p01.geometry import load_geometry
from validation_cases.numerical.steady.lak_merritt_konikow_p01.runtime_lak import (
    build_hmp_connectiondata,
    build_hmp_solver_mesh,
)
from validation_cases.shared import load_case_tolerances


def _structural_tolerances() -> dict:
    from validation_cases.numerical.steady.lak_merritt_konikow_p01.geometry import CASE_DIR

    return dict(load_case_tolerances(CASE_DIR)["structural"])


def test_connectiondata_matches_published_vertical_horizontal_split() -> None:
    tol = _structural_tolerances()
    rows = build_hmp_connectiondata()

    vertical = [r for r in rows if r[3] == "VERTICAL"]
    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]

    assert len(rows) == int(tol["n_connections"]) == 45
    assert len(vertical) == int(tol["n_vertical"]) == 25
    assert len(horizontal) == int(tol["n_horizontal"]) == 20
    # Negative invariant: a different split must NOT be produced (e.g. a missed
    # perimeter edge or a doubled vertical would change these counts).
    assert len(vertical) != len(horizontal)


def test_exactly_one_vertical_connection_per_lake_cell() -> None:
    geometry = load_geometry()
    rows = build_hmp_connectiondata(geometry)

    vertical = [r for r in rows if r[3] == "VERTICAL"]
    # One VERTICAL per lake cell, each pointing at layer 1 (first active below the
    # surface lake in layer 0).
    vert_cells = sorted(int(r[2][1]) for r in vertical)
    assert vert_cells == sorted(geometry.lake_cell_ids)
    assert all(r[2][0] == 1 for r in vertical)


def test_horizontal_connections_are_geometrically_valid() -> None:
    geometry = load_geometry()
    lake_set = set(geometry.lake_cell_ids)
    rows = build_hmp_connectiondata(geometry)

    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]
    assert horizontal
    for row in horizontal:
        lay, neighbour = int(row[2][0]), int(row[2][1])
        assert lay == 0  # surface lake occupies layer 0
        # Bank seepage never connects a lake cell to another lake cell.
        assert neighbour not in lake_set
        connlen = float(row[7])
        connwidth = float(row[8])
        assert connlen > 0.0
        assert connwidth > 0.0


def test_lake_cells_are_inactive_on_the_surface_layer() -> None:
    geometry = load_geometry()
    mesh = build_hmp_solver_mesh(geometry)
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": geometry.lake_cell_ids})

    idomain = masked.idomain()
    lake_cells = geometry.lake_cell_ids
    # idomain = 0 on exactly the lake cells in layer 0, and 1 everywhere else.
    assert np.all(idomain[0, lake_cells] == 0)
    assert np.all(idomain[1:, lake_cells] == 1)
    non_lake = [c for c in range(geometry.n_cells) if c not in set(lake_cells)]
    assert np.all(idomain[:, non_lake] == 1)
