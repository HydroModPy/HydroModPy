"""The contract of the solver port: the members, the attributes, and what ``build`` receives."""

from __future__ import annotations

from typing import Any, ClassVar

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


def test_the_port_has_the_five_members_the_runner_calls() -> None:
    assert _members(SolverAdapter) == ("validate", "build", "run", "cleanup", "extract")


def test_the_optional_members_are_listed_and_not_in_the_body_of_the_protocol() -> None:
    for name in (*RERUN_MEMBERS, *OPTIONAL_MEMBERS):
        assert not hasattr(SolverAdapter, name), name


def test_a_flow_locates_a_cell_and_a_transport_has_no_grid_of_its_own() -> None:
    assert _members(CellLocator) == ("locate_cell", "top_active_layer")


def test_build_takes_the_model_the_options_the_slot_and_the_upstream_runs() -> None:
    parameters = [one for one in SolverAdapter.build.__annotations__ if one != "return"]
    assert parameters == ["model", "options", "slot", "upstream"]


def test_the_face_flow_a_transport_reads_is_a_field_of_the_registry() -> None:
    """One name, one place: the stored form of the hand-off lives in the registry."""
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


def test_an_adapter_of_the_right_shape_answers_the_protocol_without_inheriting_it() -> None:
    assert isinstance(_ShapeAdapter(), SolverAdapter)


def test_the_port_of_the_extractor_answers_its_protocol() -> None:
    class _Reader:
        process_type: ClassVar[str] = "flow"
        solver_name: ClassVar[str] = "shape"

        def extract(self, solver_run: SolverRun, store: Any, retention: Any) -> None:
            return None

    assert isinstance(_Reader(), OutputAdapter)
