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
REQUIRED_GROUPS = ("catalog", "data", "dev", "project", "viz", "workspace")


def _parse(argv: list[str]) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


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
