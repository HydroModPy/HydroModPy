"""Unit tests for data-manager planning (explicit + inferred activation)."""

import pytest

from hydromodpy.data_managers import (
    DataManagersConfig,
    DataManagersPlanner,
)


def test_planner_infers_geology_from_domain_zone_ids() -> None:
    cfg = DataManagersConfig(types=[])

    plan = DataManagersPlanner().build(
        cfg,
        domain_zone_ids=["geology"],
        raw_toml={},
    )

    assert plan.explicit_types == ()
    assert plan.inferred_types == ("geology",)
    assert plan.types == ("geology",)
    assert "domain.zone_ids" in plan.reasons_for("geology")[0]


def test_planner_infers_hydrometry_from_hydrometry_stations_section() -> None:
    cfg = DataManagersConfig(types=[])

    plan = DataManagersPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={"hydrometry_stations": {"selection": {"mode": "mask"}}},
    )

    assert plan.explicit_types == ()
    assert plan.inferred_types == ("hydrometry",)
    assert plan.types == ("hydrometry",)
    assert "hydrometry_stations" in plan.reasons_for("hydrometry")[0]


def test_planner_does_not_duplicate_explicit_hydrometry() -> None:
    cfg = DataManagersConfig(types=["hydrometry"])

    plan = DataManagersPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={"hydrometry_stations": {}},
    )

    assert plan.explicit_types == ("hydrometry",)
    assert plan.inferred_types == ()
    assert plan.types == ("hydrometry",)


def test_planner_infers_hydrography_from_flow_stream_boundary() -> None:
    cfg = DataManagersConfig(types=[])

    plan = DataManagersPlanner().build(
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

    plan = DataManagersPlanner().build(
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

    plan = DataManagersPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={},
        flow_active_bc=["ocean"],
    )

    assert plan.explicit_types == ("oceanic",)
    assert plan.inferred_types == ()
    assert plan.types == ("oceanic",)


def test_planner_infers_types_from_hooks_file(tmp_path) -> None:
    hooks_path = tmp_path / "hooks.py"
    hooks_path.write_text(
        "from hydromodpy.watershed import Hydrography, Intermittency\n"
        "def on_after_data(result):\n"
        "    result.hydrography = Hydrography()\n"
        "    result.intermittency = Intermittency()\n",
        encoding="utf-8",
    )

    cfg = DataManagersConfig(types=[])
    plan = DataManagersPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={},
        hook_python_path=hooks_path,
    )

    assert "hydrography" in plan.types
    assert "intermittency" in plan.types
    assert "hooks.py markers" in plan.reasons_for("hydrography")[0]


def test_planner_strict_mode_raises_when_hook_infers_missing_section(tmp_path) -> None:
    hooks_path = tmp_path / "hooks.py"
    hooks_path.write_text(
        "def on_after_data(result):\n"
        "    result.hydrography = object()\n",
        encoding="utf-8",
    )

    cfg = DataManagersConfig(types=[], inference_mode="strict")
    with pytest.raises(ValueError, match="inference_mode='strict'"):
        DataManagersPlanner().build(
            cfg,
            domain_zone_ids=[],
            raw_toml={},
            hook_python_path=hooks_path,
        )


def test_planner_warn_mode_allows_hook_inference_without_section(tmp_path) -> None:
    hooks_path = tmp_path / "hooks.py"
    hooks_path.write_text(
        "def on_after_data(result):\n"
        "    result.hydrography = object()\n",
        encoding="utf-8",
    )

    cfg = DataManagersConfig(types=[], inference_mode="warn")
    plan = DataManagersPlanner().build(
        cfg,
        domain_zone_ids=[],
        raw_toml={},
        hook_python_path=hooks_path,
    )

    assert "hydrography" in plan.types


def test_with_resolved_types_injects_default_geology_section() -> None:
    cfg = DataManagersConfig(types=[])
    resolved_cfg = cfg.with_resolved_types(["geology"])

    assert resolved_cfg.types == ["geology"]
    assert resolved_cfg.geology is not None


def test_plan_types_merge_explicit_and_inferred_deterministically() -> None:
    cfg = DataManagersConfig(types=["oceanic"])
    plan = DataManagersPlanner().build(
        cfg,
        domain_zone_ids=["geology"],
        raw_toml={"hydrometry_stations": {"source": {"mode": "api"}}},
        flow_active_bc=["stream", "ocean"],
    )

    assert plan.types == ("oceanic", "geology", "hydrometry", "hydrography")
