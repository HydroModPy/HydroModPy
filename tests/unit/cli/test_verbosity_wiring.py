"""Guard tests for the ``-q/-v/--debug`` console verbosity flags.

Every leaf of the commands that do work offers the shorthands, and applies the
resolved level before doing any work.
"""

from __future__ import annotations

import argparse

import pytest

from hydromodpy.cli.main import _build_parser
from hydromodpy.core.logging import DEFAULT_VERBOSITY, current_verbosity, set_verbosity
from tests.unit.cli._tree import leaves

VERBOSITY_OPTIONS = {"--verbosity", "-q", "--quiet", "-v", "--verbose", "--debug"}

# What takes the verbosity flags, every leaf of it. A family that prints only a
# line or two (site, example, lock) leaves the level to HMP_VERBOSITY.
WITH_VERBOSITY = (
    "viz",
    "data",
    "catalog",
    "project",
    "campaign",
    "report",
    "export",
    "spinup",
    "run",
    "calibrate",
)


LEAVES = {" ".join(words): parser for words, parser in leaves() if words[0] in WITH_VERBOSITY}


@pytest.fixture(autouse=True)
def _restore_verbosity():
    """Every test in this module may flip the process-wide console level."""
    before = current_verbosity()
    yield
    set_verbosity(before)


@pytest.mark.parametrize("verb", sorted(LEAVES))
def test_a_leaf_offers_the_shorthands(verb: str) -> None:
    """A static check: most of these commands need a workspace or an index to run."""
    parser = LEAVES[verb]
    opts = {flag for action in parser._actions for flag in action.option_strings}
    assert not VERBOSITY_OPTIONS - opts, f"{verb} is missing {VERBOSITY_OPTIONS - opts}"


def test_the_level_is_applied_before_the_verb_runs(monkeypatch) -> None:
    """``main`` sets the level of the flag before it calls the handler of any verb."""
    from tests.unit.cli._hmp import run_hmp

    seen: list[str] = []
    monkeypatch.setattr(
        "hydromodpy.cli.commands.viz.list_cmd.run", lambda args: seen.append(current_verbosity())
    )
    assert run_hmp(monkeypatch, "viz", "list", "-q") == 0
    assert seen == ["quiet"]


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
