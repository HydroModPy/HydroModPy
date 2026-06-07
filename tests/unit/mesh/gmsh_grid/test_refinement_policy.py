from __future__ import annotations

from shapely.geometry import LineString

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._refinement_policy import (
    RefinementCurveCandidate,
    apply_local_refinement_policy,
    detect_refinement_hotspots,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingRefinementFamilySettings,
    ZoneMeshingRefinementGridSettings,
    ZoneMeshingRefinementHotspotSettings,
    ZoneMeshingRefinementPolicy,
    parse_zone_meshing_settings,
)


def _build_policy(
    *,
    max_curve_count: int = 10,
    max_family_count: int = 2,
    min_gap: float = 0.01,
    max_node_degree: int = 4,
    mode: str = "family_priority_local_budget",
    grid_cell_size: float | None = None,
    neighborhood_rings: int = 1,
    enable_exact_gap_check: bool = True,
    max_exact_gap_candidates: int = 256,
) -> ZoneMeshingRefinementPolicy:
    return ZoneMeshingRefinementPolicy(
        enabled=True,
        mode=mode,
        hotspot=ZoneMeshingRefinementHotspotSettings(
            radius=2.0,
            max_curve_count=max_curve_count,
            max_family_count=max_family_count,
            min_gap=min_gap,
            max_node_degree=max_node_degree,
            short_segment_length=0.05,
            max_short_segment_count=10,
        ),
        grid=ZoneMeshingRefinementGridSettings(
            cell_size=grid_cell_size,
            neighborhood_rings=neighborhood_rings,
            enable_exact_gap_check=enable_exact_gap_check,
            max_exact_gap_candidates=max_exact_gap_candidates,
        ),
        families={
            "river": ZoneMeshingRefinementFamilySettings(
                enabled=True,
                priority=300,
                interface_size=None,
                interface_distance=None,
                interface_sampling=None,
            ),
            "geology_interface": ZoneMeshingRefinementFamilySettings(
                enabled=True,
                priority=200,
                interface_size=None,
                interface_distance=None,
                interface_sampling=None,
            ),
            "watershed_boundary": ZoneMeshingRefinementFamilySettings(
                enabled=True,
                priority=100,
                interface_size=None,
                interface_distance=None,
                interface_sampling=None,
            ),
        },
    )


def _candidate(
    curve_tag: int,
    family: str,
    line: LineString,
    priority: int,
) -> RefinementCurveCandidate:
    return RefinementCurveCandidate(
        curve_tag=curve_tag,
        group_name=family,
        family=family,
        geometry=line,
        priority=priority,
        interface_size=1.0,
        interface_distance=2.0,
        interface_sampling=24,
    )


def test_parse_zone_meshing_settings_accepts_local_refinement_policy() -> None:
    settings = parse_zone_meshing_settings(
        {
            "algorithm": "delaunay",
            "global_size": 100.0,
            "min_size": 50.0,
            "max_size": 150.0,
            "refine_interfaces": True,
            "interface_size": 40.0,
            "interface_distance": 120.0,
            "interface_sampling": 64,
            "refinement_policy": {
                "enabled": True,
                "mode": "family_priority_local_budget",
                "hotspot": {
                    "max_curve_count": 25,
                    "max_family_count": 2,
                    "min_gap": 10.0,
                    "max_node_degree": 4,
                    "short_segment_length": 5.0,
                    "max_short_segment_count": 8,
                },
                "families": {
                    "river": {"priority": 300},
                    "geology_interface": {"priority": 200},
                    "watershed_boundary": {"priority": 100},
                },
            },
        }
    )

    assert settings.refinement_policy is not None
    assert settings.refinement_policy.enabled is True
    assert settings.refinement_policy.hotspot.radius == 120.0
    assert settings.refinement_policy.sorted_families_by_priority() == [
        "river",
        "geology_interface",
        "watershed_boundary",
    ]
    assert settings.refinement_policy.grid.cell_size is None


def test_parse_zone_meshing_settings_accepts_grid_local_budget_policy() -> None:
    settings = parse_zone_meshing_settings(
        {
            "algorithm": "delaunay",
            "global_size": 100.0,
            "min_size": 40.0,
            "max_size": 150.0,
            "refine_interfaces": True,
            "interface_size": 25.0,
            "interface_distance": 120.0,
            "interface_sampling": 64,
            "refinement_policy": {
                "enabled": True,
                "mode": "grid_local_budget",
                "grid": {
                    "neighborhood_rings": 2,
                    "enable_exact_gap_check": False,
                    "max_exact_gap_candidates": 64,
                },
                "families": {
                    "river": {"priority": 300},
                    "geology_interface": {"priority": 200},
                    "watershed_boundary": {"priority": 100},
                },
            },
        }
    )

    assert settings.refinement_policy is not None
    assert settings.refinement_policy.mode == "grid_local_budget"
    assert settings.refinement_policy.grid.cell_size == 60.0
    assert settings.refinement_policy.grid.neighborhood_rings == 2
    assert settings.refinement_policy.grid.enable_exact_gap_check is False
    assert settings.refinement_policy.grid.max_exact_gap_candidates == 64


