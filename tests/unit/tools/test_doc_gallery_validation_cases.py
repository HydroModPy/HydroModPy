"""Unit tests for analytical validation-case gallery discovery."""

from __future__ import annotations

from types import SimpleNamespace

from tools.doc_gallery.gallery_manifest import GalleryCaseSpec
from tools.doc_gallery.gallery_manifest import build_gallery_specs
from tools.doc_gallery.update_gallery import _build_category_page
from tools.doc_gallery.update_gallery import _build_case_page, _generate_validation_case
from tools.doc_gallery.validation_case_registry import build_validation_case_records


EXPECTED_VALIDATION_CASE_COUNT = 23


def test_build_validation_case_records_discovers_solver_coverage() -> None:
    records = {record.slug: record for record in build_validation_case_records()}

    assert len(records) == EXPECTED_VALIDATION_CASE_COUNT
    assert records["dupuit_fixed_head_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "modflow6_irregular_tri",
        "boussinesq",
    )
    assert records["dupuit_circular_island_ocean_2d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "boussinesq",
    )
    assert records["linearized_unconfined_boundary_piecewise_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "boussinesq",
    )
    assert records["boussinesq_fixed_head_piecewise_k_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "modflow6_irregular_tri",
        "boussinesq",
    )
    assert records["boussinesq_uniform_recharge_piecewise_k_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "modflow6_irregular_tri",
        "boussinesq",
    )
    assert records["boussinesq_sloping_substratum_constant_thickness_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "modflow6_irregular_tri",
        "boussinesq",
    )
    assert records["boussinesq_sloping_substratum_fixed_head_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "modflow6_irregular_tri",
        "boussinesq",
    )
    assert records["boussinesq_sloping_substratum_uniform_recharge_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "modflow6_irregular_tri",
        "boussinesq",
    )
    assert records["linearized_unconfined_drainage_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "modflow6_irregular_tri",
    )
    assert records["linearized_unconfined_hillslope_drainage_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "modflow6_irregular_tri",
    )
    assert records["boussinesq_hillslope_interception_1d"].metadata["solver_variants"] == (
        "boussinesq",
    )
    assert records["late_time_unconfined_pumping_2d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "boussinesq",
    )
    assert records["brutsaert_recession_linearized_deep_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "boussinesq",
    )
    assert records["brutsaert_recession_boussinesq_thin_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
        "boussinesq",
    )
    assert records["boussinesq_sloping_substratum_constant_thickness_1d"].equations_rst
    assert records["boussinesq_sloping_substratum_fixed_head_1d"].equations_rst
    assert records["boussinesq_sloping_substratum_uniform_recharge_1d"].equations_rst
    assert records["late_time_unconfined_pumping_2d"].equations_rst
    assert records["boussinesq_sloping_substratum_constant_thickness_1d"].metadata["process_family"] == "flow"
    assert (
        records["boussinesq_sloping_substratum_constant_thickness_1d"].metadata["validation_family"]
        == "steady_1d_boussinesq_topography_sloping_substratum"
    )
    assert records["boussinesq_sloping_substratum_fixed_head_1d"].metadata["geometry_family"] == "hillslope_1d"
    assert (
        records["boussinesq_sloping_substratum_uniform_recharge_1d"].metadata["validation_family"]
        == "steady_1d_boussinesq_topography_sloping_substratum"
    )
    assert (
        records["late_time_unconfined_pumping_2d"].metadata["validation_family"]
        == "transient_2d_radial_response"
    )
    assert records["boussinesq_hillslope_interception_1d"].metadata["reference_type"] == "semi_analytical"


def test_build_gallery_specs_exposes_validation_inventory() -> None:
    validation_specs = [spec for spec in build_gallery_specs() if spec.category == "validation"]
    record_slugs = {record.slug for record in build_validation_case_records()}

    assert len(validation_specs) == EXPECTED_VALIDATION_CASE_COUNT
    assert {spec.slug for spec in validation_specs} == record_slugs
    assert validation_specs[0].generator == "validation_case"
    assert validation_specs[0].metadata["solver_variants"]


def test_build_case_page_renders_solver_tabs_when_multiple_variants_exist() -> None:
    case = {
        "title": "Synthetic Validation Case",
        "summary": "Synthetic summary.",
        "case_setup": ["One synthetic setup bullet."],
        "what_it_shows": ["One synthetic purpose bullet."],
        "metrics": [],
        "reference_highlights": ["One synthetic analytical bullet."],
        "equations_rst": [r"h(x)=x"],
        "reproduction_command": "python -m validation_cases.synthetic.run_case --no-show",
        "gallery_update_command": "python -m tools.doc_gallery",
        "source_paths": ["validation_cases/synthetic/run_case.py"],
        "artifacts": {
            "image_repo_paths": [
                "docs/readthedocs/source/_static/capability_gallery/validation/synthetic__modflownwt.png",
                "docs/readthedocs/source/_static/capability_gallery/validation/synthetic__boussinesq.png",
            ],
            "summary_json_repo_path": "docs/readthedocs/source/_static/capability_gallery/validation/synthetic_summary.json",
        },
        "solver_runs": [
            {
                "solver": "modflownwt",
                "solver_display_name": "MODFLOW-NWT",
                "image": {
                    "doc_path": "/_static/capability_gallery/validation/synthetic__modflownwt.png",
                    "alt_text": "MODFLOW-NWT figure",
                    "caption": "MODFLOW-NWT synthetic figure.",
                },
                "metric_lines": ["RMSE: 0.0010 m"],
                "config_path": "validation_cases/synthetic/config_modflownwt.toml",
                "tolerance_path": "validation_cases/synthetic/tolerances.toml",
                "expected_output": "Expected shape: 5 x 40",
                "command": "python -m validation_cases.synthetic.run_case --no-show --solver modflownwt",
            },
            {
                "solver": "boussinesq",
                "solver_display_name": "Boussinesq",
                "image": {
                    "doc_path": "/_static/capability_gallery/validation/synthetic__boussinesq.png",
                    "alt_text": "Boussinesq figure",
                    "caption": "Boussinesq synthetic figure.",
                },
                "metric_lines": ["RMSE: 0.0020 m"],
                "config_path": "validation_cases/synthetic/config_boussinesq.toml",
                "tolerance_path": "validation_cases/synthetic/tolerances_boussinesq.toml",
                "expected_output": "Expected shape: 3 x 40",
                "command": "python -m validation_cases.synthetic.run_case --no-show --solver boussinesq",
            },
        ],
        "metadata": {
            "default_solver": "modflownwt",
        },
    }

    page = _build_case_page(case)

    assert "Solver Coverage" in page
    assert ".. tab-set::" in page
    assert ".. tab-item:: MODFLOW-NWT" in page
    assert ".. tab-item:: Boussinesq" in page
    assert "Config file: ``validation_cases/synthetic/config_modflownwt.toml``" in page


