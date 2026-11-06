"""The ``hmp`` verbs are the ones the target lists, no more, no fewer.

The target (``CIBLE.md`` D6, D9 and the retirements of section 3.1 of the
implementation prompt) names every verb and every action of a family. This
test walks the argparse tree ``main`` builds and compares it with that list:
a verb the target names and the CLI lacks fails here, and so does a verb or
an option the target retired. It also checks the two promises D9 makes about
the workspace: every verb that takes one offers ``-w``, and none falls back
on ``~/hydromodpy`` when nothing names one.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

import pytest

from hydromodpy.cli.conventions import OldVerb
from hydromodpy.cli.main import _build_parser
from tests.unit.cli._tree import leaves

from ._hmp import run_main as _run

# Families and their actions. A family lists every action the target names,
# plus the actions it keeps that the target does not retire (``catalog point``,
# ``viz list``, the ``config`` helpers), so the comparison is exact.
TARGET_FAMILIES: dict[str, frozenset[str]] = {
    "workspace": frozenset({"init", "list", "clean"}),
    "project": frozenset(
        {
            "new",
            "list",
            "show",
            "status",
            "log",
            "plan",
            "delete",
            "import",
        }
    ),
    "campaign": frozenset({"array", "case", "collect", "promote", "prune"}),
    "lock": frozenset({"update", "verify"}),
    "site": frozenset({"add", "import", "ls", "show"}),
    "catalog": frozenset(
        {
            "ls",
            "show",
            "query",
            "point",
            "rank",
            "reindex",
            "delete",
            "restore",
            "trash",
            "gc",
            "tag",
            "note",
            "rename",
            "diff",
            "watch",
            "import",
            "rerun",
        }
    ),
    "report": frozenset({"render", "compare", "catchment"}),
    "viz": frozenset({"list", "show"}),
    "config": frozenset(
        {"template", "check", "resolve", "schema", "targets", "validate-field", "wizard"}
    ),
    "data": frozenset({"ls", "get", "check", "add", "remove", "prune", "archive", "restore"}),
    "example": frozenset({"list", "show", "add"}),
    "privacy": frozenset({"purge", "verify"}),
    "dev": frozenset({"run-script", "examples", "manage", "test"}),
}

# Verbs without actions.
TARGET_LEAVES: frozenset[str] = frozenset(
    {
        "run",
        "calibrate",
        "spinup",
        "export",
        "publish",
        "completion",
        "doctor",
        "install-binaries",
    }
)

# What the target retired, by verb, by action and by option.
REMOVED_VERBS: frozenset[str] = frozenset(
    {"process", "audit", "compare", "testbed", "init", "replay", "test"}
)
REMOVED_ACTIONS: tuple[tuple[str, str], ...] = (
    ("viz", "gallery"),
    ("workspace", "prune"),
    ("workspace", "search"),
    ("workspace", "register"),
    ("workspace", "forget"),
    ("data", "import"),
    ("project", "run"),
    ("project", "export"),
    ("viz", "regen"),
    ("site", "report"),
)
REMOVED_OPTIONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("calibrate",), "--check"),
    (("doctor",), "--migrate"),
    (("doctor",), "--migrate-layout"),
    (("doctor",), "--migrate-sessions"),
    (("workspace", "clean"), "--share"),
    (("workspace", "clean"), "--figures"),
    (("report", "catchment"), "--with-lock"),
)


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def _commands(sub: argparse._SubParsersAction) -> dict[str, argparse.ArgumentParser]:
    """Return the commands a group holds. A form that only names its new one is not one."""
    return {name: child for name, child in sub.choices.items() if not isinstance(child, OldVerb)}


def _tree() -> dict[str, argparse.ArgumentParser]:
    return _commands(_subparsers(_build_parser()))


def _leaf(path: tuple[str, ...]) -> argparse.ArgumentParser | None:
    parser: argparse.ArgumentParser | None = _build_parser()
    for name in path:
        sub = _subparsers(parser) if parser is not None else None
        parser = sub.choices.get(name) if sub is not None else None
    return parser


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {option for action in parser._actions for option in action.option_strings}


def test_the_verbs_are_the_target_verbs() -> None:
    assert set(_tree()) == set(TARGET_FAMILIES) | TARGET_LEAVES


@pytest.mark.parametrize("family", sorted(TARGET_FAMILIES))
def test_each_family_holds_exactly_the_target_actions(family: str) -> None:
    sub = _subparsers(_tree()[family])
    assert sub is not None, f"hmp {family} declares no action"
    assert set(_commands(sub)) == set(TARGET_FAMILIES[family])


@pytest.mark.parametrize("verb", sorted(TARGET_LEAVES))
def test_each_leaf_verb_takes_no_action(verb: str) -> None:
    parser = _tree().get(verb)
    assert parser is not None, f"hmp {verb} is not registered"
    assert _subparsers(parser) is None


def test_every_verb_and_action_carries_its_help() -> None:
    missing = []
    for path, _parser in leaves():
        parent = _leaf(path[:-1])
        sub = _subparsers(parent)
        helps = {action.dest: action.help for action in sub._choices_actions}
        if not (helps.get(path[-1]) or "").strip():
            missing.append(" ".join(path))
    assert missing == []


@pytest.mark.parametrize("verb", sorted(REMOVED_VERBS))
def test_a_retired_verb_is_gone(verb: str) -> None:
    assert verb not in _tree()


@pytest.mark.parametrize(("family", "action"), REMOVED_ACTIONS)
def test_a_retired_action_is_gone(family: str, action: str) -> None:
    assert action not in _commands(_subparsers(_tree()[family]))


@pytest.mark.parametrize(("path", "option"), REMOVED_OPTIONS)
def test_a_retired_option_is_gone(path: tuple[str, ...], option: str) -> None:
    parser = _leaf(path)
    assert parser is not None, f"hmp {' '.join(path)} is not registered"
    assert option not in _options(parser)


# --- no silent fallback on ~/hydromodpy ---------------------------------------


@pytest.fixture
def home_workspace(tmp_path, monkeypatch) -> Path:
    """A workspace at the default folder, and a cwd that no workspace holds."""
    from hydromodpy.data.workspace import scaffold

    workspace = tmp_path / "home" / "hydromodpy"
    (workspace / "data").mkdir(parents=True)
    (workspace / "projects" / "demo").mkdir(parents=True)
    (workspace / "projects" / "demo" / "project.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(scaffold, "DEFAULT_ROOT", workspace)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return workspace


@pytest.mark.parametrize(
    "argv",
    [
        ["hmp", "project", "list"],
        ["hmp", "project", "show", "demo"],
        ["hmp", "site", "ls"],
        ["hmp", "site", "show", "demo"],
        ["hmp", "data", "ls"],
        ["hmp", "data", "check"],
        ["hmp", "workspace", "clean", "--results"],
    ],
    ids=lambda argv: " ".join(argv[1:]),
)
def test_a_verb_without_a_workspace_stops_instead_of_reading_home(
    monkeypatch, capsys, home_workspace, argv
) -> None:
    assert _run(monkeypatch, argv) == 10
    captured = capsys.readouterr()
    assert "-w" in captured.err
    assert str(home_workspace) not in captured.out + captured.err


def test_doctor_without_a_workspace_says_so_instead_of_probing_home(
    monkeypatch, capsys, home_workspace
) -> None:
    _run(monkeypatch, ["hmp", "doctor", "--format", "json"])
    report = json.loads(capsys.readouterr().out)["data"]
    workspace = next(entry for entry in report["checks"] if entry["name"] == "workspace")
    assert workspace["status"] == "WARN"
    assert "-w" in workspace["hint"]
    assert str(home_workspace) not in json.dumps(report)
