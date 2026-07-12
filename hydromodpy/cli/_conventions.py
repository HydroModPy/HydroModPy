"""Reusable argparse conventions shared by every ``hmp`` command.

Single source of the CLI grammar so commands inherit flags instead of
re-declaring them. Each builder returns a parent parser (``add_help=False``)
usable through ``subparsers.add_parser(..., parents=[...])``:

- :func:`workspace_parser` -- ``-w/--workspace`` selector
- :func:`confirm_parser` -- ``-y/--yes`` confirmation flag
- :func:`format_parser` -- ``--format {table,json,csv}`` for read commands
- :func:`profile_parser` -- ``--profile [HTML_PATH]`` pyinstrument flag
- :func:`add_sim_ref` -- canonical ``sim_ref`` positional

:func:`add_action_subparsers` attaches a *required* action group: a bare
group (``hmp catalog`` with no sub-action) is a usage error and exits 2.

A guard test (``tests/unit/cli/test_cli_conventions.py``) introspects the
argparse tree and fails if a command drifts from this grammar.
"""

from __future__ import annotations

import argparse
import sys

FORMAT_CHOICES: tuple[str, ...] = ("table", "json", "csv")


def workspace_parser() -> argparse.ArgumentParser:
    """Parent parser exposing the shared ``-w/--workspace`` selector.

    Accepts a workspace root OR a project directory; commands resolve it
    through :func:`hydromodpy.core.state.paths.find_catalog_root`.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "-w",
        "--workspace",
        metavar="WORKSPACE",
        default=None,
        help="Workspace root or project directory (default: auto-detect from cwd)",
    )
    return parser


def confirm_parser() -> argparse.ArgumentParser:
    """Parent parser exposing the shared ``-y/--yes`` confirmation flag."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    return parser


def format_parser(*, default: str = "table") -> argparse.ArgumentParser:
    """Parent parser exposing the shared ``--format`` selector for read commands."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--format",
        choices=FORMAT_CHOICES,
        default=default,
        help=f"Output format (default: {default})",
    )
    return parser


def profile_parser() -> argparse.ArgumentParser:
    """Parent parser exposing the shared ``--profile`` flag.

    Profiles the wrapped execution with pyinstrument and writes an HTML
    report. Without a value the report lands next to the config as
    ``<config>.profile.html``.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--profile",
        nargs="?",
        const="",
        default=None,
        metavar="HTML_PATH",
        help=(
            "Profile the execution with pyinstrument and write an HTML report "
            "(default: <config>.profile.html next to the config)."
        ),
    )
    return parser


def add_sim_ref(parser: argparse.ArgumentParser, *, help: str | None = None) -> None:
    """Add the canonical ``sim_ref`` positional (UUID / unique prefix / name / @-selector)."""
    parser.add_argument(
        "sim_ref",
        metavar="SIM_REF",
        help=(
            help
            or "Full sim_id, unique hex prefix, name, or an @-selector "
            "(@last, @best:METRIC, @worst:METRIC, @running)"
        ),
    )


def add_action_subparsers(
    parser: argparse.ArgumentParser,
    *,
    dest: str = "action",
    metavar: str = "<action>",
) -> argparse._SubParsersAction:
    """Attach a *required* action subparsers group to ``parser``.

    A bare group invocation (no sub-action) is a usage error: argparse
    exits 2. The fallback handler keeps that behaviour explicit even if a
    future argparse drops the ``required`` enforcement.
    """
    sub = parser.add_subparsers(dest=dest, metavar=metavar, required=True)
    parser.set_defaults(_handler=lambda args: _require_subcommand(parser))
    return sub


def _require_subcommand(parser: argparse.ArgumentParser) -> None:
    """Print help to stderr and exit 2 when a group is invoked bare."""
    from hydromodpy.cli.helpers import EXIT_USAGE

    parser.print_help(sys.stderr)
    sys.exit(EXIT_USAGE)


__all__ = (
    "FORMAT_CHOICES",
    "add_action_subparsers",
    "add_sim_ref",
    "confirm_parser",
    "format_parser",
    "profile_parser",
    "workspace_parser",
)
