"""The lake and descent section of the MODFLOW 6 build, and the spillway receivers.

The build computes the descent D of a 10 m grid, finds the foot (cell index) of each declared
spillway and leaves D beside the model. A spillway is handed to a reach that does not feed its
own lake.
"""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6 import build
from hydromodpy.solver.modflow6.build import _resolve_spillway_receivers
from hydromodpy.solver.modflow6.builders import lake_outflow as lake_builder
from hydromodpy.solver.modflow_common.descent_store import read_descent_sidecar
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

N_ROW, N_COL = 5, 7
LAKE = {"res": [2 * N_COL + 3, 2 * N_COL + 4]}
# West of the lake cell nearest the outlet, and lower than its row neighbors.
TOE = 2 * N_COL + 2


def sloping_mesh():
    """Five rows of seven 10 m cells whose top rises by 1 m per column."""
    _, cols = np.divmod(np.arange(N_ROW * N_COL), N_COL)
    return solver_mesh_from_structured_arrays(
        nrow=N_ROW,
        ncol=N_COL,
        top=(10.0 + cols).reshape(N_ROW, N_COL),
        botm=np.full((1, N_ROW, N_COL), -50.0),
        dx=10.0,
        dy=10.0,
    )


def declare_spillway(monkeypatch, declared: bool) -> None:
    outlets = [{"mover": {"to_downstream_reach": True}}] if declared else []
    monkeypatch.setattr(
        lake_builder, "_active_lake_definitions", lambda model: {"res": {"outlets": outlets}}
    )


def reach(ifno: int, cell: int, *, upstream=(), terminal_lake: int | None = None):
    """A reach of a river network, `terminal_lake` is the 1-based lake it ends in."""
    return SimpleNamespace(
        ifno=ifno,
        cellid=(0, cell),
        upstream=tuple(upstream),
        is_terminal_to_lake=terminal_lake is not None,
        terminal_lake=terminal_lake,
    )


CENTROIDS = np.array([[float(i) * 10.0, 0.0] for i in range(8)])

# Reach 0 on cell 2 feeds reach 1 on cell 3, which ends in the forebay (lake 2).
# Reach 2 on cell 5 ends in the reservoir (lake 1).
TWO_LAKE_RIVER = SimpleNamespace(
    reaches=[
        reach(0, 2),
        reach(1, 3, upstream=(0,), terminal_lake=2),
        reach(2, 5, terminal_lake=1),
    ]
)
ONE_LAKE_RIVER = SimpleNamespace(reaches=[reach(0, 2, terminal_lake=1), reach(1, 5)])

# One row per lake order and toe cell: a spillway on a feeder of its own lake is refused.
FEEDER_REFUSALS = [
    pytest.param(ONE_LAKE_RIVER, {"res": 2}, ["res"], id="one lake"),
    pytest.param(TWO_LAKE_RIVER, {"forebay": 2}, ["res", "forebay"], id="forebay on its feeder"),
]


def build_section(model):
    return build._build_descent_and_dam_feet(
        model,
        sloping_mesh(),
        LAKE,
        np.zeros(N_ROW * N_COL, dtype=bool),
        (0.0, 25.0),  # outlet x, y (m)
    )


def test_build_calls_the_descent_section() -> None:
    tree = ast.parse(inspect.getsource(build._resolve_streams))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "_build_descent_and_dam_feet" in called


@pytest.mark.parametrize(
    ("declared", "feet"),
    [
        pytest.param(True, {"res": TOE}, id="declared spillway"),
        pytest.param(False, {}, id="no spillway, D still stored"),
    ],
)
def test_section_stores_d_and_dam_feet(monkeypatch, tmp_path, declared, feet) -> None:
    declare_spillway(monkeypatch, declared)
    model = SimpleNamespace(inputs=make_model(), full_path=str(tmp_path), model_output_name="model")

    descent, _, seeds = build_section(model)

    assert seeds == feet
    assert model.dam_foot_cells == feet
    record = read_descent_sidecar(tmp_path / "model.descent.npz")
    assert record.dam_foot.tolist() == list(feet.values())
    np.testing.assert_array_equal(record.receiver, descent.receiver)


def test_spillway_may_cascade_into_a_feeder() -> None:
    # The forebay spilling into a feeder of the reservoir is a cascade, not a loop.
    receivers = _resolve_spillway_receivers(
        {"cheze": TWO_LAKE_RIVER},
        {"forebay": 5},
        lake_ids=["res", "forebay"],
        cell_centroids=CENTROIDS,
    )

    assert receivers == {"forebay": 2}


@pytest.mark.parametrize(("river", "seeds", "lake_ids"), FEEDER_REFUSALS)
def test_refusals(river, seeds, lake_ids) -> None:
    with pytest.raises(ValueError, match="circulate back into the reservoir"):
        _resolve_spillway_receivers(
            {"cheze": river}, seeds, lake_ids=lake_ids, cell_centroids=CENTROIDS
        )
