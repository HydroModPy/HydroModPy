"""``hmp catalog gc`` reads the project tree and acts on it, plan first."""

from __future__ import annotations

import importlib
import json
import os
import socket
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydromodpy.core.state.layout import RUNS_DIRNAME
from hydromodpy.results.outcome import Outcome, read_outcome, write_outcome
from hydromodpy.results.retention import TRASH_RETENTION_DAYS
from hydromodpy.results.trash import list_trash, read_tombstones, trash_run


def _run(monkeypatch, argv: list[str]) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _project(root: Path, name: str = "demo") -> Path:
    project = root / name
    project.mkdir(parents=True)
    (project / "project.toml").write_text(f'[site]\nname = "{name}"\n', encoding="utf-8")
    return project


def _make_run(project: Path, name: str) -> Path:
    run_dir = project / RUNS_DIRNAME / name
    (run_dir / "tables.parquet").mkdir(parents=True)
    return run_dir


def _dead_pid() -> int:
    """A pid that belonged to a process of this host and is gone."""
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    return pid


def _outcome(run_dir: Path, status: str, *, started_at: datetime, dead: bool = False) -> None:
    """Write an outcome. A dead attempt ran on this host under a pid that is gone."""
    write_outcome(
        run_dir,
        Outcome(
            case_id=run_dir.name,
            attempt=1,
            attempt_id="a1",
            status=status,
            written_by="worker",
            started_at=started_at,
            ended_at=None if status == "running" else started_at,
            host=socket.gethostname() if dead else "node-1",
            pid=_dead_pid() if dead else os.getpid(),
        ),
    )


def _versions(project: Path, stem: str, count: int) -> list[Path]:
    names = [stem] + [f"{stem}.v{n}" for n in range(2, count + 1)]
    return [_make_run(project, name) for name in names]


def _gc(monkeypatch, capsys, target: Path, *extra: str) -> dict:
    capsys.readouterr()
    code = _run(
        monkeypatch, ["hmp", "catalog", "gc", "-w", str(target), "--format", "json", *extra]
    )
    assert code == 0
    return json.loads(capsys.readouterr().out)["data"]


def test_gc_help_displays(monkeypatch, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "catalog", "gc", "--help"]) == 0
    assert "--keep-versions" in capsys.readouterr().out


def test_gc_plans_by_default_and_touches_nothing(monkeypatch, capsys, tmp_path) -> None:
    project = _project(tmp_path)
    runs = _versions(project, "x", 7)

    report = _gc(monkeypatch, capsys, project)

    block = report["projects"][str(project.resolve())]
    assert block["plan"]["superseded_runs"] == ["runs/x", "runs/x.v2"]
    assert block["summary"] == {}
    assert all(run.is_dir() for run in runs)
    assert list_trash(project) == []


def test_gc_apply_moves_the_superseded_versions_to_the_trash(monkeypatch, capsys, tmp_path) -> None:
    project = _project(tmp_path)
    _versions(project, "x", 7)

    report = _gc(monkeypatch, capsys, project, "-y")

    assert report["projects"][str(project.resolve())]["summary"]["superseded_runs"] == 2
    assert sorted(entry.rel_dir for entry in list_trash(project)) == ["runs/x", "runs/x.v2"]
    assert sorted(p.name for p in (project / RUNS_DIRNAME).iterdir()) == [
        f"x.v{n}" for n in range(3, 8)
    ]


def test_gc_keep_versions_all_disables_the_rule(monkeypatch, capsys, tmp_path) -> None:
    project = _project(tmp_path)
    _versions(project, "x", 7)
    report = _gc(monkeypatch, capsys, project, "--keep-versions", "all")
    assert report["projects"][str(project.resolve())]["plan"]["superseded_runs"] == []


def test_gc_spares_a_pinned_run(monkeypatch, capsys, tmp_path) -> None:
    project = _project(tmp_path)
    _versions(project, "x", 3)
    assert _run(monkeypatch, ["hmp", "catalog", "tag", "x", "pinned", "-w", str(project)]) == 0

    report = _gc(monkeypatch, capsys, project, "--keep-versions", "1", "-y")

    assert report["projects"][str(project.resolve())]["plan"]["superseded_runs"] == ["runs/x.v2"]
    assert (project / RUNS_DIRNAME / "x").is_dir()


