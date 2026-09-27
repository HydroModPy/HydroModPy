"""Guard tests for the ``-q/-v/--debug`` console verbosity flags.

``hmp run`` and ``hmp calibrate`` already offered this grammar. This module
locks the same grammar on ``viz``, ``report``, ``spinup``, ``data``,
``catalog`` and ``project``, which used to read only the default and
``HMP_VERBOSITY``: every leaf parser must offer the shorthands, and every
leaf ``run()`` must apply the resolved level before doing any work, the same
way :func:`hydromodpy.cli.commands.run.run` and
:func:`hydromodpy.cli.commands.calibrate.run` already do.
"""

from __future__ import annotations

import argparse
import importlib
import inspect

import pytest

from hydromodpy.cli.main import _build_parser
from hydromodpy.core.logging import DEFAULT_VERBOSITY, current_verbosity, set_verbosity

VERBOSITY_OPTIONS = {"--verbosity", "-q", "--quiet", "-v", "--verbose", "--debug"}

# (group, action) leaf commands that must offer the verbosity shorthands.
FAMILY_LEAF_COMMANDS = (
    ("viz", "list"),
    ("viz", "show"),
    ("viz", "gallery"),
    ("data", "ls"),
    ("data", "get"),
    ("data", "check"),
    ("data", "add"),
    ("data", "remove"),
    ("data", "prune"),
    ("data", "archive"),
    ("data", "restore"),
    ("data", "export"),
    ("data", "export-package"),
    ("data", "import"),
    ("catalog", "ls"),
    ("catalog", "query"),
    ("catalog", "show"),
    ("catalog", "point"),
    ("catalog", "gc"),
    ("catalog", "reindex"),
    ("catalog", "delete"),
    ("catalog", "restore"),
    ("catalog", "trash"),
    ("catalog", "tag"),
    ("catalog", "note"),
    ("catalog", "rename"),
    ("catalog", "diff"),
    ("catalog", "watch"),
    ("catalog", "export"),
    ("catalog", "import"),
    ("catalog", "rerun"),
    ("project", "new"),
    ("project", "list"),
    ("project", "show"),
    ("project", "delete"),
    ("report", "render"),
    ("report", "compare"),
    ("report", "catchment"),
)

# Modules whose run() must call apply_verbosity before doing anything else
# (source-order check, same style as the family grammar guard).
RUN_MODULES = (
    "hydromodpy.cli.commands.viz.list_cmd",
    "hydromodpy.cli.commands.viz.show",
    "hydromodpy.cli.commands.viz.gallery",
    "hydromodpy.cli.commands.data.ls",
    "hydromodpy.cli.commands.data.get",
    "hydromodpy.cli.commands.data.check",
    "hydromodpy.cli.commands.data.add",
    "hydromodpy.cli.commands.data.remove",
    "hydromodpy.cli.commands.data.prune",
    "hydromodpy.cli.commands.data.archive",
    "hydromodpy.cli.commands.data.restore",
    "hydromodpy.cli.commands.data.export",
    "hydromodpy.cli.commands.data.export_package",
    "hydromodpy.cli.commands.data.import_cmd",
    "hydromodpy.cli.commands.catalog.ls",
    "hydromodpy.cli.commands.catalog.query",
    "hydromodpy.cli.commands.catalog.show",
    "hydromodpy.cli.commands.catalog.point",
    "hydromodpy.cli.commands.catalog.gc",
    "hydromodpy.cli.commands.catalog.reindex",
    "hydromodpy.cli.commands.catalog.delete",
    "hydromodpy.cli.commands.catalog.restore",
    "hydromodpy.cli.commands.catalog.trash",
    "hydromodpy.cli.commands.catalog.tag",
    "hydromodpy.cli.commands.catalog.note",
    "hydromodpy.cli.commands.catalog.rename",
    "hydromodpy.cli.commands.catalog.diff",
    "hydromodpy.cli.commands.catalog.watch",
    "hydromodpy.cli.commands.catalog.export",
    "hydromodpy.cli.commands.catalog.import_archive",
    "hydromodpy.cli.commands.catalog.rerun",
    "hydromodpy.cli.commands.project.new",
    "hydromodpy.cli.commands.project.list_cmd",
    "hydromodpy.cli.commands.project.show",
    "hydromodpy.cli.commands.project.delete",
    "hydromodpy.cli.commands.report",
    "hydromodpy.cli.commands.spinup",
)


