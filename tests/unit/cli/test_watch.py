"""``hmp catalog watch`` reads the outcomes and the pulses, never the index."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from hydromodpy.cli._workers.catalog import watch_running
from tests._helpers.sealed_runs import make_project, seal_run, write_attempt

from ._hmp import run_main as _run


def test_watch_flags_stale_and_live_attempts(tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    write_attempt(root, "runs/stale_run", status="running", heartbeat_age_s=3600)
    write_attempt(root, "runs/live_run", status="running", heartbeat_age_s=3)

    rows = {row["rel_dir"]: row for row in watch_running(root)}

    assert rows["runs/stale_run"]["stale"] is True
    assert rows["runs/live_run"]["stale"] is False
    assert rows["runs/live_run"]["age_s"] is not None
    assert rows["runs/live_run"]["step"] == "run_solver"


def test_watch_lists_nothing_when_nothing_runs(tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "done")
    write_attempt(root, "runs/broken", status="failed")

    assert watch_running(root) == []


def test_a_pulse_without_a_heartbeat_file_ages_from_the_outcome(tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    write_attempt(root, "runs/silent", status="running")

    (row,) = watch_running(root, stale_minutes=60)

    assert row["age_s"] is None
    assert row["stale"] is False


def test_the_threshold_is_a_display_choice(tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    write_attempt(root, "runs/slow", status="running", heartbeat_age_s=120)

    assert watch_running(root, stale_minutes=1)[0]["stale"] is True
    assert watch_running(root, stale_minutes=10)[0]["stale"] is False


def test_the_command_answers_without_an_index(monkeypatch, tmp_path: Path, capsys) -> None:
    root = make_project(tmp_path / "demo")
    write_attempt(root, "runs/live_run", status="running", heartbeat_age_s=3)

    code = _run(
        monkeypatch, ["hmp", "catalog", "watch", "--workspace", str(root), "--format", "json"]
    )

    assert code == 0
    rows = json.loads(capsys.readouterr().out)["data"]
    assert [row["rel_dir"] for row in rows] == ["runs/live_run"]
    assert not (root / ".hmp").exists()
