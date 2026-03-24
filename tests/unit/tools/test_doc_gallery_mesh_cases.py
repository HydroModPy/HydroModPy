"""Unit tests for the mesh-gallery import workflow."""

from __future__ import annotations

import json
from pathlib import Path

from tools.doc_gallery.gallery_manifest import build_repo_mesh_gallery_case_specs
from tools.doc_gallery.import_mesh_bundle import import_mesh_bundle_case
from tools.doc_gallery.mesh_case_registry import (
    MESH_GALLERY_CASE_SCHEMA_VERSION,
    MESH_GALLERY_REQUIRED_BUNDLE_FILES,
    REPO_ROOT,
)


SAMPLE_BUNDLE = REPO_ROOT / "examples" / "mesh_viewer" / "sample_bundle"


def _write_dummy_launcher_config(repo_root: Path, relative_path: str) -> None:
    config_path = repo_root / relative_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "[mesh_catchment]\nconstraints_mode = 'geology_rivers'\n",
        encoding="utf-8",
    )


def test_import_mesh_bundle_case_creates_canonical_layout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_dummy_launcher_config(
        repo_root,
        "launchers/mesh_catchment/config_headwater_100km2.toml",
    )

    case_dir = import_mesh_bundle_case(
        source_bundle=SAMPLE_BUNDLE,
        scale="100km2",
        variant="geology_rivers_buffer30",
        outlet_id="27",
        repo_root=repo_root,
    )

    expected_case_dir = (
        repo_root
        / "examples"
        / "mesh_gallery"
        / "100km2"
        / "mesh_100km2_outlet_27_geology_rivers_buffer30"
    )
    assert case_dir == expected_case_dir

    case_json_path = expected_case_dir / "case.json"
    viewer_config_path = expected_case_dir / "viewer_config.toml"
    bundle_dir = expected_case_dir / "bundle"
    assert case_json_path.exists()
    assert viewer_config_path.exists()
    assert (expected_case_dir / "README.md").exists()
    for filename in MESH_GALLERY_REQUIRED_BUNDLE_FILES:
        assert (bundle_dir / filename).exists()

    payload = json.loads(case_json_path.read_text(encoding="utf-8"))
    assert payload["case_schema_version"] == MESH_GALLERY_CASE_SCHEMA_VERSION
    assert payload["scale"] == "100km2"
    assert payload["variant"] == "geology_rivers_buffer30"
    assert payload["outlet_id"] == "27"
    assert (
        payload["config_path"]
        == "examples/mesh_gallery/100km2/mesh_100km2_outlet_27_geology_rivers_buffer30/viewer_config.toml"
    )
    assert "launchers/mesh_catchment/config_headwater_100km2.toml" in payload["source_paths"]

    viewer_config = viewer_config_path.read_text(encoding="utf-8")
    assert 'bundle_dir = "./bundle"' in viewer_config
    assert 'color_field = "geology_key"' in viewer_config


def test_build_repo_mesh_gallery_case_specs_discovers_imported_cases(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_dummy_launcher_config(
        repo_root,
        "launchers/mesh_catchment/config_headwater_100km2.toml",
    )

    import_mesh_bundle_case(
        source_bundle=SAMPLE_BUNDLE,
        scale="100km2",
        variant="rivers_only_buffer30",
        outlet_id="27",
        repo_root=repo_root,
        case_slug="headwater_100km2_outlet_27_rivers_only_buffer30",
        title="Headwater 100 km2, outlet 27, rivers only",
    )

    specs = build_repo_mesh_gallery_case_specs(repo_root=repo_root)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.slug == "headwater_100km2_outlet_27_rivers_only_buffer30"
    assert spec.category == "mesh"
    assert spec.generator == "mesh_viewer"
    assert spec.metric_specs[0].key == "node_count"
    assert spec.metadata["config_path"] == (
        "examples/mesh_gallery/100km2/headwater_100km2_outlet_27_rivers_only_buffer30/viewer_config.toml"
    )
    assert spec.case_setup
