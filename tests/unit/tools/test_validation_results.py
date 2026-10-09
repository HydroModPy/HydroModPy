"""The validation results layer: what a test records and how runs merge."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tests.validation.helpers import assert_metric_above, assert_metric_below
from tests.validation.helpers import results as R
from tools.docs import validation_results as V

ROOT = Path(__file__).resolve().parents[3]
FILE = "tests/validation/mms/test_mms_laplacian_1d.py"


def test_a_metric_is_recorded_before_the_assertion_fails() -> None:
    record = R.new_record()
    with R.recording(record), pytest.raises(AssertionError):
        assert_metric_below("RMSE", 0.3, 0.2, unit="m")
    assert record["metrics"] == [
        {"name": "RMSE", "value": 0.3, "threshold": 0.2, "op": "<", "unit": "m", "ideal": None}
    ]


def test_a_metric_above_keeps_its_ideal_value() -> None:
    record = R.new_record()
    with R.recording(record):
        assert_metric_above("NSE", 0.9995, 0.999, ideal=1.0)
    assert record["metrics"][0]["op"] == ">"
    assert record["metrics"][0]["ideal"] == 1.0


def test_nothing_is_recorded_outside_a_recording_block() -> None:
    assert_metric_below("RMSE", 0.1, 0.2)
    R.record_scale(1.0, "range")
    assert R._CURRENT is None


def test_a_steady_profile_gives_its_curve_scale_and_case() -> None:
    x = np.linspace(0.0, 400.0, 200)
    ref = 5.0 + x * (400.0 - x) * 1e-5
    payload = SimpleNamespace(
        metadata={"case_id": "dupuit_uniform_recharge_1d"},
        x=x,
        analytical_profile=ref,
        numerical_profile=ref + 0.01,
    )
    record = R.new_record()
    with R.recording(record):
        R.record_comparison(payload)
    assert record["case"] == "dupuit_uniform_recharge_1d"
    assert record["scale"]["value"] == pytest.approx(ref.max() - ref.min())
    (series,) = record["series"]
    assert len(series["x"]) == R.MAX_POINTS
    assert series["x"][0] == 0.0 and series["x"][-1] == 400.0


def test_a_recession_is_scaled_by_its_initial_discharge() -> None:
    days = np.arange(10.0)
    ref = 2.0 * np.exp(-days / 5.0)
    payload = SimpleNamespace(
        metadata={},
        elapsed_days=days,
        analytical_discharge_m3_s=ref,
        numerical_discharge_m3_s=ref * 1.1,
    )
    record = R.new_record()
    with R.recording(record):
        R.record_comparison(payload)
    assert record["scale"]["value"] == 2.0
    assert record["series"][0]["y_label"] == "discharge (m3/s)"


def _part(tmp: Path, name: str, date: str, commit: str, outcome: str, value: float) -> Path:
    part = {
        "schema": 1,
        "run": {"date": date, "commit": commit, "version": "x"},
        "tests": [
            {
                "nodeid": f"{FILE}::test_mms_laplacian_1d_converges_at_order_two",
                "file": FILE,
                "outcome": outcome,
                "metrics": [{"name": "order", "value": value, "threshold": 0.2, "op": "<"}],
            }
        ],
    }
    path = tmp / name / "part-main-1-1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(part))
    return path.parent


def test_a_newer_run_replaces_a_result_and_an_older_one_does_not(tmp_path: Path) -> None:
    old = V.collect([_part(tmp_path, "a", "2026-10-01T00:00:00", "aaaa", "passed", 0.01)])
    new = V.collect([_part(tmp_path, "b", "2026-10-02T00:00:00", "bbbb", "failed", 0.3)])
    snap = V.merge(V.merge({}, old, replace=False, repo=ROOT), new, replace=False, repo=ROOT)
    (test,) = snap["tests"].values()
    assert test["outcome"] == "failed"
    assert list(snap["runs"]) == [V.run_key(new["runs"][test["run"]])]
    again = V.merge(snap, old, replace=False, repo=ROOT)
    assert next(iter(again["tests"].values()))["outcome"] == "failed"


def test_a_result_of_a_test_file_that_left_the_tree_is_dropped(tmp_path: Path) -> None:
    run = V.collect([_part(tmp_path, "a", "2026-10-01T00:00:00", "aaaa", "passed", 0.01)])
    gone = next(iter(run["tests"].values()))
    gone["file"] = "tests/validation/test_that_does_not_exist.py"
    assert V.merge({}, run, replace=False, repo=ROOT)["tests"] == {}


def test_the_committed_snapshot_reads_back(tmp_path: Path) -> None:
    if not V.SNAPSHOT.exists():
        pytest.skip("no snapshot committed yet")
    snap = json.loads(V.SNAPSHOT.read_text())
    assert snap["schema"] == V.SCHEMA
    assert {t["run"] for t in snap["tests"].values()} <= set(snap["runs"])


def test_the_index_reads_equations_gaps_and_the_schedule() -> None:
    from tools.docs import tests_index

    index = tests_index.build(ROOT)
    by_file = {e["file"]: e for e in index["validation"]}
    dupuit = by_file["tests/validation/analytical/steady/test_dupuit_uniform_recharge_1d.py"]
    assert "$$" in dupuit["cases"][0]["equations"]
    thin = by_file[
        "tests/validation/analytical/transient/test_brutsaert_recession_boussinesq_thin_1d.py"
    ]
    notes = thin["cases"][0]["tolerance_notes"]
    assert "gap" in notes["tolerances_modflow6.toml"]
    assert "doc" not in thin["cases"][0]["tolerance_files"]["tolerances_modflow6.toml"]
    theis = by_file["tests/validation/analytical/transient/test_theis.py"]
    assert theis["reference"].startswith("the Theis (1935) drawdown")
    nightly = [j for j in index["schedule"] if j["workflow"] == "ci-nightly.yml"]
    assert nightly and nightly[0]["markers"] == "not petsc"
    assert nightly[0]["when"] == ["every day at 05:00 UTC"]


def test_a_boussinesq_variant_is_left_out_by_a_job_that_excludes_petsc() -> None:
    from tools.docs import tests_index

    jobs = [
        {"paths": ["tests/validation/"], "markers": "not petsc", "petsc4py": False},
        {"paths": ["tests"], "markers": "fast", "petsc4py": False},
    ]
    functions = [
        {
            "name": "test_x",
            "markers": ["fast"],
            "solvers": [{"id": "modflow6", "marks": []}, {"id": "boussinesq", "marks": []}],
        }
    ]
    runs = tests_index.runs_in("tests/validation/analytical/steady/test_x.py", functions, jobs)
    assert runs["modflow6"] == [{"job": 0, "skipped": False}, {"job": 1, "skipped": False}]
    assert runs["boussinesq"] == [{"job": 1, "skipped": True}]


@pytest.mark.parametrize(
    ("cron", "words"),
    [
        ("0 5 * * *", "every day at 05:00 UTC"),
        ("0 5 * * 0", "every Sunday at 05:00 UTC"),
        ("17 4 * * 1", "every Monday at 04:17 UTC"),
    ],
)
def test_a_cron_line_reads_in_words(cron: str, words: str) -> None:
    from tools.docs import tests_index

    assert tests_index.cron_words(cron) == words


def test_every_validation_variant_runs_in_a_job_that_can_run_it() -> None:
    from tools.docs import tests_index

    index = tests_index.build(ROOT)
    orphans = [
        (entry["file"], solver)
        for entry in index["validation"]
        for solver, hits in entry["runs_in"].items()
        if not any(not hit["skipped"] for hit in hits)
    ]
    assert orphans == []


def test_fetch_merges_the_artifacts_it_finds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = V.collect([_part(tmp_path, "a", "2026-10-01T00:00:00", "aaaa", "passed", 0.01)])
    artifact = json.dumps(V.merge({}, run, replace=True, repo=ROOT))
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        calls.append(command)
        if command[:3] == ["gh", "run", "list"]:
            workflow = command[command.index("--workflow") + 1]
            return SimpleNamespace(returncode=0, stdout="11\n" if "petsc" in workflow else "7\n")
        name = command[command.index("--name") + 1]
        if "petsc" in name:
            return SimpleNamespace(returncode=1, stdout="")
        target = Path(command[command.index("--dir") + 1])
        target.mkdir(parents=True)
        (target / "validation-results.json").write_text(artifact)
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(V.subprocess, "run", fake_run)
    snapshot = tmp_path / "snapshot.json"
    assert V.main(["fetch", "--branch", "dev", "--snapshot", str(snapshot)]) == 0
    downloads = [c for c in calls if c[:3] == ["gh", "run", "download"]]
    assert [(c[3], c[c.index("--name") + 1]) for c in downloads] == [
        ("7", "validation-results-dev"),
        ("11", "validation-results-petsc-dev"),
    ]
    assert json.loads(snapshot.read_text())["tests"] == json.loads(artifact)["tests"]


def test_fetch_fails_when_no_artifact_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        V.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="")
    )
    with pytest.raises(SystemExit, match="no validation result artifact"):
        V.main(["fetch", "--snapshot", str(tmp_path / "s.json")])
