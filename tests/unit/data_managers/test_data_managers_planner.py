"""Unit tests for data-manager planning (explicit + inferred activation)."""

import pytest

from hydromodpy.data import (
    DataManagersConfig,
    DataPlanner,
)


def test_planner_infers_geology_from_domain_zone_ids() -> None:
    cfg = DataManagersConfig(types=[])

    plan = DataPlanner().build(
        cfg,
        domain_zone_ids=["geology"],
        raw_toml={},
    )

    assert plan.explicit_types == ()
    assert plan.inferred_types == ("geology",)
    assert plan.types == ("geology",)
    assert "domain.zone_ids" in plan.reasons_for("geology")[0]


def test_planner_infers_geology_from_explicit_geology_support_provider() -> None:
    cfg = DataManagersConfig(types=[])

    plan = DataPlanner().build(
        cfg,
        domain_zone_ids=[],
        domain_support_provider_names=["geology"],
        requested_spatial_support_ids=["field_geology"],
        raw_toml={},
    )

    assert plan.inferred_types == ("geology",)
    assert "domain.supports provider='geology'" in plan.reasons_for("geology")[0]


def test_planner_does_not_infer_geology_from_unused_support_provider() -> None:
    cfg = DataManagersConfig(types=[])

    plan = DataPlanner().build(
        cfg,
        domain_zone_ids=[],
        domain_support_provider_names=["geology"],
        requested_spatial_support_ids=[],
        raw_toml={},
    )

    assert plan.inferred_types == ()


def test_planner_does_not_infer_hydrometry_from_unrelated_raw_section() -> None:
    cfg = DataManagersConfig(types=[])

    plan = DataPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={"custom_data_section": {"selection": {"mode": "mask"}}},
    )

    assert plan.explicit_types == ()
    assert plan.inferred_types == ()
    assert plan.types == ()


def test_planner_does_not_duplicate_explicit_hydrometry() -> None:
    cfg = DataManagersConfig(types=["hydrometry"])

    plan = DataPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={},
    )

    assert plan.explicit_types == ("hydrometry",)
    assert plan.inferred_types == ()
    assert plan.types == ("hydrometry",)


def test_planner_infers_hydrography_from_flow_stream_boundary() -> None:
    cfg = DataManagersConfig(types=[])

    plan = DataPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={},
        flow_active_bc=["stream"],
    )

    assert plan.inferred_types == ("hydrography",)
    assert plan.types == ("hydrography",)
    assert "flow.active_bc" in plan.reasons_for("hydrography")[0]


def test_planner_infers_oceanic_from_flow_ocean_boundary() -> None:
    cfg = DataManagersConfig(types=[])

    plan = DataPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={},
        flow_active_bc=["ocean"],
    )

    assert plan.inferred_types == ("oceanic",)
    assert plan.types == ("oceanic",)
    assert "flow.active_bc" in plan.reasons_for("oceanic")[0]


def test_planner_does_not_duplicate_explicit_oceanic() -> None:
    cfg = DataManagersConfig(types=["oceanic"])

    plan = DataPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={},
        flow_active_bc=["ocean"],
    )

    assert plan.explicit_types == ("oceanic",)
    assert plan.inferred_types == ()
    assert plan.types == ("oceanic",)


def test_planner_strict_mode_raises_when_inference_has_missing_section() -> None:
    cfg = DataManagersConfig(types=[], inference_mode="strict")
    with pytest.raises(ValueError, match="inference_mode='strict'"):
        DataPlanner().build(
            cfg,
            domain_zone_ids=[],
            raw_toml={},
            flow_active_bc=["stream"],
        )


def test_planner_warn_mode_allows_inference_without_section() -> None:
    cfg = DataManagersConfig(types=[], inference_mode="warn")
    plan = DataPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={},
        flow_active_bc=["stream"],
    )

    assert "hydrography" in plan.types


def test_with_resolved_types_injects_default_geology_section() -> None:
    cfg = DataManagersConfig(types=[])
    resolved_cfg = cfg.with_resolved_types(["geology"])

    assert resolved_cfg.types == ["geology"]
    assert resolved_cfg.geology is not None


def test_plan_types_merge_explicit_and_inferred_deterministically() -> None:
    cfg = DataManagersConfig(types=["oceanic", "hydrometry"])
    plan = DataPlanner().build(
        cfg,
        domain_zone_ids=["geology"],
        raw_toml={},
        flow_active_bc=["stream", "ocean"],
    )

    assert plan.types == ("oceanic", "hydrometry", "geology", "hydrography")
