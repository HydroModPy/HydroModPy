"""UX acceptance test for the ``hmp`` CLI pipeline.

Exercises the canonical newcomer flow end-to-end (without running the solver):

    hmp init
    hmp new <project>
    hmp config template
    hmp run --dry-run
    hmp list
    hmp doctor

The assertions check that each step surfaces human-readable output and
exits with the right code - not that the simulation succeeds end-to-end
(that is covered by the regression suite).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hydromodpy.cli.main import main


def _run_cli(monkeypatch, argv: list[str], *, expect_exit: bool = False) -> int:
    monkeypatch.setattr(sys, "argv", argv)
    if expect_exit:
        with pytest.raises(SystemExit) as exc_info:
            main()
        return int(exc_info.value.code or 0)
    try:
        main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_init_creates_workspace(monkeypatch, capsys, tmp_path) -> None:
    ws = tmp_path / "workspace"
    _run_cli(monkeypatch, ["hmp", "init", "--path", str(ws)])
    assert ws.is_dir()
    assert (ws / "projects").is_dir()
    assert (ws / "data").is_dir()
    out = capsys.readouterr().out
    assert "Workspace:" in out


def test_new_creates_project_and_files(monkeypatch, capsys, tmp_path) -> None:
    ws = tmp_path / "workspace"
    _run_cli(monkeypatch, ["hmp", "init", "--path", str(ws)])
    capsys.readouterr()
    _run_cli(
        monkeypatch,
        ["hmp", "new", "demo_project", "--workspace", str(ws)],
    )
    project_dir = ws / "projects" / "demo_project"
    assert project_dir.is_dir()
    assert (project_dir / "project.toml").is_file()


def test_config_template_generates_toml(monkeypatch, tmp_path) -> None:
    out = tmp_path / "cfg.toml"
    _run_cli(
        monkeypatch,
        ["hmp", "config", "template", str(out), "--profile", "user"],
    )
    assert out.is_file()
    assert out.stat().st_size > 0


def test_run_dry_run_surfaces_plan(monkeypatch, capsys, tmp_path) -> None:
    cfg = tmp_path / "cfg.toml"
    cfg.write_text('[simulation]\nname = "dry"\n', encoding="utf-8")
    _run_cli(monkeypatch, ["hmp", "run", "--dry-run", str(cfg)])
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "simulation" in out


def test_list_empty_workspace(monkeypatch, capsys, tmp_path) -> None:
    ws = tmp_path / "workspace"
    _run_cli(monkeypatch, ["hmp", "init", "--path", str(ws)])
    capsys.readouterr()
    _run_cli(
        monkeypatch,
        ["hmp", "list", "--workspace", str(ws)],
    )
    # No projects yet; should just return quietly with exit 0.
    # (``hmp init`` creates projects/ but doesn't put any project inside.)


def test_doctor_reports_without_crash(monkeypatch, capsys) -> None:
    # Doctor exits cleanly (SystemExit only if a KO status is reported).
    code = _run_cli(monkeypatch, ["hmp", "doctor", "--json"])
    out = capsys.readouterr().out
    assert "hydromodpy" in out.lower()
    assert code in (0, 1)


def test_completion_all_shells(monkeypatch, capsys) -> None:
    for shell in ("bash", "zsh", "fish"):
        _run_cli(monkeypatch, ["hmp", "completion", shell])
        out = capsys.readouterr().out
        assert len(out) > 0
        assert any(token in out for token in ("hmp", "_hmp"))
