from __future__ import annotations

import geopandas as gpd
import numpy as np
from pathlib import Path
from types import SimpleNamespace
import pytest
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from hydromodpy.solver.utils.mesh.gmsh_grid import (
    build_zone_conformal_partition_from_dataframe,
    generate_zone_conformal_mesh_from_dataframe,
    load_zone_meshing_domain_payload,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.conformal import (
    _select_partition_face_owner,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing import ZoneLinearConstraint
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.domain import (
    ZoneMeshingDomainConfig,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingRefinementFamilySettings,
    ZoneMeshingRefinementHotspotSettings,
    ZoneMeshingRefinementPolicy,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    CleanedZonePolygonRow,
    clean_zone_rows,
    group_zone_geometries,
)

try:
    import gmsh  # noqa: F401
except (ImportError, OSError) as exc:
    pytest.skip(f"could not import 'gmsh': {exc}", allow_module_level=True)


def _build_split_zones_gdf():
    return gpd.GeoDataFrame(
        {
            "zone_key": ["A", "B"],
            "geometry": [
                Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]),
                Polygon([(1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0)]),
            ],
        },
        crs="EPSG:2154",
    )


def _build_overlapping_zones_gdf():
    return gpd.GeoDataFrame(
        {
            "zone_key": ["A", "B"],
            "priority": [10.0, 1.0],
            "geometry": [
                Polygon([(0.0, 0.0), (1.2, 0.0), (1.2, 1.0), (0.0, 1.0)]),
                Polygon([(0.8, 0.0), (2.0, 0.0), (2.0, 1.0), (0.8, 1.0)]),
            ],
        },
        crs="EPSG:2154",
    )


def test_build_zone_conformal_partition_rejects_overlap_without_priority() -> None:
    gdf = _build_overlapping_zones_gdf().drop(columns=["priority"])
    with pytest.raises(ValueError, match="Overlapping zones detected"):
        build_zone_conformal_partition_from_dataframe(gdf)


def test_build_zone_conformal_partition_resolves_overlap_with_priority() -> None:
    gdf = _build_overlapping_zones_gdf()
    partition = build_zone_conformal_partition_from_dataframe(
        gdf,
        priority_column="priority",
    )

    assert partition.zone_keys == ("A", "B")
    assert partition.n_faces == 2
    assert partition.face_counts_by_zone == {"A": 1, "B": 1}
    assert partition.covered_area == pytest.approx(2.0)


def test_generate_zone_conformal_mesh_respects_zone_interface() -> None:
    gdf = _build_split_zones_gdf()
    output_dir = Path.cwd() / "scratch_tests" / "zone_conformal_meshing"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "split_zone_conformal.msh"

    result = generate_zone_conformal_mesh_from_dataframe(
        gdf,
        output_path=output_path,
        global_size=0.20,
        refine_interfaces=True,
        interface_size=0.08,
        interface_distance=0.30,
        interface_sampling=48,
    )

    assert result.output_path.exists()
    assert result.mesh.n_cells > 0
    assert result.summary["summary_schema_version"] == "zone_conformal_sidecar_v1"
    assert result.summary["zone_keys"] == ["A", "B"]
    assert result.summary["interface_group_count"] == 1
    assert result.summary["physical_groups_summary"]["interface_group_count"] == 1
    assert result.summary["mesh_size_fields"]["interface_refinement"]["enabled"] is True
    assert (
        result.summary["mesh_size_fields"]["interface_refinement"][
            "interface_curve_count"
        ]
        == 1
    )
    assert result.summary["cleaning_diagnostics"]["cleaning_mode"] == "tolerant"
    assert result.summary["cleaning_summary"]["mode"] == "tolerant"
    assert result.summary["qa_checks"]["coverage_within_tolerance"] is True
    assert result.summary["qa_checks"]["has_interface_groups"] is True
    assert any(group.name == "interface::A::B" for group in result.physical_groups)

    interface_x = 1.0
    tol = 1.0e-9
    for cell in result.mesh.cells:
        vertices = np.asarray(cell.vertices, dtype=float)
        has_left_vertex = bool(np.any(vertices[:, 0] < interface_x - tol))
        has_right_vertex = bool(np.any(vertices[:, 0] > interface_x + tol))
        assert not (
            has_left_vertex and has_right_vertex
        ), "One generated cell crosses the zone interface instead of conforming to it"


