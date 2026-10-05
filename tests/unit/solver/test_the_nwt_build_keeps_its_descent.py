"""MODFLOW-NWT builds the descent D too, seeded on every constant-head cell it writes.

NWT has no CHD support mask: its static constant heads are ``ibound == -1``,
its transient ones are rows of the CHD package with ``ibound`` left at 1, and
its inactive cells are ``ibound == 0``. D seeds on both kinds of constant head,
as MODFLOW 6 seeds its CHD supports, leaves its sidecar beside the model and
keeps itself there without its adjacency. The steady initialization builds none.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow_common.mesh_descent import read_descent_sidecar
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt

NROW = NCOL = 5


def _mesh() -> SolverMesh:
    rows, cols = np.divmod(np.arange(NROW * NCOL), NCOL)
    return SolverMesh.from_structured_arrays(
        nrow=NROW,
        ncol=NCOL,
        top=(10.0 + rows + cols).reshape(NROW, NCOL).astype(float),
        botm=np.full((2, NROW, NCOL), -10.0) - np.arange(2)[:, None, None],
    )


def _inputs() -> SimpleNamespace:
    ibound = np.ones((2, NROW, NCOL), dtype=int)
    ibound[1, 2, 2] = -1  # a static constant head in the lower layer only
    ibound[:, 0, 4] = 0  # an inactive column
    # A transient constant head: CHD rows in two periods, ibound left at 1.
    chd_spd = {0: [[0, 3, 1, 5.0, 5.0]], 1: [[0, 3, 1, 6.0, 6.0]]}
    return SimpleNamespace(ibound=ibound, chd_spd=chd_spd)


def test_the_nwt_build_seeds_d_on_every_constant_head_and_leaves_it_beside_the_model(
    tmp_path,
) -> None:
    model = SimpleNamespace(
        geographic=None, full_path=str(tmp_path), model_name="nwt", descent=None, auxiliary=False
    )

    descent = ModflowNwt._build_descent(model, _mesh(), _inputs())

    assert model.descent is descent
    assert descent.adjacency is None
    static, transient, inactive = 2 * NCOL + 2, 3 * NCOL + 1, 0 * NCOL + 4
    assert np.flatnonzero(descent.constant_head).tolist() == [static, transient]
    assert descent.base_level[static] and descent.base_level[transient]
    assert not descent.routable[inactive]
    assert not descent.pinned.any()
    record = read_descent_sidecar(tmp_path / "nwt.descent.npz")
    assert record is not None
    np.testing.assert_array_equal(record.receiver, descent.receiver)
    np.testing.assert_array_equal(record.constant_head, descent.constant_head)


def test_the_steady_initialization_builds_no_descent(tmp_path) -> None:
    model = SimpleNamespace(
        geographic=None, full_path=str(tmp_path), model_name="nwt", descent=None, auxiliary=True
    )

    assert ModflowNwt._build_descent(model, _mesh(), _inputs()) is None
    assert model.descent is None
    assert not list(tmp_path.glob("*.descent.npz"))
