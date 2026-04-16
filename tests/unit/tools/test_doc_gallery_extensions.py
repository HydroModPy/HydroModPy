"""Unit tests for the extended capability-gallery categories and generators."""

from __future__ import annotations

from pathlib import Path

from tools.doc_gallery.gallery_manifest import build_gallery_specs
from tools.doc_gallery.update_gallery import _build_category_page, _build_index_page, _generate_case


def _spec_by_slug(slug: str):
    return next(spec for spec in build_gallery_specs() if spec.slug == slug)


def test_build_gallery_specs_exposes_extended_categories() -> None:
    specs = {spec.slug: spec for spec in build_gallery_specs()}

    assert specs["geographic_bdtopage_hydrography_overlay"].category == "geographic"
    assert specs["geographic_nancon_identity_card"].category == "geographic"
    assert specs["geographic_nancon_observed_timeseries"].category == "geographic"
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
    assert specs["headwater_100km2_outlet_2_mf6_transient_reference"].category == "simulation"
    assert specs["regional_lab_headwater_100km2_dry_plan"].category == "simulation"
    assert specs["regional_lab_headwater_100km2_mf6_reference_recipe"].category == "simulation"
    assert specs["regional_lab_headwater_100km2_backend_compare_recipe"].category == "simulation"
    assert specs["regional_lab_headwater_100km2_transient_backend_compare_recipe"].category == "simulation"
    assert specs["example12_map_method_comparison"].category == "method_comparison"
    assert specs["ex12_mf6_nwt_moderate_same_s60"].category == "method_comparison"
    assert specs["ex12_multi_method_moderate"].category == "method_comparison"
    assert "comparison_config_path" in specs["example12_map_method_comparison"].metadata
    assert specs["ex12_multi_method_moderate"].metadata["comparison_family_key"] == "multi_method_suites"
    assert specs["regional_lab_headwater_100km2_backend_compare_recipe"].metadata["regional_lab_recipe_id"] == "backend_compare"


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
    assert "**Data Overview**" in page
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


def test_generate_additional_method_comparison_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("ex12_mf6_nwt_moderate_same_s60")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "method_comparison"
    assert summary["metadata"]["focus_variant_label"] == "NWT annual moderate on 60x60 structured grid"
    assert "outlet_flux_series" in summary["metadata"]["observable_names"]
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "method_comparison"
        / "ex12_mf6_nwt_moderate_same_s60.png"
    ).exists()


def test_generate_diagnostic_method_comparison_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("ex12_multi_method_moderate_causes")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "method_comparison"
    assert summary["metadata"]["focus_variant_label"] == "Boussinesq annual moderate on committed triangular mesh"
    assert "surface_excess_flux_series" in summary["metadata"]["observable_names"]
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "method_comparison"
        / "ex12_multi_method_moderate_causes.png"
    ).exists()


def test_generate_committed_mesh_simulation_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("headwater_100km2_outlet_2_mf6_transient_reference")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "simulation"
    assert summary["metadata"]["workflow_family_key"] == "committed_mesh_replays"
    assert len(summary["images"]) == 5
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "simulation"
        / "headwater_100km2_outlet_2_mf6_transient_reference_flow_state_triptych.png"
    ).exists()


def test_generate_regional_lab_simulation_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("regional_lab_headwater_100km2_dry_plan")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "simulation"
    assert summary["metadata"]["workflow_family_key"] == "regional_orchestration"
    assert summary["metrics"][0]["key"] == "selected_site_count"
    assert summary["artifacts"]["extra_repo_paths"]
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "simulation"
        / "regional_lab_headwater_100km2_dry_plan.png"
    ).exists()


def test_generate_regional_lab_recipe_simulation_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("regional_lab_headwater_100km2_mf6_reference_recipe")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "simulation"
    assert summary["metadata"]["regional_lab_recipe_id"] == "mf6_reference"
    assert summary["metadata"]["recipe_ids"] == ["mf6_reference"]
    assert summary["metrics"][0]["key"] == "candidate_site_count"
    assert summary["metrics"][0]["value"] == 3
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "simulation"
        / "regional_lab_headwater_100km2_mf6_reference_recipe.png"
    ).exists()


def test_generate_regional_lab_recipe_method_comparison_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("regional_lab_headwater_100km2_backend_compare_recipe")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "simulation"
    assert summary["metadata"]["regional_lab_recipe_id"] == "backend_compare"
    assert summary["metadata"]["recipe_ids"] == ["backend_compare"]
    assert summary["metadata"]["candidate_site_count"] == 3
    assert summary["artifacts"]["extra_repo_paths"]
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "simulation"
        / "regional_lab_headwater_100km2_backend_compare_recipe.png"
    ).exists()


