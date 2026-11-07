"""Fakes shared by the prepare-solver tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from tests._helpers.sealed_runs import seal_run


def sealed_run(project: Path, name: str) -> str:
    sid = seal_run(project, name, site=None)
    (project / "runs" / name / FIELDS_STORE_NAME).mkdir()
    return sid


def square_and_pentagon() -> HydroMesh:
    vertices = np.array(
        [[0, 0], [1, 0], [1, 1], [0, 1], [2, 0], [2.5, 0.5], [2, 1]], dtype=np.float64
    )
    cells = (np.array([0, 1, 2, 3]), np.array([1, 4, 5, 6, 2]))
    return HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),))
