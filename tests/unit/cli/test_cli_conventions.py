"""Structural guard for the hmp CLI grammar (interface refactor).

Introspects the argparse tree built by :func:`hydromodpy.cli.main._build_parser`
and the shared builders in :mod:`hydromodpy.cli._conventions`. These tests are
the anti-drift gate: a command that diverges from the canonical grammar breaks
here instead of silently shipping.

Phase 0 locks the "bare group exits 2" rule and the parent-parser builders.
Later phases extend this module with per-command flag conventions (``sim_ref``,
``-y/--yes``, ``--format``, ``epilog``).
"""

from __future__ import annotations

import argparse

import pytest

from hydromodpy.cli import _conventions
from hydromodpy.cli.main import _build_parser

# Family groups whose bare invocation must be a usage error (exit 2).
REQUIRED_GROUPS = (
    "catalog",
    "data",
    "dev",
    "project",
    "viz",
    "workspace",
    "audit",
    "report",
    "privacy",
)

# (group, action) leaf commands that reference a single simulation: positional sim_ref.
SIM_REF_COMMANDS = (
    ("catalog", "show"),
    ("catalog", "delete"),
    ("viz", "show"),
    ("privacy", "purge"),
    ("report", "render"),
)

# Destructive leaf commands that must offer -y/--yes.
DESTRUCTIVE_COMMANDS = (
    ("catalog", "delete"),
    ("project", "delete"),
    ("privacy", "purge"),
)

# Read leaf commands that must offer --format.
READ_FORMAT_COMMANDS = (
    ("catalog", "ls"),
    ("catalog", "show"),
    ("catalog", "query"),
)

# Workflow execution verbs that must offer --profile (pyinstrument).
PROFILE_COMMANDS = ("run", "calibrate")


def _parse(argv: list[str]) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


def _subparsers_action(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _leaf_parser(group: str, action: str) -> argparse.ArgumentParser:
    top = _subparsers_action(_build_parser())
    grp = top.choices[group]
    grp_sub = _subparsers_action(grp)
    return grp_sub.choices[action]


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    opts: set[str] = set()
    for action in parser._actions:
        opts.update(action.option_strings)
    return opts


def _positional_dests(parser: argparse.ArgumentParser) -> list[str]:
    return [a.dest for a in parser._actions if not a.option_strings and a.dest != "help"]


def test_bare_top_level_exits_2() -> None:
    """``hmp`` with no command is a usage error, not a silent exit 0."""
    with pytest.raises(SystemExit) as exc:
        _parse([])
    assert exc.value.code == 2


@pytest.mark.parametrize("group", REQUIRED_GROUPS)
def test_bare_group_exits_2(group: str) -> None:
    """``hmp <group>`` with no sub-action exits 2 (required subparsers)."""
    with pytest.raises(SystemExit) as exc:
        _parse([group])
    assert exc.value.code == 2


@pytest.mark.parametrize("group", REQUIRED_GROUPS)
def test_group_help_still_exits_0(group: str) -> None:
    """``hmp <group> --help`` keeps working (required does not block help)."""
    with pytest.raises(SystemExit) as exc:
        _parse([group, "--help"])
    assert exc.value.code == 0


# --- Shared builders -------------------------------------------------------


def test_workspace_parser_exposes_short_and_long() -> None:
    parser = argparse.ArgumentParser(add_help=False, parents=[_conventions.workspace_parser()])
    assert parser.parse_args(["-w", "/x"]).workspace == "/x"
    assert parser.parse_args(["--workspace", "/y"]).workspace == "/y"
    assert parser.parse_args([]).workspace is None


def test_confirm_parser_exposes_yes() -> None:
    parser = argparse.ArgumentParser(add_help=False, parents=[_conventions.confirm_parser()])
    assert parser.parse_args(["-y"]).yes is True
    assert parser.parse_args(["--yes"]).yes is True
    assert parser.parse_args([]).yes is False


def test_format_parser_defaults_and_choices() -> None:
    parser = argparse.ArgumentParser(add_help=False, parents=[_conventions.format_parser()])
    assert parser.parse_args([]).format == "table"
    assert parser.parse_args(["--format", "json"]).format == "json"
    with pytest.raises(SystemExit):
        parser.parse_args(["--format", "yaml"])


def test_add_sim_ref_adds_positional() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    _conventions.add_sim_ref(parser)
    assert parser.parse_args(["ab12cd34"]).sim_ref == "ab12cd34"


def test_profile_parser_grammar() -> None:
    parser = argparse.ArgumentParser(add_help=False, parents=[_conventions.profile_parser()])
    assert parser.parse_args([]).profile is None
    assert parser.parse_args(["--profile"]).profile == ""
    assert parser.parse_args(["--profile", "out.html"]).profile == "out.html"


# --- Per-command grammar (Phase 3 sweep) -----------------------------------


@pytest.mark.parametrize(("group", "action"), SIM_REF_COMMANDS)
def test_simulation_reference_is_named_sim_ref(group: str, action: str) -> None:
    parser = _leaf_parser(group, action)
    assert "sim_ref" in _positional_dests(parser), (
        f"{group} {action}: the simulation reference positional must be 'sim_ref'"
    )


@pytest.mark.parametrize(("group", "action"), DESTRUCTIVE_COMMANDS)
def test_destructive_commands_offer_yes(group: str, action: str) -> None:
    opts = _option_strings(_leaf_parser(group, action))
    assert "-y" in opts and "--yes" in opts, f"{group} {action} must offer -y/--yes"


@pytest.mark.parametrize(("group", "action"), READ_FORMAT_COMMANDS)
def test_read_commands_offer_format(group: str, action: str) -> None:
    opts = _option_strings(_leaf_parser(group, action))
    assert "--format" in opts, f"{group} {action} must offer --format"


@pytest.mark.parametrize("verb", PROFILE_COMMANDS)
def test_workflow_verbs_offer_profile(verb: str) -> None:
    args = _parse([verb, "config.toml", "--profile"])
    assert args.profile == ""


def test_dev_doctor_removed() -> None:
    """``hmp dev doctor`` is gone; the canonical verb is ``hmp doctor``."""
    top = _subparsers_action(_build_parser())
    dev_sub = _subparsers_action(top.choices["dev"])
    assert "doctor" not in dev_sub.choices
    assert "doctor" in top.choices
