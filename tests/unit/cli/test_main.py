"""The argparse tree that ``hmp`` builds, walked as a whole.

The verbs are the ones the target lists, no more, no fewer. Every command has a help, a leaf
carries an Example section whose lines parse, a retired form is refused with the command that
replaces it, and no verb falls back on ``~/hydromodpy`` when nothing names a workspace.
"""

from __future__ import annotations

import argparse
import builtins
import importlib
import json
import re
import shlex
import sys
from pathlib import Path

import pytest

from hydromodpy.cli.commands import ALL_COMMANDS
from hydromodpy.cli.conventions import OldVerb
from hydromodpy.cli.main import _build_parser
from tests.unit.cli._tree import commands, leaves

from ._hmp import run_main as _run

# Families and their actions. A family lists every action the target names, plus the actions it
# keeps that the target does not retire (``config figures``), so the comparison is exact.
TARGET_FAMILIES: dict[str, frozenset[str]] = {
    "workspace": frozenset({"init", "list", "clean"}),
    "project": frozenset({"new", "list", "log", "plan", "delete", "import"}),
    "campaign": frozenset({"array", "case", "collect", "promote", "prune"}),
    "site": frozenset({"add", "import", "ls", "show"}),
    "catalog": frozenset(
        {
            "query",
            "reindex",
            "delete",
            "restore",
            "trash",
            "gc",
            "tag",
            "note",
            "rename",
            "watch",
            "import",
            "rerun",
        }
    ),
    "config": frozenset({"template", "figures", "resolve", "schema", "targets", "wizard"}),
    "data": frozenset({"ls", "get", "lock", "remove", "prune", "archive", "restore"}),
    "example": frozenset({"list", "show", "add"}),
    "privacy": frozenset({"purge", "verify"}),
}

# Verbs without actions.
TARGET_LEAVES: frozenset[str] = frozenset(
    {
        "run",
        "replay",
        "calibrate",
        "spinup",
        "stop",
        "ls",
        "show",
        "diff",
        "check",
        "export",
        "publish",
        "completion",
        "doctor",
        "install-binaries",
    }
)

REMOVED_VERBS = (
    "process",
    "audit",
    "compare",
    "testbed",
    "init",
    "test",
    "dev",
    "lock",
    "report",
    "viz",
)
REMOVED_ACTIONS = (
    ("workspace", "prune"),
    ("workspace", "search"),
    ("workspace", "register"),
    ("workspace", "forget"),
    ("data", "import"),
    ("data", "add"),
    ("project", "run"),
    ("project", "export"),
    ("site", "report"),
    ("project", "show"),
    ("project", "status"),
    ("catalog", "ls"),
    ("catalog", "show"),
    ("catalog", "diff"),
    ("catalog", "point"),
    ("catalog", "rank"),
    ("config", "check"),
)
REMOVED_OPTIONS = (
    (("calibrate",), "--check"),
    (("doctor",), "--migrate"),
    (("doctor",), "--migrate-layout"),
    (("doctor",), "--migrate-sessions"),
    (("workspace", "clean"), "--share"),
    (("workspace", "clean"), "--figures"),
)

# What each command module calls in hydromodpy.project.api.
VERB_OF_COMMAND = {
    "run": "run",
    "check": "check",
    "calibrate": "calibrate",
    "spinup": "spinup",
    "replay": "replay",
    "stop": "stop",
    "export": "export",
    "publish": "publish",
    "doctor": "doctor",
    "ls": "status",
    "show": "show",
    "diff": "compare",
}

SUBCOMMANDS = [
    getattr(module, "NAME", module.__name__.rsplit(".", 1)[-1]) for module in ALL_COMMANDS
]
LEAVES = list(leaves())
LEAF_PATHS = [path for path, _ in LEAVES]
EXAMPLE_HEADING = re.compile(r"^Examples?:\s*$")
NAMES_OF_EXAMPLE_PROJECTS = ("cheze", "nancon", "naizin", "step4", "step5")


