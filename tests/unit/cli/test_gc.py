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

from ._hmp import run_main as _run


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
    out = capsys.readouterr().out
    assert "--keep-versions" in out
    assert "--trial-fields-days" in out


def test_gc_plans_by_default_and_touches_nothing(monkeypatch, capsys, tmp_path) -> None:
    project = _project(tmp_path)
    runs = _versions(project, "x", 7)

    report = _gc(monkeypatch, capsys, project)

    block = report["projects"][str(project.resolve())]
    assert block["applied"] is False
    assert block["plan"]["superseded_runs"] == ["runs/x", "runs/x.v2"]
    assert block["freed"] == {}
    assert set(block["bytes"]) == set(block["plan"])
    assert block["weight"]["total_before"] > 0
    assert block["weight"]["total_after"] == block["weight"]["total_before"]
    assert all(run.is_dir() for run in runs)
    assert list_trash(project) == []


def test_gc_apply_moves_the_superseded_versions_to_the_trash(monkeypatch, capsys, tmp_path) -> None:
    project = _project(tmp_path)
    _versions(project, "x", 7)

    report = _gc(monkeypatch, capsys, project, "-y")

    block = report["projects"][str(project.resolve())]
    assert block["applied"] is True
    assert block["freed"]["superseded_runs"] == block["bytes"]["superseded_runs"]
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

    block = report["projects"][str(project.resolve())]
    assert len(block["plan"]["expired_trash"]) == 1
    assert block["freed"]["expired_trash"] == block["bytes"]["expired_trash"]
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


def _sealed_trial(project: Path, trial: str, *, days: int) -> Path:
    """Write the sealed directory of a kept trial, its fields and its mesh."""
    from hydromodpy.results.session.descriptor import write_session
    from hydromodpy.results.storage.contract import (
        FIELDS_STORE_NAME,
        MESH_DIRNAME,
        RUN_MANIFEST_FILENAME,
    )
    from tests._helpers.sealed_runs import manifest_document
    from tests._helpers.session_documents import best_trial, session_descriptor

    session = project / "sessions" / "calib"
    write_session(
        session,
        session_descriptor("calib", site="demo", best=best_trial(1), status="completed"),
    )
    directory = session / "trials" / trial
    directory.mkdir(parents=True)
    document = manifest_document(
        name=trial,
        sealed_at=(datetime.now(UTC) - timedelta(days=days)).isoformat(),
        lineage={"kind": "trial", "trial": int(trial), "session_id": "sess0001"},
    )
    (directory / RUN_MANIFEST_FILENAME).write_text(json.dumps(document), encoding="utf-8")
    (directory / FIELDS_STORE_NAME).mkdir()
    (directory / FIELDS_STORE_NAME / "chunk").write_bytes(b"x" * 64)
    (directory / MESH_DIRNAME).mkdir()
    (directory / MESH_DIRNAME / "grid.npz").write_bytes(b"x" * 16)
    return directory


def test_gc_purges_the_fields_of_an_old_kept_trial(monkeypatch, capsys, tmp_path) -> None:
    from hydromodpy.results import retention
    from hydromodpy.results.storage.contract import FIELDS_STORE_NAME, MESH_DIRNAME
    from hydromodpy.results.storage.kept import read_purged

    project = _project(tmp_path)
    trial = _sealed_trial(project, "0002", days=100)
    # No call sets the inode change of a directory: the trial arrives with its seal.
    arrived = datetime.now(UTC) - timedelta(days=100)
    monkeypatch.setattr(retention, "_arrival", lambda directory: arrived)

    report = _gc(monkeypatch, capsys, project, "--trial-fields-days", "90")

    block = report["projects"][str(project.resolve())]
    assert block["plan"]["old_trial_fields"] == ["sessions/calib/trials/0002"]
    assert block["bytes"]["old_trial_fields"] == 64
    assert block["weight"]["total_before"] == block["weight"]["total_after"]
    assert (trial / FIELDS_STORE_NAME).is_dir()

    report = _gc(monkeypatch, capsys, project, "--trial-fields-days", "90", "-y")

    block = report["projects"][str(project.resolve())]
    assert block["freed"]["old_trial_fields"] == 64
    assert not (trial / FIELDS_STORE_NAME).exists()
    assert (trial / MESH_DIRNAME / "grid.npz").is_file()
    purged = read_purged(trial)
    assert purged is not None
    assert purged.entries == {FIELDS_STORE_NAME: 64}


def test_gc_never_purges_trial_fields_when_the_rule_is_off(monkeypatch, capsys, tmp_path) -> None:
    project = _project(tmp_path)
    _sealed_trial(project, "0002", days=400)

    report = _gc(monkeypatch, capsys, project, "--trial-fields-days", "never")

    block = report["projects"][str(project.resolve())]
    assert block["plan"]["old_trial_fields"] == []
    assert block["bytes"]["old_trial_fields"] == 0


def test_gc_rejects_a_trial_fields_window_of_zero(monkeypatch, tmp_path) -> None:
    project = _project(tmp_path)
    code = _run(
        monkeypatch,
        ["hmp", "catalog", "gc", "-w", str(project), "--trial-fields-days", "0"],
    )
    assert code == 2


def test_gc_collects_a_project_whose_project_toml_does_not_read(
    monkeypatch, capsys, tmp_path
) -> None:
    project = _project(tmp_path)
    (project / "project.toml").write_text("[[[ not toml\n", encoding="utf-8")
    scratch = project / ".hmp" / "scratch" / f"gone.p{_dead_pid()}"
    scratch.mkdir(parents=True)
    (scratch / "work").write_bytes(b"x" * 8)

    report = _gc(monkeypatch, capsys, project, "-y")

    block = report["projects"][str(project.resolve())]
    assert block["freed"]["dead_scratch"] == 8
    assert block["plan"]["products"] == []
    assert not scratch.exists()
