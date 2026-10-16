"""``hmp catalog ls``: the ``overrides`` column, ``--best``, ``--by site``, no silent fallback.

The runs are sealed directories indexed by the indexer. A ``.v2`` launched
with ``--set`` shows what it changed; ``--best nse`` ranks; ``--by site
--best nse`` keeps one run per site; scores on two windows are refused unless
``--mixed-windows``; a listing outside any project or workspace stops with
the not-found code instead of reading a default folder.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_USAGE, EXIT_VALIDATION
from hydromodpy.cli.main import main as hmp_main
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.record import RunRecord
from tests._helpers.sealed_runs import make_project, seal_run


def _run(monkeypatch, argv: list[str]) -> int:
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    try:
        hmp_main(argv[1:])
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _with_overrides(run_dir: Path, overrides: dict) -> None:
    record = RunRecord.read(run_dir)
    record.model_copy(
        update={"lineage": record.lineage.model_copy(update={"overrides": overrides})}
    ).write(run_dir)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = make_project(tmp_path / "bretagne")
    seal_run(root, "J0014010-base", project="bretagne", site="J0014010", recipe="base", nse=0.62)
    seal_run(root, "J0014010-base.v2", project="bretagne", site="J0014010", recipe="base", nse=0.81)
    _with_overrides(root / "runs" / "J0014010-base.v2", {"flow.param.K.field.value": 2e-5})
    seal_run(root, "J0170000-base", project="bretagne", site="J0170000", recipe="base", nse=0.55)
    rebuild_index(root)
    return root


def _rows(capsys) -> list[dict]:
    return json.loads(capsys.readouterr().out)


def test_a_version_shows_the_overrides_it_was_run_with(monkeypatch, project, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "catalog", "ls", "-w", str(project), "--format", "json"]) == 0

    by_name = {row["name"]: row for row in _rows(capsys)}
    assert by_name["J0014010-base.v2"]["overrides"] == "flow.param.K.field.value=2e-05"
    assert by_name["J0014010-base"]["overrides"] == ""

    assert _run(monkeypatch, ["hmp", "catalog", "ls", "-w", str(project)]) == 0
    assert "overrides: flow.param.K.field.value=2e-05" in capsys.readouterr().out


def test_best_ranks_the_runs_best_first(monkeypatch, project, capsys) -> None:
    argv = ["hmp", "catalog", "ls", "-w", str(project), "--best", "nse", "--format", "json"]
    assert _run(monkeypatch, argv) == 0

    assert [row["name"] for row in _rows(capsys)] == [
        "J0014010-base.v2",
        "J0014010-base",
        "J0170000-base",
    ]


def test_by_site_with_best_keeps_one_run_per_site(monkeypatch, project, capsys) -> None:
    argv = ["hmp", "catalog", "ls", "-w", str(project), "--by", "site", "--best", "nse"]
    assert _run(monkeypatch, [*argv, "--format", "json"]) == 0
    assert [(row["site"], row["name"]) for row in _rows(capsys)] == [
        ("J0014010", "J0014010-base.v2"),
        ("J0170000", "J0170000-base"),
    ]

    assert _run(monkeypatch, argv) == 0
    text = capsys.readouterr().out
    assert "# site: J0014010" in text
    assert "# site: J0170000" in text


def test_by_site_alone_groups_every_run_under_its_site(monkeypatch, project, capsys) -> None:
    argv = ["hmp", "catalog", "ls", "-w", str(project), "--by", "site", "--format", "json"]
    assert _run(monkeypatch, argv) == 0

    assert [row["site"] for row in _rows(capsys)] == ["J0014010", "J0014010", "J0170000"]


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
    argv = ["hmp", "catalog", "ls", "-w", str(root), "--best", "nse"]

    assert _run(monkeypatch, argv) == EXIT_VALIDATION
    assert "--mixed-windows" in capsys.readouterr().err
    assert _run(monkeypatch, [*argv, "--mixed-windows"]) == 0


def test_a_metric_without_a_direction_is_a_usage_error(monkeypatch, project, capsys) -> None:
    argv = ["hmp", "catalog", "ls", "-w", str(project), "--best", "log_nse"]

    assert _run(monkeypatch, argv) == EXIT_USAGE
    assert "nse_log" in capsys.readouterr().err


def test_nothing_around_the_cwd_is_not_found(monkeypatch, tmp_path, capsys) -> None:
    empty = tmp_path / "nowhere"
    empty.mkdir()
    monkeypatch.chdir(empty)

    assert _run(monkeypatch, ["hmp", "catalog", "ls"]) == EXIT_NOT_FOUND
    assert "-w" in capsys.readouterr().err
