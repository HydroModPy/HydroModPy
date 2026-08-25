"""The lake / reservoir entries in the flow boundary-condition registry.

A lake is an advanced package (it carries internal stage/storage state), only
implemented by the modflow6 backend (LAK). This checks that:

* ``lake`` and ``reservoir`` are canonical flow boundary ids;
* ``supported_boundary_ids_for_backend('modflow6')`` includes them and maps them
  to the LAK package, while ``boussinesq`` / ``modflow_nwt`` do NOT (declaring a
  lake there must be detectable as unsupported);
* the canonical Dirichlet helpers are untouched by the advanced-package family.
"""

from __future__ import annotations

from hydromodpy.physics.flow import (
    FLOW_BOUNDARY_DEFINITIONS,
    SUPPORTED_FLOW_BOUNDARY_IDS,
)
from hydromodpy.physics.flow.boundary_condition_registry import (
    BoundaryConditionBundle,
    boundary_definition,
    canonical_dirichlet_boundary_ids,
    supported_boundary_ids_for_backend,
)


def test_lake_and_reservoir_are_canonical_advanced_packages() -> None:
    for bc_id in ("lake", "reservoir"):
        definition = boundary_definition(bc_id)
        assert definition is not None
        assert bc_id in SUPPORTED_FLOW_BOUNDARY_IDS
        assert definition.family == "advanced_package"
        assert definition.support_kind == "advanced_package"
        assert definition.application_domain == "top"
        assert definition.supports_forcing is True
        assert definition.backend_packages["modflow6"] == "LAK"
        assert definition.package_for_backend("modflow6") == "LAK"


def test_only_modflow6_backend_supports_lakes() -> None:
    modflow6_ids = supported_boundary_ids_for_backend("modflow6")
    assert "lake" in modflow6_ids
    assert "reservoir" in modflow6_ids

    # Negative invariant: the lake is NOT supported by the other backends.
    for backend in ("boussinesq", "modflow_nwt"):
        ids = supported_boundary_ids_for_backend(backend)
        assert "lake" not in ids
        assert "reservoir" not in ids


def test_advanced_package_does_not_leak_into_dirichlet_helpers() -> None:
    # The canonical Dirichlet ids must stay exactly the side/stream/ocean set.
    dirichlet = canonical_dirichlet_boundary_ids()
    assert "lake" not in dirichlet
    assert "reservoir" not in dirichlet
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
