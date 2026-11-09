"""The contract of the solver port: the members, the attributes, and what ``build`` receives."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from hydromodpy.results.field_registry import all_zarr_paths
from hydromodpy.solver.base.adapter_protocol import (
    HANDOFF_PRODUCTS,
    NULLABLE_ATTRIBUTES,
    OPTIONAL_MEMBERS,
    RERUN_MEMBERS,
    CellLocator,
    OutputAdapter,
    SolverAdapter,
    extractor_members,
    solver_members,
)
from hydromodpy.solver.base.plan import RunSlot, SolverRun


def _members(protocol: object) -> tuple[str, ...]:
    return tuple(
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("_")
    )


def test_the_port_has_the_five_members_the_runner_calls() -> None:
    assert _members(SolverAdapter) == ("validate", "build", "run", "cleanup", "extract")


def test_the_member_list_of_a_backend_holds_the_attributes_then_the_methods() -> None:
    """The attributes of the port, minus the two nullable, then the five members."""
    attributes = (
        "name",
        "process_type",
        "accepted_meshes",
        "geometry",
        "writes",
        "reads",
        "supports",
        "category",
        "mutable",
        "requires",
    )
    assert solver_members() == (*attributes, "validate", "build", "run", "cleanup", "extract")


def test_the_two_nullable_attributes_are_named_and_turn_none_not_absent() -> None:
    """A backend declares ``options`` and ``native_step`` even when it binds them to None."""
    assert NULLABLE_ATTRIBUTES == ("options", "native_step")
    assert len(set(solver_members()) | set(NULLABLE_ATTRIBUTES)) == 17


def test_the_extractor_port_has_two_attributes_and_the_extract_member() -> None:
    assert extractor_members() == ("process_type", "solver_name", "extract")


def test_the_optional_members_are_listed_and_not_in_the_body_of_the_protocol() -> None:
    for name in (*RERUN_MEMBERS, *OPTIONAL_MEMBERS):
        assert not hasattr(SolverAdapter, name), name


def test_a_flow_locates_a_cell_and_a_transport_has_no_grid_of_its_own() -> None:
    assert _members(CellLocator) == ("locate_cell", "top_active_layer")


def test_build_takes_the_model_the_options_the_slot_and_the_upstream_runs() -> None:
    parameters = [one for one in SolverAdapter.build.__annotations__ if one != "return"]
    assert parameters == ["model", "options", "slot", "upstream"]


def test_hand_off_names_the_products_a_flow_hands_a_transport() -> None:
    assert HANDOFF_PRODUCTS == ("face_flow",)


@pytest.mark.parametrize("product", HANDOFF_PRODUCTS)
def test_no_hand_off_product_is_known_to_the_field_registry(product: str) -> None:
    """One name, one place: the product leaves the tuple when the registry takes it."""
    assert product not in all_zarr_paths()


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


def test_the_built_run_of_a_shape_adapter_is_neither_written_nor_solved(tmp_path: Path) -> None:
    built = _ShapeAdapter().build(object(), _Options(), RunSlot(tmp_path, "island"), ())

    assert (built.written, built.solved) == (False, False)


def test_the_port_of_the_extractor_answers_its_protocol() -> None:
    class _Reader:
        process_type: ClassVar[str] = "flow"
        solver_name: ClassVar[str] = "shape"

        def extract(self, solver_run: SolverRun, store: Any, retention: Any) -> None:
            return None

    assert isinstance(_Reader(), OutputAdapter)
