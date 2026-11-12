"""The descent D of a solver mesh and the sidecar file that keeps it beside the run.

D routes every cell of a grid to its receiver (cell index) down the steepest path.
The sidecar stores D and the basin of D, so the extractors read both back.
A damaged sidecar, or a stored basin that does not hold, is refused.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.catchment.drainage.descent import DescentBasin
from hydromodpy.solver.modflow_common.descent_store import (
    read_descent_sidecar,
    write_descent_sidecar,
)
from hydromodpy.solver.modflow_common.flow_directions import build_solver_mesh_descent
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

N = 6


def tilted_descent():
    """D of a 6 x 6 grid whose top rises towards the south-east corner."""
    rows, cols = np.divmod(np.arange(N * N), N)
    mesh = solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=(10.0 + rows + cols).reshape(N, N), botm=np.full((1, N, N), -5.0)
    )
    return build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)


def corner_basin(outlet: int = 0, rule: str = "within_polygon") -> DescentBasin:
    mask = np.zeros(N * N, dtype=bool)
    mask[[0, 1, N]] = True
    return DescentBasin(mask=mask, outlet=outlet, rule=rule, area_m2=3.0, seeded_at_outlet=True)


# Each row damages the stored file the way an old or a broken run would. `drop` removes an
# array and `trim` cuts the last cell of one array.
REFUSED_SIDECARS = [
    pytest.param(
        corner_basin(rule="polygon_centroid"),
        None,
        None,
        "names basin rule 'polygon_centroid'",
        id="unknown basin rule",
    ),
    pytest.param(
        corner_basin(outlet=5), None, None, "basin outlet outside its basin", id="outlet outside"
    ),
    pytest.param(
        corner_basin(), "basin_rule", None, "holds a basin without basin_rule", id="no basin rule"
    ),
    pytest.param(corner_basin(), "surface", None, "lacks surface", id="lost array"),
    pytest.param(corner_basin(), None, "channel", "mixes cell counts", id="mixed cell counts"),
]


def test_sidecar_without_a_file_is_none(tmp_path) -> None:
    assert read_descent_sidecar(tmp_path / "model.descent.npz") is None


@pytest.mark.parametrize(("basin", "drop", "trim", "message"), REFUSED_SIDECARS)
def test_refusals(tmp_path, basin, drop, trim, message) -> None:
    path = write_descent_sidecar(tilted_descent(), tmp_path, "m", basin=basin)
    with np.load(path) as payload:
        arrays = {name: payload[name] for name in payload.files if name != drop}
    arrays = {name: (values[:-1] if name == trim else values) for name, values in arrays.items()}
    np.savez(path, **arrays)

    with pytest.raises(ValueError, match=message):
        read_descent_sidecar(path)
