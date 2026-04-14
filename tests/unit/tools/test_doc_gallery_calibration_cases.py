"""Unit tests for calibration capability-gallery discovery."""

from __future__ import annotations

from tools.doc_gallery.calibration_case_registry import build_calibration_case_records
from tools.doc_gallery.gallery_manifest import build_gallery_specs
from tools.doc_gallery.update_gallery import (
    _build_calibration_intercomparison_page,
    _build_case_page,
    _build_calibration_intercomparison_rows,
    _with_parameter_docs,
)


EXPECTED_CALIBRATION_CASE_COUNT = 4


def test_build_calibration_case_records_discovers_curated_benchmarks() -> None:
    records = {record.slug: record for record in build_calibration_case_records()}

    assert len(records) == EXPECTED_CALIBRATION_CASE_COUNT
    assert (
        records["calibration_twin_dupuit_fixed_head_modflow6"].metadata["solver_name"]
        == "modflow6"
    )
    assert (
        records["calibration_twin_dupuit_fixed_head_posterior_modflow6"].metadata[
            "display_method_name"
        ]
        == "da_mh_gp"
    )
    assert "gp_mapping" in records[
        "calibration_twin_linearized_recharge_step_modflow6"
    ].metadata["method_names"]
    assert "da_mh_gp" in records[
        "calibration_twin_linearized_recharge_step_modflow6"
    ].metadata["method_names"]
    assert "cma_es" in records[
        "calibration_twin_dupuit_fixed_head_modflow6"
    ].metadata["method_names"]
    assert records[
        "calibration_twin_boussinesq_fixed_head_piecewise_k_modflow6"
    ].metadata["output_names"] == [
        "head_west",
        "head_middle",
        "head_east",
        "q_east",
    ]


def test_build_gallery_specs_exposes_calibration_inventory() -> None:
    calibration_specs = [
        spec for spec in build_gallery_specs() if spec.category == "calibration"
    ]
    record_slugs = {record.slug for record in build_calibration_case_records()}

    assert len(calibration_specs) == EXPECTED_CALIBRATION_CASE_COUNT
    assert {spec.slug for spec in calibration_specs} == record_slugs
    assert all(spec.generator == "calibration_case" for spec in calibration_specs)


def test_build_case_page_renders_calibration_parameter_sections() -> None:
    case = {
        "category": "calibration",
        "title": "Synthetic Calibration Case",
        "summary": "Synthetic calibration summary.",
        "case_setup": ["One setup bullet."],
        "what_it_shows": ["One purpose bullet."],
        "metrics": [
            {
                "label": "Calibration total",
                "key": "calibration_time_seconds",
                "value": 1.23,
                "display": "1.23 s",
            }
        ],
        "key_parameters": [],
        "how_to_read": [],
        "next_steps": [],
        "reference_highlights": [],
        "equations_rst": [],
        "reproduction_command": "python -m validation_cases.calibration.synthetic.run_case",
        "gallery_update_command": "python -m tools.doc_gallery",
        "source_paths": ["validation_cases/calibration/synthetic/run_case.py"],
        "images": [
            {
                "filename": "synthetic__configuration.png",
                "caption": "Configuration.",
                "alt_text": "Configuration",
                "doc_path": "/_static/capability_gallery/calibration/synthetic__configuration.png",
                "repo_path": "docs/readthedocs/source/_static/capability_gallery/calibration/synthetic__configuration.png",
            },
            {
                "filename": "synthetic__random_search_landscape.png",
                "caption": "Landscape.",
                "alt_text": "Landscape",
                "doc_path": "/_static/capability_gallery/calibration/synthetic__random_search_landscape.png",
                "repo_path": "docs/readthedocs/source/_static/capability_gallery/calibration/synthetic__random_search_landscape.png",
            },
            {
                "filename": "synthetic__random_search_trace.png",
                "caption": "Trace.",
                "alt_text": "Trace",
                "doc_path": "/_static/capability_gallery/calibration/synthetic__random_search_trace.png",
                "repo_path": "docs/readthedocs/source/_static/capability_gallery/calibration/synthetic__random_search_trace.png",
            },
            {
                "filename": "synthetic__random_search_posterior.png",
                "caption": "Posterior.",
                "alt_text": "Posterior",
                "doc_path": "/_static/capability_gallery/calibration/synthetic__random_search_posterior.png",
                "repo_path": "docs/readthedocs/source/_static/capability_gallery/calibration/synthetic__random_search_posterior.png",
            },
        ],
        "artifacts": {
            "image_repo_paths": [],
            "summary_json_repo_path": (
                "docs/readthedocs/source/_static/capability_gallery/"
                "calibration/synthetic_summary.json"
            ),
        },
        "metadata": {
            "solver_name": "modflow6",
            "regime": "steady",
            "output_names": ["q_east"],
            "observation_noise": "none",
            "evaluation_budget": 12,
            "truth_params": {"K_global_factor": 1.0},
            "bounds": {"K_global_factor": [0.65, 1.35]},
            "parameter_abs_tolerances": {"K_global_factor": 0.06},
            "method_runs": [
                {
                    "method_name": "random_search",
                    "meets_success_target": True,
                    "cost_best": 0.01,
                    "n_evaluations": 16,
                    "model_distribution_sample_count": 12,
                    "calibration_time_seconds": 1.5,
                    "estimated_candidate_runtime_seconds": 1.2,
                    "algorithm_overhead_time_seconds": 0.3,
                    "mean_candidate_actualize_time_seconds": 0.01,
                    "mean_candidate_launcher_prepare_time_seconds": 0.004,
                    "mean_candidate_runtime_patch_time_seconds": 0.002,
                    "mean_candidate_preparation_time_seconds": 0.02,
                    "mean_candidate_simulation_time_seconds": 0.03,
                    "mean_candidate_output_selection_time_seconds": 0.006,
                    "mean_candidate_objective_compute_time_seconds": 0.005,
                    "objective_landscape_filename": "synthetic__random_search_landscape.png",
                    "posterior_distribution_filename": "synthetic__random_search_posterior.png",
                    "objective_trace_filename": "synthetic__random_search_trace.png",
                }
            ],
            "lead_image_filenames": ["synthetic__configuration.png"],
            "tab_specs": [
                {
                    "title": "random_search",
                    "filenames": [
                        "synthetic__random_search_landscape.png",
                        "synthetic__random_search_posterior.png",
                        "synthetic__random_search_trace.png",
                    ],
                    "body_lines": ["target=True", "n_eval=16"],
                }
            ],
        },
    }

    page = _build_case_page(_with_parameter_docs(case))

    assert "Benchmark Setup" in page
    assert "Calibrated Parameters" in page
    assert "Methods And Timing" in page
    assert "Displayed Metrics" in page
    assert "K_global_factor" in page
    assert "random_search" in page
    assert ".. tab-set::" in page
    assert "synthetic__configuration.png" in page
    assert "synthetic__random_search_landscape.png" in page
    assert "synthetic__random_search_posterior.png" in page
    assert "synthetic__random_search_trace.png" in page


