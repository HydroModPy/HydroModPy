"""The contract of the solver port: the members, the attributes, and what ``build`` receives."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from hydromodpy.results.field_registry import FACE_FLOW, FIELD_REGISTRY, all_zarr_paths
from hydromodpy.solver.base import adapter_protocol
from hydromodpy.solver.base.adapter_protocol import (
    OPTIONAL_MEMBERS,
    RERUN_MEMBERS,
    CellLocator,
    OutputAdapter,
    SolverAdapter,
)
from hydromodpy.solver.base.plan import SolverRun


def _members(protocol: object) -> tuple[str, ...]:
    return tuple(
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("_")
    )


def test_solver_adapter_members() -> None:
    assert _members(SolverAdapter) == ("validate", "build", "run", "cleanup", "extract")


def test_optional_members_outside() -> None:
    for name in (*RERUN_MEMBERS, *OPTIONAL_MEMBERS):
        assert not hasattr(SolverAdapter, name), name


def test_cell_locator_members() -> None:
    assert _members(CellLocator) == ("locate_cell", "top_active_layer")


def test_locator_apart_from_adapter() -> None:
    # A transport adapter has no grid to look on.
    assert hasattr(CellLocator, "locate_cell")
    assert not hasattr(SolverAdapter, "locate_cell")


FLOW_BACKENDS = [
    pytest.param("hydromodpy.solver.modflow6.adapter", "Modflow6FlowAdapter", id="modflow6"),
    pytest.param(
        "hydromodpy.solver.modflow_nwt.adapter", "ModflowNwtFlowAdapter", id="modflow nwt"
    ),
    pytest.param("hydromodpy.solver.boussinesq.adapter", "BoussinesqFlowAdapter", id="boussinesq"),
]


@pytest.mark.parametrize(("module", "cls"), FLOW_BACKENDS)
def test_flow_backend_locates_cell(module: str, cls: str) -> None:
    adapter = getattr(importlib.import_module(module), cls)

    assert callable(getattr(adapter, "locate_cell", None))
    assert isinstance(adapter(), CellLocator)


def test_build_arguments() -> None:
    parameters = [one for one in SolverAdapter.build.__annotations__ if one != "return"]
    assert parameters == ["model", "options", "slot", "upstream"]


def test_face_flow_is_a_registry_field() -> None:
    # One name, one place: the stored form of the hand-off lives in the registry.
    assert FACE_FLOW in FIELD_REGISTRY
    assert FACE_FLOW in all_zarr_paths()
    assert not hasattr(adapter_protocol, "HANDOFF_PRODUCTS")


class _Options(BaseModel):
    depth: float = 1.0


class _ShapeAdapter:
    """A backend of the right shape, to see the Protocol is structural."""

    name: ClassVar[str] = "shape"
    process_type: ClassVar[str] = "flow"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset()
    geometry: ClassVar[str] = "cells"
    writes: ClassVar[tuple[str, ...]] = ()
    reads: ClassVar[tuple[str, ...]] = ()
    supports: ClassVar[frozenset[str]] = frozenset()
    options: ClassVar[type[BaseModel] | None] = _Options
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = ()

    def validate(self, model: Any, options: Any, slot: Any) -> None:
        return None

    def build(self, model: Any, options: Any, slot: Any, upstream: Any = ()) -> SolverRun:
        return SolverRun(slot=slot)

    def run(self, solver_run: SolverRun) -> SolverRun:
        return solver_run

    def cleanup(self, solver_run: SolverRun) -> None:
        return None

    def extract(self, solver_run: SolverRun, store: Any, retention: Any) -> None:
        return None


def test_protocol_is_structural() -> None:
    assert isinstance(_ShapeAdapter(), SolverAdapter)


def test_extractor_protocol() -> None:
    class _Reader:
        process_type: ClassVar[str] = "flow"
        solver_name: ClassVar[str] = "shape"

        def extract(self, solver_run: SolverRun, store: Any, retention: Any) -> None:
            return None

    assert isinstance(_Reader(), OutputAdapter)
