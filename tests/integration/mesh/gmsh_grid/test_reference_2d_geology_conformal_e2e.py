from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import matplotlib
import pytest
from shapely.geometry import LineString, box

matplotlib.use("Agg", force=True)

try:
    import gmsh  # noqa: F401

    _gmsh_available = True
except (ImportError, OSError):
    _gmsh_available = False
_skip_no_gmsh = pytest.mark.skipif(not _gmsh_available, reason="gmsh not available")

import hydromodpy

# The reference_2d_geology_conformal case config resolution consumes the
# GeologyDataSource registered by bootstrap; force it so this file is
# order-independent when run in isolation (its own CI tier).
hydromodpy.bootstrap()

from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal import (
    run_reference_2d_zone_conformal_case_from_toml,
)

CASE_TOML = (
    Path(__file__).resolve().parents[4]
    / "hydromodpy"
    / "spatial"
    / "mesh"
    / "gmsh_grid"
    / "cases"
    / "reference_2d_geology_conformal"
    / "case_config_zone_conformal.toml"
)
_CASE_RELATIVE_GEOLOGY_PATH = "../../../../../../examples/data/geology/GEO1M_brittany.shp"
_CASE_RELATIVE_REFERENCE_RASTER_PATH = (
    "../../../cartesian_grid/examples/discretization/demo_top_bretagne_10km.tif"
)


def _write_invalid_clip_bbox_domain_case_toml(path: Path) -> None:
    raw = CASE_TOML.read_text(encoding="utf-8-sig")
    old_block = (
        "[mesh_case.domain]\n"
        'kind = "vector"\n'
        'path = "domain_window.geojson"\n'
        'id_field = "domain_id"\n'
        'selected_id = "main"\n'
    )
    new_block = "[mesh_case.domain]\nclip_bbox = [355000.0, 6712500.0, 359000.0, 6716500.0]\n"
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
    section_raw = raw.replace("[mesh_case]", f"[{section}]").replace("[mesh_case.", f"[{section}.")
    case_dir = CASE_TOML.parent
    absolute_domain_path = (case_dir / "domain_window.geojson").resolve().as_posix()
    absolute_geology_path = (case_dir / _CASE_RELATIVE_GEOLOGY_PATH).resolve().as_posix()
    absolute_reference_raster_path = (
        (case_dir / _CASE_RELATIVE_REFERENCE_RASTER_PATH).resolve().as_posix()
    )
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
            'source = "geographic_features"\n'
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
    new_block = f'[{section}.domain]\nkind = "geographic_box_buffer"\n'
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


def _build_reference_river_trace() -> SimpleNamespace:
    return SimpleNamespace(
        lines=(
            LineString([(355150.0, 6713000.0), (358850.0, 6716200.0)]),
            LineString([(355300.0, 6716100.0), (358700.0, 6712800.0)]),
        )
    )


@_skip_no_gmsh
def test_reference_2d_geology_conformal_rejects_removed_clip_bbox_syntax(tmp_path: Path) -> None:
    output_dir = tmp_path / "runtime_invalid_clip_bbox_domain"
    output_dir.mkdir(parents=True, exist_ok=True)
    invalid_toml = output_dir / "case_config_invalid_clip_bbox_domain.toml"
    _write_invalid_clip_bbox_domain_case_toml(invalid_toml)

    with pytest.raises(ValueError, match="requires one explicit geometry source"):
        run_reference_2d_zone_conformal_case_from_toml(
            invalid_toml,
            output_mesh=output_dir / "reference_2d_geology_conformal.msh",
            output_summary_json=output_dir / "reference_2d_geology_conformal_summary.json",
            output_figure=output_dir / "reference_2d_geology_conformal.png",
        )


@_skip_no_gmsh
def test_watershed_boundary_runs_end_to_end_with_smoothed_constraint(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mesh_launcher.toml"
    config_path.write_text(
        '[mesh_catchment]\nconstraints_mode = "geology_only"\n', encoding="utf-8"
    )

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


@_skip_no_gmsh
def test_watershed_boundary_buffered_geology_conformity_runs_end_to_end(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mesh_launcher.toml"
    config_path.write_text(
        '[mesh_catchment]\nconstraints_mode = "geology_only"\n',
        encoding="utf-8",
    )

    watershed_path = tmp_path / "watershed.geojson"
    gpd.GeoDataFrame(
        {"catch_id": ["ws_1"]},
        geometry=[box(355400.0, 6712900.0, 358400.0, 6716100.0)],
        crs="EPSG:2154",
    ).to_file(watershed_path, driver="GeoJSON")

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
                "outside_coarsening": {
                    "enabled": True,
                    "size_factor": 2.0,
                    "transition_distance": 300.0,
                    "grid_resolution": 250.0,
                },
                "geology_conformity": {
                    "mode": "buffered_watershed_envelope",
                    "buffer_distance": 250.0,
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
        output_mesh=tmp_path / "watershed_boundary_buffered_geology_mesh.msh",
        output_summary_json=tmp_path / "watershed_boundary_buffered_geology_summary.json",
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

    assert summary["geology_conformity"]["mode"] == "buffered_watershed_envelope"
    assert summary["geology_conformity"]["buffer_distance"] == pytest.approx(250.0)
    assert summary["geology_conformity"]["constraint_line_count"] > 0
    assert summary["watershed_boundary"]["explicit_constraint_applied"] is False
    assert summary["watershed_boundary"]["geometry_mode"] == "buffered_watershed_envelope"
    assert summary["zone_keys"] == ["domain"]
    assert "outside_background" not in summary["zone_keys"]
    assert "geology::active_interfaces" in summary["linear_constraints"]
    assert summary["linear_constraints"]["geology::active_interfaces"]["curve_count"] > 0
    assert summary["constraints_qa"]["overall_pass"] is True
    assert summary["outside_coarsening"]["enabled"] is True
    assert summary["n_cells"] > 0


@_skip_no_gmsh
def test_geographic_box_buffer_domain_uses_domain_geographic_support(tmp_path: Path) -> None:
    output_dir = tmp_path / "runtime_geographic_box_buffer"
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
def test_reference_case_accepts_watershed_boundary_section(tmp_path: Path) -> None:
    output_dir = tmp_path / "runtime_geographic_box_buffer_watershed_boundary"
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
    assert summary["n_cells_in_watershed"] > 0
    assert summary["n_cells_outside_watershed"] >= 0
    assert (
        summary["n_cells_in_watershed"] + summary["n_cells_outside_watershed"] == summary["n_cells"]
    )
    assert summary["n_cells"] > 0


@_skip_no_gmsh
def test_geology_rivers_mode_builds_combined_constraints_contract(tmp_path: Path) -> None:
    output_dir = tmp_path / "runtime_geology_rivers"
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
        output_summary_json=output_dir / "reference_2d_zone_conformal_geology_rivers_summary.json",
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


@_skip_no_gmsh
def test_rivers_only_mode_builds_river_constraints_contract(tmp_path: Path) -> None:
    output_dir = tmp_path / "runtime_rivers_only"
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
                'source = "geographic_features"',
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