def test_build_calibration_intercomparison_page_renders_rows() -> None:
    calibration_case = {
        "slug": "synthetic_case",
        "title": "Synthetic Calibration Case",
        "deck": "Synthetic deck.",
        "docname": "cases/synthetic_case",
        "metadata": {
            "solver_name": "modflow6",
            "regime": "steady",
            "method_runs": [
                {
                    "method_name": "random_search",
                    "method_instance_name": "random_search",
                    "success_metric": "best_fit",
                    "meets_success_target": True,
                    "recovered_truth": True,
                    "cost_best": 0.01,
                    "n_evaluations": 16,
                    "calibration_time_seconds": 1.6,
                    "estimated_candidate_runtime_seconds": 1.1,
                    "algorithm_overhead_time_seconds": 0.5,
                    "mean_candidate_actualize_time_seconds": 0.01,
                    "mean_candidate_launcher_prepare_time_seconds": 0.02,
                    "mean_candidate_runtime_patch_time_seconds": 0.003,
                    "mean_candidate_simulation_time_seconds": 0.05,
                    "mean_candidate_output_selection_time_seconds": 0.004,
                    "mean_candidate_objective_compute_time_seconds": 0.006,
                }
            ],
        },
    }
    rows = _build_calibration_intercomparison_rows([calibration_case])
    comparison_summary = {
        "case_count": 1,
        "method_row_count": 1,
        "rows": rows,
        "figures": [
            {
                "filename": "benchmark_candidate_timing_breakdown.png",
                "caption": "Timing breakdown.",
                "alt_text": "Timing breakdown",
                "doc_path": "/_static/capability_gallery/calibration/intercomparison/benchmark_candidate_timing_breakdown.png",
                "repo_path": "docs/readthedocs/source/_static/capability_gallery/calibration/intercomparison/benchmark_candidate_timing_breakdown.png",
            }
        ],
    }

    page = _build_calibration_intercomparison_page(
        calibration_cases=[calibration_case],
        comparison_summary=comparison_summary,
    )

    assert "Calibration Intercomparison" in page
    assert "benchmark_candidate_timing_breakdown.png" in page
    assert "Synthetic Calibration Case" in page
    assert "random_search" in page
    assert "Output select (s)" in page
    assert "Algorithm overhead (s)" in page
