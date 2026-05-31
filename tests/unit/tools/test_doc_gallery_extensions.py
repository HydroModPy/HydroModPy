"""Unit tests for the extended capability-gallery categories and generators."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from shutil import copyfile

import pytest

import tools.doc_gallery.import_simulation_comparison as import_simulation_comparison
from tools.doc_gallery.gallery_manifest import build_gallery_specs
from tools.doc_gallery.gallery_simulation_comparison_specs import (
    build_published_simulation_comparison_specs,
)
from tools.doc_gallery.update_gallery import (
    _build_index_page,
    _generate_case,
    _should_preserve_previous_case_summary,
)


def _spec_by_slug(slug: str):
    return next(spec for spec in build_gallery_specs() if spec.slug == slug)


def test_build_gallery_specs_exposes_extended_categories() -> None:
    specs = {spec.slug: spec for spec in build_gallery_specs()}

    assert specs["geometry_constraints_canut"].category == "geometry"
    assert specs["geometry_topography_canut"].category == "geometry"
    assert specs["geometry_indicators_canut"].category == "geometry"
    assert (
        specs["hydraulic_conductivity_square_parameterizations"].category == "hydraulic_properties"
    )
    assert specs["hydraulic_conductivity_irregular_mesh"].category == "hydraulic_properties"
    assert specs["hydraulic_conductivity_depth_dependence"].category == "hydraulic_properties"
    assert (
        specs["hydraulic_conductivity_geology_transfer_brittany"].category == "hydraulic_properties"
    )
    assert (
        specs["hydraulic_conductivity_geology_transfer_variants"].category == "hydraulic_properties"
    )
    assert specs["mesh_constraint_balance_scale_ladder"].category == "mesh"
    assert specs["mesh_resolution_sensitivity_scale_ladder"].category == "mesh"
    assert specs["mesh_zoom_panels_naizin_10km2"].category == "mesh"
    assert specs["example12_map_simulation_comparison"].category == "simulation_comparison"
    assert "comparison_summary_path" in specs["example12_map_simulation_comparison"].metadata
    assert not any(
        path.endswith(
            "example12_map_simulation_comparison_summary.json",
        )
        for path in specs["example12_map_simulation_comparison"].source_paths
    )
    assert not any(
        path.endswith("regional_lab_headwater_100km2_dry_plan_summary.json")
        for path in specs["regional_lab_headwater_100km2_dry_plan"].source_paths
    )


def test_build_index_page_lists_extended_categories_when_populated() -> None:
    page = _build_index_page(
        {
            "mesh": [{"slug": "mesh_case"}],
            "validation": [{"slug": "validation_case"}],
            "geographic": [{"slug": "geographic_case"}],
            "hydraulic_properties": [{"slug": "property_case"}],
            "simulation_comparison": [{"slug": "comparison_case"}],
            "simulation": [{"slug": "simulation_case"}],
        }
    )

    assert ":link: hydraulic_properties" in page
    assert ":link: simulation_comparison" in page
    assert "   hydraulic_properties" in page
    assert "   simulation_comparison" in page
    assert "   simulation" in page


def test_published_simulation_comparison_specs_are_discovered(tmp_path: Path) -> None:
    case_root = (
        tmp_path
        / "examples"
        / "projects"
        / "09_capability_gallery"
        / "simulation_comparison"
        / "case"
    )
    case_root.mkdir(parents=True)
    for name in ("comparison_manifest.json", "summary_metrics.csv"):
        (case_root / name).write_text("", encoding="utf-8")
    (case_root / "case.json").write_text(
        json.dumps(
            {
                "slug": "natural_site_03_mf6_bouss",
                "title": "Natural Site 03 MF6/Boussinesq",
                "deck": "Published comparison artifacts.",
                "summary": "Stable artifact publication for the natural testbed.",
                "study_area": "Natural N1 10 km2 testbed",
                "focus_simulation_id": "bouss_candidate",
                "comparison_case_order": 30,
                "what_it_shows": ["Published comparison artifacts drive the page."],
            }
        ),
        encoding="utf-8",
    )

    specs = build_published_simulation_comparison_specs(repo_root=tmp_path)

    assert len(specs) == 1
    spec = specs[0]
    assert spec.slug == "natural_site_03_mf6_bouss"
    assert spec.generator == "simulation_comparison_case"
    assert spec.metadata["comparison_config_path"].endswith("case/comparison.toml")
    assert spec.metadata["focus_simulation_id"] == "bouss_candidate"
    assert spec.metadata["publish_full_artifacts"] is False
    assert any(path.endswith("comparison_manifest.json") for path in spec.source_paths)
    assert any(path.endswith("summary_metrics.csv") for path in spec.source_paths)
    assert spec.image_assets[0].filename == "natural_site_03_mf6_bouss.png"


def test_import_simulation_comparison_publishes_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_project_name = "_".join(("launcher", "simulation"))
    source_root = tmp_path / "comparison"
    source_root.mkdir()
    (source_root / "comparison_manifest.json").write_text(
        json.dumps(
            {
                "comparison_id": "site_03_natural_n1_10km2_mf6_bouss",
                "reference_simulation": "mf6_ref",
                "simulations": [
                    {"id": "mf6_ref"},
                    {
                        "id": "bouss_candidate",
                        "run_folder": (
                            f"examples/projects/{legacy_project_name}/"
                            "results_reused_real_meshes/site_03/"
                            "results_simulations/bouss_candidate"
                        ),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (source_root / "comparison_metrics.json").write_text(
        json.dumps(
            {
                "summary": [
                    {
                        "simulation_id": "bouss_candidate",
                        "observable": "head_map_last",
                        "unit": "m",
                        "n_pairs": 2,
                        "bias": 0.1,
                        "mae": 0.2,
                        "rmse": 0.3,
                        "max_abs_error": 0.4,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (source_root / "source_manifest.json").write_text(
        json.dumps(
            {
                "config_path": (
                    f"examples/projects/{legacy_project_name}/"
                    "run_simulation_comparison_site_03.toml"
                )
            }
        ),
        encoding="utf-8",
    )
    published_root = tmp_path / "published"
    monkeypatch.setattr(import_simulation_comparison, "PUBLISHED_ROOT", published_root)

    destination = import_simulation_comparison.publish_comparison(
        source_root,
        slug="natural_site_03_mf6_bouss",
        title="Natural Site 03 MF6/Boussinesq",
        study_area="Natural N1 10 km2 testbed",
    )

    assert destination == published_root / "natural_site_03_mf6_bouss"
    assert (destination / "comparison_manifest.json").exists()
    assert (destination / "summary_metrics.csv").exists()
    published_manifest_text = (destination / "comparison_manifest.json").read_text(encoding="utf-8")
    assert legacy_project_name not in published_manifest_text
    assert "simulation_regression" not in published_manifest_text
    assert "run_folder" not in published_manifest_text
    assert legacy_project_name not in (destination / "source_manifest.json").read_text(
        encoding="utf-8"
    )
    assert not (destination / "comparison_metrics.json").exists()
    assert not (destination / "observables.csv").exists()
    case_payload = json.loads((destination / "case.json").read_text(encoding="utf-8"))
    assert case_payload["slug"] == "natural_site_03_mf6_bouss"
    assert case_payload["title"] == "Natural Site 03 MF6/Boussinesq"
    assert case_payload["focus_simulation_id"] == "bouss_candidate"
    assert case_payload["publish_full_artifacts"] is False


def test_import_simulation_comparison_discovers_testbed_roots(tmp_path: Path) -> None:
    first = tmp_path / "testbed" / "comparisons" / "site_03"
    second = tmp_path / "testbed" / "comparison"
    duplicate = tmp_path / "testbed" / "comparisons" / "site_03"
    for root in (first, second):
        root.mkdir(parents=True)
        (root / "comparison_manifest.json").write_text("{}", encoding="utf-8")

    roots = import_simulation_comparison.discover_comparison_roots(
        comparison_roots=[duplicate],
        testbed_output_roots=[tmp_path / "testbed"],
    )

    assert roots == [first.resolve(), second.resolve()]


def test_generate_square_property_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("hydraulic_conductivity_square_parameterizations")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "hydraulic_properties"
    assert len(summary["metrics"]) == 4
    assert summary["metadata"]["vertical_profiles"] == [
        "No profile",
        "Exponential",
        "Tabulated",
    ]
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "hydraulic_properties"
        / "hydraulic_conductivity_square_parameterizations.png"
    ).exists()


def test_generate_irregular_property_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("hydraulic_conductivity_irregular_mesh")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "hydraulic_properties"
    assert len(summary["metrics"]) == 4
    assert summary["metadata"]["irregular_mesh_seed"] == 23
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "hydraulic_properties"
        / "hydraulic_conductivity_irregular_mesh.png"
    ).exists()


def test_generate_depth_property_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("hydraulic_conductivity_depth_dependence")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "hydraulic_properties"
    assert summary["metadata"]["depth_profiles"] == ["exponential", "tabulated"]
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "hydraulic_properties"
        / "hydraulic_conductivity_depth_dependence.png"
    ).exists()


def _simulation_comparison_generation_spec(tmp_path: Path, *, publish_full_artifacts: bool):
    spec = _spec_by_slug("example12_map_simulation_comparison")
    static_root = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "source"
        / "_static"
        / "capability_gallery"
        / "simulation_comparison"
    )
    artifact_map = {
        "example12_map_simulation_comparison_comparison_manifest.json": "comparison_manifest.json",
        "example12_map_simulation_comparison_comparison_metrics.json": "comparison_metrics.json",
        "example12_map_simulation_comparison_observables.csv": "observables.csv",
    }
    committed_root = tmp_path / "simulation_comparison" / "example12_map_simulation_comparison"
    committed_root.mkdir(parents=True)
    for source_name, target_name in artifact_map.items():
        source_path = static_root / source_name
        assert source_path.exists()
        copyfile(source_path, committed_root / target_name)

    config_path = tmp_path / "run_comparison_example12_map_existing.toml"
    config_path.write_text(
        f"""
