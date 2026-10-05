"""The descent sidecar reads back exactly what the build wrote, or refuses.

The extractors never see the model: D reaches the run store through this file.
Its arrays come back with their dtypes (receiver int64, surface float64, masks
bool), its adjacency and epsilon, and the build report. An absent file reads as
None; a file that lost an array or mixes cell counts is refused.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow_common.mesh_descent import (
    DESCENT_EPSILON_M,
    build_solver_mesh_descent,
    read_descent_sidecar,
    write_descent_sidecar,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh


def _descent():
    nrow = ncol = 6
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    top = (10.0 + rows + np.abs(cols - 3)).astype(float)
    top[2 * ncol + 3] = 0.0  # a pit D raises
    mesh = SolverMesh.from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=top.reshape(nrow, ncol),
        botm=np.full((1, nrow, ncol), -10.0),
    )
    return build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)


def test_the_sidecar_round_trips(tmp_path) -> None:
    descent = _descent()

    path = write_descent_sidecar(descent, tmp_path, "model")
    record = read_descent_sidecar(path)

    assert path == tmp_path / "model.descent.npz"
    assert record is not None
    np.testing.assert_array_equal(record.receiver, descent.receiver)
    np.testing.assert_array_equal(record.surface, descent.surface)
    np.testing.assert_array_equal(record.base_level, descent.base_level)
    np.testing.assert_array_equal(record.channel, descent.channel)
    np.testing.assert_array_equal(record.pinned, descent.pinned)
    assert record.receiver.dtype == np.int64
    assert record.surface.dtype == np.float64
    assert record.base_level.dtype == bool
    assert record.adjacency == "shared_nodes"
    assert record.epsilon == DESCENT_EPSILON_M
    assert record.n_raised == descent.n_raised >= 1
    assert record.max_raise_m == descent.max_raise_m
    assert record.report()["n_raised"] == descent.n_raised


def test_an_absent_sidecar_reads_as_none(tmp_path) -> None:
    assert read_descent_sidecar(tmp_path / "model.descent.npz") is None


def test_a_sidecar_that_lost_an_array_is_refused(tmp_path) -> None:
    path = write_descent_sidecar(_descent(), tmp_path, "model")
    with np.load(path) as payload:
        kept = {name: payload[name] for name in payload.files if name != "surface"}
    np.savez(path, **kept)

    with pytest.raises(ValueError, match="lacks surface"):
        read_descent_sidecar(path)


def test_a_sidecar_that_mixes_cell_counts_is_refused(tmp_path) -> None:
    path = write_descent_sidecar(_descent(), tmp_path, "model")
    with np.load(path) as payload:
        arrays = {name: payload[name] for name in payload.files}
    arrays["channel"] = arrays["channel"][:-1]
    np.savez(path, **arrays)

    with pytest.raises(ValueError, match="mixes cell counts"):
        read_descent_sidecar(path)
