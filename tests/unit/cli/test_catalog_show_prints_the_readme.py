"""``hmp catalog show <ref>`` prints the README the run carries, without the index (D9)."""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime

from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.annotations import add_note, add_tag
from tests._helpers.sealed_runs import make_project, seal_run

README = "# alpha\n\nRun `alpha` of project `demo`, status **completed**.\n"


def _run(monkeypatch, argv: list[str]) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_show_prints_the_readme_and_the_annotations(monkeypatch, capsys, tmp_path) -> None:
    project = make_project(tmp_path / "demo")
    run_dir = project / "runs" / "alpha"
    seal_run(project, "alpha")
    (run_dir / "README.md").write_text(README, encoding="utf-8")
    add_tag(run_dir, "pinned")
    add_note(run_dir, "K hits its upper bound", now=datetime(2026, 10, 16, 8, 0, tzinfo=UTC))

    code = _run(monkeypatch, ["hmp", "catalog", "show", "alpha", "-w", str(project)])

    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith(README.rstrip())
    assert "tags: pinned" in out
    assert "2026-10-16 08:00 K hits its upper bound" in out
    assert "hmp catalog show runs/alpha --detail" in out
    assert not catalog_path_for(project).exists(), "show never builds the index"


def test_show_of_a_name_the_project_lacks_exits_not_found(monkeypatch, capsys, tmp_path) -> None:
    project = make_project(tmp_path / "demo")
    seal_run(project, "alpha")

    code = _run(monkeypatch, ["hmp", "catalog", "show", "beta", "-w", str(project)])

    assert code == 10
    assert "beta" in capsys.readouterr().err


def test_show_of_last_outside_a_workspace_names_dash_w(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.chdir(make_project(tmp_path / "demo"))

    code = _run(monkeypatch, ["hmp", "catalog", "show", "@last"])

    assert code == 10
    err = capsys.readouterr().err
    assert "'@last' is answered by the index" in err
    assert "with -w" in err


def test_show_of_last_with_dash_w_does_not_repeat_the_hint(monkeypatch, capsys, tmp_path) -> None:
    project = make_project(tmp_path / "demo")

    code = _run(monkeypatch, ["hmp", "catalog", "show", "@last", "-w", str(project)])

    assert code == 10
    assert "with -w" not in capsys.readouterr().err
