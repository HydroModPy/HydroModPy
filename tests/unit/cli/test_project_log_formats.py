"""``hmp project log --format csv`` writes CSV, one row per event; json stays json."""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

import pytest

from hydromodpy.cli.commands.project import log
from hydromodpy.project.launch.journal import Journal, new_job_dir


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "campaign"
    project.mkdir()
    (project / "project.toml").write_text("[sites]\n", encoding="utf-8")
    journal = Journal(new_job_dir(project, "local"))
    journal.append("launch_start", plan_hash="abc", n_cases=2)
    journal.append("case_end", case_id="alpha-base", status="completed", exit_code=0)
    journal.append(
        "case_end",
        case_id="beta-base",
        status="failed",
        exit_code=15,
        error={"type": "SolverError", "message": "boom"},
        rel_dir="runs/beta-base",
    )
    return project


def _args(project: Path, fmt: str) -> argparse.Namespace:
    return argparse.Namespace(
        project=str(project), workspace=None, failed=False, job=None, format=fmt, verbosity=None
    )


def test_csv_is_one_row_per_event(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _project(tmp_path)

    log.run(_args(project, "csv"))

    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert [row["event"] for row in rows] == ["launch_start", "case_end", "case_end"]
    assert rows[2]["case_id"] == "beta-base"
    assert rows[2]["error"] == "SolverError: boom"
    assert rows[2]["exit_code"] == "15"
    assert rows[0]["case_id"] == ""


def test_json_stays_the_events(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _project(tmp_path)

    log.run(_args(project, "json"))

    events = json.loads(capsys.readouterr().out)["data"]
    assert [event["event"] for event in events] == ["launch_start", "case_end", "case_end"]