def test_detect_refinement_hotspots_flags_mixed_high_degree_nodes() -> None:
    policy = _build_policy(max_node_degree=3, min_gap=0.0)
    candidates = (
        _candidate(1, "river", LineString([(0.0, 0.0), (1.0, 0.0)]), 300),
        _candidate(2, "river", LineString([(0.0, 0.0), (-1.0, 0.0)]), 300),
        _candidate(3, "watershed_boundary", LineString([(0.0, 0.0), (0.0, 1.0)]), 100),
        _candidate(4, "watershed_boundary", LineString([(0.0, 0.0), (0.0, -1.0)]), 100),
    )

    hotspots = detect_refinement_hotspots(candidates=candidates, policy=policy)

    assert hotspots
    assert hotspots[0].reason == "mixed_node_degree"
    assert hotspots[0].family_counts["river"] == 2
    assert hotspots[0].family_counts["watershed_boundary"] == 2


def test_apply_local_refinement_policy_demotes_watershed_before_geology() -> None:
    policy = _build_policy(max_family_count=2, min_gap=0.01, max_node_degree=3)
    candidates = (
        _candidate(1, "river", LineString([(0.0, 0.0), (1.0, 0.0)]), 300),
        _candidate(2, "river", LineString([(0.0, 0.0), (-1.0, 0.0)]), 300),
        _candidate(3, "geology_interface", LineString([(0.6, 0.0), (0.6, 1.0)]), 200),
        _candidate(4, "geology_interface", LineString([(-0.6, 0.0), (-0.6, 1.0)]), 200),
        _candidate(5, "watershed_boundary", LineString([(0.0, 0.0), (1.0, 1.0)]), 100),
        _candidate(6, "watershed_boundary", LineString([(0.0, 0.0), (-1.0, 1.0)]), 100),
    )

    result = apply_local_refinement_policy(candidates=candidates, policy=policy)

    assert result.filtered_curve_tags_by_family["watershed_boundary"] == (5, 6)
    assert result.actions
    assert result.actions[0].family == "watershed_boundary"
    assert result.actions[0].dropped_curve_tags == (5, 6)


def test_detect_refinement_hotspots_grid_mode_flags_local_curve_density() -> None:
    policy = _build_policy(
        mode="grid_local_budget",
        max_curve_count=3,
        max_family_count=2,
        min_gap=0.0,
        grid_cell_size=1.0,
        neighborhood_rings=1,
        enable_exact_gap_check=False,
    )
    candidates = (
        _candidate(1, "river", LineString([(0.0, 0.0), (0.8, 0.0)]), 300),
        _candidate(2, "river", LineString([(0.0, 0.2), (0.8, 0.2)]), 300),
        _candidate(3, "geology_interface", LineString([(0.2, -0.1), (0.2, 0.9)]), 200),
        _candidate(4, "geology_interface", LineString([(0.5, -0.1), (0.5, 0.9)]), 200),
    )

    hotspots = detect_refinement_hotspots(candidates=candidates, policy=policy)

    assert hotspots
    assert hotspots[0].reason == "local_curve_density"
    assert hotspots[0].curve_count == 4
    assert hotspots[0].family_count == 2


def test_apply_local_refinement_policy_grid_mode_demotes_watershed_before_geology() -> None:
    policy = _build_policy(
        mode="grid_local_budget",
        max_family_count=2,
        min_gap=0.01,
        max_node_degree=3,
        grid_cell_size=1.0,
        neighborhood_rings=1,
        enable_exact_gap_check=False,
    )
    candidates = (
        _candidate(1, "river", LineString([(0.0, 0.0), (0.8, 0.0)]), 300),
        _candidate(2, "river", LineString([(0.0, 0.2), (0.8, 0.2)]), 300),
        _candidate(3, "geology_interface", LineString([(0.2, -0.1), (0.2, 0.9)]), 200),
        _candidate(4, "geology_interface", LineString([(0.5, -0.1), (0.5, 0.9)]), 200),
        _candidate(5, "watershed_boundary", LineString([(0.0, 0.0), (0.8, 0.8)]), 100),
        _candidate(6, "watershed_boundary", LineString([(0.0, 0.8), (0.8, 0.0)]), 100),
    )

    result = apply_local_refinement_policy(candidates=candidates, policy=policy)

    assert result.filtered_curve_tags_by_family["watershed_boundary"] == (5, 6)
    assert result.actions
    assert result.actions[0].family == "watershed_boundary"
