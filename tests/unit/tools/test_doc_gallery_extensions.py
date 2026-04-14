"""Unit tests for the extended capability-gallery categories and generators."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.doc_gallery.gallery_manifest import build_gallery_specs
from tools.doc_gallery.update_gallery import _build_index_page, _generate_case


def _spec_by_slug(slug: str):
    return next(spec for spec in build_gallery_specs() if spec.slug == slug)


def test_build_gallery_specs_exposes_extended_categories() -> None:
    specs = {spec.slug: spec for spec in build_gallery_specs()}

    assert specs["geometry_constraints_canut"].category == "geometry"
    assert specs["geometry_topography_canut"].category == "geometry"
    assert specs["geometry_indicators_canut"].category == "geometry"
    assert specs["hydraulic_conductivity_square_parameterizations"].category == "hydraulic_properties"
    assert specs["hydraulic_conductivity_irregular_mesh"].category == "hydraulic_properties"
    assert specs["hydraulic_conductivity_depth_dependence"].category == "hydraulic_properties"
    assert specs["hydraulic_conductivity_geology_transfer_brittany"].category == "hydraulic_properties"
    assert specs["hydraulic_conductivity_geology_transfer_variants"].category == "hydraulic_properties"
    assert specs["mesh_constraint_balance_scale_ladder"].category == "mesh"
    assert specs["mesh_resolution_sensitivity_scale_ladder"].category == "mesh"
    assert specs["mesh_zoom_panels_naizin_10km2"].category == "mesh"
    assert specs["example12_map_method_comparison"].category == "method_comparison"
    assert "comparison_config_path" in specs["example12_map_method_comparison"].metadata


def test_build_index_page_lists_extended_categories_when_populated() -> None:
    page = _build_index_page(
        {
            "mesh": [{"slug": "mesh_case"}],
            "validation": [{"slug": "validation_case"}],
            "geographic": [{"slug": "geographic_case"}],
            "hydraulic_properties": [{"slug": "property_case"}],
            "method_comparison": [{"slug": "comparison_case"}],
            "simulation": [{"slug": "simulation_case"}],
        }
    )

    assert ":link: hydraulic_properties" in page
    assert ":link: method_comparison" in page
    assert "   hydraulic_properties" in page
    assert "   method_comparison" in page
    assert "   simulation" in page


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


def test_generate_method_comparison_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("example12_map_method_comparison")
    run_folder = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "projects"
        / "launcher_simulation"
        / "results_simulations"
        / "example12_fast_mf6_mesh_catchment"
    )
    if not run_folder.exists():
        pytest.skip("method comparison run folder not available on this branch")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "method_comparison"
    assert summary["metadata"]["study_area"] == "Naizin catchment"
    assert any(metric["label"].endswith("RMSE") for metric in summary["metrics"])
    assert summary["artifacts"]["extra_repo_paths"]
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "method_comparison"
        / "example12_map_method_comparison.png"
    ).exists()
