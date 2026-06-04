"""Unit tests for static comparison HTML report generation.

Structural coverage targets stable anchors (section ids, figure-category ids,
table classes, asset filenames). The exact human-facing French labels are
verified once, in ``test_human_facing_labels_render_in_french``.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from hydromodpy.reporting.comparison.render import write_comparison_web_report

_SYNTHETIC_BASE_TOML = """
[flow]
flow_regime = "transient"
runtime_backend = "petsc"
surface_interaction_model = "ts_vi_obstacle"
active_bc = ["drainage"]
ts_vi_type = "beuler"
ts_vi_snes_type = "vinewtonrsls"
ts_vi_steps_per_period = 4
runtime_tol_residual_inf = 1.0e-6

[flow.ic]
type = "steady_state"

[flow.sinks_sources.recharge]
first_clim = "first"
negative_to_evt = true

[flow.bc.cauchy.drainage]
value = "0.2 m2/s"
"""


def _render_linked_outputs_report(root: Path) -> str:
    """Render a report without the optional closure table.

    Used by the structure test so the negative assertions on the closure
    table header and on wall time remain meaningful in their own context.
    """
    figure_root = root / "comparison_figures"
    figure_root.mkdir(parents=True)
    (figure_root / "case_configuration.png").write_bytes(b"png")
    (figure_root / "comparable_outflow_dashboard.png").write_bytes(b"png")
    (figure_root / "head_map_wet_year1__fine_raster_map_comparison.png").write_bytes(b"png")
    (figure_root / "storage_comparison_dashboard.png").write_bytes(b"png")
    (figure_root / "total_inputs_outputs_dashboard.png").write_bytes(b"png")
    (root / "comparison_report.md").write_text("# report\n", encoding="utf-8")
    (root / "comparison_audit.json").write_text(
        json.dumps({"status": "warn", "issues": [{"message": "demo issue"}]}),
        encoding="utf-8",
    )
    _write_csv(
        root / "comparison_metrics.csv",
        [
            {
                "simulation_id": "candidate",
                "observable": "head",
                "unit": "m",
                "n_pairs": "2",
                "rmse": "0.1",
                "normalization_scale": "2.0",
                "rmse_normalized_percent": "5.0",
            }
        ],
    )
    _write_csv(
        root / "budget_timeseries_wide.csv",
        [
            {
                "component": "comparable_outflow_total_m3_s",
                "period_index": "0",
                "time_label": "1.0 d",
                "value__mf6_ref": "1.0",
                "value__bouss_candidate": "1.1",
            }
        ],
    )

    path = write_comparison_web_report(
        comparison_root=root,
        manifest={
            "comparison_id": "demo_compare",
            "audit_status": "warn",
            "reference_simulation": "mf6_ref",
            "simulations": [
                {
                    "id": "mf6_ref",
                    "solver": "modflow6",
                    "status": "completed",
                    "flow_solve_time_seconds": 5.0,
                    "wall_time_seconds": 12.0,
                },
                {
                    "id": "bouss_candidate",
                    "solver": "boussinesq",
                    "status": "completed",
                    "flow_solve_time_seconds": 10.0,
                    "wall_time_seconds": 24.0,
                },
            ],
        },
    )
    return path.read_text(encoding="utf-8")


def _render_full_report(root: Path) -> str:
    """Render one report that exercises every default section.

    Drives the single labels test so all sections, tables and figure
    categories are present in one document.
    """
    figure_root = root / "comparison_figures"
    figure_root.mkdir(parents=True)
    (figure_root / "case_configuration.png").write_bytes(b"png")
    (figure_root / "comparable_outflow_dashboard.png").write_bytes(b"png")
    (figure_root / "head_map_wet_year1__fine_raster_map_comparison.png").write_bytes(b"png")
    (figure_root / "storage_comparison_dashboard.png").write_bytes(b"png")
    (figure_root / "total_inputs_outputs_dashboard.png").write_bytes(b"png")
    (root / "comparison_report.md").write_text("# report\n", encoding="utf-8")
    (root / "comparison_audit.json").write_text(
        json.dumps({"status": "warn", "issues": [{"message": "demo issue"}]}),
        encoding="utf-8",
    )
    (root / "base.toml").write_text(_SYNTHETIC_BASE_TOML, encoding="utf-8")
    _write_csv(
        root / "comparison_metrics.csv",
        [
            {
                "simulation_id": "candidate",
                "observable": "head",
                "unit": "m",
                "n_pairs": "2",
                "rmse": "0.1",
                "normalization_scale": "2.0",
                "rmse_normalized_percent": "5.0",
            }
        ],
    )
    _write_csv(
        root / "numerical_closure_summary.csv",
        [
            {
                "simulation_id": "bouss_candidate",
                "solver": "boussinesq",
                "n_periods": "2",
                "max_abs_closure_m3_s": "0.02",
                "max_abs_closure_mm_d": "0.004",
                "relative_closure_error_p95": "0.006",
                "diagnostic": "WARN",
            },
        ],
    )
    _write_csv(
        root / "budget_timeseries_wide.csv",
        [
            {
                "component": "comparable_outflow_total_m3_s",
                "period_index": "0",
                "time_label": "1.0 d",
                "value__mf6_ref": "1.0",
                "value__bouss_candidate": "1.1",
            }
        ],
    )

    path = write_comparison_web_report(
        comparison_root=root,
        manifest={
            "comparison_id": "synthetic_patchy_unit",
            "base_simulation_config": "base.toml",
            "audit_status": "warn",
            "reference_simulation": "mf6_ref",
            "simulations": [
                {
                    "id": "mf6_ref",
                    "solver": "modflow6",
                    "status": "completed",
                    "flow_solve_time_seconds": 5.0,
                    "wall_time_seconds": 12.0,
                },
                {
                    "id": "bouss_candidate",
                    "solver": "boussinesq",
                    "status": "completed",
                    "flow_solve_time_seconds": 10.0,
                    "wall_time_seconds": 24.0,
                },
            ],
        },
    )
    return path.read_text(encoding="utf-8")


def test_write_comparison_web_report_structure(tmp_path: Path) -> None:
    text = _render_linked_outputs_report(tmp_path / "comparison")

    assert 'id="section-introduction"' in text
    assert 'id="section-case_configuration"' in text
    assert 'id="section-numerical_methods"' in text
    assert 'id="section-categorized_figures"' in text
    assert 'id="section-metrics"' in text
    assert 'id="section-coherence_analysis"' in text
    assert 'id="section-simulations"' in text
    assert 'id="section-files"' in text

    assert 'id="figures-heads"' in text
    assert 'id="figures-water_balance"' in text
    assert "head_map_wet_year1__fine_raster_map_comparison.png" in text
    assert "storage_comparison_dashboard.png" in text
    assert "total_inputs_outputs_dashboard.png" in text
    # comparable outflow lives in the budget data, not as a standalone figure.
    assert "comparable_outflow_dashboard.png" not in text
    assert "comparison_report.md" in text
    assert "runtime-bar boussinesq" in text
    assert "flow_solve" in text
    # wall time is intentionally excluded from the flow-only runtime table.
    assert "24.0 s" not in text
    assert "<th>simulation</th>" not in text
    assert 'class="metric-table"' in text
    # numerical methods splits into two key-value grids (hydraulic + numeric).
    assert text.count('class="info-grid"') >= 2


def test_report_title_derives_from_comparison_id(tmp_path: Path) -> None:
    root = tmp_path / "comparison"
    root.mkdir()

    path = write_comparison_web_report(
        comparison_root=root,
        manifest={
            "comparison_id": "demo_compare",
            "reference_simulation": "mf6_ref",
            "simulations": [],
        },
    )

    text = path.read_text(encoding="utf-8")
    assert "<h1>demo compare</h1>" in text
    assert "<title>demo compare</title>" in text


def test_human_facing_labels_render_in_french(tmp_path: Path) -> None:
    text = _render_full_report(tmp_path / "comparison")

    # Synthetic case title.
    assert "Comparaison synthetique MF6 / Boussinesq - recharge heterogene" in text
    # Section and subsection headings.
    assert "Contexte du cas" in text
    assert "Methodes numeriques" in text
    assert "Configuration hydraulique et conditions aux limites" in text
    assert "Parametrage numerique" in text
    assert "Comparaisons de resultats" in text
    assert "Precision de resolution" in text
    assert "Lecture physique des ecarts" in text
    # Figure-category title.
    assert "Charges hydrauliques" in text
    # Key-value row labels.
    assert "Conditions aux limites MODFLOW 6" in text
    assert "Conditions aux limites Boussinesq" in text
    # Table column headers.
    assert "RMSE / ref" in text
    assert "valeur ref" in text
    assert "erreur rel. p95" in text
    # Labels that must not reappear after renaming.
    assert "Flux agrege et chroniques" not in text
    assert "ecart moy m" not in text


def test_synthetic_web_report_splits_hydraulic_and_numerical_settings(
    tmp_path: Path,
) -> None:
    root = tmp_path / "comparison"
    root.mkdir()
    base_config = root / "base.toml"
    base_config.write_text(_SYNTHETIC_BASE_TOML, encoding="utf-8")

    path = write_comparison_web_report(
        comparison_root=root,
        manifest={
            "comparison_id": "synthetic_patchy_unit",
            "base_simulation_config": "base.toml",
            "reference_simulation": "mf6_ref",
            "simulations": [],
        },
    )

    text = path.read_text(encoding="utf-8")
    assert 'id="section-numerical_methods"' in text
    assert text.count('class="info-grid"') >= 2
    assert "first_clim=first" in text
    assert "negative_to_evt=true" in text
    assert "drainage de surface actif sur le toit, conductance 0.2 m2/s" in text


def test_web_report_includes_numerical_closure_section(tmp_path: Path) -> None:
    root = tmp_path / "comparison"
    root.mkdir()
    _write_csv(
        root / "numerical_closure_summary.csv",
        [
            {
                "simulation_id": "mf6_ref",
                "solver": "modflow6",
                "n_periods": "2",
                "max_abs_closure_m3_s": "0.001",
                "max_abs_closure_mm_d": "0.0002",
                "relative_closure_error_p95": "0.0005",
                "diagnostic": "OK",
            },
            {
                "simulation_id": "bouss_candidate",
                "solver": "boussinesq",
                "n_periods": "2",
                "max_abs_closure_m3_s": "0.02",
                "max_abs_closure_mm_d": "0.004",
                "relative_closure_error_p95": "0.006",
                "diagnostic": "WARN",
            },
        ],
    )

    path = write_comparison_web_report(
        comparison_root=root,
        manifest={
            "comparison_id": "closure_demo",
            "reference_simulation": "mf6_ref",
            "simulations": [],
        },
    )

    text = path.read_text(encoding="utf-8")
    assert 'id="section-numerical_closure"' in text
    assert "bouss_candidate" in text


def test_synthetic_web_report_documents_disabled_boussinesq_drainage(
    tmp_path: Path,
) -> None:
    root = tmp_path / "comparison"
    root.mkdir()
    base_config = root / "base.toml"
    base_config.write_text(
        """
