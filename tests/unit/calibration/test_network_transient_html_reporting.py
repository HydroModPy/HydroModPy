from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.calibration.reporting import (
    build_network_transient_html,
    inspect_network_transient_html_artifacts,
)


def test_network_transient_html_artifact_contract_reports_required_inputs(
    tmp_path: Path,
) -> None:
    truth = tmp_path / "truth"
    truth.mkdir()
    (truth / "metadata.json").write_text("{}", encoding="utf-8")
    (truth / "normalization.json").write_text("{}", encoding="utf-8")
    (truth / "transient_q_total_release.csv").write_text(
        "period,q_total_release\n0,1.0\n",
        encoding="utf-8",
    )
    score = tmp_path / "scores.csv"
    score.write_text("candidate_id,status,J\nc01,completed,0.1\n", encoding="utf-8")

    report = inspect_network_transient_html_artifacts(
        real_root=tmp_path,
        source_transient_config=tmp_path / "missing.toml",
        reference_run_root=tmp_path / "missing_reference",
        steady_summary_csv=tmp_path / "missing_steady.csv",
        truth_packages=[truth],
        score_tables=[score],
    )

    assert report.ok
    assert report.truth_dir == truth.resolve()
    assert report.score_table == score.resolve()
    assert "truth.metadata_json" in report.available
    assert "score_table.completed_rows" in report.available
    assert "source_transient_config" in report.optional_missing


def test_network_transient_html_artifact_contract_warns_on_transient_network_map(
    tmp_path: Path,
) -> None:
    truth = tmp_path / "site_01_truth_package"
    truth.mkdir()
    (truth / "metadata.json").write_text(
        json.dumps({"site_id": "site_01", "mK_true": 0.65, "Sy_true": 0.05}),
        encoding="utf-8",
    )
    (truth / "normalization.json").write_text("{}", encoding="utf-8")
    (truth / "transient_q_total_release.csv").write_text(
        "period,q_total_release\n0,1.0\n",
        encoding="utf-8",
    )
    score = tmp_path / "site_01_scores.csv"
    score.write_text(
        "candidate_id,status,J,mK,Sy,network_map_source\n"
        "truth_mK_0p65_Sy_0p05,completed,0.0,0.65,0.05,transient_last\n",
        encoding="utf-8",
    )

    report = inspect_network_transient_html_artifacts(
        real_root=tmp_path,
        source_transient_config=tmp_path / "missing.toml",
        reference_run_root=tmp_path / "missing_reference",
        steady_summary_csv=tmp_path / "missing_steady.csv",
        truth_packages=[truth],
        score_tables=[score],
    )

    assert report.ok
    assert (
        "score_table.non_steady_network_map_source=transient_last"
        in report.contract_warnings
    )


def test_network_transient_html_artifact_contract_flags_missing_required(
    tmp_path: Path,
) -> None:
    report = inspect_network_transient_html_artifacts(
        real_root=tmp_path,
        source_transient_config=tmp_path / "missing.toml",
        reference_run_root=tmp_path / "missing_reference",
        steady_summary_csv=tmp_path / "missing_steady.csv",
        truth_packages=[tmp_path / "missing_truth"],
        score_tables=[tmp_path / "missing_scores.csv"],
    )

    assert not report.ok
    assert "truth_package" in report.required_missing
    assert "score_table" in report.required_missing


