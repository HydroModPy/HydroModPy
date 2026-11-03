"""``hmp project collect``: the action module of the ``hmp project`` family.

The family lists its actions at the head of the wave, so the action is
driven here through its own ``register`` and ``run``, the way the family
calls them.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.cli.commands.campaign import collect
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_VALIDATION, exit_code_for
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.run.sealed import MixedWindowsError
from tests._helpers.sealed_runs import seal_run


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="hmp project")
    sub = parser.add_subparsers(dest="action")
    collect.register(sub)
    return parser.parse_args([collect.NAME, *argv])


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "bretagne"
    root.mkdir()
    (root / "project.toml").write_text(
        '[sites]\ntable = "sites.csv"\n\n[sites.summary]\nbest = "any"\n', encoding="utf-8"
    )
    return root


def test_the_action_carries_the_four_symbols_of_a_family_action() -> None:
    assert collect.NAME == "collect"
    assert collect.HELP
    assert callable(collect.register)
    assert callable(collect.run)


def test_collect_writes_the_summary_of_the_project(tmp_path, capsys) -> None:
    root = _project(tmp_path)
    seal_run(root, "a-base", project="bretagne", site="a", recipe="base", nse=0.6)

    args = _parse([str(root / "runs"), "--write-sites"])
    args._handler(args)

    out = capsys.readouterr().out
    assert f"wrote {root / 'summary'}" in out
    assert "catalog.csv" in out
    assert (root / "summary" / "by_site.csv").is_file()
    assert (root / "summary" / "catalog.csv").is_file()


def test_mixed_windows_exit_with_the_validation_code(tmp_path, capsys) -> None:
    root = _project(tmp_path)
    seal_run(root, "a-base", project="bretagne", site="a", recipe="base", nse=0.6)
    seal_run(
        root,
        "b-base",
        project="bretagne",
        site="b",
        recipe="base",
        nse=0.7,
        window=DateWindow(start=date(2010, 1, 1), end=date(2014, 12, 31)),
    )

    args = _parse([str(root)])
    with pytest.raises(MixedWindowsError, match="--mixed-windows") as refused:
        args._handler(args)
    assert exit_code_for(refused.value) == EXIT_VALIDATION

    args = _parse([str(root), "--mixed-windows"])
    args._handler(args)
    assert (root / "summary" / "by_site.parquet").is_file()


def test_a_folder_outside_any_project_is_not_found(tmp_path) -> None:
    lonely = tmp_path / "lonely"
    lonely.mkdir()

    args = _parse([str(lonely)])
    with pytest.raises(FileNotFoundError) as missing:
        args._handler(args)
    assert exit_code_for(missing.value) == EXIT_NOT_FOUND


def test_a_figure_not_drawn_is_named_on_stderr(tmp_path, capsys) -> None:
    root = _project(tmp_path)
    (root / "project.toml").write_text(
        '[sites]\ntable = "sites.csv"\n\n[sites.summary]\nbest = "any"\nmetrics = ["nse", "kge"]\n'
        'figures = ["distribution"]\nvariables = ["kge"]\n',
        encoding="utf-8",
    )
    seal_run(root, "a-base", project="bretagne", site="a", recipe="base", nse=0.6)

    args = _parse([str(root)])
    args._handler(args)

    assert "figure not drawn: distribution of kge: " in capsys.readouterr().err
