"""``hmp ls``: the runs of a project from the index or from the directories, and the plan."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._helpers.sealed_runs import make_project, seal_run, write_attempt, write_session_dir
from tests.unit.project.launch.test_plan import write_sites_project

from ._hmp import run_hmp

pytestmark = pytest.mark.fast


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    write_attempt(root, "runs/beta", status="failed")
    write_session_dir(root, "calage", trials=2, best_trial=1)
    return root


def test_disk_lists_the_runs_and_the_sessions_without_an_index(
    monkeypatch, capsys, project: Path
) -> None:
    code = run_hmp(monkeypatch, "ls", "--disk", "-w", str(project), "--format", "json")

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["schema"] == "hmp.ls.disk.v1"
    rows = {row["name"]: row for row in document["data"]}
    assert {name: row["kind"] for name, row in rows.items()} == {
        "alpha": "run",
        "beta": "run",
        "calage": "session",
    }
    assert rows["alpha"]["status"] == "completed"
    assert rows["beta"]["status"] == "failed"


def test_disk_says_so_when_the_project_holds_nothing(monkeypatch, capsys, tmp_path: Path) -> None:
    root = make_project(tmp_path / "empty")

    code = run_hmp(monkeypatch, "ls", "--disk", "-w", str(root))

    assert code == 0
    assert "(no run or session under" in capsys.readouterr().out


def test_without_an_index_the_listing_names_the_reading_of_the_directories(
    monkeypatch, capsys, project: Path
) -> None:
    code = run_hmp(monkeypatch, "ls", "-w", str(project))

    assert code == 10
    assert "hmp ls --disk" in capsys.readouterr().err


def test_plan_says_where_each_case_stands(monkeypatch, capsys, tmp_path: Path) -> None:
    root = write_sites_project(tmp_path)
    assert run_hmp(monkeypatch, "project", "plan", str(root)) == 0
    capsys.readouterr()

    code = run_hmp(monkeypatch, "ls", "--plan", "-w", str(root), "--format", "json")

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["schema"] == "hmp.ls.plan.v1"
    data = document["data"]
    assert data["plan_stale"] is False
    assert len(data["cases"]) == 4
    assert data["counts"] == {"planned": 4}


def test_plan_takes_a_stale_age_in_minutes(monkeypatch, capsys, tmp_path: Path) -> None:
    root = write_sites_project(tmp_path)
    assert run_hmp(monkeypatch, "project", "plan", str(root)) == 0
    capsys.readouterr()

    code = run_hmp(monkeypatch, "ls", "--plan", "--stale-minutes", "1", "-w", str(root))

    assert code == 0
    assert "plan " in capsys.readouterr().out


def test_the_old_forms_are_refused_with_the_new_one(monkeypatch, capsys, project: Path) -> None:
    assert run_hmp(monkeypatch, "catalog", "ls", "-w", str(project)) == 2
    assert "Write: hmp ls" in capsys.readouterr().err
    assert run_hmp(monkeypatch, "project", "status", "-w", str(project)) == 2
    assert "Write: hmp ls --plan" in capsys.readouterr().err
