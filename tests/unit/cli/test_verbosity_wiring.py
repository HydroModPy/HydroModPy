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
    "ls",
    "show",
    "diff",
    "data",
    "catalog",
    "project",
    "campaign",
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
        "hydromodpy.cli.commands.config._cmd_config_figures",
        lambda args: seen.append(current_verbosity()),
    )
    assert run_hmp(monkeypatch, "config", "figures", "-q") == 0
    assert seen == ["quiet"]


@pytest.mark.parametrize("verb", ["run", "calibrate", "spinup"])
def test_a_toml_verb_applies_the_level_of_its_file(verb: str) -> None:
    """These verbs read ``[workflow] verbosity`` from their file, so they apply it themselves."""
    import importlib
    import inspect

    module = importlib.import_module(f"hydromodpy.cli.commands.{verb}")
    assert "apply_verbosity(args" in inspect.getsource(module)


@pytest.mark.parametrize(
    ("words", "flag", "expected"),
    [
        (("config", "figures"), "-q", "quiet"),
        (("config", "figures"), "-v", "verbose"),
        (("config", "figures"), "--debug", "debug"),
        (("data", "ls"), "-q", "quiet"),
        (("ls",), "-v", "verbose"),
        (("project", "list"), "--debug", "debug"),
        (("diff", "a", "b"), "-q", "quiet"),
    ],
)
def test_family_leaf_flag_maps_to_level(words: tuple[str, ...], flag: str, expected: str) -> None:
    parser = _build_parser()
    args = parser.parse_args([*words, flag])
    assert args.verbosity == expected


@pytest.mark.parametrize(
    "flag,expected", [("-q", "quiet"), ("-v", "verbose"), ("--debug", "debug")]
)
def test_spinup_flag_maps_to_level(flag: str, expected: str) -> None:
    parser = _build_parser()
    args = parser.parse_args(["spinup", "config.toml", flag])
    assert args.verbosity == expected
