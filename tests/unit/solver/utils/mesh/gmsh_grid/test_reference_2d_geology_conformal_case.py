from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import matplotlib
import numpy as np
import pytest
from shapely.geometry import LineString, Polygon, box

matplotlib.use("Agg", force=True)

try:
    import gmsh  # noqa: F401
    _gmsh_available = True
except (ImportError, OSError):
    _gmsh_available = False
_skip_no_gmsh = pytest.mark.skipif(not _gmsh_available, reason="gmsh not available")

import hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.run_case_zone_conformal as conformal_case_module
import hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal as conformal_case_package
import hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning as conformal_planning_module
import hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.plotting as conformal_plotting_module
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal import (
    run_reference_2d_zone_conformal_case_from_toml,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.case_config import (
    _resolve_case_config,
    _resolve_constraint_families,
    _resolve_constraints_mode,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalDomainConfig,
    ZoneConformalGeometryPayload,
    ZoneConformalGeologyConfig,
    ZoneConformalRiversConfig,
    ZoneConformalZoneMeshingConfig,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning import (
    _build_zone_conformal_meshing_inputs,
    _clip_river_trace_to_domain,
    _resolve_river_trace_for_meshing,
)

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "reference_2d_geology_conformal_signature.json"
CASE_TOML = (
    Path(__file__).resolve().parents[6]
    / "hydromodpy"
    / "solver"
    / "utils"
    / "mesh"
    / "gmsh_grid"
    / "cases"
    / "reference_2d_geology_conformal"
    / "case_config_zone_conformal.toml"
)
_CASE_RELATIVE_GEOLOGY_PATH = (
    "../../../../../../../examples/data/geology/GEO1M_brittany.shp"
)
_CASE_RELATIVE_REFERENCE_RASTER_PATH = (
    "../../../cartesian_grid/examples/discretization/demo_top_bretagne_10km.tif"
)


def test_partition_overlay_gdf_excludes_domain_background_fill() -> None:
    partition_gdf = gpd.GeoDataFrame(
        {"zone_key": ["domain_background", "geo_a", "geo_b"]},
        geometry=[
            box(0.0, 0.0, 10.0, 10.0),
            box(1.0, 1.0, 3.0, 3.0),
            box(4.0, 4.0, 6.0, 6.0),
        ],
        crs="EPSG:2154",
    )

    overlay_gdf = conformal_plotting_module._build_partition_overlay_gdf(partition_gdf)

    assert overlay_gdf["zone_key"].astype(str).tolist() == ["geo_a", "geo_b"]


def test_collect_display_zone_keys_includes_background_lithology() -> None:
    source_domain_gdf = gpd.GeoDataFrame(
        {"zone_key": ["geo_outside", "geo_inside"]},
        geometry=[
            box(0.0, 0.0, 6.0, 6.0),
            box(6.0, 0.0, 12.0, 6.0),
        ],
        crs="EPSG:2154",
    )
    partition_overlay_gdf = gpd.GeoDataFrame(
        {"zone_key": ["geo_inside"]},
        geometry=[box(6.0, 0.0, 12.0, 6.0)],
        crs="EPSG:2154",
    )

    zone_keys = conformal_plotting_module._collect_display_zone_keys(
        source_domain_gdf,
        partition_overlay_gdf,
    )

    assert zone_keys == ["geo_inside", "geo_outside"]


def test_geographic_mesh_figure_uses_raw_black_boundary_and_blue_hydro_overlay() -> None:
    domain_gdf = gpd.GeoDataFrame(
        geometry=[box(0.0, 0.0, 10.0, 10.0)],
        crs="EPSG:2154",
    )
    source_domain_gdf = gpd.GeoDataFrame(
        {"zone_key": ["geo_a", "geo_b"]},
        geometry=[
            box(0.0, 0.0, 5.0, 10.0),
            box(5.0, 0.0, 10.0, 10.0),
        ],
        crs="EPSG:2154",
    )
    partition_gdf = source_domain_gdf.copy()
    topo_background = (
        np.arange(100, dtype=float).reshape(10, 10),
        (0.0, 10.0, 0.0, 10.0),
    )
    catchment_gdf = gpd.GeoDataFrame(
        geometry=[box(1.0, 1.0, 9.0, 9.0)],
        crs="EPSG:2154",
    )
    catchment_boundary_gdf = gpd.GeoDataFrame(
        {"name": ["watershed::boundary"]},
        geometry=[LineString([(1.5, 1.3), (8.8, 1.6), (8.6, 8.5), (1.7, 8.2), (1.5, 1.3)])],
        crs="EPSG:2154",
    )

    fig = conformal_plotting_module._build_geographic_mesh_figure(
        domain_gdf=domain_gdf,
        source_domain_gdf=source_domain_gdf,
        partition_gdf=partition_gdf,
        mesh=SimpleNamespace(cells=[]),
        domain_bounds=[0.0, 0.0, 10.0, 10.0],
        catchment_gdf=catchment_gdf,
        catchment_boundary_gdf=catchment_boundary_gdf,
        topo_background=topo_background,
        river_lines=[LineString([(2.0, 2.0), (8.0, 8.0)])],
    )
    try:
        fig.canvas.draw()
        ax_overlay = fig.axes[1]
        overlay_legend = ax_overlay.get_legend()
        assert overlay_legend is not None
        legend_labels = [text.get_text() for text in overlay_legend.get_texts()]
        assert "geo_a" not in legend_labels
        assert "geo_b" not in legend_labels
        assert "Catchment boundary" in legend_labels
        assert "Raw catchment boundary" not in legend_labels
        assert "Regularized boundary" not in legend_labels

        colorbar_ax = fig.axes[-1]
        bbox = colorbar_ax.get_position()
        assert bbox.width > bbox.height

        hydro_handle = next(
            handle
            for handle, label in zip(overlay_legend.legend_handles, legend_labels)
            if label == "Hydro network"
        )
        assert hydro_handle.get_color() == "#1f78b4"
    finally:
        conformal_plotting_module.plt.close(fig)


def test_regional_context_figure_uses_bottom_horizontal_colorbar() -> None:
    domain_gdf = gpd.GeoDataFrame(
        geometry=[box(0.0, 0.0, 10.0, 10.0)],
        crs="EPSG:2154",
    )
    topo_background = (
        np.arange(100, dtype=float).reshape(10, 10),
        (0.0, 10.0, 0.0, 10.0),
    )

    fig = conformal_plotting_module._build_regional_context_figure(
        domain_gdf=domain_gdf,
        catchment_gdf=None,
        catchment_boundary_gdf=None,
        topo_background=topo_background,
        river_lines=[],
        outlet_xy=None,
    )
    try:
        fig.canvas.draw()
        colorbar_ax = fig.axes[-1]
        bbox = colorbar_ax.get_position()
        assert bbox.width > bbox.height
    finally:
        conformal_plotting_module.plt.close(fig)


def test_resolve_constraint_families_marks_enabled_inputs() -> None:
    families = _resolve_constraint_families("geology_rivers")

    assert families.geology_interface is True
    assert families.river is True


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_invalid_clip_bbox_domain_case_toml(path: Path) -> None:
    raw = CASE_TOML.read_text(encoding="utf-8-sig")
    old_block = (
        "[mesh_case.domain]\n"
        'kind = "vector"\n'
        'path = "domain_window.geojson"\n'
        'id_field = "domain_id"\n'
        'selected_id = "main"\n'
    )
    new_block = (
        "[mesh_case.domain]\n"
        "clip_bbox = [355000.0, 6712500.0, 359000.0, 6716500.0]\n"
    )
    if old_block not in raw:
        raise AssertionError(
            "Unable to build invalid clip_bbox-domain test config: domain block not found"
        )
    migrated = raw.replace(old_block, new_block)

    absolute_geology_path = (CASE_TOML.parent / _CASE_RELATIVE_GEOLOGY_PATH).resolve()
    migrated = migrated.replace(
        f'path = "{_CASE_RELATIVE_GEOLOGY_PATH}"',
        f'path = "{absolute_geology_path.as_posix()}"',
    )
    path.write_text(migrated, encoding="utf-8")


def _rewrite_case_config_section_and_paths(raw: str, *, section: str) -> str:
    section_raw = raw.replace("[mesh_case]", f"[{section}]").replace(
        "[mesh_case.", f"[{section}."
    )
    case_dir = CASE_TOML.parent
    absolute_domain_path = (case_dir / "domain_window.geojson").resolve().as_posix()
    absolute_geology_path = (
        case_dir / _CASE_RELATIVE_GEOLOGY_PATH
    ).resolve().as_posix()
    absolute_reference_raster_path = (
        case_dir / _CASE_RELATIVE_REFERENCE_RASTER_PATH
    ).resolve().as_posix()
    section_raw = section_raw.replace(
        'path = "domain_window.geojson"',
        f'path = "{absolute_domain_path}"',
    )
    section_raw = section_raw.replace(
        f'path = "{_CASE_RELATIVE_GEOLOGY_PATH}"',
        f'path = "{absolute_geology_path}"',
    )
    section_raw = section_raw.replace(
        f'reference_raster_path = "{_CASE_RELATIVE_REFERENCE_RASTER_PATH}"',
        f'reference_raster_path = "{absolute_reference_raster_path}"',
    )
    return section_raw


def _write_mode_case_toml(
    path: Path,
    *,
    constraints_mode: str,
    section: str = "case",
    add_rivers_block: bool = False,
) -> None:
    raw = CASE_TOML.read_text(encoding="utf-8-sig")
    migrated = _rewrite_case_config_section_and_paths(raw, section=section)
    migrated = migrated.replace(
        'constraints_mode = "geology_only"',
        f'constraints_mode = "{constraints_mode}"',
    )
    if add_rivers_block and f"[{section}.rivers]" not in migrated:
        migrated = (
            f"{migrated.rstrip()}\n\n"
            f"[{section}.rivers]\n"
            'source = "domain_geographic"\n'
            "clip_to_domain = true\n"
            "min_segment_length = 0.0\n"
            "snap_tolerance = 0.0\n"
        )
    path.write_text(migrated, encoding="utf-8")


def _write_geographic_box_buffer_case_toml(
    path: Path,
    *,
    constraints_mode: str = "geology_only",
    section: str = "case",
) -> None:
    raw = CASE_TOML.read_text(encoding="utf-8-sig")
    migrated = _rewrite_case_config_section_and_paths(raw, section=section)
    old_block = (
        f"[{section}.domain]\n"
        'kind = "vector"\n'
        f'path = "{(CASE_TOML.parent / "domain_window.geojson").resolve().as_posix()}"\n'
        'id_field = "domain_id"\n'
        'selected_id = "main"\n'
    )
    new_block = (
        f"[{section}.domain]\n"
        'kind = "geographic_box_buffer"\n'
    )
    if old_block not in migrated:
        raise AssertionError(
            "Unable to build geographic_box_buffer test config: domain block not found"
        )
    migrated = migrated.replace(old_block, new_block)
    migrated = migrated.replace(
        'constraints_mode = "geology_only"',
        f'constraints_mode = "{constraints_mode}"',
    )
    path.write_text(migrated, encoding="utf-8")


def _write_geographic_box_buffer_watershed_boundary_case_toml(
    path: Path,
    *,
    constraints_mode: str = "geology_only",
    section: str = "case",
) -> None:
    _write_geographic_box_buffer_case_toml(
        path,
        constraints_mode=constraints_mode,
        section=section,
    )
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            "\n".join(
                (
                    "",
                    f"[{section}.watershed_boundary]",
                    "enabled = true",
                    "boundary_refinement_distance = 500.0",
                    "",
                    f"[{section}.watershed_boundary.smoothing]",
                    "enabled = true",
                    "distance = 50.0",
                    "river_buffer_distance = 100.0",
                    "outer_bias_distance = 10.0",
                    "",
                )
            )
        )


def _write_base_config_inheritance_case_toml(
    base_path: Path,
    child_path: Path,
    *,
    section: str = "mesh_catchment",
    constraints_mode: str = "geology_rivers",
) -> None:
    raw = CASE_TOML.read_text(encoding="utf-8-sig")
    migrated = _rewrite_case_config_section_and_paths(raw, section=section)
    migrated = migrated.replace(
        'constraints_mode = "geology_only"',
        f'constraints_mode = "{constraints_mode}"',
    )
    base_path.write_text(migrated, encoding="utf-8")
    child_path.write_text(
        "\n".join(
            (
                f'base_config = "{base_path.name}"',
                "",
                f"[{section}]",
                'output_figure = "outputs/inherited_overview.png"',
            )
        )
        + "\n",
        encoding="utf-8",
    )


def _write_scope_vector(path: Path, *, bounds: tuple[float, float, float, float]) -> None:
    gdf = gpd.GeoDataFrame(
        {"domain_id": [path.stem]},
        geometry=[box(*bounds)],
        crs="EPSG:2154",
    )
    gdf.to_file(path, driver="GeoJSON")


def _write_geographic_scope_case_toml(
    path: Path,
    *,
    section: str = "case",
    constraints_mode: str = "geology_only",
) -> None:
    raw = CASE_TOML.read_text(encoding="utf-8-sig")
    migrated = _rewrite_case_config_section_and_paths(raw, section=section)
    old_block = (
        f"[{section}.domain]\n"
        'kind = "vector"\n'
        f'path = "{(CASE_TOML.parent / "domain_window.geojson").resolve().as_posix()}"\n'
        'id_field = "domain_id"\n'
        'selected_id = "main"\n'
    )
    new_block = (
        f"[{section}.domain]\n"
        'kind = "geographic_box_buffer"\n'
        "\n"
        f"[{section}.interface_scope]\n"
        'kind = "geographic_watershed"\n'
        "\n"
        f"[{section}.refinement_scope]\n"
        'kind = "geographic_watershed_box"\n'
    )
    if old_block not in migrated:
        raise AssertionError(
            "Unable to build geographic scope test config: domain block not found"
        )
    migrated = migrated.replace(old_block, new_block)
    migrated = migrated.replace(
        'constraints_mode = "geology_only"',
        f'constraints_mode = "{constraints_mode}"',
    )
    path.write_text(migrated, encoding="utf-8")


def _write_geographic_scope_watershed_boundary_case_toml(
    path: Path,
    *,
    section: str = "case",
    constraints_mode: str = "geology_only",
) -> None:
    _write_geographic_scope_case_toml(
        path,
        section=section,
        constraints_mode=constraints_mode,
    )
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            "\n".join(
                (
                    "",
                    f"[{section}.watershed_boundary]",
                    "enabled = true",
                    "boundary_refinement_distance = 500.0",
                    "",
                    f"[{section}.watershed_boundary.smoothing]",
                    "enabled = true",
                    "distance = 50.0",
                    "river_buffer_distance = 100.0",
                    "outer_bias_distance = 10.0",
                    "",
                )
            )
        )


