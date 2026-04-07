"""Unit tests for analytical validation-case gallery discovery."""

from __future__ import annotations

from tools.doc_gallery.gallery_manifest import build_gallery_specs
from tools.doc_gallery.update_gallery import _build_case_page
from tools.doc_gallery.validation_case_registry import build_validation_case_records


EXPECTED_VALIDATION_CASE_COUNT = 20


def test_build_validation_case_records_discovers_solver_coverage() -> None:
    records = {record.slug: record for record in build_validation_case_records()}

    assert len(records) == EXPECTED_VALIDATION_CASE_COUNT
    assert records["dupuit_fixed_head_1d"].metadata["solver_variants"] == (
        "modflownwt",
        "modflow6",
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
        "boussinesq",
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
    assert records["late_time_unconfined_pumping_2d"].equations_rst


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
