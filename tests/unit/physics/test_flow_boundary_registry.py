from __future__ import annotations

import pytest

from hydromodpy.physics.flow import (
    FLOW_BOUNDARY_DEFINITIONS,
    SUPPORTED_FLOW_BOUNDARY_IDS,
    Flow,
    FlowConfig,
)
from hydromodpy.physics.flow.boundary_condition_registry import (
    FLOW_BOUNDARY_DEFINITIONS as FLOW_BOUNDARY_DEFINITIONS_2,
)
from hydromodpy.physics.flow.boundary_condition_registry import (
    SIDE_DIRICHLET_BC_IDS_ORDERED,
    BoundaryConditionBundle,
    active_side_dirichlet_boundary_ids,
    boundary_condition_bundle_from_flow,
    boundary_definition,
    supported_boundary_ids_for_backend,
)


def test_boundary_registry_keeps_solver_side_order_and_capabilities() -> None:
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
    assert stream.backend_packages["modflow6"] == "CHD"

    assert "stream" in supported_boundary_ids_for_backend("boussinesq")
    assert "stream" not in supported_boundary_ids_for_backend("modflow_nwt")
    assert SUPPORTED_FLOW_BOUNDARY_IDS == frozenset(FLOW_BOUNDARY_DEFINITIONS)


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
    assert active_side_dirichlet_boundary_ids(flow) == ("west_side", "east_side")
    assert flow.boundary_condition_application_domains == {
        "west_side": "west side",
        "east_side": "east side",
    }


# The lake entry in the flow boundary-condition registry.
#
# A lake is an advanced package (it carries internal stage/storage state), only
# implemented by the modflow6 backend (LAK). This checks that:
#
# * ``lake`` is a canonical flow boundary id;
# * ``supported_boundary_ids_for_backend('modflow6')`` includes it and maps it
#   to the LAK package, while ``boussinesq`` / ``modflow_nwt`` do NOT (declaring a
#   lake there must be detectable as unsupported);
# * the canonical Dirichlet helpers are untouched by the advanced-package family.


def test_lake_is_a_canonical_advanced_package() -> None:
    definition = boundary_definition("lake")
    assert definition is not None
    assert "lake" in SUPPORTED_FLOW_BOUNDARY_IDS
    assert boundary_definition("reservoir") is None
    assert definition.family == "advanced_package"
    assert definition.support_kind == "advanced_package"
    assert definition.application_domain == "top"
    assert definition.supports_forcing is True
    assert definition.backend_packages["modflow6"] == "LAK"


def test_only_modflow6_backend_supports_lakes() -> None:
    modflow6_ids = supported_boundary_ids_for_backend("modflow6")
    assert "lake" in modflow6_ids

    # Negative invariant: the lake is NOT supported by the other backends.
    for backend in ("boussinesq", "modflow_nwt"):
        ids = supported_boundary_ids_for_backend(backend)
        assert "lake" not in ids


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


def test_bundle_flags_lake_as_unsupported_on_boussinesq() -> None:
    bundle = BoundaryConditionBundle(
        conditions={"lake": object()},
        active_ids=("lake",),
    )
    # The lake is a known canonical id, but boussinesq does not support it.
    assert bundle.unknown_active_ids() == ()
    assert bundle.unsupported_active_ids("boussinesq") == ("lake",)
    assert bundle.unsupported_active_ids("modflow6") == ()


def test_registry_ids_match_definition_keys() -> None:
    assert SUPPORTED_FLOW_BOUNDARY_IDS == frozenset(FLOW_BOUNDARY_DEFINITIONS)