def test_generate_zone_conformal_mesh_validates_interface_parameters() -> None:
    gdf = _build_split_zones_gdf()
    output_dir = Path.cwd() / "scratch_tests" / "zone_conformal_meshing"
    output_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(
        ValueError,
        match="interface_size must be finite and > 0 when refine_interfaces=true",
    ):
        generate_zone_conformal_mesh_from_dataframe(
            gdf,
            output_path=output_dir / "invalid_missing_interface_size.msh",
            global_size=0.20,
            refine_interfaces=True,
            interface_distance=0.30,
        )

    with pytest.raises(
        ValueError,
        match="interface_distance must be finite and > 0 when refine_interfaces=true",
    ):
        generate_zone_conformal_mesh_from_dataframe(
            gdf,
            output_path=output_dir / "invalid_missing_interface_distance.msh",
            global_size=0.20,
            refine_interfaces=True,
            interface_size=0.08,
        )


def test_generate_zone_conformal_mesh_accepts_river_trace() -> None:
    gdf = _build_split_zones_gdf()
    output_dir = Path.cwd() / "scratch_tests" / "zone_conformal_meshing"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "split_zone_conformal_with_river.msh"

    river_trace = SimpleNamespace(
        lines=(LineString([(0.0, 0.5), (2.0, 0.5)]),)
    )

    result = generate_zone_conformal_mesh_from_dataframe(
        gdf,
        output_path=output_path,
        global_size=0.20,
        refine_interfaces=True,
        interface_size=0.08,
        interface_distance=0.30,
        interface_sampling=48,
        river_trace=river_trace,
    )

    river_summary = dict(result.summary.get("river_trace", {}))
    assert river_summary.get("provided") is True
    assert int(river_summary.get("line_count", 0)) == 1
    assert int(river_summary.get("curve_count", 0)) > 0
    assert any(group.name == "river::trace" for group in result.physical_groups)


def test_generate_zone_conformal_mesh_accepts_generic_linear_constraints() -> None:
    gdf = _build_split_zones_gdf()
    output_dir = Path.cwd() / "scratch_tests" / "zone_conformal_meshing"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "split_zone_conformal_with_watershed_boundary.msh"

    constraint = ZoneLinearConstraint(
        name="watershed::boundary",
        kind="watershed_boundary",
        lines=(LineString([(0.0, 0.5), (2.0, 0.5)]),),
        participates_in_refinement=False,
    )

    result = generate_zone_conformal_mesh_from_dataframe(
        gdf,
        output_path=output_path,
        global_size=0.20,
        refine_interfaces=True,
        interface_size=0.08,
        interface_distance=0.30,
        interface_sampling=48,
        linear_constraints=(constraint,),
    )

    payload = dict(result.summary.get("linear_constraints", {})).get(
        "watershed::boundary", {}
    )
    assert payload.get("provided") is True
    assert int(payload.get("line_count", 0)) == 1
    assert int(payload.get("curve_count", 0)) > 0
    assert payload.get("refined_with_interface_field") is False
    assert any(
        group.name == "watershed::boundary" for group in result.physical_groups
    )


