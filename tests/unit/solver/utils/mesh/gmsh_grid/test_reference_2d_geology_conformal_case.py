from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

try:
    import gmsh  # noqa: F401
    _gmsh_available = True
except (ImportError, OSError):
    _gmsh_available = False
_skip_no_gmsh = pytest.mark.skipif(not _gmsh_available, reason="gmsh not available")

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.run_case_zone_conformal import (
    _clip_river_trace_to_domain,
    _resolve_constraints_mode,
    _resolve_river_trace_for_meshing,
    run_reference_2d_zone_conformal_case_from_toml,
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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_legacy_clip_bbox_case_toml(path: Path) -> None:
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
            "Unable to build legacy clip_bbox test config: domain block not found"
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
    assert summary["interface_scope"]["domain_kind"] == "vector"
    assert summary["refinement_scope"]["domain_kind"] == "vector"
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
    stable.pop("refinement_scope", None)
    stable.pop("domain_source_path", None)
    stable.pop("source_path", None)
    interface_refinement = dict(stable["mesh_size_fields"]["interface_refinement"])
    interface_refinement.pop("candidate_interface_curve_count", None)
    interface_refinement.pop("scope_filtered_interface_curve_count", None)
    interface_refinement.pop("refinement_scope_applied", None)
    stable["mesh_size_fields"] = {"interface_refinement": interface_refinement}

    if update_goldens:
        _write_json(GOLDEN_FILE, stable)
        return

    expected = _load_json(GOLDEN_FILE)
    assert stable == expected


@_skip_no_gmsh
def test_reference_2d_geology_conformal_legacy_clip_bbox_rejected() -> None:
    output_dir = (
        Path.cwd()
        / "scratch_tests"
        / "reference_2d_geology_conformal"
        / "runtime_legacy_clip_bbox"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    legacy_toml = output_dir / "case_config_legacy_clip_bbox.toml"
    _write_legacy_clip_bbox_case_toml(legacy_toml)

    with pytest.raises(ValueError, match="clip_bbox is no longer supported"):
        run_reference_2d_zone_conformal_case_from_toml(
            legacy_toml,
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
        rivers_cfg={"source": "domain_geographic"},
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
        rivers_cfg={"source": "domain_geographic"},
        config_path=Path.cwd(),
    )

    assert resolved is domain_trace


def test_resolve_river_trace_for_meshing_returns_none_without_inputs() -> None:
    resolved = _resolve_river_trace_for_meshing(
        river_trace=None,
        domain_geographic=None,
        rivers_cfg={"source": "domain_geographic"},
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

@_skip_no_gmsh
def test_geographic_scopes_limit_interfaces_and_refinement() -> None:
    output_dir = (
        Path.cwd()
        / "scratch_tests"
        / "reference_2d_geology_conformal"
        / "runtime_geographic_scopes"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "case_geographic_scopes.toml"
    _write_geographic_scope_case_toml(config_path)

    support_path = output_dir / "support.geojson"
    refinement_path = output_dir / "refinement.geojson"
    interface_path = output_dir / "interface.geojson"
    _write_scope_vector(
        support_path,
        bounds=(355000.0, 6712500.0, 359000.0, 6716500.0),
    )
    _write_scope_vector(
        refinement_path,
        bounds=(355500.0, 6712900.0, 358500.0, 6716100.0),
    )
    _write_scope_vector(
        interface_path,
        bounds=(356000.0, 6713300.0, 358000.0, 6715700.0),
    )

    summary = run_reference_2d_zone_conformal_case_from_toml(
        config_path,
        section="case",
        output_mesh=output_dir / "reference_2d_zone_conformal_geographic_scopes.msh",
        output_summary_json=output_dir
        / "reference_2d_zone_conformal_geographic_scopes_summary.json",
        domain_geographic=SimpleNamespace(
            box_buff_shp=str(support_path),
            watershed_box_shp=str(refinement_path),
            watershed_shp=str(interface_path),
        ),
        show_plot=False,
    )

    assert summary["domain_kind"] == "geographic_box_buffer"
    assert summary["interface_scope"]["domain_kind"] == "geographic_watershed"
    assert summary["refinement_scope"]["domain_kind"] == "geographic_watershed_box"
    assert "domain_background" in summary["zone_keys"]
    refinement_summary = summary["mesh_size_fields"]["interface_refinement"]
    assert refinement_summary["refinement_scope_applied"] is True
    assert (
        refinement_summary["scope_filtered_interface_curve_count"]
        <= refinement_summary["candidate_interface_curve_count"]
    )
    assert summary["n_cells"] > 0
    assert summary["n_nodes"] > 0


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