[flow]
flow_regime = "transient"
runtime_backend = "petsc"
surface_interaction_model = "ts_vi_obstacle"
active_bc = ["drainage"]

[flow.ic]
type = "steady_state"

[flow.sinks_sources.recharge]
first_clim = "first"
negative_to_evt = true

[flow.bc.cauchy.drainage]
value = "0.2 m2/s"
""",
        encoding="utf-8",
    )
    (root / "mf6_child.toml").write_text(
        """
[flow]
flow_regime = "transient"
active_bc = ["drainage"]

[flow.bc.cauchy.drainage]
value = "0.2 m2/s"
""",
        encoding="utf-8",
    )
    (root / "bouss_child.toml").write_text(
        """
[flow]
flow_regime = "transient"
runtime_backend = "petsc"
surface_interaction_model = "ts_vi_obstacle"
active_bc = ["drainage"]

[flow.bc.cauchy.drainage]
value = "0.0 m2/s"
""",
        encoding="utf-8",
    )

    path = write_comparison_web_report(
        comparison_root=root,
        manifest={
            "comparison_id": "synthetic_patchy_unit",
            "base_simulation_config": "base.toml",
            "reference_simulation": "mf6_ref",
            "simulations": [
                {
                    "id": "mf6_ref",
                    "solver": "modflow6",
                    "config_path": "mf6_child.toml",
                },
                {
                    "id": "bouss_candidate",
                    "solver": "boussinesq",
                    "config_path": "bouss_child.toml",
                },
            ],
        },
    )

    text = path.read_text(encoding="utf-8")
    assert "drainage de surface actif sur le toit, conductance 0.2 m2/s" in text
    assert "drainage Cauchy declare mais desactive par conductance nulle" in text
    assert "obstacle libre strict h &lt;= z_top conserve" in text


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