[comparison]
comparison_id = "example12_map_simulation_comparison"
output_root = "{committed_root.as_posix()}"
reference_simulation = "mf6_gmsh_existing"

[comparison.execution]
run_simulations = false

[[comparison.simulation]]
id = "mf6_gmsh_existing"
label = "MODFLOW 6"
run_folder = "mf6_gmsh_existing"

[[comparison.simulation]]
id = "boussinesq_reused_gmsh"
label = "Boussinesq"
run_folder = "boussinesq_reused_gmsh"

[[comparison.observable]]
name = "watertable_elevation_map"
variable = "watertable_elevation"
support = "map"
time = "last"
unit = "m"
""",
        encoding="utf-8",
    )
    return replace(
        spec,
        generator="simulation_comparison_case",
        source_paths=(
            config_path.as_posix(),
            *((committed_root / name).as_posix() for name in artifact_map.values()),
        ),
        metadata={
            **spec.metadata,
            "comparison_config_path": config_path.as_posix(),
            "publish_full_artifacts": publish_full_artifacts,
        },
    )


def test_generate_simulation_comparison_case_smoke(tmp_path: Path) -> None:
    spec = _simulation_comparison_generation_spec(tmp_path, publish_full_artifacts=True)

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "simulation_comparison"
    assert summary["metadata"]["study_area"] == "Naizin catchment"
    assert any(metric["label"].endswith("RMSE") for metric in summary["metrics"])
    assert summary["artifacts"]["extra_repo_paths"]
    assert any(
        path.endswith("example12_map_simulation_comparison_comparison_metrics.json")
        for path in summary["artifacts"]["extra_repo_paths"]
    )
    public_observables = (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "simulation_comparison"
        / "example12_map_simulation_comparison_observables.csv"
    )
    header = public_observables.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert "source_path" not in header
    assert "run_folder" not in header
    public_manifest = (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "simulation_comparison"
        / "example12_map_simulation_comparison_comparison_manifest.json"
    ).read_text(encoding="utf-8")
    assert "run_folder" not in public_manifest
    assert "config_path" not in public_manifest
    assert ":\\\\" not in public_manifest
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "simulation_comparison"
        / "example12_map_simulation_comparison.png"
    ).exists()


def test_generate_simulation_comparison_case_can_publish_compact_static_artifacts(
    tmp_path: Path,
) -> None:
    spec = _simulation_comparison_generation_spec(tmp_path, publish_full_artifacts=False)
    static_dir = tmp_path / "_static" / "capability_gallery" / "simulation_comparison"
    static_dir.mkdir(parents=True)
    stale_names = (
        "example12_map_simulation_comparison_comparison_metrics.json",
        "example12_map_simulation_comparison_observables.csv",
        "example12_map_simulation_comparison_difference_metrics.csv",
    )
    for name in stale_names:
        (static_dir / name).write_text("stale\n", encoding="utf-8")

    summary = _generate_case(spec, tmp_path)

    extra_paths = summary["artifacts"]["extra_repo_paths"]
    assert any(
        path.endswith("example12_map_simulation_comparison_comparison_manifest.json")
        for path in extra_paths
    )
    assert any(
        path.endswith("example12_map_simulation_comparison_summary_metrics.csv")
        for path in extra_paths
    )
    assert not any(path.endswith("observables.csv") for path in extra_paths)
    assert not any(path.endswith("comparison_metrics.json") for path in extra_paths)
    assert not any(path.endswith("difference_metrics.csv") for path in extra_paths)
    assert all(not (static_dir / name).exists() for name in stale_names)


def test_compact_simulation_comparison_summary_can_reduce_artifact_count() -> None:
    previous_summary = {
        "images": [{"repo_path": "docs/source/_static/capability_gallery/case.png"}],
        "metrics": [{"key": "rmse"}],
        "artifacts": {
            "image_repo_paths": ["docs/source/_static/capability_gallery/case.png"],
            "extra_repo_paths": [
                "docs/source/_static/capability_gallery/case_manifest.json",
                "docs/source/_static/capability_gallery/case_metrics.json",
                "docs/source/_static/capability_gallery/case_observables.csv",
            ],
        },
        "metadata": {},
    }
    new_summary = {
        **previous_summary,
        "artifacts": {
            "image_repo_paths": ["docs/source/_static/capability_gallery/case.png"],
            "extra_repo_paths": [
                "docs/source/_static/capability_gallery/case_manifest.json",
            ],
        },
        "metadata": {"publish_full_artifacts": False},
    }

    assert not _should_preserve_previous_case_summary(
        previous_summary=previous_summary,
        new_summary=new_summary,
    )
