from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import pytest

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

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "reference_2d_geology_conformal_signature.json"
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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


@_skip_no_gmsh
def test_reference_2d_geology_conformal_case_non_regression(
    update_goldens: bool,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "runtime"
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
        summary["mesh_size_fields"]["interface_refinement"]["candidate_interface_curve_count"]
        >= summary["mesh_size_fields"]["interface_refinement"]["interface_curve_count"]
    )
    assert (
        summary["mesh_size_fields"]["interface_refinement"]["scope_filtered_interface_curve_count"]
        == summary["mesh_size_fields"]["interface_refinement"]["interface_curve_count"]
    )
    assert summary["mesh_size_fields"]["interface_refinement"]["refinement_scope_applied"] is False
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
    assert summary["physical_groups_summary"]["surface_group_count"] == len(summary["zone_keys"])
    assert summary["qa_checks"]["coverage_within_tolerance"] is True
    assert summary["qa_checks"]["has_interface_groups"] is True
    assert summary["qa_checks"]["constraints_contract_pass"] is True
    assert len(summary["surface_physical_groups"]) == len(summary["zone_keys"])
    assert any(
        group["name"].startswith("interface::") for group in summary["curve_physical_groups"]
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
