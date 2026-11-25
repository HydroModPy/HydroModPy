"""The board of a [sites] launch reads the journal lines and the progress files.

Without a terminal it prints one line per prepare and per finished case, with the
counts and the time left. On a terminal it draws the bars and one row per running
case, with the stress periods MODFLOW has solved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

from hydromodpy.cli.launch_board import LaunchBoard


def _start(n_cases: int = 3, parallel: int = 2) -> dict:
    return {
        "event": "launch_start",
        "plan_hash": "7c1d23fa",
        "n_cases": n_cases,
        "parallel": parallel,
    }


def test_without_a_terminal_it_prints_one_line_per_prepare_and_per_case(
    capsys: pytest.CaptureFixture[str],
) -> None:
    board = LaunchBoard(live=False)
    with board:
        board(_start())
        board({"event": "prepare_start", "case_id": "a-p1"})
        board({"event": "prepare_end", "case_id": "a-p1", "status": "completed"})
        for case in ("a-p2", "a-p3"):
            board({"event": "prepare_end", "case_id": case, "status": "completed", "like": "a-p1"})
        board({"event": "lockfile", "path": "hydromodpy.lock"})
        board({"event": "case_start", "case_id": "a-p1"})
        board({"event": "case_end", "case_id": "a-p1", "status": "completed"})
        board({"event": "case_start", "case_id": "a-p2"})
        board({"event": "case_end", "case_id": "a-p2", "status": "failed"})

    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == "[launch] plan 7c1d23fa: 3 cases, 2 side by side"
    assert lines[1].startswith("[prepare] a-p1: completed in ")
    assert lines[2].startswith("[prepare] 3 cases ready from 1 prepare in ")
    assert lines[3].startswith("[1/3] completed a-p1")
    assert "1 completed, 0 not, 0 running, about" in lines[3]
    assert lines[4].startswith("[2/3] failed    a-p2")
    assert len(lines) == 5


def test_a_bad_line_never_stops_the_launch(capsys: pytest.CaptureFixture[str]) -> None:
    board = LaunchBoard(live=False)
    with board:
        board({"event": "launch_start", "n_cases": "many"})

    assert capsys.readouterr().err == ""


def test_the_board_shows_the_periods_a_running_case_solved(tmp_path: Path) -> None:
    events = tmp_path / "a-p1.run.ndjson"
    lines = [
        {"stage": "prepare_solver", "step": None, "of": None},
        {"stage": "Solving stress periods", "step": 6209, "of": 12418},
    ]
    events.write_text("\n".join(json.dumps(line) for line in lines) + "\n{torn", encoding="utf-8")
    board = LaunchBoard(live=False)
    board(_start())
    board({"event": "case_start", "case_id": "a-p1", "progress": str(events)})
    board({"event": "case_start", "case_id": "a-p2"})

    console = Console(width=120, record=True, force_terminal=True)
    console.print(board)
    text = console.export_text()

    assert "7c1d23fa" in text
    assert "0/3" in text
    assert "a-p1" in text and "Solving stress periods" in text and "6209/12418" in text
    assert "a-p2" in text and "run" in text