def test_network_transient_html_writes_reference_manifest(tmp_path: Path) -> None:
    real_root = tmp_path / "real_runs"
    truth = real_root / "site_01_truth_package_mK_0p65"
    truth.mkdir(parents=True)
    (truth / "metadata.json").write_text(
        json.dumps(
            {
                "site_id": "site_01",
                "mK_true": 0.65,
                "Sy_true": 0.05,
                "n_cells": 3,
                "n_timesteps": 1,
            }
        ),
        encoding="utf-8",
    )
    (truth / "normalization.json").write_text(
        json.dumps({"Qbar_ref": 1.0, "w_reseau": 0.5, "w_debit": 0.5}),
        encoding="utf-8",
    )
    (truth / "transient_q_total_release.csv").write_text(
        "period,q_total_release\n0,1.0\n",
        encoding="utf-8",
    )
    score = real_root / "site_01_parameter_grid_light_scores_mK_0p65.csv"
    score.write_text(
        "candidate_id,status,J,mK,Sy,steady_drain_npz\n"
        "truth_mK_0p65_Sy_0p05,completed,0.0,0.65,0.05,steady.npz\n",
        encoding="utf-8",
    )

    out = build_network_transient_html(
        real_root=real_root,
        web_root=tmp_path / "web",
        source_transient_config=tmp_path / "missing.toml",
        reference_run_root=tmp_path / "missing_reference",
        steady_summary_csv=tmp_path / "missing_steady.csv",
        truth_packages=[truth],
        score_tables=[score],
        page_title="Manifest smoke",
    )

    manifest = json.loads((real_root / "b0_reference_manifest.json").read_text("utf-8"))
    assert out == tmp_path / "web" / "index.html"
    assert manifest["contract_version"] == "b0_network_steady_discharge_transient.v1"
    assert manifest["paths"]["score_table"] == str(score.resolve())
    assert manifest["grid"]["completed"] == 1
    assert manifest["best_global"]["candidate_id"] == "truth_mK_0p65_Sy_0p05"


