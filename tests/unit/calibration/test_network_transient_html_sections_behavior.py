from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

import hydromodpy.calibration.reporting.network_transient_html as report
from hydromodpy.calibration.reporting.network_transient import sections


@pytest.fixture()
def restore_report_globals(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    names = (
        "FIGURE_ROOT",
        "PAGE_TITLE",
        "PATH_BASE",
        "REAL_ROOT",
        "REFERENCE_RUN_ROOT",
        "SCORE_TABLE_CANDIDATES",
        "SOURCE_TRANSIENT_CONFIG",
        "STEADY_SUMMARY_CSV",
        "TRUTH_PACKAGE_CANDIDATES",
        "WEB_ROOT",
    )
    saved = {name: getattr(report, name) for name in names}
    yield
    for name, value in saved.items():
        monkeypatch.setattr(report, name, value)


def _minimal_network_transient_inputs(tmp_path: Path) -> dict[str, Path]:
    real_root = tmp_path / "real_runs"
    truth = real_root / "truth_package"
    web_root = tmp_path / "web"
    mesh = tmp_path / "mesh"
    truth.mkdir(parents=True)
    mesh.mkdir()

    source_config = tmp_path / "source.toml"
    k_values = tmp_path / "k_values.csv"
    k_values.write_text("K_value\n1e-5\n3e-5\n", encoding="utf-8")
    source_config.write_text(
        """
[geographic]

[geographic.catchment]
x_outlet = 10.0
y_outlet = 20.0

[data.recharge]
sources = [{values = [1.0, 2.0, 3.0]}]

[flow.param.K.field]
values_csv_file = "k_values.csv"
""",
        encoding="utf-8",
    )

    (mesh / "nodes.csv").write_text(
        "node_id,x,y\n0,10.0,20.0\n1,20.0,20.0\n2,20.0,30.0\n3,10.0,30.0\n",
        encoding="utf-8",
    )
    (mesh / "cells.csv").write_text(
        "cell_id,n0,n1,n2,n3,z_top_mean\n0,0,1,2,3,42.0\n",
        encoding="utf-8",
    )

    (truth / "metadata.json").write_text(
        json.dumps(
            {
                "mK_true": 0.65,
                "Sy_true": 0.05,
                "site_id": "site-01",
                "steady_solver": "modflow6",
                "n_cells": 1,
                "n_timesteps": 3,
                "mesh_bundle": "mesh",
            }
        ),
        encoding="utf-8",
    )
    (truth / "normalization.json").write_text(
        json.dumps(
            {
                "Q_ref_steady": 3.0,
                "Qbar_ref": 2.0,
                "L_ref": 100.0,
                "d_tol": 5.0,
                "tau_network": 0.1,
            }
        ),
        encoding="utf-8",
    )
    (truth / "transient_q_total_release.csv").write_text(
        "period,datetime,q_total_release\n0,2000-01-01,1.0\n1,2000-02-01,2.0\n2,2000-03-01,3.0\n",
        encoding="utf-8",
    )
    np.savez(truth / "cell_geometry.npz", centroids=np.asarray([[15.0, 25.0]]))
    np.savez(truth / "steady_network_active_mask.npz", active_mask=np.asarray([True]))
    np.savez(truth / "steady_network_drain_by_cell.npz", outflow_drain=np.asarray([2.0]))

    steady_summary_csv = real_root / "steady_mK_network_extent_summary.csv"
    steady_summary_csv.write_text(
        "threshold_m3_s,mK,q_total_m3_s,active_fraction\n"
        "0.0,0.50,2.5,0.5\n"
        "0.0,0.65,3.0,1.0\n"
        "0.1,0.80,4.0,1.0\n",
        encoding="utf-8",
    )

    candidate_q = tmp_path / "candidate_q.csv"
    candidate_q.write_text(
        "period,q_total_release\n0,1.2\n1,2.1\n2,2.8\n",
        encoding="utf-8",
    )
    np.savez(tmp_path / "candidate_drain.npz", outflow_drain=np.asarray([1.5]))
    score_table = real_root / "scores.csv"
    score_table.write_text(
        "candidate_id,status,mK,Sy,J,C_debit_phys,C_reseau_phys,"
        "transient_q_csv,steady_drain_npz\n"
        "truth_identity,completed,0.65,0.05,0.0,0.0,0.0,"
        "candidate_q.csv,candidate_drain.npz\n"
        "cand_sy_low,completed,0.65,0.03,0.5,0.4,0.6,"
        "candidate_q.csv,candidate_drain.npz\n"
        "cand_mk_low,completed,0.50,0.05,0.2,0.1,0.3,"
        "candidate_q.csv,candidate_drain.npz\n"
        "cand_mk_high,completed,0.80,0.05,0.3,0.2,0.4,"
        "candidate_q.csv,candidate_drain.npz\n"
        "cand_failed,failed,0.90,0.07,0.1,0.1,0.1,"
        "candidate_q.csv,candidate_drain.npz\n",
        encoding="utf-8",
    )

    return {
        "real_root": real_root,
        "truth": truth,
        "web_root": web_root,
        "source_config": source_config,
        "steady_summary_csv": steady_summary_csv,
        "score_table": score_table,
        "candidate_q": candidate_q,
        "candidate_drain": tmp_path / "candidate_drain.npz",
    }


def _configure_report_for_tmp(
    paths: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report, "PATH_BASE", tmp_path)
    monkeypatch.setattr(report, "SOURCE_TRANSIENT_CONFIG", paths["source_config"])
    monkeypatch.setattr(report, "REFERENCE_RUN_ROOT", tmp_path / "missing_reference")


def test_build_network_transient_html_renders_sections_and_figures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore_report_globals: None,
) -> None:
    del restore_report_globals
    paths = _minimal_network_transient_inputs(tmp_path)
    monkeypatch.setattr(report, "_save_watershed_id_card", lambda _root, _path: None)

    out = report.build_network_transient_html(
        real_root=paths["real_root"],
        web_root=paths["web_root"],
        source_transient_config=paths["source_config"],
        path_base=tmp_path,
        page_title="Calibration <network>",
        reference_run_root=tmp_path / "missing_reference",
        steady_summary_csv=paths["steady_summary_csv"],
        truth_packages=[paths["truth"]],
        score_tables=[paths["score_table"]],
    )

    html = out.read_text(encoding="utf-8")
    assert "Calibration &lt;network&gt;" in html
    assert "Probleme de calibration" in html
    assert "Configuration spatiale et temporelle" in html
    assert "Fonction objectif dans l'espace des parametres" in html
    assert "cand_mk_low" in html
    assert "<strong>4 / 5</strong>" in html
    assert "contrat artefacts" in html
    assert "manquants optionnels" in html

    artifact_report = json.loads(
        (paths["web_root"] / "network_transient_html_artifacts.json").read_text(encoding="utf-8")
    )
    assert artifact_report["ok"] is True
    assert artifact_report["truth_dir"] == str(paths["truth"].resolve())
    assert artifact_report["score_table"] == str(paths["score_table"].resolve())
    assert "score_table.completed_rows" in artifact_report["available"]
    assert artifact_report["optional_missing"] == ["reference_run_root"]

    figure_root = paths["web_root"] / "figures"
    expected_figures = {
        "dem_context_map.png",
        "steady_balance_didactic.png",
        "recharge_chronicle.png",
        "outflow_drain_maps.png",
        "q_total_release_timeseries.png",
        "objective_parameter_maps.png",
        "objective_profile_cuts.png",
    }
    assert expected_figures <= {path.name for path in figure_root.glob("*.png")}