def subparsers_of(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def commands_of(sub: argparse._SubParsersAction) -> dict[str, argparse.ArgumentParser]:
    """The commands a group holds. A form that only names its new one is not one."""
    return {name: child for name, child in sub.choices.items() if not isinstance(child, OldVerb)}


def top_level() -> dict[str, argparse.ArgumentParser]:
    return commands_of(subparsers_of(_build_parser()))


def parser_at(path: tuple[str, ...]) -> argparse.ArgumentParser | None:
    parser: argparse.ArgumentParser | None = _build_parser()
    for name in path:
        sub = subparsers_of(parser) if parser is not None else None
        parser = sub.choices.get(name) if sub is not None else None
    return parser


def options_of(parser: argparse.ArgumentParser) -> set[str]:
    return {option for action in parser._actions for option in action.option_strings}


def example_lines(epilog: str | None) -> list[str]:
    lines: list[str] = []
    inside = False
    for line in (epilog or "").splitlines():
        if EXAMPLE_HEADING.match(line):
            inside = True
        elif inside and line.startswith(" "):
            lines.append(line.strip())
        elif line.strip():
            inside = False
    return lines


def example_argv(line: str) -> list[str]:
    words = shlex.split(line)
    # Drop a shell redirection such as `> out.json 2> err.log`.
    for i, word in enumerate(words):
        if word.startswith((">", "2>")):
            words = words[:i]
            break
    assert words[0] == "hmp", line
    return words[1:]


def run_help(monkeypatch, argv: list[str]) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


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


MOVED_READS = [
    pytest.param(["catalog", "ls"], "hmp ls", id="catalog ls"),
    pytest.param(["catalog", "show", "x"], "hmp show REF", id="catalog show"),
    pytest.param(["catalog", "diff", "a", "b"], "hmp diff REF REF", id="catalog diff"),
    pytest.param(["catalog", "point", "x"], "hmp show REF --point", id="catalog point"),
    pytest.param(["catalog", "rank"], "hmp show PROJECT --rank METRIC", id="catalog rank"),
    pytest.param(["viz", "show", "x", "head_map"], "hmp show REF --figure NAME", id="viz show"),
    pytest.param(["viz", "list"], "hmp config figures", id="viz list"),
    pytest.param(["report", "render"], "hmp show SESSION --report", id="report render"),
    pytest.param(["report", "catchment", "x"], "hmp show RUN --report", id="report catchment"),
    pytest.param(["report", "compare", "a", "b"], "hmp diff REF REF --to DIR", id="report compare"),
    pytest.param(["config", "check", "f.toml"], "hmp check FILE", id="config check"),
    pytest.param(["project", "status"], "hmp ls --plan", id="project status"),
    pytest.param(["project", "show"], "hmp show PROJECT", id="project show"),
]

NO_WORKSPACE_ARGV = [
    ["hmp", "project", "list"],
    ["hmp", "show", "demo"],
    ["hmp", "site", "ls"],
    ["hmp", "site", "show", "demo"],
    ["hmp", "data", "ls"],
    ["hmp", "workspace", "clean", "--results"],
]


def test_the_verbs_are_the_target_verbs() -> None:
    assert set(top_level()) == set(TARGET_FAMILIES) | TARGET_LEAVES


@pytest.mark.parametrize("family", sorted(TARGET_FAMILIES))
def test_each_family_holds_exactly_the_target_actions(family: str) -> None:
    sub = subparsers_of(top_level()[family])

    assert sub is not None, f"hmp {family} declares no action"
    assert set(commands_of(sub)) == set(TARGET_FAMILIES[family])


@pytest.mark.parametrize("verb", sorted(TARGET_LEAVES))
def test_each_leaf_verb_takes_no_action(verb: str) -> None:
    parser = top_level().get(verb)

    assert parser is not None, f"hmp {verb} is not registered"
    assert subparsers_of(parser) is None


def test_every_verb_and_action_carries_its_help() -> None:
    missing = []
    for path in LEAF_PATHS:
        sub = subparsers_of(parser_at(path[:-1]))
        helps = {action.dest: action.help for action in sub._choices_actions}
        if not (helps.get(path[-1]) or "").strip():
            missing.append(" ".join(path))
    assert missing == []


@pytest.mark.parametrize("verb", sorted(REMOVED_VERBS))
def test_a_retired_verb_is_gone(verb: str) -> None:
    assert verb not in top_level()


@pytest.mark.parametrize(("family", "action"), REMOVED_ACTIONS)
def test_a_retired_action_is_gone(family: str, action: str) -> None:
    assert action not in commands_of(subparsers_of(top_level()[family]))


@pytest.mark.parametrize(("path", "option"), REMOVED_OPTIONS)
def test_a_retired_option_is_gone(path: tuple[str, ...], option: str) -> None:
    parser = parser_at(path)

    assert parser is not None, f"hmp {' '.join(path)} is not registered"
    assert option not in options_of(parser)


@pytest.mark.parametrize("argv", NO_WORKSPACE_ARGV, ids=lambda argv: " ".join(argv[1:]))
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


@pytest.mark.parametrize("verb", ("ls", "show", "diff", "export", "publish"))
def test_each_read_is_a_command_of_the_first_level(verb: str) -> None:
    assert verb in top_level()


@pytest.mark.parametrize(("typed", "names"), MOVED_READS)
def test_a_read_that_moved_is_refused_with_its_replacement(
    monkeypatch, capsys, typed: list[str], names: str
) -> None:
    assert _run(monkeypatch, ["hmp", *typed]) == 2
    assert f"Write: {names}" in capsys.readouterr().err


def test_each_command_imports_the_api_and_calls_its_verb() -> None:
    import ast
    import inspect

    missing = []
    for command, verb in VERB_OF_COMMAND.items():
        module = importlib.import_module(f"hydromodpy.cli.commands.{command}")
        tree = ast.parse(inspect.getsource(module))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "hydromodpy.project.api"
            for alias in node.names
        }
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        reads_as = {verb, f"{verb}_verb"}
        if verb not in imported or not (reads_as & calls or "run_verb" in calls):
            missing.append(command)
    assert missing == []


