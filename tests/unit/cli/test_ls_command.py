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


def test_disk_listing(monkeypatch, capsys, project: Path) -> None:
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


def test_disk_listing_of_an_empty_project(monkeypatch, capsys, tmp_path: Path) -> None:
    root = make_project(tmp_path / "empty")

    code = run_hmp(monkeypatch, "ls", "--disk", "-w", str(root))

    assert code == 0
    assert "(no run or session under" in capsys.readouterr().out


def test_no_index_names_the_disk_flag(monkeypatch, capsys, project: Path) -> None:
    code = run_hmp(monkeypatch, "ls", "-w", str(project))

    assert code == 10
    assert "hmp ls --disk" in capsys.readouterr().err


def test_plan_listing(monkeypatch, capsys, tmp_path: Path) -> None:
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


def test_plan_stale_minutes(monkeypatch, capsys, tmp_path: Path) -> None:
    root = write_sites_project(tmp_path)
    assert run_hmp(monkeypatch, "project", "plan", str(root)) == 0
    capsys.readouterr()

    code = run_hmp(monkeypatch, "ls", "--plan", "--stale-minutes", "1", "-w", str(root))

    assert code == 0
    assert "plan " in capsys.readouterr().out
