from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, box

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
        "[case.domain]\n"
        'kind = "vector"\n'
        'path = "domain_window.geojson"\n'
        'id_field = "domain_id"\n'
        'selected_id = "main"\n'
    )
    new_block = (
        "[case.domain]\n" "clip_bbox = [355000.0, 6712500.0, 359000.0, 6716500.0]\n"
    )
    if old_block not in raw:
        raise AssertionError(
            "Unable to build legacy clip_bbox test config: domain block not found"
        )
    migrated = raw.replace(old_block, new_block)

    relative_geology_path = "../../../../../../../data/Brittany_small_test_example/geology/GEO1M_brittany.shp"
    absolute_geology_path = (CASE_TOML.parent / relative_geology_path).resolve()
    migrated = migrated.replace(
        f'path = "{relative_geology_path}"',
        f'path = "{absolute_geology_path.as_posix()}"',
    )
    path.write_text(migrated, encoding="utf-8")


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
    assert summary["mesh_size_fields"]["interface_refinement"]["enabled"] is True
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
    assert len(summary["surface_physical_groups"]) == len(summary["zone_keys"])
    assert any(
        group["name"].startswith("interface::")
        for group in summary["curve_physical_groups"]
    )

    stable = dict(summary)
    stable.pop("output_mesh", None)
    stable.pop("output_summary_json", None)
    stable.pop("output_figure", None)

    if update_goldens:
        _write_json(GOLDEN_FILE, stable)
        return

    expected = _load_json(GOLDEN_FILE)
    assert stable == expected


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
    )

    assert resolved is explicit_trace


def test_resolve_river_trace_for_meshing_falls_back_to_domain_geographic() -> None:
    domain_trace = object()

    class _DomainGeographic:
        river_mesh_trace = domain_trace

    resolved = _resolve_river_trace_for_meshing(
        river_trace=None,
        domain_geographic=_DomainGeographic(),
    )

    assert resolved is domain_trace


def test_resolve_river_trace_for_meshing_returns_none_without_inputs() -> None:
    resolved = _resolve_river_trace_for_meshing(
        river_trace=None,
        domain_geographic=None,
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


def test_resolve_constraints_mode_accepts_valid_modes() -> None:
    assert _resolve_constraints_mode("geology_only") == "geology_only"
    assert _resolve_constraints_mode("rivers_only") == "rivers_only"
    assert _resolve_constraints_mode("geology_rivers") == "geology_rivers"


def test_resolve_constraints_mode_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="constraints_mode must be one of"):
        _ = _resolve_constraints_mode("unsupported_mode")


def test_river_mode_requires_river_trace(tmp_path: Path) -> None:
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
                "[case.zone_meshing]",
                'algorithm = "delaunay"',
                "global_size = 250.0",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires one river trace"):
        run_reference_2d_zone_conformal_case_from_toml(
            config_path,
            section="case",
            output_mesh=tmp_path / "mesh.msh",
            show_plot=False,
        )
