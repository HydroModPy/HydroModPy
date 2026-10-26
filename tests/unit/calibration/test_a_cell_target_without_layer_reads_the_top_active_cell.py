"""A cell target given without a layer reads the top active cell of its column.

The v2 vertical contract places a point without a layer in the top active cell
of its column. ``CalibOutputCell.layer`` used to default to 0, which is a
pinched cell (idomain -1) or an inactive one where layer 0 does not reach. The
layer is now asked of the flow adapter when the request is built, through
``CellLocator.top_active_layer``: the MODFLOW backends read the idomain of the
run, Boussinesq has one layer. An explicit layer keeps its meaning, and a
backend that cannot answer is refused rather than read at layer 0.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.config import CalibOutputCell
from hydromodpy.calibration.metrics import solver_extract
from hydromodpy.calibration.metrics.solver_extract import observable_request_for_output
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.adapters.flow import ModflowNwtFlowAdapter
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

NROW, NCOL, NLAY = 2, 3, 3


def _pinched_mesh() -> SolverMesh:
    """Three layers on 2 x 3 cells. Row 0, col 1 loses layer 0; row 1, col 2 loses two."""
    mesh = solver_mesh_from_structured_arrays(
        nrow=NROW,
        ncol=NCOL,
        top=np.full((NROW, NCOL), 30.0),
        botm=np.stack([np.full((NROW, NCOL), z) for z in (20.0, 10.0, 0.0)]),
    )
    idomain = np.ones((NLAY, NROW, NCOL), dtype=int)
    idomain[0, 0, 1] = -1
    idomain[0, 1, 2] = -1
    idomain[1, 1, 2] = 0
    return replace(mesh, idomain=idomain.reshape(NLAY, -1))


def _wire(monkeypatch, adapter: object, model: object) -> SimpleNamespace:
    run_ctx = SimpleNamespace(run=SimpleNamespace(id="r1"), model=model)
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, run_ctx))
    return SimpleNamespace()


@pytest.fixture(params=[Modflow6FlowAdapter, ModflowNwtFlowAdapter], ids=["mf6", "nwt"])
def ctx(request, monkeypatch):
    return _wire(monkeypatch, request.param(), SimpleNamespace(solver_mesh=_pinched_mesh()))


def _cell(**selector: int) -> CalibOutputCell:
    return CalibOutputCell.model_validate({"variable": "head", "support": "cell", **selector})


def test_a_cell_target_declares_no_layer_by_default() -> None:
    assert _cell(row=0, col=1).layer is None


def test_a_column_pinched_at_layer_0_is_read_at_layer_1(ctx) -> None:
    request = observable_request_for_output("piezo", _cell(row=0, col=1), ctx)
    assert request.cell == (1, 0, 1)


def test_a_column_that_starts_lower_is_read_at_its_first_active_layer(ctx) -> None:
    request = observable_request_for_output("piezo", _cell(row=1, col=2), ctx)
    assert request.cell == (2, 1, 2)


def test_a_column_active_from_the_top_is_read_at_layer_0(ctx) -> None:
    request = observable_request_for_output("piezo", _cell(row=1, col=0), ctx)
    assert request.cell == (0, 1, 0)


@pytest.mark.parametrize("layer", [0, 2])
def test_an_explicit_layer_is_kept_even_on_a_pinched_column(ctx, layer: int) -> None:
    request = observable_request_for_output("piezo", _cell(row=0, col=1, layer=layer), ctx)
    assert request.cell == (layer, 0, 1)


def test_a_cell_outside_the_grid_is_refused_by_name(ctx) -> None:
    with pytest.raises(ValueError, match="'piezo'.*outside the 2 x 3 grid"):
        observable_request_for_output("piezo", _cell(row=5, col=0), ctx)


def test_the_one_layer_solver_reads_layer_0(monkeypatch) -> None:
    ctx = _wire(monkeypatch, BoussinesqFlowAdapter(), SimpleNamespace())
    request = observable_request_for_output("piezo", _cell(row=1, col=2), ctx)
    assert request.cell == (0, 1, 2)


def test_a_run_without_a_grid_is_refused_rather_than_read_at_layer_0(monkeypatch) -> None:
    ctx = _wire(monkeypatch, Modflow6FlowAdapter(), None)
    with pytest.raises(NotImplementedError, match="'piezo' gives no layer.*no grid yet"):
        observable_request_for_output("piezo", _cell(row=1, col=2), ctx)


def test_a_backend_that_cannot_answer_is_refused_by_name(monkeypatch) -> None:
    ctx = _wire(monkeypatch, object(), SimpleNamespace(solver_mesh=_pinched_mesh()))
    with pytest.raises(NotImplementedError, match="'piezo' gives no layer.*Write the layer"):
        observable_request_for_output("piezo", _cell(row=0, col=1), ctx)
