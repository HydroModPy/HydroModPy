from __future__ import annotations

import pytest

from hydromodpy.physics.flow import (
    FLOW_BOUNDARY_DEFINITIONS,
    SUPPORTED_FLOW_BOUNDARY_IDS,
    Flow,
    FlowConfig,
)
from hydromodpy.physics.flow.boundary_condition_registry import (
    BoundaryConditionBundle,
    active_side_dirichlet_boundary_ids,
    boundary_condition_bundle_from_flow,
    boundary_definition,
    side_dirichlet_boundary_ids,
    supported_boundary_ids_for_backend,
)


def test_boundary_registry_keeps_solver_side_order_and_capabilities() -> None:
    assert side_dirichlet_boundary_ids() == (
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
    assert stream.package_for_backend("modflow6") == "CHD"

    assert "stream" in supported_boundary_ids_for_backend("boussinesq")
    assert "stream" not in supported_boundary_ids_for_backend("modflow_nwt")
    assert SUPPORTED_FLOW_BOUNDARY_IDS == frozenset(FLOW_BOUNDARY_DEFINITIONS)


def test_boundary_bundle_exposes_active_defined_and_missing_ids() -> None:
    bundle = BoundaryConditionBundle(
        conditions={"west_side": object()},
        active_ids=("west_side", "drainage"),
    )

    assert bundle.is_active("west_side")
    assert bundle.get_active("west_side") is bundle.conditions["west_side"]
    assert bundle.get_active("east_side") is None
    assert bundle.missing_active_ids() == ("drainage",)
    assert bundle.active_side_dirichlet_ids() == ("west_side",)
    assert [
        (bc_id, definition.backend_packages["modflow6"])
        for bc_id, _, definition in bundle.active_definition_items(
            family="dirichlet",
            backend="modflow6",
        )
    ] == [("west_side", "CHD")]

    with pytest.raises(ValueError, match="Active boundary 'drainage' is missing"):
        bundle.require_active("drainage")


def test_flow_builds_boundary_bundle_from_config() -> None:
    cfg = FlowConfig(
        active_bc=["east_side", "west_side"],
        bc={
            "dirichlet": {
                "west_side": {"value": "10 m"},
                "east_side": {"value": "8 m"},
            }
        },
    )

    flow = Flow(cfg)
    bundle = boundary_condition_bundle_from_flow(flow)

    assert bundle is flow.boundary_condition_bundle
    assert bundle.active_side_dirichlet_ids() == ("west_side", "east_side")
    assert active_side_dirichlet_boundary_ids(flow) == ("west_side", "east_side")
    assert bundle.missing_active_ids() == ()
    assert flow.boundary_condition_application_domains == {
        "west_side": "west side",
        "east_side": "east side",
    }
