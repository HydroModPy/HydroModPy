"""The descent sidecar carries the basin of D; an older sidecar reads back without one.

The extractors never see the model, so the basin reaches them through the
sidecar with its outlet, rule, area and seeding. A sidecar written before the
basin was stored reads back with ``basin`` None, so its readers fall back on
their old support. A stored basin naming an unknown rule, or an outlet outside
itself, is refused.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.descent import DescentBasin
from hydromodpy.solver.modflow_common.mesh_descent import (
    build_solver_mesh_descent,
    read_descent_sidecar,
    write_descent_sidecar,
)
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

N = 6


def _descent():
    rows, cols = np.divmod(np.arange(N * N), N)
    mesh = solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=(10.0 + rows + cols).reshape(N, N), botm=np.full((1, N, N), -5.0)
    )
    return build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)


def _basin(outlet: int = 0, rule: str = "within_polygon") -> DescentBasin:
    mask = np.zeros(N * N, dtype=bool)
    mask[[0, 1, N]] = True
    return DescentBasin(mask=mask, outlet=outlet, rule=rule, area_m2=3.0, seeded_at_outlet=True)


def test_the_sidecar_round_trips_the_basin(tmp_path) -> None:
    basin = _basin()
    write_descent_sidecar(_descent(), tmp_path, "m", basin=basin)

    record = read_descent_sidecar(tmp_path / "m.descent.npz")

    assert record is not None
    np.testing.assert_array_equal(record.basin, basin.mask)
    assert (record.basin_outlet, record.basin_rule) == (0, "within_polygon")
    assert record.basin_area_m2 == 3.0
    assert record.basin_seeded_at_outlet is True


def test_a_sidecar_written_before_the_basin_reads_back_without_one(tmp_path) -> None:
    write_descent_sidecar(_descent(), tmp_path, "m")

    record = read_descent_sidecar(tmp_path / "m.descent.npz")

    assert record is not None
    assert record.basin is None
    assert record.basin_outlet == -1
    assert record.basin_rule == ""
    assert np.isnan(record.basin_area_m2)
    assert record.basin_seeded_at_outlet is False


@pytest.mark.parametrize(
    ("basin", "message"),
    [
        (_basin(rule="polygon_centroid"), "names basin rule 'polygon_centroid'"),
        (_basin(outlet=5), "basin outlet outside its basin"),
    ],
)
def test_a_stored_basin_that_does_not_hold_is_refused(tmp_path, basin, message) -> None:
    write_descent_sidecar(_descent(), tmp_path, "m", basin=basin)

    with pytest.raises(ValueError, match=message):
        read_descent_sidecar(tmp_path / "m.descent.npz")


def test_a_basin_without_its_fields_is_refused(tmp_path) -> None:
    path = write_descent_sidecar(_descent(), tmp_path, "m", basin=_basin())
    assert path is not None
    with np.load(path) as payload:
        kept = {name: payload[name] for name in payload.files if name != "basin_rule"}
    np.savez(path, **kept)

    with pytest.raises(ValueError, match="holds a basin without basin_rule"):
        read_descent_sidecar(path)
