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


def test_modflow6_builds_start_heads_from_typed_initial_conditions() -> None:
    model = toy_model()
    model.inputs = replace(
        model.inputs, initial=initial_state_of(FlowInitialConditions(h=FlowICTop(id="h")))
    )
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=float)
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )

    strt = build_start_heads(model, solver_mesh)

    # DISV: strt shape is (nlay, ncpl)
    assert strt.shape == (1, 6)
    assert np.allclose(strt[0], top.ravel())


def test_modflow6_steady_state_initial_condition_uses_top_as_build_guess() -> None:
    model = toy_model()
    initial = initial_state_of(FlowInitialConditions(h=FlowICSteadyState(id="h")))
    assert isinstance(initial, SteadyStart)
    model.inputs = replace(model.inputs, initial=initial)
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.ones_like(top)
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )

    strt = build_start_heads(model, solver_mesh)

    assert strt.shape == (1, 6)
    assert np.allclose(strt[0], top.ravel())


def test_modflow6_cyclic_spinup_initial_condition_uses_top_as_build_guess() -> None:
    model = toy_model()
    model.inputs = replace(model.inputs, initial=CyclicStart(CyclicSpinupStrategy()))
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=top, botm=np.stack([np.ones_like(top)])
    )

    assert np.allclose(build_start_heads(model, solver_mesh)[0], top.ravel())


def test_modflow6_accepts_bottom_initial_condition_name() -> None:
    model = toy_model()
    model.inputs = replace(
        model.inputs, initial=initial_state_of(FlowInitialConditions(h=FlowICBottom(id="h")))
    )
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_layer1 = np.array([[6.0, 6.0, 6.0], [6.0, 6.0, 6.0]], dtype=float)
    botm_layer2 = np.array([[2.0, 3.0, 4.0], [5.0, 6.0, 7.0]], dtype=float)
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_layer1, botm_layer2]),
    )

    strt = build_start_heads(model, solver_mesh)

    # DISV: strt shape is (nlay, ncpl) - all layers start at deepest botm
    assert np.allclose(strt[0], botm_layer2.ravel())


def _two_layer_row(top: list[float]):
    """A row of three cells over two layers, and the toy model that reads it."""
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


def _prior_zarr(tmp_path, head: np.ndarray) -> str:
    import zarr

    prior = tmp_path / "prior.zarr"
    zarr.open(str(prior), mode="w")["head"] = head
    return str(prior)


def test_a_prior_state_of_another_cell_count_is_refused(tmp_path) -> None:
    """A cell-count mismatch raises (rather than silently reindexing)."""
    path = _prior_zarr(tmp_path, np.zeros((1, 2, 3)))
    model, _ = _two_layer_row([10.0, 20.0, 30.0])
    model.ncpl = 5
    mesh = solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=5,
        top=np.zeros((1, 5)),
        botm=np.stack([np.full((1, 5), -5.0), np.full((1, 5), -10.0)]),
    )
    model.inputs = replace(
        model.inputs, initial=PriorState(head=read_final_head(path), lake_stages={}, path=path)
    )

    with pytest.raises(ValueError, match="does not match"):
        build_start_heads(model, mesh)


STARTS: tuple[tuple[str, object, bool], ...] = (
    ("a head rule", HeadRule("top"), False),
    ("a steady start", SteadyStart(), False),
    ("a cyclic start", CyclicStart(CyclicSpinupStrategy()), False),
    ("a solved state", SolvedState(head=np.zeros((1, 6)), solver="modflow6"), False),
    ("a prior state", PriorState(head=np.zeros((1, 6)), lake_stages={}, path="prior.zarr"), True),
)


@pytest.mark.parametrize(("case", "initial", "binary"), STARTS, ids=[c for c, *_ in STARTS])
def test_only_a_prior_state_is_written_as_a_binary_double_precision_record(
    case: str, initial: object, binary: bool
) -> None:
    del case
    model = toy_model()
    model.inputs = replace(model.inputs, initial=initial)

    strt = build_start_heads(model, model.solver_mesh)

    if not binary:
        assert isinstance(strt, np.ndarray)
        return
    assert set(strt) == {"filename", "binary", "data", "iprn"}
    assert strt["filename"] == f"{model.model_name_mf6}.ic_strt.bin"
    assert strt["binary"] is True
    assert strt["data"].dtype == np.float64
    assert strt["data"].shape == (1, 6)


def _disv_head_after_writing(tmp_path, strt, *, n_cells: int) -> np.ndarray:
    """Write a two-layer vertex grid with ``strt`` as the IC package, read the package back."""
    import flopy

    vertices, cell2d = [], []
    for cell in range(n_cells):
        x = 10.0 * cell
        corners = [(x, 0.0), (x, 10.0), (x + 10.0, 10.0), (x + 10.0, 0.0)]
        first = len(vertices)
        vertices += [[first + k, cx, cy] for k, (cx, cy) in enumerate(corners)]
        cell2d.append([cell, x + 5.0, 5.0, 4, first, first + 1, first + 2, first + 3])
    sim = flopy.mf6.MFSimulation(sim_name="s", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="m")
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=2,
        ncpl=n_cells,
        nvert=len(vertices),
        top=20.0,
        botm=[10.0, 0.0],
        vertices=vertices,
        cell2d=cell2d,
    )
    flopy.mf6.ModflowGwfic(gwf, strt=strt)
    flopy.mf6.ModflowGwfnpf(gwf)
    sim.write_simulation(silent=True)
    loaded = flopy.mf6.MFSimulation.load(sim_ws=str(tmp_path), verbosity_level=0)
    return np.asarray(loaded.get_model("m").ic.strt.get_data())


def _west_head() -> BoundaryConditionBundle:
    return BoundaryConditionBundle(
        conditions={"west_side": SimpleNamespace(value=[50.0, 51.0])}, active_ids=("west_side",)
    )


def test_a_prior_state_keeps_the_constant_heads_over_it() -> None:
    model = toy_model()
    model.inputs = replace(
        model.inputs,
        initial=PriorState(head=np.full((1, 6), 7.0), lake_stages={}, path="prior.zarr"),
        boundaries=_west_head(),
    )

    strt = build_start_heads(model, model.solver_mesh)["data"]

    # The west side of the 2 x 3 grid is cells 0 and 3.
    assert np.array_equal(strt, [[50.0, 7.0, 7.0, 50.0, 7.0, 7.0]])


def test_a_solved_state_is_set_as_it_is_under_no_constant_head() -> None:
    model = toy_model()
    solved = np.arange(6.0).reshape(1, 6)
    model.inputs = replace(
        model.inputs, initial=SolvedState(head=solved, solver="modflow6"), boundaries=_west_head()
    )

    strt = build_start_heads(model, model.solver_mesh)

    assert np.array_equal(strt, solved)
    strt[0, 0] = -1.0  # the array is the solver's own, the state keeps its head
    assert model.inputs.initial.head[0, 0] == 0.0


def test_a_solved_state_of_another_size_is_refused() -> None:
    model, mesh = _two_layer_row([10.0, 20.0, 30.0])
    model.inputs = replace(
        model.inputs, initial=SolvedState(head=np.zeros((2, 4)), solver="modflow6")
    )

    with pytest.raises(ValueError, match="holds 8 value"):
        build_start_heads(model, mesh)


def test_a_head_rule_start_is_the_rule_on_the_grid() -> None:
    model, mesh = _two_layer_row([10.0, 20.0, 30.0])
    model.inputs = replace(model.inputs, initial=HeadRule("top_offset", 2.0))

    assert np.array_equal(build_start_heads(model, mesh), [[8.0, 18.0, 28.0]] * 2)