def test_gc_trashes_the_runs_past_the_age_limit(monkeypatch, capsys, tmp_path) -> None:
    project = _project(tmp_path)
    old = _make_run(project, "old")
    _outcome(old, "completed", started_at=datetime.now(UTC) - timedelta(days=400))
    recent = _make_run(project, "recent")
    _outcome(recent, "completed", started_at=datetime.now(UTC) - timedelta(days=2))
    _make_run(project, "unknown_age")

    report = _gc(monkeypatch, capsys, project, "--max-age-days", "180", "-y")

    assert report["projects"][str(project.resolve())]["plan"]["expired_runs"] == ["runs/old"]
    assert not old.exists()
    assert recent.is_dir()
    assert (project / RUNS_DIRNAME / "unknown_age").is_dir()


def test_gc_marks_a_stale_attempt_aborted_and_leaves_a_live_one(
    monkeypatch, capsys, tmp_path
) -> None:
    project = _project(tmp_path)
    stale = _make_run(project, "stale")
    _outcome(stale, "running", started_at=datetime.now(UTC) - timedelta(days=1), dead=True)
    day_ago = time.time() - 86400
    os.utime(stale / "outcome.json", (day_ago, day_ago))
    (stale / ".hmp" / "scratch").mkdir(parents=True)
    live = _make_run(project, "live")
    _outcome(live, "running", started_at=datetime.now(UTC))

    report = _gc(monkeypatch, capsys, project, "--keep-versions", "1", "--max-age-days", "1", "-y")

    plan = report["projects"][str(project.resolve())]["plan"]
    assert plan["stale_runs"] == ["runs/stale"]
    assert plan["expired_runs"] == []
    closed = read_outcome(stale)
    assert closed is not None and closed.status == "aborted" and closed.written_by == "launcher"
    assert closed.error is not None and closed.error.type == "stale"
    assert (stale / ".hmp" / "scratch").is_dir()
    assert read_outcome(live).status == "running"


def test_gc_closes_a_stale_session_so_it_can_be_trashed(monkeypatch, capsys, tmp_path) -> None:
    from hydromodpy.results.session.descriptor import read_session, write_session
    from tests._helpers.session_documents import session_descriptor

    project = _project(tmp_path)
    session = project / "sessions" / "calib"
    session.mkdir(parents=True)
    started = datetime.now(UTC) - timedelta(days=1)
    write_session(
        session,
        session_descriptor(
            "calib", site="demo", session_id="sess0001", method="tpe", started_at=started
        ),
    )
    _outcome(session, "running", started_at=started, dead=True)
    day_ago = time.time() - 86400
    os.utime(session / "outcome.json", (day_ago, day_ago))

    report = _gc(monkeypatch, capsys, project, "-y")

    assert report["projects"][str(project.resolve())]["plan"]["stale_sessions"] == [
        "sessions/calib"
    ]
    assert read_outcome(session).status == "aborted"
    descriptor = read_session(session)
    assert descriptor.status == "aborted" and descriptor.ended_at is not None
    trash_run(project, "sessions/calib", now=datetime.now(UTC))
    assert not session.exists()


def test_gc_removes_the_expired_trash_with_tombstones(monkeypatch, capsys, tmp_path) -> None:
    project = _project(tmp_path)
    long_ago = datetime.now(UTC) - timedelta(days=TRASH_RETENTION_DAYS + 1)
    _make_run(project, "gone")
    trash_run(project, "runs/gone", now=long_ago)
    kept = _make_run(project, "kept")
    assert _run(monkeypatch, ["hmp", "catalog", "tag", "kept", "pinned", "-w", str(project)]) == 0
    trash_run(project, "runs/kept", now=long_ago, force=True)
    del kept
    _make_run(project, "fresh")
    trash_run(project, "runs/fresh", now=datetime.now(UTC))

    report = _gc(monkeypatch, capsys, project, "-y")

    assert report["projects"][str(project.resolve())]["summary"]["expired_trash"] == 1
    assert sorted(entry.rel_dir for entry in list_trash(project)) == ["runs/fresh", "runs/kept"]
    assert [tombstone.rel_dir for tombstone in read_tombstones(project)] == ["runs/gone"]


def test_gc_walks_every_project_of_a_workspace(monkeypatch, capsys, tmp_path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "projects").mkdir(parents=True)
    first = _project(workspace / "projects", "a")
    second = _project(workspace / "projects", "b")
    _versions(first, "x", 2)
    _versions(second, "y", 2)

    report = _gc(monkeypatch, capsys, workspace, "--keep-versions", "1")

    plans = {
        Path(root).name: block["plan"]["superseded_runs"]
        for root, block in report["projects"].items()
    }
    assert plans == {"a": ["runs/x"], "b": ["runs/y"]}
    assert not (workspace / ".hmp").exists()


def test_gc_rejects_a_retention_window_of_zero(monkeypatch, tmp_path) -> None:
    project = _project(tmp_path)
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "-w", str(project), "--keep-versions", "0"])
    assert code == 2