def test_network_transient_html_uses_truth_mesh_when_reference_run_is_empty(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real_runs"
    truth = real_root / "natural_observation_package"
    truth.mkdir(parents=True)
    mesh_bundle = real_root / "mesh_bundle"
    _write_line_mesh_bundle(mesh_bundle, n_cells=4)

    (truth / "metadata.json").write_text(
        json.dumps(
            {
                "site_id": "natural_site",
                "mesh_bundle": str(mesh_bundle.resolve()),
                "n_cells": 4,
                "n_timesteps": 2,
            }
        ),
        encoding="utf-8",
    )
    (truth / "normalization.json").write_text(
        json.dumps(
            {
                "contract_version": "natural_network_steady_discharge_transient.v1",
                "tau_network": 0.0,
                "Qbar_ref": 1.0,
                "w_reseau": 0.3,
                "w_debit": 0.7,
            }
        ),
        encoding="utf-8",
    )
    (truth / "transient_q_total_release.csv").write_text(
        "period,q_total_release\n0,1.0\n1,1.1\n",
        encoding="utf-8",
    )
    np.savez_compressed(
        truth / "steady_network_drain_by_cell.npz",
        outflow_drain=np.array([0.0, 1.0, 1.0, 0.0]),
    )
    np.savez_compressed(
        truth / "cell_geometry.npz",
        centroids=np.column_stack([np.arange(4, dtype=float), np.zeros(4, dtype=float)]),
        cell_area=np.ones(4, dtype=float),
    )

    candidates = real_root / "candidates"
    candidates.mkdir()
    np.savez_compressed(
        candidates / "shifted.npz",
        outflow_drain=np.array([0.0, 0.0, 1.0, 1.0]),
    )
    score = real_root / "natural_site_scores.csv"
    score.write_text(
        "candidate_id,status,J,mK,Sy,network_map_source,steady_drain_npz,"
        "C_reseau_phys,C_debit_phys\n"
        "truth_identity,completed,0.0,0.65,0.05,steady,candidates/shifted.npz,0.0,0.0\n"
        "shifted,completed,0.2,0.95,0.05,steady,candidates/shifted.npz,0.2,0.0\n",
        encoding="utf-8",
    )
    empty_reference = real_root / "candidate_mK_0p65_Sy_0p05_steady_mf6"
    empty_reference.mkdir()

    build_network_transient_html(
        real_root=real_root,
        web_root=tmp_path / "web",
        source_transient_config=tmp_path / "missing.toml",
        path_base=real_root,
        reference_run_root=empty_reference,
        steady_summary_csv=tmp_path / "missing_steady.csv",
        truth_packages=[truth],
        score_tables=[score],
        page_title="Natural mesh fallback smoke",
    )

    assert (tmp_path / "web" / "figures" / "dem_context_map.png").is_file()
    assert (tmp_path / "web" / "figures" / "outflow_drain_maps.png").is_file()
    manifest = json.loads((real_root / "b0_reference_manifest.json").read_text("utf-8"))
    assert manifest["contract_version"] == "natural_network_steady_discharge_transient.v1"
    assert manifest["contract"]["objective"] == "0.3*C_reseau_naturel + 0.7*C_debit_obs"


def test_workflow_step_delegates_network_transient_html_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hydromodpy.workflow.steps.calibration import (
        step_render_network_transient_calibration_html,
    )

    captured: dict[str, object] = {}
    expected = tmp_path / "web" / "index.html"

    def fake_builder(**kwargs: object) -> Path:
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(
        "hydromodpy.calibration.reporting.build_network_transient_html",
        fake_builder,
    )

    out = step_render_network_transient_calibration_html(
        real_root=tmp_path / "real_runs",
        web_root=tmp_path / "web",
        page_title="Synthetic calibration",
    )

    assert out == expected
    assert captured["real_root"] == tmp_path / "real_runs"
    assert captured["web_root"] == tmp_path / "web"
    assert captured["page_title"] == "Synthetic calibration"


@pytest.mark.slow
def test_network_transient_html_smoke_on_existing_example_outputs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    example_root = repo_root / "examples" / "projects" / "12_calibration_network_transient_b0"
    real_root = example_root / "outputs" / "real_runs"
    truth = real_root / "site_01_truth_package_mK_0p65"
    score = real_root / "site_01_parameter_grid_scores_mK_0p65.csv"
    if not truth.is_dir() or not score.is_file():
        pytest.skip("network/transient example outputs are not available")

    out = build_network_transient_html(
        real_root=real_root,
        web_root=tmp_path / "web",
        path_base=example_root,
        page_title="Smoke calibration reseau",
        truth_packages=[truth],
        score_tables=[score],
    )

    text = out.read_text(encoding="utf-8")
    for marker in (
        "Probleme de calibration",
        "Configuration spatiale et temporelle",
        "Fonction objectif dans l'espace des parametres",
        "Cartes de drainage vis-a-vis de la cible",
        "Chroniques de flux",
    ):
        assert marker in text
    for figure_name in (
        "objective_parameter_maps.png",
        "objective_profile_cuts.png",
        "outflow_drain_maps.png",
        "q_total_release_timeseries.png",
        "recharge_chronicle.png",
        "steady_balance_didactic.png",
        "watershed_id_card.png",
    ):
        assert (tmp_path / "web" / "figures" / figure_name).is_file()
    artifact_report = json.loads(
        (tmp_path / "web" / "network_transient_html_artifacts.json").read_text(encoding="utf-8")
    )
    assert artifact_report["ok"] is True


def _write_line_mesh_bundle(bundle_dir: Path, *, n_cells: int) -> None:
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "nodes.csv").write_text(
        "node_id,x,y\n"
        + "".join(
            f"{idx},{float(idx) - 0.5},-0.5\n"
            f"{idx + n_cells + 1},{float(idx) - 0.5},0.5\n"
            for idx in range(n_cells + 1)
        ),
        encoding="utf-8",
    )
    (bundle_dir / "cells.csv").write_text(
        "cell_id,n0,n1,n2,n3,area_m2,z_top_mean\n"
        + "".join(
            f"{cell_id},{cell_id},{cell_id + 1},{cell_id + n_cells + 2},"
            f"{cell_id + n_cells + 1},1.0,{10.0 - cell_id}\n"
            for cell_id in range(n_cells)
        ),
        encoding="utf-8",
    )
