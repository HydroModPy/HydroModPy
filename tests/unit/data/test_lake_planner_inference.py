"""DataPlanner: activate the consumed lake families from flow.active_bc.

Guards that ``flow.active_bc`` containing ``lake`` (or ``reservoir``) infers the
lake families the model actually consumes (geometry + abacus build the LAK
package, inflow + withdrawal feed its forcings) with a traceable reason, that
families without a consumer (bathymetry / levels / outflow) are NOT auto-inferred
so the catalog never dead-loads, and - crucially - that a config WITHOUT a lake
boundary does NOT infer any of them.
"""

from __future__ import annotations

from hydromodpy.data.managers.config_schema import DataManagersConfig
from hydromodpy.data.managers.planner import DataPlanner

_CONSUMED_LAKE_FAMILIES = ("lake_geometry", "lake_abacus", "lake_inflow", "lake_withdrawal")
_UNCONSUMED_LAKE_FAMILIES = ("lake_bathymetry", "lake_levels", "lake_outflow")


def _empty_config() -> DataManagersConfig:
    return DataManagersConfig.model_validate({"types": []})


def test_lake_boundary_infers_the_consumed_families() -> None:
    plan = DataPlanner().build(_empty_config(), flow_active_bc=["lake"])
    for family in _CONSUMED_LAKE_FAMILIES:
        assert family in plan.inferred_types
        reasons = plan.reasons_by_type[family]
        assert any("lake" in r for r in reasons)


def test_unconsumed_lake_families_are_not_auto_inferred() -> None:
    # bathymetry / levels / outflow have no consumer yet; auto-inferring them
    # would persist data nothing reads, the dead-load the review flagged.
    plan = DataPlanner().build(_empty_config(), flow_active_bc=["lake"])
    assert not any(family in plan.inferred_types for family in _UNCONSUMED_LAKE_FAMILIES)


def test_reservoir_token_also_infers_families() -> None:
    plan = DataPlanner().build(_empty_config(), flow_active_bc=["reservoir"])
    assert set(_CONSUMED_LAKE_FAMILIES).issubset(set(plan.inferred_types))
    assert all(
        any("reservoir" in r for r in plan.reasons_by_type[family])
        for family in _CONSUMED_LAKE_FAMILIES
    )


def test_non_lake_boundary_does_not_infer_lake_families() -> None:
    plan = DataPlanner().build(_empty_config(), flow_active_bc=["stream", "ocean"])
    everything = (*_CONSUMED_LAKE_FAMILIES, *_UNCONSUMED_LAKE_FAMILIES)
    assert not any(family in plan.inferred_types for family in everything)


def test_explicit_lake_family_is_not_re_inferred() -> None:
    cfg = DataManagersConfig.model_validate({"types": ["lake_abacus"]})
    plan = DataPlanner().build(cfg, flow_active_bc=["lake"])
    # Already explicit -> stays out of the inferred set.
    assert "lake_abacus" not in plan.inferred_types
    # The other consumed families remain inferred.
    assert "lake_geometry" in plan.inferred_types
    assert "lake_inflow" in plan.inferred_types