@pytest.fixture(autouse=True)
def _restore_verbosity():
    """Every test in this module may flip the process-wide console level."""
    before = current_verbosity()
    yield
    set_verbosity(before)


def _subparsers_action(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _leaf_parser(*path: str) -> argparse.ArgumentParser:
    parser = _build_parser()
    for name in path:
        sub = _subparsers_action(parser)
        parser = sub.choices[name]
    return parser


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    opts: set[str] = set()
    for action in parser._actions:
        opts.update(action.option_strings)
    return opts


@pytest.mark.parametrize(("group", "action"), FAMILY_LEAF_COMMANDS)
def test_family_leaf_offers_verbosity_shorthands(group: str, action: str) -> None:
    opts = _option_strings(_leaf_parser(group, action))
    missing = VERBOSITY_OPTIONS - opts
    assert not missing, f"{group} {action} is missing {missing}"


def test_spinup_offers_verbosity_shorthands() -> None:
    opts = _option_strings(_leaf_parser("spinup"))
    missing = VERBOSITY_OPTIONS - opts
    assert not missing, f"spinup is missing {missing}"


@pytest.mark.parametrize(
    ("group", "action", "flag", "expected"),
    [
        ("viz", "list", "-q", "quiet"),
        ("viz", "list", "-v", "verbose"),
        ("viz", "list", "--debug", "debug"),
        ("data", "ls", "-q", "quiet"),
        ("catalog", "ls", "-v", "verbose"),
        ("project", "list", "--debug", "debug"),
        ("report", "compare", "-q", "quiet"),
    ],
)
def test_family_leaf_flag_maps_to_level(group: str, action: str, flag: str, expected: str) -> None:
    parser = _build_parser()
    extra: dict[str, list[str]] = {
        ("data", "ls"): [],
        ("catalog", "ls"): [],
        ("project", "list"): [],
        ("viz", "list"): [],
        ("report", "compare"): ["a", "b"],
    }
    positionals = extra.get((group, action), [])
    args = parser.parse_args([group, action, *positionals, flag])
    assert args.verbosity == expected


@pytest.mark.parametrize(
    "flag,expected", [("-q", "quiet"), ("-v", "verbose"), ("--debug", "debug")]
)
def test_spinup_flag_maps_to_level(flag: str, expected: str) -> None:
    parser = _build_parser()
    args = parser.parse_args(["spinup", "config.toml", flag])
    assert args.verbosity == expected


@pytest.mark.parametrize("dotted", RUN_MODULES)
def test_run_applies_verbosity(dotted: str) -> None:
    """``run()`` sets the console level, the same way ``run``/``calibrate`` do.

    A static check rather than an execution one: most of these commands need
    a workspace or a catalog to actually run. ``run``/``calibrate`` themselves
    validate their config argument (file exists, right suffix) before this
    call, so an early argument-error print is expected here too; what must
    not happen is doing real work first.
    """
    module = importlib.import_module(dotted)
    source = inspect.getsource(module.run)
    assert "apply_verbosity(args" in source, f"{dotted}.run() never calls apply_verbosity"


def test_dev_run_script_respects_quiet(monkeypatch, tmp_path) -> None:
    """``hmp dev run-script`` must not print its banner when quiet is set."""
    from hydromodpy.cli.commands.dev import run_script

    calls: list[None] = []
    monkeypatch.setattr("hydromodpy.cli.banner.print_hydromodpy", lambda: calls.append(None))
    script = tmp_path / "proto.py"
    script.write_text("pass\n")

    set_verbosity("quiet")
    parser = argparse.ArgumentParser()
    parsed = run_script.register(parser.add_subparsers()).parse_args([str(script)])
    monkeypatch.setattr(
        "hydromodpy.cli.commands.dev.run_script.subprocess.run",
        lambda *a, **k: type("R", (), {"returncode": 0})(),
    )
    with pytest.raises(SystemExit):
        run_script.run(parsed)
    assert calls == []

    set_verbosity(DEFAULT_VERBOSITY)
    calls.clear()
    with pytest.raises(SystemExit):
        run_script.run(parsed)
    assert calls == [None]
