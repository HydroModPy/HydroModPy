"""``hmp ls`` with ``--best``, ``--by site`` and ``--mixed-windows`` on sealed runs of two sites.

``--best nse`` ranks, ``--by site --best nse`` keeps one run per site, and scores on two windows are
refused unless ``--mixed-windows``. A listing outside any project or workspace stops with the
not-found code instead of reading a default folder. nse has no unit.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.cli.exit_codes import EXIT_NOT_FOUND, EXIT_USAGE, EXIT_VALIDATION
from hydromodpy.cli.main import main as hmp_main
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.record.record import RunRecord
from tests._helpers.sealed_runs import make_project, seal_run


def run_ls(monkeypatch, argv: list[str]) -> int:
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    try:
        hmp_main(argv[1:])
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def with_overrides(run_dir: Path, overrides: dict) -> None:
    record = RunRecord.read(run_dir)
    record.model_copy(
        update={"lineage": record.lineage.model_copy(update={"overrides": overrides})}
    ).write(run_dir)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = make_project(tmp_path / "bretagne")
    seal_run(root, "J0014010-base", project="bretagne", site="J0014010", recipe="base", nse=0.62)
    seal_run(root, "J0014010-base.v2", project="bretagne", site="J0014010", recipe="base", nse=0.81)
    with_overrides(root / "runs" / "J0014010-base.v2", {"flow.param.K.field.value": 2e-5})
    seal_run(root, "J0170000-base", project="bretagne", site="J0170000", recipe="base", nse=0.55)
    rebuild_index(root)
    return root


def rows_of(capsys) -> list[dict]:
    return json.loads(capsys.readouterr().out)["data"]


def test_best_refuses_runs_scored_at_different_stations(monkeypatch, project, capsys) -> None:
    argv = ["hmp", "ls", "-w", str(project), "--best", "nse", "--format", "json"]

    assert run_ls(monkeypatch, argv) != 0

    err = capsys.readouterr().err
    assert "different rules" in err
    assert "--by site" in err


def test_by_site_alone_groups_every_run_under_its_site(monkeypatch, project, capsys) -> None:
    argv = ["hmp", "ls", "-w", str(project), "--by", "site", "--format", "json"]
    assert run_ls(monkeypatch, argv) == 0

    assert [row["site"] for row in rows_of(capsys)] == ["J0014010", "J0014010", "J0170000"]


def test_scores_on_two_windows_are_refused_unless_mixed(monkeypatch, tmp_path, capsys) -> None:
    root = make_project(tmp_path / "mixed")
    seal_run(root, "a-base", project="mixed", site="a", recipe="base", nse=0.6)
    seal_run(
        root,
        "b-base",
        project="mixed",
        site="b",
        recipe="base",
        nse=0.7,
        window=DateWindow(start=date(2010, 1, 1), end=date(2014, 12, 31)),
    )
    rebuild_index(root)
    argv = ["hmp", "ls", "-w", str(root), "--best", "nse"]

    assert run_ls(monkeypatch, argv) == EXIT_VALIDATION
    assert "--mixed-windows" in capsys.readouterr().err
    assert run_ls(monkeypatch, [*argv, "--mixed-windows"]) == 0


def test_a_metric_without_a_direction_is_a_usage_error(monkeypatch, project, capsys) -> None:
    argv = ["hmp", "ls", "-w", str(project), "--best", "log_nse"]

    assert run_ls(monkeypatch, argv) == EXIT_USAGE
    assert "nse_log" in capsys.readouterr().err


def test_nothing_around_the_cwd_is_not_found(monkeypatch, tmp_path, capsys) -> None:
    empty = tmp_path / "nowhere"
    empty.mkdir()
    monkeypatch.chdir(empty)

    assert run_ls(monkeypatch, ["hmp", "ls"]) == EXIT_NOT_FOUND
    assert "-w" in capsys.readouterr().err


def test_best_names_a_site_without_a_scored_run_and_why(monkeypatch, tmp_path, capsys) -> None:
    root = make_project(tmp_path / "unscored")
    seal_run(root, "a-base", project="unscored", site="a", recipe="base", nse=None, window=None)
    seal_run(root, "b-base", project="unscored", site="b", recipe="base", nse=0.7)
    rebuild_index(root)
    argv = ["hmp", "ls", "-w", str(root), "--by", "site", "--best", "nse"]

    assert run_ls(monkeypatch, argv) == 0
    out = capsys.readouterr().out
    assert "# site: b" in out
    assert out.strip().endswith("no sealed run of a is scored: declare [metrics] window")

    assert run_ls(monkeypatch, [*argv, "--format", "json"]) == 0
    captured = capsys.readouterr()
    assert [row["site"] for row in json.loads(captured.out)["data"]] == ["b"]
    assert "no sealed run of a is scored: declare [metrics] window" in captured.err


def test_best_on_unscored_runs_only_says_why_nothing_is_listed(
    monkeypatch, tmp_path, capsys
) -> None:
    root = make_project(tmp_path / "steady")
    seal_run(root, "a-base", project="steady", site="a", recipe="base", nse=None, window=None)
    rebuild_index(root)

    assert run_ls(monkeypatch, ["hmp", "ls", "-w", str(root), "--best", "nse"]) == 0
    out = capsys.readouterr().out
    assert "has a nse)" in out
    assert "no sealed run of a is scored: declare [metrics] window" in out


@pytest.mark.parametrize("fmt", ["json", "csv"])
def test_best_on_unscored_runs_keeps_stdout_machine_readable(
    monkeypatch, tmp_path, capsys, fmt
) -> None:
    root = make_project(tmp_path / "steady")
    seal_run(root, "a-base", project="steady", site="a", recipe="base", nse=None, window=None)
    rebuild_index(root)
    argv = ["hmp", "ls", "-w", str(root), "--best", "nse", "--format", fmt]

    assert run_ls(monkeypatch, argv) == 0
    captured = capsys.readouterr()
    assert "has a nse)" in captured.err
    assert "no sealed run of a is scored: declare [metrics] window" in captured.err
    assert "has a nse)" not in captured.out
    assert "scored" not in captured.out
    if fmt == "json":
        assert json.loads(captured.out)["data"] == []
