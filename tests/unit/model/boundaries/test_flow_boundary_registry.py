from __future__ import annotations

import typing

import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import (
    FLOW_BC_IDS,
    FLOW_BC_KINDS,
    FLOW_BOUNDARY_DEFINITIONS,
    SIDE_DIRICHLET_BC_IDS_ORDERED,
    SUPPORTED_FLOW_BOUNDARY_IDS,
    BoundaryConditionBundle,
    FlowBcId,
    boundary_condition_bundle_from_flow,
    boundary_definition,
)
from hydromodpy.model.boundaries.boundary_conditions import BoundaryKind, DirichletBC, DrainBC
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig

# Which backend builds which boundary is said by its ``supports`` and held for
# every backend by tests/contract/test_solver_backend_contract.py. The table here
# names no backend.


def test_boundary_registry_keeps_solver_side_order() -> None:
    assert SIDE_DIRICHLET_BC_IDS_ORDERED == (
        "west_side",
        "east_side",
        "north_side",
        "south_side",
    )

    stream = boundary_definition("stream")
    assert stream is not None
    assert stream.default_type == "dirichlet"
    assert stream.support_kind == "stream"
    assert SUPPORTED_FLOW_BOUNDARY_IDS == frozenset(FLOW_BOUNDARY_DEFINITIONS)


def test_flow_bc_takes_the_seven_ids_that_are_not_an_advanced_package() -> None:
    assert FLOW_BC_IDS == (
        "west_side",
        "east_side",
        "north_side",
        "south_side",
        "stream",
        "ocean",
        "drainage",
    )
    assert typing.get_args(FlowBcId) == FLOW_BC_IDS


def test_the_kinds_of_flow_bc_come_from_the_table_and_name_the_payload_classes() -> None:
    """The tags of the two payload classes are their identity in the union, held equal here."""
    assert FLOW_BC_KINDS == ("dirichlet", "drain")
    assert typing.get_args(BoundaryKind) == FLOW_BC_KINDS
    tags = {
        typing.get_args(cls.model_fields["kind"].annotation)[0] for cls in (DirichletBC, DrainBC)
    }
    assert tags == set(FLOW_BC_KINDS)


@pytest.mark.parametrize(
    ("bc_id", "declared_at"),
    [
        ("west_side", "flow.bc.west_side"),
        ("drainage", "flow.bc.drainage"),
        ("lake", "flow.sinks_sources.lakes"),
        ("sfr", "flow.sinks_sources.sfr"),
    ],
)
def test_each_boundary_says_which_table_declares_it(bc_id: str, declared_at: str) -> None:
    assert FLOW_BOUNDARY_DEFINITIONS[bc_id].declared_at == declared_at


def test_boundary_bundle_orders_the_active_side_ids() -> None:
    bundle = BoundaryConditionBundle(
        conditions={"west_side": object()},
        active_ids=("west_side", "drainage"),
    )

    assert bundle.is_active("west_side")
    assert bundle.active_side_dirichlet_ids() == ("west_side",)
    assert not bundle.is_active("east_side")


def test_flow_builds_boundary_bundle_from_config() -> None:
    cfg = FlowConfig(
        bc={
            "west_side": {"kind": "dirichlet", "value": "10 m"},
            "east_side": {"kind": "dirichlet", "value": "8 m"},
        },
    )

    flow = Flow(cfg)
    bundle = boundary_condition_bundle_from_flow(flow)

    assert bundle is flow.boundary_condition_bundle
    assert bundle.active_side_dirichlet_ids() == ("west_side", "east_side")
    assert {
        bc_id: condition.application_domain for bc_id, condition in flow.boundary_conditions.items()
    } == {"west_side": "west side", "east_side": "east side"}


def test_the_bundle_is_rebuilt_when_the_flow_s_active_ids_change() -> None:
    flow = Flow(FlowConfig(bc={"west_side": {"kind": "dirichlet", "value": "10 m"}}))
    flow.active_bc = []

    bundle = boundary_condition_bundle_from_flow(flow)

    assert bundle is not flow.boundary_condition_bundle
    assert bundle.active_ids == ()


# The lake entry in the flow boundary-condition registry.
#
# A lake is an advanced package: it carries internal stage and storage state.
# This checks that ``lake`` is a canonical flow boundary id, that a bundle tells
# a backend whose ``supports`` leaves it out, and that the canonical Dirichlet
# helpers are untouched by the advanced-package family.


def test_lake_is_a_canonical_advanced_package() -> None:
    definition = boundary_definition("lake")
    assert definition is not None
    assert "lake" in SUPPORTED_FLOW_BOUNDARY_IDS
    assert boundary_definition("reservoir") is None
    assert definition.family == "advanced_package"
    assert definition.support_kind == "advanced_package"
    assert definition.application_domain == "top"
    assert definition.supports_forcing is True
    assert "lake" not in FLOW_BC_IDS


def test_advanced_package_does_not_leak_into_dirichlet_helpers() -> None:
    # The canonical Dirichlet ids must stay exactly the side/stream/ocean set.
    dirichlet = [
        bc_id
        for bc_id, definition in FLOW_BOUNDARY_DEFINITIONS.items()
        if definition.family == "dirichlet"
    ]
    assert "lake" not in dirichlet
    assert set(dirichlet) == {
        "west_side",
        "east_side",
        "north_side",
        "south_side",
        "stream",
        "ocean",
    }


def test_bundle_flags_a_lake_the_supports_leave_out() -> None:
    bundle = BoundaryConditionBundle(
        conditions={"lake": object()},
        active_ids=("lake",),
    )
    # The lake is a known canonical id; a backend without it in supports does not build it.
    assert bundle.unknown_active_ids() == ()
    assert bundle.active_ids_outside(frozenset({"drainage", "west_side"})) == ("lake",)
    assert bundle.active_ids_outside(frozenset({"drainage", "lake"})) == ()


def test_registry_ids_match_definition_keys() -> None:
    assert SUPPORTED_FLOW_BOUNDARY_IDS == frozenset(FLOW_BOUNDARY_DEFINITIONS)