def _build_reference_river_trace() -> SimpleNamespace:
    return SimpleNamespace(
        lines=(
            LineString([(355150.0, 6713000.0), (358850.0, 6716200.0)]),
            LineString([(355300.0, 6716100.0), (358700.0, 6712800.0)]),
        )
    )


@_skip_no_gmsh
def test_reference_2d_geology_conformal_case_non_regression(
    update_goldens: bool,
) -> None:
    output_dir = (
        Path.cwd() / "scratch_tests" / "reference_2d_geology_conformal" / "runtime"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = run_reference_2d_zone_conformal_case_from_toml(
        CASE_TOML,
        output_mesh=output_dir / "reference_2d_geology_conformal.msh",
        output_summary_json=output_dir / "reference_2d_geology_conformal_summary.json",
        output_figure=output_dir / "reference_2d_geology_conformal.png",
    )

    assert Path(summary["output_mesh"]).exists()
    assert Path(summary["output_summary_json"]).exists()
    assert Path(summary["output_figure"]).exists()
    assert summary["n_cells"] > 0
    assert summary["n_nodes"] > 0
    assert summary["summary_schema_version"] == "zone_conformal_sidecar_v1"
    assert summary["n_source_features_total"] >= summary["n_source_features_clipped"]
    assert summary["covered_area"] == summary["domain_area"]
    assert summary["interface_group_count"] > 0
    assert summary["domain_kind"] == "vector"
    assert summary["constraints_mode"] == "geology_only"
    assert summary["constraints_qa"]["mode"] == "geology_only"
    assert summary["constraints_qa"]["overall_pass"] is True
    assert summary["mesh_size_fields"]["interface_refinement"]["enabled"] is True
    assert summary["effective_domain"]["domain_kind"] == "vector"
    assert (
        summary["mesh_size_fields"]["interface_refinement"][
            "candidate_interface_curve_count"
        ]
        >= summary["mesh_size_fields"]["interface_refinement"]["interface_curve_count"]
    )
    assert (
        summary["mesh_size_fields"]["interface_refinement"][
            "scope_filtered_interface_curve_count"
        ]
        == summary["mesh_size_fields"]["interface_refinement"]["interface_curve_count"]
    )
    assert (
        summary["mesh_size_fields"]["interface_refinement"][
            "refinement_scope_applied"
        ]
        is False
    )
    assert summary["cleaning_diagnostics"]["cleaning_mode"] == "tolerant"
    assert summary["cleaning_summary"]["mode"] == "tolerant"
    assert (
        summary["cleaning_summary"]["source_feature_count"]
        == summary["cleaning_diagnostics"]["source_feature_count"]
    )
    assert (
        summary["cleaning_diagnostics"]["source_feature_count"]
        >= summary["n_source_features_clipped"]
    )
    assert summary["physical_groups_summary"]["surface_group_count"] == len(
        summary["zone_keys"]
    )
    assert summary["qa_checks"]["coverage_within_tolerance"] is True
    assert summary["qa_checks"]["has_interface_groups"] is True
    assert summary["qa_checks"]["constraints_contract_pass"] is True
    assert len(summary["surface_physical_groups"]) == len(summary["zone_keys"])
    assert any(
        group["name"].startswith("interface::")
        for group in summary["curve_physical_groups"]
    )

    stable = dict(summary)
    stable.pop("output_mesh", None)
    stable.pop("output_summary_json", None)
    stable.pop("output_figure", None)
    stable.pop("interface_scope", None)
    stable.pop("effective_domain", None)
    stable.pop("refinement_scope", None)
    stable.pop("domain_source_path", None)
    stable.pop("source_path", None)
    stable.pop("linear_constraints", None)
    interface_refinement = dict(stable["mesh_size_fields"]["interface_refinement"])
    interface_refinement.pop("candidate_interface_curve_count", None)
    interface_refinement.pop("scope_filtered_interface_curve_count", None)
    interface_refinement.pop("refinement_scope_applied", None)
    interface_refinement.pop("stop_at_distance_max", None)
    stable["mesh_size_fields"] = {"interface_refinement": interface_refinement}

    if update_goldens:
        _write_json(GOLDEN_FILE, stable)
        return

    expected = _load_json(GOLDEN_FILE)
    assert stable == expected


@_skip_no_gmsh
def test_reference_2d_geology_conformal_rejects_removed_clip_bbox_syntax() -> None:
    output_dir = (
        Path.cwd()
        / "scratch_tests"
        / "reference_2d_geology_conformal"
        / "runtime_invalid_clip_bbox_domain"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    invalid_toml = output_dir / "case_config_invalid_clip_bbox_domain.toml"
    _write_invalid_clip_bbox_domain_case_toml(invalid_toml)

    with pytest.raises(ValueError, match="requires one explicit geometry source"):
        run_reference_2d_zone_conformal_case_from_toml(
            invalid_toml,
            output_mesh=output_dir / "reference_2d_geology_conformal.msh",
            output_summary_json=output_dir
            / "reference_2d_geology_conformal_summary.json",
            output_figure=output_dir / "reference_2d_geology_conformal.png",
        )


def test_resolve_river_trace_for_meshing_prefers_explicit_trace() -> None:
    explicit_trace = object()

    class _DomainGeographic:
        river_mesh_trace = object()

    resolved = _resolve_river_trace_for_meshing(
        river_trace=explicit_trace,
        domain_geographic=_DomainGeographic(),
        rivers_cfg=ZoneConformalRiversConfig(
            source="domain_geographic",
            path=None,
            clip_to_domain=True,
            min_segment_length=0.0,
            snap_tolerance=0.0,
        ),
        config_path=Path.cwd(),
    )

    assert resolved is explicit_trace


def test_resolve_river_trace_for_meshing_falls_back_to_domain_geographic() -> None:
    domain_trace = object()

    class _DomainGeographic:
        river_mesh_trace = domain_trace

    resolved = _resolve_river_trace_for_meshing(
        river_trace=None,
        domain_geographic=_DomainGeographic(),
        rivers_cfg=ZoneConformalRiversConfig(
            source="domain_geographic",
            path=None,
            clip_to_domain=True,
            min_segment_length=0.0,
            snap_tolerance=0.0,
        ),
        config_path=Path.cwd(),
    )

    assert resolved is domain_trace


def test_resolve_river_trace_for_meshing_returns_none_without_inputs() -> None:
    resolved = _resolve_river_trace_for_meshing(
        river_trace=None,
        domain_geographic=None,
        rivers_cfg=ZoneConformalRiversConfig(
            source="domain_geographic",
            path=None,
            clip_to_domain=True,
            min_segment_length=0.0,
            snap_tolerance=0.0,
        ),
        config_path=Path.cwd(),
    )

    assert resolved is None


def test_clip_river_trace_to_domain_discards_outside_segments() -> None:
    river_trace = SimpleNamespace(
        lines=(
            LineString([(0.0, 0.0), (3.0, 0.0)]),
            LineString([(10.0, 10.0), (11.0, 11.0)]),
        )
    )

    resolved = _clip_river_trace_to_domain(
        river_trace=river_trace,
        domain_geometry=box(0.0, -1.0, 2.0, 1.0),
    )

    assert resolved is not None
    clipped_lines = tuple(resolved.lines)
    assert len(clipped_lines) == 1
    assert clipped_lines[0].bounds[0] >= 0.0
    assert clipped_lines[0].bounds[2] <= 2.0


def test_resolve_constraints_mode_accepts_supported_values() -> None:
    assert _resolve_constraints_mode("geology_only") == "geology_only"
    assert _resolve_constraints_mode("rivers_only") == "rivers_only"
    assert _resolve_constraints_mode("geology_rivers") == "geology_rivers"


def test_resolve_constraints_mode_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="constraints_mode must be one of"):
        _ = _resolve_constraints_mode("unsupported_mode")


def test_resolve_case_config_supports_base_config_inheritance(tmp_path: Path) -> None:
    base_path = tmp_path / "base_case.toml"
    child_path = tmp_path / "child_case.toml"
    _write_base_config_inheritance_case_toml(
        base_path,
        child_path,
        section="mesh_catchment",
        constraints_mode="geology_rivers",
    )

    cfg = _resolve_case_config(child_path, section="mesh_catchment")

    assert cfg.constraints_mode_label == "geology_rivers"
    assert cfg.output_figure == "outputs/inherited_overview.png"
    assert isinstance(cfg.geology, ZoneConformalGeologyConfig)
    assert cfg.zone_meshing is not None
    assert isinstance(cfg.zone_meshing, ZoneConformalZoneMeshingConfig)
    assert isinstance(cfg.domain, ZoneConformalDomainConfig)


def test_resolve_case_config_accepts_prevalidated_launcher_section_defaults(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mesh_launcher.toml"
    config_path.write_text("[mesh_catchment]\nconstraints_mode = \"geology_only\"\n", encoding="utf-8")

    section_data = {
        "constraints_mode": "geology_only",
        "domain": {"kind": "geographic_box_buffer"},
        "geology": {
            "source": {
                "path": str((CASE_TOML.parent / _CASE_RELATIVE_GEOLOGY_PATH).resolve()),
                "kind": "vector",
                "code_field": "CODE_GEOL",
                "reference_raster_path": str(
                    (CASE_TOML.parent / _CASE_RELATIVE_REFERENCE_RASTER_PATH).resolve()
                ),
            }
        },
        "zone_meshing": {
            "algorithm": "delaunay",
            "global_size": 250.0,
            "simplify_tolerance": 0.0,
            "heal_tolerance": 0.0,
            "min_polygon_area": 0.0,
            "refine_interfaces": False,
            "interface_sampling": 64,
        }
    }

    cfg = _resolve_case_config(
        config_path,
        section="mesh_catchment",
        section_data_override=section_data,
    )

    assert cfg.constraints_mode_label == "geology_only"
    assert isinstance(cfg.domain, ZoneConformalDomainConfig)
    assert cfg.domain.kind == "geographic_box_buffer"
    assert cfg.domain.to_mapping()["kind"] == "geographic_box_buffer"
    assert isinstance(cfg.geology, ZoneConformalGeologyConfig)
    assert cfg.geology.source.kind == "vector"


def test_watershed_boundary_builds_linear_constraint_and_preserves_full_geology(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mesh_launcher.toml"
    config_path.write_text("[mesh_catchment]\nconstraints_mode = \"geology_only\"\n", encoding="utf-8")

    watershed_path = tmp_path / "watershed.geojson"
    watershed_gdf = gpd.GeoDataFrame(
        {"catch_id": ["ws_1"]},
        geometry=[box(355400.0, 6712900.0, 358400.0, 6716100.0)],
        crs="EPSG:2154",
    )
    watershed_gdf.to_file(watershed_path, driver="GeoJSON")

    section_data = {
        "constraints_mode": "geology_only",
        "watershed_boundary": {
            "enabled": True,
            "boundary_refinement_distance": 500.0,
            "smoothing": {
                "enabled": True,
                "distance": 50.0,
                "river_buffer_distance": 100.0,
                "outer_bias_distance": 10.0,
            },
            "outside_coarsening": {
                "enabled": True,
                "size_factor": 2.0,
                "transition_distance": 300.0,
                "grid_resolution": 250.0,
            },
        },
        "domain": {
            "kind": "vector",
            "path": str((CASE_TOML.parent / "domain_window.geojson").resolve()),
            "id_field": "domain_id",
            "selected_id": "main",
        },
        "geology": {
            "source": {
                "path": str((CASE_TOML.parent / _CASE_RELATIVE_GEOLOGY_PATH).resolve()),
                "kind": "vector",
                "code_field": "CODE_LEG",
                "reference_raster_path": str(
                    (CASE_TOML.parent / _CASE_RELATIVE_REFERENCE_RASTER_PATH).resolve()
                ),
            }
        },
        "zone_meshing": {
            "algorithm": "delaunay",
            "global_size": 250.0,
            "min_size": 125.0,
            "max_size": 400.0,
            "simplify_tolerance": 0.0,
            "heal_tolerance": 0.0,
            "min_polygon_area": 0.0,
            "refine_interfaces": True,
            "interface_size": 90.0,
            "interface_distance": 450.0,
            "interface_sampling": 64,
        },
    }

    cfg = _resolve_case_config(
        config_path,
        section="mesh_catchment",
        section_data_override=section_data,
    )
    river_trace = SimpleNamespace(
        lines=(
            LineString(
                [
                    (355450.0, 6713000.0),
                    (356800.0, 6714200.0),
                    (358250.0, 6715900.0),
                ]
            ),
        )
    )

    inputs = _build_zone_conformal_meshing_inputs(
        cfg=cfg,
        config_path=config_path,
        river_trace=river_trace,
        domain_geographic=SimpleNamespace(watershed_shp=str(watershed_path)),
    )

    assert set(inputs.zone_gdf["zone_key"].astype(str)) == set(
        inputs.diagnostics.source_plot_gdf["zone_key"].astype(str)
    )
    assert "outside_background" not in set(inputs.zone_gdf["zone_key"].astype(str))
    assert any(
        constraint.name == "watershed::boundary"
        for constraint in inputs.linear_constraints
    )
    assert inputs.zone_meshing_cfg.global_size == pytest.approx(250.0)
    assert inputs.zone_meshing_cfg.refinement_policy is not None
    assert (
        inputs.zone_meshing_cfg.refinement_policy.families["watershed_boundary"].enabled
        is True
    )
    assert (
        inputs.zone_meshing_cfg.refinement_policy.families["watershed_boundary"].interface_distance
        == pytest.approx(500.0)
    )
    assert inputs.diagnostics.watershed_boundary_summary is not None
    assert inputs.diagnostics.watershed_boundary_summary["enabled"] is True
    assert len(inputs.regional_size_fields) == 1
    assert inputs.regional_size_fields[0].inside_size == pytest.approx(250.0)
    assert inputs.regional_size_fields[0].outside_size == pytest.approx(500.0)
    assert inputs.diagnostics.outside_coarsening_summary is not None
    assert inputs.diagnostics.outside_coarsening_summary["enabled"] is True
    assert inputs.diagnostics.outside_coarsening_summary["size_factor"] == pytest.approx(2.0)
    assert inputs.diagnostics.watershed_boundary_plot_gdf is not None
    assert not inputs.diagnostics.watershed_boundary_plot_gdf.empty


def test_watershed_boundary_defaults_regularization_tolerance_to_global_size(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mesh_launcher.toml"
    config_path.write_text("[mesh_catchment]\nconstraints_mode = \"geology_only\"\n", encoding="utf-8")

    watershed_path = tmp_path / "watershed.geojson"
    gpd.GeoDataFrame(
        {"catch_id": ["ws_1"]},
        geometry=[box(355400.0, 6712900.0, 358400.0, 6716100.0)],
        crs="EPSG:2154",
    ).to_file(watershed_path, driver="GeoJSON")

    section_data = {
        "constraints_mode": "geology_only",
        "watershed_boundary": {
            "enabled": True,
            "smoothing": {
                "enabled": True,
                "river_buffer_distance": 100.0,
                "outer_bias_distance": 10.0,
            },
        },
        "domain": {
            "kind": "vector",
            "path": str((CASE_TOML.parent / "domain_window.geojson").resolve()),
            "id_field": "domain_id",
            "selected_id": "main",
        },
        "geology": {
            "source": {
                "path": str((CASE_TOML.parent / _CASE_RELATIVE_GEOLOGY_PATH).resolve()),
                "kind": "vector",
                "code_field": "CODE_LEG",
                "reference_raster_path": str(
                    (CASE_TOML.parent / _CASE_RELATIVE_REFERENCE_RASTER_PATH).resolve()
                ),
            }
        },
        "zone_meshing": {
            "algorithm": "delaunay",
            "global_size": 250.0,
            "min_size": 125.0,
            "max_size": 400.0,
            "simplify_tolerance": 0.0,
            "heal_tolerance": 0.0,
            "min_polygon_area": 0.0,
            "refine_interfaces": True,
            "interface_size": 90.0,
            "interface_distance": 450.0,
            "interface_sampling": 64,
        },
    }

    cfg = _resolve_case_config(
        config_path,
        section="mesh_catchment",
        section_data_override=section_data,
    )
    inputs = _build_zone_conformal_meshing_inputs(
        cfg=cfg,
        config_path=config_path,
        river_trace=SimpleNamespace(
            lines=(LineString([(355450.0, 6713000.0), (358250.0, 6715900.0)]),)
        ),
        domain_geographic=SimpleNamespace(watershed_shp=str(watershed_path)),
    )

    assert inputs.diagnostics.watershed_boundary_summary is not None
    assert inputs.diagnostics.watershed_boundary_summary["smoothing"]["distance"] == pytest.approx(250.0)


@_skip_no_gmsh
def test_watershed_boundary_runs_end_to_end_with_smoothed_constraint(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mesh_launcher.toml"
    config_path.write_text("[mesh_catchment]\nconstraints_mode = \"geology_only\"\n", encoding="utf-8")

    watershed_path = tmp_path / "watershed.geojson"
    watershed_gdf = gpd.GeoDataFrame(
        {"catch_id": ["ws_1"]},
        geometry=[box(355400.0, 6712900.0, 358400.0, 6716100.0)],
        crs="EPSG:2154",
    )
    watershed_gdf.to_file(watershed_path, driver="GeoJSON")

    summary = run_reference_2d_zone_conformal_case_from_toml(
        config_path,
        section="mesh_catchment",
        section_data_override={
            "constraints_mode": "geology_only",
            "watershed_boundary": {
                "enabled": True,
                "boundary_refinement_distance": 500.0,
                "smoothing": {
                    "enabled": True,
                    "distance": 50.0,
                    "river_buffer_distance": 100.0,
                    "outer_bias_distance": 10.0,
                },
            },
            "domain": {
                "kind": "vector",
                "path": str((CASE_TOML.parent / "domain_window.geojson").resolve()),
                "id_field": "domain_id",
                "selected_id": "main",
            },
            "geology": {
                "source": {
                    "path": str((CASE_TOML.parent / _CASE_RELATIVE_GEOLOGY_PATH).resolve()),
                    "kind": "vector",
                    "code_field": "CODE_LEG",
                    "reference_raster_path": str(
                        (CASE_TOML.parent / _CASE_RELATIVE_REFERENCE_RASTER_PATH).resolve()
                    ),
                }
            },
            "zone_meshing": {
                "algorithm": "delaunay",
                "global_size": 250.0,
                "min_size": 125.0,
                "max_size": 400.0,
                "simplify_tolerance": 0.0,
                "heal_tolerance": 0.0,
                "min_polygon_area": 0.0,
                "refine_interfaces": True,
                "interface_size": 90.0,
                "interface_distance": 450.0,
                "interface_sampling": 64,
            },
        },
        output_mesh=tmp_path / "watershed_boundary_mesh.msh",
        output_summary_json=tmp_path / "watershed_boundary_summary.json",
        river_trace=SimpleNamespace(
            lines=(
                LineString(
                    [
                        (355450.0, 6713000.0),
                        (356800.0, 6714200.0),
                        (358250.0, 6715900.0),
                    ]
                ),
            )
        ),
        domain_geographic=SimpleNamespace(watershed_shp=str(watershed_path)),
        show_plot=False,
    )

    assert summary["watershed_boundary"]["enabled"] is True
    assert summary["watershed_boundary"]["smoothing_enabled"] is True
    assert summary["mesh_size_fields"]["interface_refinement"]["enabled"] is True
    assert summary["n_cells"] > 0

def test_main_prints_summary_json(monkeypatch, capsys) -> None:
    payload = {"status": "ok", "n_cells": 3}

    def fake_run(
        config_toml,
        *,
        section="mesh_case",
        output_mesh=None,
        output_summary_json=None,
        output_figure=None,
        output_figure_regional=None,
        show_plot=False,
    ):
        assert config_toml == "dummy.toml"
        assert section == "case"
        assert output_mesh is None
        assert output_summary_json is None
        assert output_figure is None
        assert output_figure_regional is None
        assert show_plot is False
        return payload

    monkeypatch.setattr(
        conformal_case_module,
        "run_reference_2d_zone_conformal_case_from_toml",
        fake_run,
    )

    exit_code = conformal_case_module.main(["--config-file", "dummy.toml", "--section", "case"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == payload


def test_package_exports_public_entrypoints_only() -> None:
    assert conformal_case_package.run_reference_2d_zone_conformal_case_from_toml is (
        run_reference_2d_zone_conformal_case_from_toml
    )
    assert conformal_case_package.main is conformal_case_module.main
    assert set(conformal_case_package.__all__) == {
        "DEFAULT_CONFIG_FILE",
        "DEFAULT_SECTION",
        "main",
        "run_reference_2d_zone_conformal_case_from_toml",
    }


def test_runner_module_declares_explicit_compatibility_exports() -> None:
    exported = set(conformal_case_module.__all__)

    assert exported == {
        "DEFAULT_CONFIG_FILE",
        "DEFAULT_SECTION",
        "main",
        "run_reference_2d_zone_conformal_case_from_toml",
    }


def test_river_constraints_mode_requires_river_trace(tmp_path: Path) -> None:
    config_path = tmp_path / "case_rivers.toml"
    config_path.write_text(
        "\n".join(
            [
                "[case]",
                'constraints_mode = "rivers_only"',
                "",
                "[case.domain]",
                'kind = "bbox"',
                "bbox = [355000.0, 6712500.0, 359000.0, 6716500.0]",
                "",
                "[case.rivers]",
                'source = "domain_geographic"',
                "",
                "[case.zone_meshing]",
                'algorithm = "delaunay"',
                "global_size = 250.0",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires one usable river trace"):
        run_reference_2d_zone_conformal_case_from_toml(
            config_path,
            section="case",
            output_mesh=tmp_path / "mesh.msh",
            show_plot=False,
        )


def test_mesh_mode_key_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "case_legacy_mesh_mode.toml"
    config_path.write_text(
        "\n".join(
            [
                "[case]",
                'mesh_mode = "rivers"',
                "",
                "[case.domain]",
                'kind = "bbox"',
                "bbox = [355000.0, 6712500.0, 359000.0, 6716500.0]",
                "",
                "[case.zone_meshing]",
                'algorithm = "delaunay"',
                "global_size = 250.0",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mesh_mode is no longer supported"):
        _ = run_reference_2d_zone_conformal_case_from_toml(
            config_path,
            section="case",
            output_mesh=tmp_path / "mesh.msh",
            show_plot=False,
        )


@_skip_no_gmsh
def test_geographic_box_buffer_domain_uses_domain_geographic_support() -> None:
    output_dir = (
        Path.cwd()
        / "scratch_tests"
        / "reference_2d_geology_conformal"
        / "runtime_geographic_box_buffer"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "case_geographic_box_buffer.toml"
    _write_geographic_box_buffer_case_toml(config_path)
    box_buff_shp = (CASE_TOML.parent / "domain_window.geojson").resolve()

    summary = run_reference_2d_zone_conformal_case_from_toml(
        config_path,
        section="case",
        output_mesh=output_dir / "reference_2d_zone_conformal_geographic_box_buffer.msh",
        output_summary_json=output_dir
        / "reference_2d_zone_conformal_geographic_box_buffer_summary.json",
        domain_geographic=SimpleNamespace(box_buff_shp=str(box_buff_shp)),
        show_plot=False,
    )

    assert summary["domain_kind"] == "geographic_box_buffer"
    assert summary["domain_source_path"] == str(box_buff_shp)
    assert summary["domain_area"] > 0.0
    assert summary["n_cells"] > 0
    assert summary["n_nodes"] > 0


@_skip_no_gmsh
def test_reference_case_accepts_watershed_boundary_section() -> None:
    output_dir = (
        Path.cwd()
        / "scratch_tests"
        / "reference_2d_geology_conformal"
        / "runtime_geographic_box_buffer_watershed_boundary"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "case_geographic_box_buffer_watershed_boundary.toml"
    _write_geographic_box_buffer_watershed_boundary_case_toml(config_path)
    box_buff_shp = (CASE_TOML.parent / "domain_window.geojson").resolve()
    watershed_path = output_dir / "watershed.geojson"
    gpd.GeoDataFrame(
        {"catch_id": ["ws_1"]},
        geometry=[box(355400.0, 6712900.0, 358400.0, 6716100.0)],
        crs="EPSG:2154",
    ).to_file(watershed_path, driver="GeoJSON")

    summary = run_reference_2d_zone_conformal_case_from_toml(
        config_path,
        section="case",
        output_mesh=output_dir
        / "reference_2d_zone_conformal_geographic_box_buffer_watershed_boundary.msh",
        output_summary_json=output_dir
        / "reference_2d_zone_conformal_geographic_box_buffer_watershed_boundary_summary.json",
        domain_geographic=SimpleNamespace(
            box_buff_shp=str(box_buff_shp),
            watershed_shp=str(watershed_path),
        ),
        show_plot=False,
    )

    assert summary["watershed_boundary"]["enabled"] is True
    assert summary["watershed_boundary"]["smoothing_enabled"] is True
    assert summary["n_cells"] > 0


@_skip_no_gmsh
def test_geology_rivers_mode_builds_combined_constraints_contract() -> None:
    output_dir = (
        Path.cwd()
        / "scratch_tests"
        / "reference_2d_geology_conformal"
        / "runtime_geology_rivers"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    case_toml = output_dir / "case_geology_rivers.toml"
    _write_mode_case_toml(
        case_toml,
        constraints_mode="geology_rivers",
        section="case",
        add_rivers_block=True,
    )

    summary = run_reference_2d_zone_conformal_case_from_toml(
        case_toml,
        section="case",
        output_mesh=output_dir / "reference_2d_zone_conformal_geology_rivers.msh",
        output_summary_json=output_dir
        / "reference_2d_zone_conformal_geology_rivers_summary.json",
        river_trace=_build_reference_river_trace(),
        show_plot=False,
    )

    assert summary["constraints_mode"] == "geology_rivers"
    assert summary["constraints_qa"]["contract_version"] == "constraints_qa_v1"
    assert summary["constraints_qa"]["mode"] == "geology_rivers"
    assert summary["constraints_qa"]["overall_pass"] is True
    checks = summary["constraints_qa"]["checks"]
    assert checks["has_geology_interfaces"] is True
    assert checks["river_curves_generated"] is True
    assert checks["river_embedded_on_surfaces"] is True
    assert checks["geology_and_river_constraints_coexist"] is True
    assert summary["qa_checks"]["constraints_contract_pass"] is True
    assert summary["river_trace"]["curve_count"] > 0
    assert summary["river_trace"]["embedded_surface_curve_pairs"] > 0

def test_reference_case_rejects_removed_scope_sections() -> None:
    output_dir = (
        Path.cwd()
        / "scratch_tests"
        / "reference_2d_geology_conformal"
        / "runtime_geographic_scopes"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "case_geographic_scopes.toml"
    _write_geographic_scope_case_toml(config_path)

    with pytest.raises(
        ValueError,
        match=r"\[case\.interface_scope\] is no longer supported",
    ):
        run_reference_2d_zone_conformal_case_from_toml(
            config_path,
            section="case",
            output_mesh=output_dir / "reference_2d_zone_conformal_geographic_scopes.msh",
            show_plot=False,
        )


@_skip_no_gmsh
def test_rivers_only_mode_builds_river_constraints_contract() -> None:
    output_dir = (
        Path.cwd()
        / "scratch_tests"
        / "reference_2d_geology_conformal"
        / "runtime_rivers_only"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "case_rivers_only.toml"
    config_path.write_text(
        "\n".join(
            [
                "[case]",
                'constraints_mode = "rivers_only"',
                "",
                "[case.domain]",
                'kind = "bbox"',
                "bbox = [355000.0, 6712500.0, 359000.0, 6716500.0]",
                "",
                "[case.rivers]",
                'source = "domain_geographic"',
                "clip_to_domain = true",
                "min_segment_length = 0.0",
                "snap_tolerance = 0.0",
                "",
                "[case.zone_meshing]",
                'algorithm = "delaunay"',
                "global_size = 250.0",
                "refine_interfaces = true",
                "interface_size = 100.0",
                "interface_distance = 500.0",
                "interface_sampling = 64",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_reference_2d_zone_conformal_case_from_toml(
        config_path,
        section="case",
        output_mesh=output_dir / "reference_2d_zone_conformal_rivers_only.msh",
        river_trace=_build_reference_river_trace(),
        show_plot=False,
    )

    assert summary["constraints_mode"] == "rivers_only"
    assert summary["constraints_qa"]["mode"] == "rivers_only"
    assert summary["constraints_qa"]["overall_pass"] is True
    checks = summary["constraints_qa"]["checks"]
    assert checks["river_trace_provided"] is True
    assert checks["river_curves_generated"] is True
    assert checks["river_curve_group_present"] is True
    assert checks["river_embedded_on_surfaces"] is True
    assert checks["river_refinement_consistent_with_config"] is True
    assert "has_geology_interfaces" not in checks
