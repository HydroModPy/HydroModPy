"""Lake cells must be made inactive before DISV is built.

LAK lays the lake on the existing grid by deactivating the occupied cells
(``idomain = 0``) and supplying the storage / exchange itself. The mask must be
applied on a *copy* of the frozen ``SolverMesh`` so the original survives, and it
must zero the active domain on exactly the lake cells' occupied layers (leaving
an active aquifer cell below for the LAK VERTICAL connection) so RCH, EVT and
DRN stay consistent with the footprint.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders import apply_lake_idomain_mask
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh


def _grid(nrow: int, ncol: int, nlay: int = 3) -> SolverMesh:
    top = np.full((nrow, ncol), 10.0)
    botm = np.stack([np.full((nrow, ncol), 10.0 - (lay + 1) * 3.0) for lay in range(nlay)])
    return SolverMesh.from_structured_arrays(nrow=nrow, ncol=ncol, top=top, botm=botm)


def test_apply_lake_idomain_mask_deactivates_surface_layer_of_lake_cells() -> None:
    mesh = _grid(3, 3, nlay=3)
    # Central cell (row 1, col 1) -> flat id 4 in row-major order.
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [4]})

    idomain = masked.idomain()
    assert idomain.shape == (3, 9)
    # Lake cell inactive on the occupied (top) layer ...
    assert idomain[0, 4] == 0
    # ... but the aquifer below stays active for the VERTICAL connection.
    assert idomain[1, 4] == 1
    assert idomain[2, 4] == 1
    # Every other cell stays active on every layer.
    active_cells = [c for c in range(9) if c != 4]
    assert np.all(idomain[:, active_cells] == 1)


def test_apply_lake_idomain_mask_respects_occupied_layers() -> None:
    mesh = _grid(2, 2, nlay=3)
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [0]}, occupied_layers=2)
    idomain = masked.idomain()
    assert idomain[0, 0] == 0
    assert idomain[1, 0] == 0
    # The deepest layer stays active so the lake has somewhere to leak.
    assert idomain[2, 0] == 1


def test_apply_lake_idomain_mask_leaves_original_mesh_unchanged() -> None:
    mesh = _grid(2, 3, nlay=2)
    before = mesh.idomain().copy()

    apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [0, 1]})

    # The frozen mesh is replaced, never mutated in place.
    assert np.array_equal(mesh.idomain(), before)
    assert np.all(mesh.idomain() == 1)


def test_apply_lake_idomain_mask_rejects_full_column_occupation() -> None:
    mesh = _grid(2, 2, nlay=2)
    with pytest.raises(ValueError, match="at least one active layer"):
        apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [0]}, occupied_layers=2)


def test_apply_lake_idomain_mask_handles_multiple_lakes() -> None:
    mesh = _grid(2, 4, nlay=2)
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [0], "lac1": [7]})
    idomain = masked.idomain()
    assert idomain[0, 0] == 0
    assert idomain[0, 7] == 0
    assert idomain[0, [1, 2, 3, 4, 5, 6]].tolist() == [1, 1, 1, 1, 1, 1]
