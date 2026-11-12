"""The build keeps the cell below each declared spillway, with D, for the heads of the criterion.

Only a lake whose spillway is declared (an outlet releasing downstream, which
the production path resolves to a toe cell) has a dam foot. A lake without one
has none, and a foot that is a cell of a lake is dropped. The cells travel in
the descent sidecar, and a sidecar written before they were kept reads as having
none.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.catchment.drainage.descent import descent_basin
from hydromodpy.solver.modflow6 import build
from hydromodpy.solver.modflow_common.descent_store import (
    read_descent_sidecar,
    write_descent_sidecar,
)
from tests._helpers.descent_cases import grid_descent
from tests.unit.catchment.drainage.test_descent import _valley


def _descent():
    top, lake_of = _valley()
    return grid_descent(top, lake_of=lake_of)


def _keep(model, descent, feet) -> None:
    basin = descent_basin(descent, cell_area_m2=np.ones(descent.receiver.size))
    build._keep_dam_feet_and_leave_descent(model, descent, feet, basin=basin)


def test_an_auxiliary_model_keeps_no_foot_and_leaves_no_sidecar(tmp_path) -> None:
    model = SimpleNamespace(full_path=str(tmp_path), model_output_name="model", auxiliary=True)

    _keep(model, _descent(), {"reservoir": 3})

    assert model.dam_foot_cells == {}
    assert not list(tmp_path.glob("*.descent.npz"))


def test_a_sidecar_written_before_the_feet_were_kept_reads_as_having_none(tmp_path) -> None:
    path = write_descent_sidecar(_descent(), tmp_path, "model", dam_foot_cells={"a": 12})
    with np.load(path) as payload:
        kept = {name: payload[name] for name in payload.files if name != "dam_foot"}
    np.savez(path, **kept)

    record = read_descent_sidecar(path)

    assert record is not None
    assert record.dam_foot.size == 0
