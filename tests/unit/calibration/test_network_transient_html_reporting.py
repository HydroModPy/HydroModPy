from __future__ import annotations

import json
from pathlib import Path

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
