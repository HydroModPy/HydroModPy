"""A constant head below the bottom of its cell is refused before MODFLOW-NWT runs.

MODFLOW-NWT does not stop on such a head: the cell holds no saturated
thickness, the boundary does not act there, and the budget drifts.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.solver.modflow_nwt.nwt.payloads.chd import refuse_constant_heads_below_bottom


def _adapter(boundary_conditions: dict[str, object], *, nper: int = 1) -> FlowToModflowAdapter:
    dem = np.array([[20.0, 20.0, 20.0], [20.0, 20.0, 20.0]])
    flow = SimpleNamespace(
        initial_conditions=SimpleNamespace(h=SimpleNamespace(type="top", value=0.0)),
        boundary_conditions=boundary_conditions,
        active_bc=list(boundary_conditions),
        sinks_sources={},
        active_sinks_sources=[],
        parameters={},
    )
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=dem,
        botm=np.stack([dem - 10.0, dem - 20.0]),
        dx=5.0,
        dy=5.0,
    )
    return FlowToModflowAdapter(
        flow=flow,
        domain=SimpleNamespace(zones={}),
        solver_mesh=solver_mesh,
        nper=nper,
        sink_fill=False,
    )


def test_a_static_side_head_below_the_top_layer_is_refused() -> None:
    adapter = _adapter({"west_side": SimpleNamespace(value=5.0)})
    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    with pytest.raises(SolverInputError) as excinfo:
        refuse_constant_heads_below_bottom(adapter, ibound=ibound, strt=strt, chd_spd=None)
    message = str(excinfo.value)
    assert "MODFLOW-NWT" in message
    assert "flow.bc.west_side: 2 cell(s)" in message
    assert "layer 1 row 1 column 1 (head 5.00 m, bottom 10.00 m, period 1)" in message
    assert "domain.depth_model" in message


def test_a_side_head_above_every_bottom_passes() -> None:
    adapter = _adapter({"west_side": SimpleNamespace(value=15.0)})
    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    refuse_constant_heads_below_bottom(adapter, ibound=ibound, strt=strt, chd_spd=None)


def test_a_chd_row_below_its_bottom_names_the_period() -> None:
    adapter = _adapter({"east_side": SimpleNamespace(value=[15.0, 8.0])}, nper=2)
    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    chd_spd = adapter._build_side_chd()
    with pytest.raises(SolverInputError) as excinfo:
        refuse_constant_heads_below_bottom(adapter, ibound=ibound, strt=strt, chd_spd=chd_spd)
    message = str(excinfo.value)
    assert "flow.bc.east_side" in message
    assert "column 3 (head 8.00 m, bottom 10.00 m, period 2)" in message


def test_the_build_refuses_before_any_package_is_assembled() -> None:
    adapter = _adapter({"west_side": SimpleNamespace(value=5.0)})
    with pytest.raises(SolverInputError, match="flow.bc.west_side"):
        adapter.build()