def test_section_summaries_select_best_non_truth_and_report_missing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore_report_globals: None,
) -> None:
    del restore_report_globals
    paths = _minimal_network_transient_inputs(tmp_path)
    _configure_report_for_tmp(paths, tmp_path, monkeypatch)
    score_rows = report._read_csv(paths["score_table"])

    best_html = sections.best_candidate_summary(score_rows, paths["truth"])

    assert "cand_mk_low" in best_html
    assert "truth_identity" not in best_html
    assert "<strong>4 / 5</strong>" in best_html
    assert "<strong>1</strong>" in best_html

    artifact_report = report.NetworkTransientHtmlArtifactReport(
        real_root=tmp_path,
        truth_dir=None,
        score_table=None,
        available=("source_transient_config",),
        required_missing=("truth_package", "score_table"),
        optional_missing=tuple(f"optional_{idx}" for idx in range(9)),
    )
    summary_html = sections.artifact_contract_summary(artifact_report)

    assert "incomplet" in summary_html
    assert "manquants requis" in summary_html
    assert "truth_package, score_table, optional_0" in summary_html
    assert "..." in summary_html


def test_readers_and_configuration_metrics_load_csv_json_and_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore_report_globals: None,
) -> None:
    del restore_report_globals
    paths = _minimal_network_transient_inputs(tmp_path)
    _configure_report_for_tmp(paths, tmp_path, monkeypatch)

    assert report._read_json(paths["truth"] / "metadata.json")["mK_true"] == 0.65
    assert report._read_csv(paths["score_table"])[0]["candidate_id"] == "truth_identity"
    assert (
        report._read_toml(paths["source_config"])["geographic"]["catchment"]["x_outlet"] == 10.0
    )
    assert report._read_truth_discharge(paths["truth"] / "transient_q_total_release.csv") == [
        1.0,
        2.0,
        3.0,
    ]

    np.testing.assert_allclose(sections.source_k_values(), np.asarray([1.0e-5, 3.0e-5]))
    conductivity = sections.conductivity_context({"mK_true": "2.0"})
    assert conductivity["K_mean_target"] == pytest.approx(4.0e-5)
    assert conductivity["K_over_R_mean"] == pytest.approx(1728.0)

    metrics_html = sections.configuration_metrics(
        report._read_json(paths["truth"] / "normalization.json"),
        paths["truth"],
    )
    assert "site-01" in metrics_html
    assert "2000-01-01 -&gt; 2000-03-01" in metrics_html
    assert "cellules drainantes cible" in metrics_html
    assert "K moyen / R moyen" in metrics_html


