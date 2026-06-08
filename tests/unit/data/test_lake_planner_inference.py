"""DataPlanner: activate the lake family from flow.active_bc.

Guards that ``flow.active_bc`` containing ``lake`` (or
``reservoir``) infers the four lake data families with a traceable reason,
and - crucially - that a config WITHOUT a lake boundary does NOT infer them.
"""

from __future__ import annotations

from hydromodpy.data.data_managers_config import DataManagersConfig
from hydromodpy.data.planner import DataPlanner

_LAKE_FAMILIES = ("lake_geometry", "lake_bathymetry", "lake_abacus", "lake_levels")


def _empty_config() -> DataManagersConfig:
    return DataManagersConfig.model_validate({"types": []})


def test_lake_boundary_infers_all_four_families() -> None:
    plan = DataPlanner().build(_empty_config(), flow_active_bc=["lake"])
    for family in _LAKE_FAMILIES:
        assert family in plan.inferred_types
        reasons = plan.reasons_by_type[family]
        assert any("lake" in r for r in reasons)


def test_reservoir_token_also_infers_families() -> None:
    plan = DataPlanner().build(_empty_config(), flow_active_bc=["reservoir"])
    assert set(_LAKE_FAMILIES).issubset(set(plan.inferred_types))
    assert all(
        any("reservoir" in r for r in plan.reasons_by_type[family]) for family in _LAKE_FAMILIES
    )


def test_non_lake_boundary_does_not_infer_lake_families() -> None:
    plan = DataPlanner().build(_empty_config(), flow_active_bc=["stream", "ocean"])
    assert not any(family in plan.inferred_types for family in _LAKE_FAMILIES)


def test_explicit_lake_family_is_not_re_inferred() -> None:
    cfg = DataManagersConfig.model_validate({"types": ["lake_abacus"]})
    plan = DataPlanner().build(cfg, flow_active_bc=["lake"])
    # Already explicit -> stays out of the inferred set.
    assert "lake_abacus" not in plan.inferred_types
    # The other three remain inferred.
    assert "lake_geometry" in plan.inferred_types