def test_build_validation_category_page_groups_cases_by_family() -> None:
    page = _build_category_page(
        "validation",
        [
            {
                "slug": "synthetic_core_case",
                "title": "Synthetic Core Case",
                "deck": "One core-flow benchmark.",
                "docname": "cases/synthetic_core_case",
                "metadata": {
                    "solver_variants": ("modflownwt", "modflow6"),
                    "process_family": "flow",
                    "process_family_label": "Flow",
                    "validation_family": "core_1d_steady",
                    "validation_family_label": "Core 1D Steady",
                    "validation_family_order": 10,
                    "reference_type": "analytical_exact",
                    "reference_type_label": "Analytical Exact",
                    "regime": "steady",
                    "dimension": "1d",
                },
            },
            {
                "slug": "synthetic_hillslope_case",
                "title": "Synthetic Hillslope Case",
                "deck": "One hillslope benchmark.",
                "docname": "cases/synthetic_hillslope_case",
                "metadata": {
                    "solver_variants": ("boussinesq",),
                    "process_family": "flow",
                    "process_family_label": "Flow",
                    "validation_family": "hillslopes",
                    "validation_family_label": "Hillslopes",
                    "validation_family_order": 20,
                    "reference_type": "semi_analytical",
                    "reference_type_label": "Semi-Analytical / Diagnostic",
                    "regime": "steady",
                    "dimension": "1d",
                },
            },
        ],
    )

    assert "Grouped Benchmarks" in page
    assert "\nFlow\n~~~~\n" in page
    assert "\nCore 1D Steady\n^^^^^^^^^^^^^^\n" in page
    assert "\nHillslopes\n^^^^^^^^^^\n" in page
    assert "Process families populated today: Flow (2)." in page
    assert "Synthetic Core Case" in page
    assert "Synthetic Hillslope Case" in page


def test_generate_validation_case_skips_missing_solver_figures(
    tmp_path,
    monkeypatch,
) -> None:
    def comparison_function(*, caller_file, timeout, solver):
        return SimpleNamespace(
            solver=solver,
            observable_name="head",
            metadata={"solver": solver},
            tolerances={"rmse": 0.1},
        )

    def plotting_function(comparison, *, output_png, show_plot):
        if comparison.solver == "modflownwt":
            output_png.parent.mkdir(parents=True, exist_ok=True)
            output_png.write_bytes(b"fake-png")

    def metric_builder(comparison):
        return [f"Solver: {comparison.solver}"]

    fake_module = SimpleNamespace(
        comparison_function=comparison_function,
        plotting_function=plotting_function,
        metric_builder=metric_builder,
    )
    monkeypatch.setattr(
        "tools.doc_gallery.update_gallery.importlib.import_module",
        lambda name: fake_module,
    )

    spec = GalleryCaseSpec(
        slug="synthetic_validation_case",
        title="Synthetic Validation Case",
        category="validation",
        deck="Synthetic deck.",
        summary="Synthetic summary.",
        what_it_shows=("One synthetic purpose bullet.",),
        reproduction_command="python -m validation_cases.synthetic.run_case --no-show",
        source_paths=("README.md",),
        generator="validation_case",
        image_assets=(),
        metadata={
            "run_case_module": "validation_cases.synthetic.run_case",
            "comparison_function_name": "comparison_function",
            "plotting_function_name": "plotting_function",
            "metric_builder_name": "metric_builder",
            "run_case_file": "README.md",
            "case_dir": "validation_cases/synthetic",
            "solver_variants": ("modflownwt", "boussinesq"),
            "default_solver": "modflownwt",
            "solver_details": {
                "modflownwt": {"display_name": "MODFLOW-NWT"},
                "boussinesq": {"display_name": "Boussinesq"},
            },
        },
    )

    summary = _generate_validation_case(spec, tmp_path)

    solver_runs = {run["solver"]: run for run in summary["solver_runs"]}
    assert solver_runs["modflownwt"]["image"] is not None
    assert solver_runs["boussinesq"]["image"] is None
    assert summary["artifacts"]["image_repo_paths"] == [
        "docs/readthedocs/source/_static/capability_gallery/validation/synthetic_validation_case__modflownwt.png"
    ]

    page = _build_case_page(summary)
    assert "synthetic_validation_case__modflownwt.png" in page
    assert "synthetic_validation_case__boussinesq.png" not in page