def test_series_and_path_wrappers_resolve_relative_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore_report_globals: None,
) -> None:
    del restore_report_globals
    paths = _minimal_network_transient_inputs(tmp_path)
    _configure_report_for_tmp(paths, tmp_path, monkeypatch)

    assert report._score_file_path("candidate_q.csv") == paths["candidate_q"].resolve()
    assert sections.score_file_path("candidate_drain.npz") == paths["candidate_drain"].resolve()
    assert sections.score_catalog_path("") is None

    series = sections.q_total_release_series(
        score_rows=[
            {"candidate_id": "best", "transient_q_csv": "candidate_q.csv"},
            {"candidate_id": "missing", "transient_q_csv": "missing.csv"},
        ],
        truth_q=[9.0],
    )

    assert series == {
        "reference synthetique": [9.0],
        "best": [1.2, 2.1, 2.8],
    }


def test_generate_figures_with_minimal_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore_report_globals: None,
) -> None:
    del restore_report_globals
    paths = _minimal_network_transient_inputs(tmp_path)
    _configure_report_for_tmp(paths, tmp_path, monkeypatch)
    monkeypatch.setattr(report, "_save_watershed_id_card", lambda _root, _path: None)
    monkeypatch.setattr(report, "FIGURE_ROOT", tmp_path / "figures")
    k_rows = [
        row
        for row in report._read_csv(paths["steady_summary_csv"])
        if row["threshold_m3_s"] == "0.0"
    ]
    score_rows = report._read_csv(paths["score_table"])
    truth_q = report._read_truth_discharge(paths["truth"] / "transient_q_total_release.csv")

    figures = report._generate_figures(
        truth_dir=paths["truth"],
        k_rows=k_rows,
        score_rows=score_rows,
        truth_q=truth_q,
    )

    assert {
        "dem_context_map",
        "steady_balance_didactic",
        "recharge_chronicle",
        "outflow_drain_maps",
        "q_total_release_timeseries",
        "objective_parameter_maps",
        "objective_profile_cuts",
    } <= set(figures)
    assert all(path.is_file() for path in figures.values())
