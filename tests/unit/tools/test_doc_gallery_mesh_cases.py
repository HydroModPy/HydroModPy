"""Unit tests for the mesh-gallery import workflow."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import tools.doc_gallery.update_gallery as update_gallery_module
from tools.doc_gallery.gallery_manifest import build_repo_mesh_gallery_case_specs
from tools.doc_gallery.import_mesh_bundle import import_mesh_bundle_case
from tools.doc_gallery.mesh_case_registry import (
    MESH_GALLERY_CASE_SCHEMA_VERSION,
    MESH_GALLERY_REQUIRED_BUNDLE_FILES,
    REPO_ROOT,
)
from tools.doc_gallery.update_gallery import _build_category_page, _generate_mesh_viewer_case

SAMPLE_BUNDLE = REPO_ROOT / "examples" / "projects" / "08_mesh_viewer" / "sample_bundle"


def _write_dummy_launcher_config(repo_root: Path, relative_path: str) -> None:
    config_path = repo_root / relative_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "[mesh_catchment]\nconstraints_mode = 'geology_rivers'\n",
        encoding="utf-8",
    )


def _build_bundle_with_mesher_figures(tmp_path: Path) -> tuple[Path, Path, Path]:
    bundle_dir = tmp_path / "bundle_with_figures"
    shutil.copytree(SAMPLE_BUNDLE, bundle_dir)

    overview_png = tmp_path / "source_mesh_overview.png"
    regional_png = tmp_path / "source_mesh_regional.png"
    overview_png.write_bytes(b"fake-png-overview")
    regional_png.write_bytes(b"fake-png-regional")

    summary_path = bundle_dir / "mesh_summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["output_figure"] = str(overview_png)
    payload["output_figure_regional"] = str(regional_png)
    summary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return bundle_dir, overview_png, regional_png


def test_import_mesh_bundle_case_creates_canonical_layout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_dummy_launcher_config(
        repo_root,
        "old/launchers/mesh_catchment/scenarios/config_headwater_100km2.toml",
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
        / "projects"
        / "07_mesh_gallery"
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
        == "examples/projects/07_mesh_gallery/100km2/mesh_100km2_outlet_27_geology_rivers_buffer30/viewer_config.toml"
    )
    assert (
        "old/launchers/mesh_catchment/scenarios/config_headwater_100km2.toml"
        in payload["source_paths"]
    )

    viewer_config = viewer_config_path.read_text(encoding="utf-8")
    assert 'bundle_dir = "./bundle"' in viewer_config
    assert 'color_field = "geology_key"' in viewer_config


def test_build_repo_mesh_gallery_case_specs_discovers_imported_cases(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_dummy_launcher_config(
        repo_root,
        "old/launchers/mesh_catchment/scenarios/config_headwater_100km2.toml",
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
        "examples/projects/07_mesh_gallery/100km2/headwater_100km2_outlet_27_rivers_only_buffer30/viewer_config.toml"
    )
    assert spec.case_setup
    assert spec.metadata["comparison_group"] == "100km2::outlet::27"


def test_imported_mesh_case_prefers_copied_mesher_figures_when_available(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_dummy_launcher_config(
        repo_root,
        "old/launchers/mesh_catchment/scenarios/config_headwater_100km2.toml",
    )
    source_bundle, overview_png, regional_png = _build_bundle_with_mesher_figures(tmp_path)

    import_mesh_bundle_case(
        source_bundle=source_bundle,
        scale="100km2",
        variant="geology_rivers_buffer30",
        outlet_id="27",
        repo_root=repo_root,
    )

    case_dir = (
        repo_root
        / "examples"
        / "projects"
        / "07_mesh_gallery"
        / "100km2"
        / "mesh_100km2_outlet_27_geology_rivers_buffer30"
    )
    case_payload = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    assert case_payload["preferred_doc_figure_path"].endswith("/figures/mesh_overview.png")
    assert case_payload["preferred_doc_regional_figure_path"].endswith("/figures/mesh_regional.png")
    assert (case_dir / "figures" / "mesh_overview.png").read_bytes() == overview_png.read_bytes()
    assert (case_dir / "figures" / "mesh_regional.png").read_bytes() == regional_png.read_bytes()

    specs = build_repo_mesh_gallery_case_specs(repo_root=repo_root)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.generator == "mesh_viewer"
    assert spec.image_assets[0].source_path == case_payload["preferred_doc_figure_path"]
    assert spec.image_assets[1].source_path == case_payload["preferred_doc_regional_figure_path"]


def test_generate_mesh_viewer_case_uses_preferred_doc_figure_when_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    _write_dummy_launcher_config(
        repo_root,
        "old/launchers/mesh_catchment/scenarios/config_headwater_100km2.toml",
    )
    source_bundle, overview_png, regional_png = _build_bundle_with_mesher_figures(tmp_path)
    import_mesh_bundle_case(
        source_bundle=source_bundle,
        scale="100km2",
        variant="geology_rivers_buffer30",
        outlet_id="27",
        repo_root=repo_root,
    )

    spec = build_repo_mesh_gallery_case_specs(repo_root=repo_root)[0]
    source_root = tmp_path / "docs_source"
    monkeypatch.setattr(update_gallery_module, "REPO_ROOT", repo_root)
    summary = _generate_mesh_viewer_case(spec, source_root)

    generated_overview = (
        source_root
        / "_static"
        / "capability_gallery"
        / "mesh"
        / "mesh_100km2_outlet_27_geology_rivers_buffer30_overview.png"
    )
    generated_regional = (
        source_root
        / "_static"
        / "capability_gallery"
        / "mesh"
        / "mesh_100km2_outlet_27_geology_rivers_buffer30_regional.png"
    )
    assert generated_overview.read_bytes() == overview_png.read_bytes()
    assert generated_regional.read_bytes() == regional_png.read_bytes()
    assert summary["metrics"][0]["key"] == "node_count"
    assert len(summary["images"]) == 2
    assert summary["metadata"]["scale"] == "100km2"
    assert summary["metadata"]["comparison_group"] == "100km2::outlet::27"


def test_build_mesh_category_page_renders_scale_variant_coverage_matrix() -> None:
    page = _build_category_page(
        "mesh",
        [
            {
                "title": "10 km2 geology+rivers",
                "deck": "Deck",
                "docname": "cases/mesh_10km2_outlet_1_geology_rivers_buffer30",
                "metadata": {
                    "scale": "10km2",
                    "scale_label": "10 km2",
                    "variant": "geology_rivers_buffer30",
                    "variant_label": "Geology + rivers, 30% buffer",
                    "outlet_id": "1",
                },
            },
            {
                "title": "100 km2 rivers only",
                "deck": "Deck",
                "docname": "cases/mesh_100km2_outlet_27_rivers_only_buffer30",
                "metadata": {
                    "scale": "100km2",
                    "scale_label": "100 km2",
                    "variant": "rivers_only_buffer30",
                    "variant_label": "Rivers only, 30% buffer",
                    "outlet_id": "27",
                },
            },
        ],
    )

    assert "Coverage Matrix" in page
    assert "Geology + rivers, 30% buffer" in page
    assert "Rivers only, 30% buffer" in page
    assert "Versioned (outlet 1)" in page
    assert "Versioned (outlet 27)" in page
    assert "Missing" in page


def test_build_mesh_category_page_groups_similar_cases_in_tabs() -> None:
    page = _build_category_page(
        "mesh",
        [
            {
                "title": "Mesh sample bundle",
                "deck": "Deck",
                "docname": "cases/mesh_sample_bundle",
                "images": [],
                "metrics": [],
                "metadata": {},
            },
            {
                "title": "100 km2 geology+rivers",
                "deck": "Deck geology+rivers",
                "docname": "cases/mesh_100km2_outlet_27_geology_rivers_buffer30",
                "images": [
                    {
                        "doc_path": "/_static/capability_gallery/mesh/geology.png",
                        "alt_text": "geology",
                        "caption": "Geology case",
                    }
                ],
                "metrics": [{"label": "Cells", "display": "3922"}],
                "metadata": {
                    "scale": "100km2",
                    "scale_label": "100 km2",
                    "variant": "geology_rivers_buffer30",
                    "variant_label": "Geology + rivers, 30% buffer",
                    "outlet_id": "27",
                    "constraints_mode": "geology_rivers",
                    "comparison_group": "100km2::outlet::27",
                    "comparison_group_title": "100 km2, outlet 27",
                },
            },
            {
                "title": "100 km2 rivers only",
                "deck": "Deck rivers only",
                "docname": "cases/mesh_100km2_outlet_27_rivers_only_buffer30",
                "images": [
                    {
                        "doc_path": "/_static/capability_gallery/mesh/rivers.png",
                        "alt_text": "rivers only",
                        "caption": "Rivers-only case",
                    }
                ],
                "metrics": [{"label": "Cells", "display": "3100"}],
                "metadata": {
                    "scale": "100km2",
                    "scale_label": "100 km2",
                    "variant": "rivers_only_buffer30",
                    "variant_label": "Rivers only, 30% buffer",
                    "outlet_id": "27",
                    "constraints_mode": "rivers_only",
                    "comparison_group": "100km2::outlet::27",
                    "comparison_group_title": "100 km2, outlet 27",
                },
            },
        ],
    )

    assert "Comparable Variants" in page
    assert ".. tab-set::" in page
    assert ".. tab-item:: Geology + rivers, 30% buffer" in page
    assert ".. tab-item:: Rivers only, 30% buffer" in page
    assert (
        "Cross-variant comparisons: 100 km2, outlet 27 "
        "(Geology + rivers, 30% buffer; Rivers only, 30% buffer)."
    ) in page
    assert (
        "See :doc:`the full case page <cases/mesh_100km2_outlet_27_rivers_only_buffer30>`." in page
    )
    assert ":link: cases/mesh_100km2_outlet_27_geology_rivers_buffer30" not in page


def test_build_mesh_category_page_family_coverage_lists_variant_specific_outlets() -> None:
    page = _build_category_page(
        "mesh",
        [
            {
                "title": "10 km2 geology+rivers outlet 1",
                "deck": "Deck geology+rivers outlet 1",
                "docname": "cases/mesh_s3_10km2_outlet_1_geology_rivers_buffer30",
                "images": [],
                "metrics": [],
                "metadata": {
                    "scale": "10km2",
                    "scale_label": "10 km2",
                    "variant": "geology_rivers_buffer30",
                    "variant_label": "Geology + rivers, 30% buffer",
                    "outlet_id": "1",
                    "case_family_key": "s3_10km2",
                    "case_family_label": "10 km2, Strahler 3",
                    "case_family_order": 1,
                    "site_tabs_group_key": "family::s3_10km2",
                    "site_tabs_group_title": "10 km2, Strahler 3",
                    "site_tabs_label": "Outlet 1",
                    "site_tabs_order": 1,
                },
            },
            {
                "title": "10 km2 geology+rivers outlet 2",
                "deck": "Deck geology+rivers outlet 2",
                "docname": "cases/mesh_s3_10km2_outlet_2_geology_rivers_buffer30",
                "images": [],
                "metrics": [],
                "metadata": {
                    "scale": "10km2",
                    "scale_label": "10 km2",
                    "variant": "geology_rivers_buffer30",
                    "variant_label": "Geology + rivers, 30% buffer",
                    "outlet_id": "2",
                    "case_family_key": "s3_10km2",
                    "case_family_label": "10 km2, Strahler 3",
                    "case_family_order": 1,
                    "site_tabs_group_key": "family::s3_10km2",
                    "site_tabs_group_title": "10 km2, Strahler 3",
                    "site_tabs_label": "Outlet 2",
                    "site_tabs_order": 2,
                },
            },
            {
                "title": "10 km2 rivers only outlet 1",
                "deck": "Deck rivers only outlet 1",
                "docname": "cases/mesh_s3_10km2_outlet_1_rivers_only_buffer30",
                "images": [],
                "metrics": [],
                "metadata": {
                    "scale": "10km2",
                    "scale_label": "10 km2",
                    "variant": "rivers_only_buffer30",
                    "variant_label": "Rivers only, 30% buffer",
                    "outlet_id": "1",
                    "case_family_key": "s3_10km2",
                    "case_family_label": "10 km2, Strahler 3",
                    "case_family_order": 1,
                    "comparison_group": "s3_10km2::outlet::1",
                    "comparison_group_title": "10 km2, Strahler 3, outlet 1",
                },
            },
        ],
    )

    assert "Family Coverage" in page
    assert "Variants present" in page
    assert "Coverage detail" in page
    assert "Geology + rivers, 30% buffer" in page
    assert "Rivers only, 30% buffer" in page
    assert "Geology + rivers, 30% buffer: outlet 1, outlet 2" in page
    assert "Rivers only, 30% buffer: outlet 1" in page
