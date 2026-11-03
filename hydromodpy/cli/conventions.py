"""Reusable argparse conventions shared by every ``hmp`` command.

Single source of the CLI grammar so commands inherit flags instead of
re-declaring them. Each builder returns a parent parser (``add_help=False``)
usable through ``subparsers.add_parser(..., parents=[...])``:

- :func:`workspace_parser` -- ``-w/--workspace`` selector
- :func:`confirm_parser` -- ``-y/--yes`` confirmation flag
- :func:`format_parser` -- ``--format {table,json,csv}`` for read commands
- :func:`profile_parser` -- ``--profile [HTML_PATH]`` pyinstrument flag
- :func:`verbosity_parser` -- ``-q/-v/--debug/--verbosity`` console verbosity
- :func:`add_sim_ref` -- canonical ``sim_ref`` positional

:func:`add_action_subparsers` attaches a *required* action group: a bare
group (``hmp catalog`` with no sub-action) is a usage error and exits 2.

:data:`OLD_CLI_FORMS` lists the commands and flags that moved in a stable
version, and :func:`install_old_cli_forms` keeps them working: each warns, then
forwards to the new form. The policy is ``docs/source/about/versions.md``.

A guard test (``tests/unit/cli/test_cli_conventions.py``) introspects the
argparse tree and fails if a command drifts from this grammar.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from hydromodpy.core.logging import VERBOSITY_LEVELS

FORMAT_CHOICES: tuple[str, ...] = ("table", "json", "csv")


@dataclass(frozen=True, slots=True)
class OldCliForm:
    """A command or a flag of ``hmp`` that moved in a stable version.

    Both forms are written as a user types them. A flag stays on its command, and
    its new form may fix a value: ``hmp catalog ls --long`` to ``hmp catalog ls
    --detail``, or ``hmp catalog ls --json`` to ``hmp catalog ls --format json``.
    A command may move anywhere, under another group or to the top level.
    """

    old: str
    new: str
    since: str
    """The version that moved it. It keeps working for two minor versions, that one included."""


OLD_CLI_FORMS: tuple[OldCliForm, ...] = ()
"""The old forms :func:`install_old_cli_forms` keeps working.

Empty at 2.0.0, because a form removed before the first stable version has no
entry. From then on ``tools/surface_snapshot.py`` refuses a command or a flag that
leaves ``hmp`` without an entry here, and a test fails once an entry outlives its
delay.
"""


def _warn_old_form(form: OldCliForm) -> None:
    # stacklevel=1 names this file: the console routing hides a deprecation it
    # reads as a third party's, and the reader of this one typed the command.
    warnings.warn(
        f"{form.old} is now {form.new}. The old form keeps working for two minor versions "
        f"from {form.since}.",
        FutureWarning,
        stacklevel=1,
    )


class OldFlag(argparse.Action):
    """Stands for a flag that moved: warns, then does what the new flag does."""

    def __init__(
        self,
        option_strings: Sequence[str],
        dest: str,
        *,
        form: OldCliForm,
        target: argparse.Action,
        value: str | None = None,
    ) -> None:
        del dest
        fixed = value is not None
        super().__init__(
            option_strings,
            target.dest,
            nargs=0 if fixed else target.nargs,
            const=target.const,
            default=argparse.SUPPRESS,
            type=None if fixed else target.type,
            choices=None if fixed else target.choices,
            help=argparse.SUPPRESS,
        )
        self.form, self.target = form, target
        self.value = target.type(value) if fixed and target.type else value

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        _warn_old_form(self.form)
        self.target(parser, namespace, values if self.value is None else self.value, option_string)


class OldVerb(argparse.ArgumentParser):
    """Stands for a command that moved: warns, then the new command reads the rest of the line."""

    def __init__(self, form: OldCliForm, target: argparse.ArgumentParser) -> None:
        super().__init__(prog=form.old, add_help=False)
        self.form, self.target = form, target

    def parse_known_args(self, args=None, namespace=None) -> tuple[argparse.Namespace, list[str]]:
        _warn_old_form(self.form)
        return self.target.parse_known_args(args, namespace)


def _commands_of(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Return the commands of a group, by name."""
    return next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices


def _parser_of(root: argparse.ArgumentParser, words: Sequence[str]) -> argparse.ArgumentParser:
    """Return the parser of the command *words* name, under *root*."""
    parser = root
    for word in words:
        parser = _commands_of(parser)[word]
    return parser


def install_old_cli_forms(root: argparse.ArgumentParser) -> None:
    """Make each form of :data:`OLD_CLI_FORMS` work on the parser tree of ``hmp``.

    A form that names a command or a flag the tree does not hold raises when the
    tree is built, so the gate of the surfaces finds it before a user does.
    """
    for form in OLD_CLI_FORMS:
        old, new = form.old.split()[1:], form.new.split()[1:]
        if not old[-1].startswith("-"):
            _commands_of(_parser_of(root, old[:-1]))[old[-1]] = OldVerb(form, _parser_of(root, new))
            continue
        command = old[:-1]
        flag, *value = new[len(command) :]
        owner = _parser_of(root, command)
        target = owner._option_string_actions[flag]
        container: Any = owner
        if target.required:
            # argparse asks a required flag for itself: either form must answer now.
            target.required = False
            container = owner.add_mutually_exclusive_group(required=True)
            container._group_actions.append(target)
        container.add_argument(
            old[-1], action=OldFlag, form=form, target=target, value=value[0] if value else None
        )


def workspace_parser() -> argparse.ArgumentParser:
    """Parent parser exposing the shared ``-w/--workspace`` selector.

    Accepts a workspace root or a project directory. A project verb resolves
    it through :func:`hydromodpy.cli.helpers.resolve_project`, a workspace
    verb through :func:`hydromodpy.cli.helpers.resolve_workspace`. Without
    ``-w`` the verb looks above the current directory and stops when it finds
    nothing: it never falls back on ``~/hydromodpy``.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "-w",
        "--workspace",
        metavar="WORKSPACE",
        default=None,
        help=(
            "Workspace root or project directory "
            "(default: the one that holds the current directory)"
        ),
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


def verbosity_parser() -> argparse.ArgumentParser:
    """Parent parser exposing the shared console verbosity selector.

    ``-q``, ``-v`` and ``--debug`` are shorthands for ``--verbosity``; they
    are mutually exclusive. Nothing given leaves the choice to the config
    (``[workflow] verbosity``) and to ``HMP_VERBOSITY``.
    """
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--verbosity",
        choices=VERBOSITY_LEVELS,
        default=None,
        help="Console verbosity (default: normal, or [workflow] verbosity)",
    )
    group.add_argument(
        "-q",
        "--quiet",
        dest="verbosity",
        action="store_const",
        const="quiet",
        help="Warnings and errors only",
    )
    group.add_argument(
        "-v",
        "--verbose",
        dest="verbosity",
        action="store_const",
        const="verbose",
        help="Every INFO line the run emits",
    )
    group.add_argument(
        "--debug",
        dest="verbosity",
        action="store_const",
        const="debug",
        help="Every DEBUG line, with module and line number",
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
    "OLD_CLI_FORMS",
    "OldCliForm",
    "OldFlag",
    "OldVerb",
    "add_action_subparsers",
    "add_sim_ref",
    "confirm_parser",
    "format_parser",
    "install_old_cli_forms",
    "profile_parser",
    "workspace_parser",
)
