"""The descent D that MODFLOW-NWT builds, seeded on every constant-head cell (cell index).

NWT has no CHD support mask. A static constant head is `ibound == -1`, a transient one is a
row of the CHD package with `ibound` left at 1, and an inactive cell is `ibound == 0`.
D seeds on both kinds of constant head, is written beside the model and has no adjacency.
The steady initialization builds none.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.model.domain.geometry import RasterGeometry
from hydromodpy.model.model import Geometry
from hydromodpy.solver.modflow_common.descent_store import read_descent_sidecar
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

N_ROW = N_COL = 5
STATIC_HEAD = 2 * N_COL + 2
TRANSIENT_HEAD = 3 * N_COL + 1
INACTIVE = 4


def two_layer_mesh():
    rows, cols = np.divmod(np.arange(N_ROW * N_COL), N_COL)
    return solver_mesh_from_structured_arrays(
        nrow=N_ROW,
        ncol=N_COL,
        top=(10.0 + rows + cols).reshape(N_ROW, N_COL).astype(float),
        botm=np.full((2, N_ROW, N_COL), -10.0) - np.arange(2)[:, None, None],
    )


def nwt_inputs():
    ibound = np.ones((2, N_ROW, N_COL), dtype=int)
    ibound[1, 2, 2] = -1  # a static constant head in the lower layer only
    ibound[:, 0, 4] = 0  # an inactive column
    chd_spd = {0: [[0, 3, 1, 5.0, 5.0]], 1: [[0, 3, 1, 6.0, 6.0]]}  # CHD rows in two periods
    return SimpleNamespace(ibound=ibound, chd_spd=chd_spd)


def nwt_model(tmp_path, *, auxiliary: bool):
    """A model with the DEM grid NWT builds on, and no river network."""
    raster = RasterGeometry.from_geographic(SimpleNamespace())
    return SimpleNamespace(
        inputs=make_model(geometry=Geometry(cells=None, domain=None, raster=raster)),
        full_path=str(tmp_path),
        model_name="nwt",
        descent=None,
        auxiliary=auxiliary,
    )


def test_d_seeds_on_every_constant_head(tmp_path) -> None:
    model = nwt_model(tmp_path, auxiliary=False)

    descent = ModflowNwt._build_descent(model, two_layer_mesh(), nwt_inputs())

    assert model.descent is descent
    assert descent.adjacency is None
    assert np.flatnonzero(descent.constant_head).tolist() == [STATIC_HEAD, TRANSIENT_HEAD]
    assert descent.base_level[STATIC_HEAD] and descent.base_level[TRANSIENT_HEAD]
    assert not descent.routable[INACTIVE]
    assert not descent.pinned.any()
    record = read_descent_sidecar(tmp_path / "nwt.descent.npz")
    np.testing.assert_array_equal(record.receiver, descent.receiver)
    np.testing.assert_array_equal(record.constant_head, descent.constant_head)


def test_steady_initialization_builds_no_d(tmp_path) -> None:
    model = nwt_model(tmp_path, auxiliary=True)

    assert ModflowNwt._build_descent(model, two_layer_mesh(), nwt_inputs()) is None
    assert model.descent is None
    assert not list(tmp_path.glob("*.descent.npz"))