def test_generate_zone_conformal_mesh_reports_local_refinement_policy() -> None:
    gdf = _build_split_zones_gdf()
    output_dir = Path.cwd() / "scratch_tests" / "zone_conformal_meshing"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "split_zone_conformal_with_local_policy.msh"

    river_trace = SimpleNamespace(
        lines=(LineString([(0.0, 0.5), (2.0, 0.5)]),)
    )
    watershed_boundary = ZoneLinearConstraint(
        name="watershed::boundary",
        kind="watershed_boundary",
        lines=(LineString([(0.0, 0.55), (2.0, 0.55)]),),
        participates_in_refinement=True,
    )
    refinement_policy = ZoneMeshingRefinementPolicy(
        enabled=True,
        mode="family_priority_local_budget",
        hotspot=ZoneMeshingRefinementHotspotSettings(
            radius=0.4,
            max_curve_count=20,
            max_family_count=2,
            min_gap=0.06,
            max_node_degree=5,
            short_segment_length=0.02,
            max_short_segment_count=10,
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

    result = generate_zone_conformal_mesh_from_dataframe(
        gdf,
        output_path=output_path,
        global_size=0.20,
        refine_interfaces=True,
        interface_size=0.08,
        interface_distance=0.30,
        interface_sampling=48,
        refinement_policy=refinement_policy,
        river_trace=river_trace,
        linear_constraints=(watershed_boundary,),
    )

    policy_summary = dict(result.summary.get("refinement_policy", {}))
    assert policy_summary["candidate_curve_count"] > 0
    assert policy_summary["active_curve_count"] > 0
    assert policy_summary["family_curve_counts_after"]["river"] >= 0
    family_fields = result.summary["mesh_size_fields"]["interface_refinement"][
        "family_fields"
    ]
    assert "river" in family_fields
    assert "geology_interface" in family_fields
    assert "watershed_boundary" in family_fields
    assert any(
        bool(dict(payload).get("enabled", False))
        for payload in family_fields.values()
    )


def test_load_zone_meshing_domain_payload_supports_inline_polygon() -> None:
    payload = load_zone_meshing_domain_payload(
        ZoneMeshingDomainConfig(
            kind="polygon",
            coordinates=(
                (0.0, 0.0),
                (2.0, 0.0),
                (1.5, 1.0),
                (0.0, 1.0),
            ),
        ),
        target_crs="EPSG:2154",
    )

    assert payload.summary["domain_kind"] == "polygon"
    assert payload.summary["domain_vertex_count"] == 4
    assert payload.summary["domain_area"] == pytest.approx(1.75)
    assert str(payload.gdf.crs) == "EPSG:2154"


def test_build_zone_conformal_partition_reports_tolerant_cleaning_diagnostics() -> None:
    invalid_bowtie = Polygon(
        [(0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    )
    tiny_piece = Polygon(
        [(3.1, 0.0), (3.15, 0.0), (3.15, 0.05), (3.1, 0.05), (3.1, 0.0)]
    )
    big_piece = Polygon([(2.0, 0.0), (3.0, 0.0), (3.0, 1.0), (2.0, 1.0), (2.0, 0.0)])
    gdf = gpd.GeoDataFrame(
        {
            "zone_key": ["A", "B"],
            "geometry": [
                invalid_bowtie,
                MultiPolygon([big_piece, tiny_piece]),
            ],
        },
        crs="EPSG:2154",
    )
    partition = build_zone_conformal_partition_from_dataframe(
        gdf,
        min_polygon_area=0.01,
    )

    diag = dict(partition.cleaning_diagnostics or {})
    assert diag["cleaning_mode"] == "tolerant"
    assert diag["source_feature_count"] == 2
    assert diag["source_invalid_geometry_count"] >= 1
    assert diag["invalid_geometries_repaired_count"] >= 1
    assert diag["polygons_removed_by_area_threshold_count"] >= 1
    assert diag["tolerances"]["min_polygon_area"] == pytest.approx(0.01)


def test_clean_zone_rows_and_grouping_return_typed_internal_contracts() -> None:
    gdf = _build_overlapping_zones_gdf()

    cleaned_rows, diagnostics = clean_zone_rows(
        gdf,
        zone_key_column="zone_key",
        priority_column="priority",
        domain_geometry=None,
        simplify_tolerance=0.0,
        heal_tolerance=0.0,
        min_polygon_area=0.0,
        normalize_zone_key_fn=lambda value: str(value).strip(),
    )
    grouped = group_zone_geometries(cleaned_rows)

    assert cleaned_rows
    assert isinstance(cleaned_rows[0], CleanedZonePolygonRow)
    assert diagnostics.cleaned_zone_polygon_count == len(cleaned_rows)
    assert grouped.priorities == {"A": 10.0, "B": 1.0}
    assert set(grouped.geometries) == {"A", "B"}


def test_select_partition_face_owner_falls_back_to_priority_on_shared_boundary() -> None:
    resolved_geometries = {
        "A": Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]),
        "B": Polygon([(1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0)]),
    }
    part = Polygon(
        [
            (1.0 - 1.0e-7, 0.49),
            (1.0 + 1.0e-7, 0.49),
            (1.0 + 1.0e-7, 0.51),
            (1.0 - 1.0e-7, 0.51),
        ]
    )
    point = Point(1.0, 0.5)

    owner = _select_partition_face_owner(
        part=part,
        point=point,
        resolved_geometries=resolved_geometries,
        grouped_priorities={"A": 10.0, "B": 1.0},
        overlap_tolerance=1.0e-4,
        probe_radius=0.0,
    )

    assert owner == "A"