def test_no_command_reads_the_root_package() -> None:
    import pkgutil

    import hydromodpy.cli.commands as command_package

    offenders = []
    for info in pkgutil.walk_packages(command_package.__path__, "hydromodpy.cli.commands."):
        source = Path(importlib.import_module(info.name).__file__).read_text(encoding="utf-8")
        if "import hydromodpy as" in source or "from hydromodpy import" in source:
            offenders.append(info.name)
    assert offenders == []


@pytest.mark.parametrize("path", LEAF_PATHS, ids=" ".join)
def test_leaf_command_has_an_example(path: tuple[str, ...]) -> None:
    parser = dict(LEAVES)[path]

    assert example_lines(parser.epilog), f"hmp {' '.join(path)} has no Example section"


@pytest.mark.parametrize("path", LEAF_PATHS, ids=" ".join)
def test_example_lines_parse(path: tuple[str, ...]) -> None:
    root = _build_parser()
    for line in example_lines(dict(LEAVES)[path].epilog):
        argv = example_argv(line)
        assert argv[: len(path)] == list(path), f"{line!r} is not an example of {path}"
        try:
            root.parse_args(argv)
        except SystemExit as exc:
            pytest.fail(f"the parser rejects {line!r} (exit {exc.code})")


def test_examples_name_no_example_project() -> None:
    for path, parser in LEAVES:
        text = (parser.epilog or "").lower()
        for name in NAMES_OF_EXAMPLE_PROJECTS:
            assert name not in text, f"hmp {' '.join(path)} names an example project: {name}"


def test_top_level_help(monkeypatch, capsys) -> None:
    assert run_help(monkeypatch, ["hmp", "--help"]) == 0

    out = capsys.readouterr().out
    for cmd in SUBCOMMANDS:
        assert cmd in out, f"{cmd} missing from top-level --help"


@pytest.mark.parametrize("words", [words for words, _ in commands()], ids=" ".join)
def test_each_command_has_a_help(monkeypatch, capsys, words: tuple[str, ...]) -> None:
    assert run_help(monkeypatch, ["hmp", *words, "--help"]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_a_missing_argcomplete_does_not_crash(monkeypatch) -> None:
    cli_main = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.delitem(sys.modules, "argcomplete", raising=False)
    real_import = builtins.__import__

    def block_argcomplete(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "argcomplete":
            raise ImportError("simulated absence")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", block_argcomplete)

    cli_main._enable_argcomplete(argparse.ArgumentParser(prog="hmp"))


def test_main_carries_the_argcomplete_marker() -> None:
    cli_main = importlib.import_module("hydromodpy.cli.main")

    source = Path(cli_main.__file__).read_text(encoding="utf-8")

    assert "PYTHON_ARGCOMPLETE_OK" in source
