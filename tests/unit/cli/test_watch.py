"""``hmp catalog watch`` reads the outcomes and the pulses, never the index."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from tests._helpers.sealed_runs import make_project, write_attempt

from ._hmp import run_main as _run


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
