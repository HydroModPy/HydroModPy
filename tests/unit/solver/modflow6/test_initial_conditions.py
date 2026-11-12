"""Start heads (m) written to the IC package of a MODFLOW 6 DISV model.

A head rule, a steady start or a cyclic spin-up give the top as a build guess. A solved state
is set as it is and a prior state is written as a binary double record. Constant heads (CHD)
are laid over a prior state.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.initial.state import (
    CyclicSpinupStrategy,
    CyclicStart,
    HeadRule,
    PriorState,
    SolvedState,
    SteadyStart,
)
from hydromodpy.model.initial_config import (
    FlowICBottom,
    FlowICSteadyState,
    FlowICTop,
    FlowInitialConditions,
    initial_state_of,
)
from hydromodpy.results.storage.prior_state import read_final_head
from hydromodpy.solver.modflow6.builders.initial_conditions import build_start_heads
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

TOP_2X3 = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]])  # m


def one_layer_plate():
    """Two rows of three cells, one layer with its bottom at 1 m."""
    return solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=TOP_2X3, botm=np.stack([np.ones_like(TOP_2X3)])
    )


def two_layer_row(top):
    """A row of three cells over two layers (bottoms 5 m and 0 m), and the toy model that reads it."""
    model = toy_model()
    model.nlay = 2
    model.ncpl = 3
    mesh = solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=3,
        top=np.array([top]),
        botm=np.stack([np.full((1, 3), 5.0), np.full((1, 3), 0.0)]),
    )
    return model, mesh


def west_head():
    """A constant head of 50 and 51 m on the west side of the 2 x 3 toy grid (cells 0 and 3)."""
    return BoundaryConditionBundle(
        conditions={"west_side": SimpleNamespace(value=[50.0, 51.0])}, active_ids=("west_side",)
    )


def with_initial(model, initial, **inputs):
    model.inputs = replace(model.inputs, initial=initial, **inputs)
    return model


TOP_GUESSES = [
    pytest.param(
        initial_state_of(FlowInitialConditions(h=FlowICTop(id="h"))), id="typed top condition"
    ),
    pytest.param(
        initial_state_of(FlowInitialConditions(h=FlowICSteadyState(id="h"))), id="steady start"
    ),
    pytest.param(CyclicStart(CyclicSpinupStrategy()), id="cyclic spin-up"),
]


@pytest.mark.parametrize("initial", TOP_GUESSES)
def test_start_heads_guess_the_top(initial) -> None:
    strt = build_start_heads(with_initial(toy_model(), initial), one_layer_plate())

    # DISV: strt has shape (nlay, ncpl).
    assert strt.shape == (1, 6)
    np.testing.assert_allclose(strt[0], TOP_2X3.ravel())


def test_start_heads_from_the_bottom() -> None:
    model = with_initial(
        toy_model(), initial_state_of(FlowInitialConditions(h=FlowICBottom(id="h")))
    )
    deepest_bottom = np.array([[2.0, 3.0, 4.0], [5.0, 6.0, 7.0]])  # m
    mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=TOP_2X3,
        botm=np.stack([np.full((2, 3), 6.0), deepest_bottom]),
    )

    strt = build_start_heads(model, mesh)

    np.testing.assert_allclose(strt[0], deepest_bottom.ravel())


def test_head_rule_on_two_layers() -> None:
    model, mesh = two_layer_row([10.0, 20.0, 30.0])
    with_initial(model, HeadRule("top_offset", 2.0))

    # Every layer starts 2 m under the top.
    np.testing.assert_array_equal(build_start_heads(model, mesh), [[8.0, 18.0, 28.0]] * 2)


STARTS_AS_ARRAY = [
    pytest.param(HeadRule("top"), id="head rule"),
    pytest.param(SteadyStart(), id="steady start"),
    pytest.param(CyclicStart(CyclicSpinupStrategy()), id="cyclic spin-up"),
    pytest.param(SolvedState(head=np.zeros((1, 6)), solver="modflow6"), id="solved state"),
]


@pytest.mark.parametrize("initial", STARTS_AS_ARRAY)
def test_start_heads_as_array(initial) -> None:
    model = with_initial(toy_model(), initial)

    assert isinstance(build_start_heads(model, model.solver_mesh), np.ndarray)


def test_prior_state_is_a_binary_record() -> None:
    prior = PriorState(head=np.zeros((1, 6)), lake_stages={}, path="prior.zarr")
    model = with_initial(toy_model(), prior)

    strt = build_start_heads(model, model.solver_mesh)

    assert set(strt) == {"filename", "binary", "data", "iprn"}
    assert strt["filename"] == f"{model.model_name_mf6}.ic_strt.bin"
    assert strt["binary"] is True
    assert strt["data"].dtype == np.float64
    assert strt["data"].shape == (1, 6)


def test_prior_state_keeps_constant_heads() -> None:
    prior = PriorState(head=np.full((1, 6), 7.0), lake_stages={}, path="prior.zarr")
    model = with_initial(toy_model(), prior, boundaries=west_head())

    strt = build_start_heads(model, model.solver_mesh)["data"]

    np.testing.assert_array_equal(strt, [[50.0, 7.0, 7.0, 50.0, 7.0, 7.0]])


def test_solved_state_is_set_as_it_is() -> None:
    solved = np.arange(6.0).reshape(1, 6)
    model = with_initial(
        toy_model(), SolvedState(head=solved, solver="modflow6"), boundaries=west_head()
    )

    strt = build_start_heads(model, model.solver_mesh)

    np.testing.assert_array_equal(strt, solved)
    strt[0, 0] = -1.0  # the array is the solver's own, the state keeps its head
    assert model.inputs.initial.head[0, 0] == 0.0


def test_prior_state_of_another_size_is_refused(tmp_path) -> None:
    import zarr

    path = str(tmp_path / "prior.zarr")
    zarr.open(path, mode="w")["head"] = np.zeros((1, 2, 3))
    model, _ = two_layer_row([10.0, 20.0, 30.0])
    model.ncpl = 5
    mesh = solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=5,
        top=np.zeros((1, 5)),
        botm=np.stack([np.full((1, 5), -5.0), np.full((1, 5), -10.0)]),
    )
    with_initial(model, PriorState(head=read_final_head(path), lake_stages={}, path=path))

    with pytest.raises(ValueError, match="does not match"):
        build_start_heads(model, mesh)


def test_solved_state_of_another_size_is_refused() -> None:
    model, mesh = two_layer_row([10.0, 20.0, 30.0])
    with_initial(model, SolvedState(head=np.zeros((2, 4)), solver="modflow6"))

    with pytest.raises(ValueError, match="holds 8 value"):
        build_start_heads(model, mesh)