def test_build_simulation_category_page_groups_workflow_families() -> None:
    page = _build_category_page(
        "simulation",
        [
            {
                "title": "Runtime mesh case",
                "deck": "Runtime deck",
                "docname": "cases/runtime_mesh_case",
                "metadata": {
                    "study_area": "Naizin",
                    "process_families": ["flow", "transport"],
                    "mesh_supports": ["runtime_gmsh_triangular_mesh"],
                    "flow_solvers": ["MODFLOW 6"],
                    "transport_solvers": ["MODFLOW 6 GWT"],
                    "workflow_family_key": "runtime_mesh_build",
                    "workflow_family_label": "Runtime Mesh Build",
                    "workflow_family_deck": "Runtime-built supports.",
                    "workflow_family_order": 10,
                    "workflow_case_order": 10,
                },
            },
            {
                "title": "Committed mesh case",
                "deck": "Committed deck",
                "docname": "cases/committed_mesh_case",
                "metadata": {
                    "study_area": "Headwater 100 km2 outlet 2",
                    "process_families": ["flow", "postprocess"],
                    "mesh_supports": ["committed_triangular_mesh_input"],
                    "flow_solvers": ["MODFLOW 6"],
                    "workflow_family_key": "committed_mesh_replays",
                    "workflow_family_label": "Committed Mesh Replays",
                    "workflow_family_deck": "Support-reuse workflows.",
                    "workflow_family_order": 20,
                    "workflow_case_order": 10,
                },
            },
            {
                "title": "Regional orchestration case",
                "deck": "Regional orchestration deck",
                "docname": "cases/regional_orchestration_case",
                "metadata": {
                    "study_area": "Brittany regional laboratory",
                    "process_families": ["planning", "simulation", "reporting"],
                    "workflow_family_key": "regional_orchestration",
                    "workflow_family_label": "Regional Orchestration",
                    "workflow_family_deck": "Population-to-recipe planning workflows.",
                    "workflow_family_order": 30,
                    "workflow_case_order": 10,
                },
            },
        ],
    )

    assert "Workflow Families" in page
    assert "\nRuntime Mesh Build\n~~~~~~~~~~~~~~~~~~\n" in page
    assert "\nCommitted Mesh Replays\n~~~~~~~~~~~~~~~~~~~~~~\n" in page
    assert "\nRegional Orchestration\n~~~~~~~~~~~~~~~~~~~~~~\n" in page
    assert "Runtime-built supports." in page
    assert "Support-reuse workflows." in page
    assert "Population-to-recipe planning workflows." in page
    assert ":link: cases/runtime_mesh_case" in page


def test_build_method_comparison_category_page_groups_comparison_families() -> None:
    page = _build_category_page(
        "method_comparison",
        [
            {
                "title": "Same support case",
                "deck": "Same support deck",
                "docname": "cases/same_support_case",
                "metadata": {
                    "study_area": "Naizin",
                    "observable_names": ["watertable_elevation"],
                    "variant_labels": {"a": "MF6", "b": "Boussinesq"},
                    "comparison_family_key": "shared_support_cross_solver",
                    "comparison_family_label": "Same Support, Different Solvers",
                    "comparison_family_deck": "Pure solver-family comparisons.",
                    "comparison_family_order": 10,
                    "comparison_case_order": 10,
                },
            },
            {
                "title": "Multi-method case",
                "deck": "Multi-method deck",
                "docname": "cases/multi_method_case",
                "metadata": {
                    "study_area": "Naizin",
                    "observable_names": ["watertable_depth"],
                    "variant_labels": {"a": "MF6", "b": "NWT", "c": "Boussinesq"},
                    "comparison_family_key": "multi_method_suites",
                    "comparison_family_label": "Multi-Method Suites",
                    "comparison_family_deck": "Broader suites that separate several comparison axes.",
                    "comparison_family_order": 30,
                    "comparison_case_order": 10,
                },
            },
        ],
    )

    assert "Comparison Families" in page
    assert "\nSame Support, Different Solvers\n~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n" in page
    assert "\nMulti-Method Suites\n~~~~~~~~~~~~~~~~~~~\n" in page
    assert "Pure solver-family comparisons." in page
    assert "Broader suites that separate several comparison axes." in page
    assert ":link: cases/same_support_case" in page


def test_generate_bdtopage_hydrography_overlay_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("geographic_bdtopage_hydrography_overlay")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "geographic"
    assert summary["images"][0]["filename"] == "geographic_bdtopage_hydrography_overlay.png"
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "geographic"
        / "geographic_bdtopage_hydrography_overlay.png"
    ).exists()


def test_generate_nancon_identity_card_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("geographic_nancon_identity_card")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "geographic"
    assert len(summary["images"]) == 6
    assert summary["metadata"]["workflow_stage"] == "observation_identity_card"
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "geographic"
        / "geographic_nancon_identity_card_map_dem.png"
    ).exists()


def test_generate_nancon_observed_timeseries_case_smoke(tmp_path: Path) -> None:
    spec = _spec_by_slug("geographic_nancon_observed_timeseries")

    summary = _generate_case(spec, tmp_path)

    assert summary["category"] == "geographic"
    assert len(summary["images"]) == 4
    assert summary["metadata"]["workflow_stage"] == "observed_time_series"
    assert (
        tmp_path
        / "_static"
        / "capability_gallery"
        / "geographic"
        / "geographic_nancon_timeseries_discharge.png"
    ).exists()


def test_build_geographic_category_page_groups_workflow_stages() -> None:
    page = _build_category_page(
        "geographic",
        [
            {
                "title": "Context case",
                "deck": "Context deck",
                "docname": "cases/context_case",
                "metadata": {
                    "workflow_stage": "watershed_context",
                    "workflow_stage_label": "Watershed Context",
                    "workflow_stage_deck": "Frame the basin first.",
                    "workflow_stage_order": 10,
                    "panel_families": ["dem_overview"],
                    "loaded_data_types": ["hydrography"],
                    "reading_order": 10,
                },
            },
            {
                "title": "Observed-series case",
                "deck": "Series deck",
                "docname": "cases/series_case",
                "metadata": {
                    "workflow_stage": "observed_time_series",
                    "workflow_stage_label": "Observed Time Series",
                    "workflow_stage_deck": "Inspect the chronologies.",
                    "workflow_stage_order": 40,
                    "panel_families": ["timeseries_discharge"],
                    "loaded_data_types": ["hydrometry"],
                    "reading_order": 40,
                },
            },
        ],
    )

    assert "Workflow Stages" in page
    assert "\nWatershed Context\n~~~~~~~~~~~~~~~~~\n" in page
    assert "\nObserved Time Series\n~~~~~~~~~~~~~~~~~~~~\n" in page
    assert "Frame the basin first." in page
    assert "Inspect the chronologies." in page
