"""Reusable argparse conventions shared by every ``hmp`` command.

Single source of the CLI grammar so commands inherit flags instead of
re-declaring them. Each builder returns a parent parser (``add_help=False``)
usable through ``subparsers.add_parser(..., parents=[...])``:

- :func:`workspace_parser` -- ``-w/--workspace`` selector
- :func:`confirm_parser` -- ``-y/--yes`` confirmation flag
- :func:`format_parser` -- ``--format {table,json,csv}``, what :mod:`hydromodpy.cli.output` writes
- :func:`dry_run_parser` -- ``--dry-run`` on a verb that removes or rewrites
- :func:`add_destination` -- ``--to``, the one spelling of a destination
- :func:`profile_parser` -- ``--profile [HTML_PATH]`` pyinstrument flag
- :func:`verbosity_parser` -- ``-q/-v/--debug/--verbosity`` console verbosity
- :func:`add_sim_ref` -- canonical ``sim_ref`` positional

:func:`add_action_subparsers` attaches a *required* action group: a bare
group (``hmp catalog`` with no sub-action) is a usage error and exits 2.

:data:`OLD_CLI_FORMS` lists the commands and flags that moved, and
:func:`install_old_cli_forms` puts them on the tree. One that moved in a stable
version keeps working: it warns, then forwards to the new form. One that left
before the first stable version is refused with a message that names the new
form. The policy is ``docs/source/about/versions.md``.

``--force`` has one meaning on every verb: go past a refusal this verb makes
because of what is already there, or what protects it. An existing file, a
pinned run, a running case. It never skips a question, which is ``-y``.

A guard test (``tests/unit/cli/test_cli_conventions.py``) introspects the
argparse tree and fails if a command drifts from this grammar.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NoReturn

from hydromodpy.core.exceptions import CommandUsageError
from hydromodpy.core.logging import VERBOSITY_LEVELS

FORMAT_CHOICES: tuple[str, ...] = ("table", "json", "csv")


class HmpParser(argparse.ArgumentParser):
    """The parser of ``hmp``: a mistake on the command line carries its code, as any failure does."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, f"{CommandUsageError.code}: {self.prog}: {message}\n")


@dataclass(frozen=True, slots=True)
class OldCliForm:
    """A command or a flag of ``hmp`` that moved.

    Both forms are written as a user types them. A flag stays on its command, and
    its new form may fix a value: ``hmp catalog ls --long`` to ``hmp catalog ls
    --detail``, or ``hmp catalog ls --json`` to ``hmp catalog ls --format json``.
    A command may move anywhere, under another group or to the top level.
    """

    old: str
    new: str
    since: str
    """The version that moved it. It stays here for two minor versions, that one included."""

    refused: bool = False
    """It has no alias: it is refused, and the message names *new*, which may then hold
    words to fill in (``REF``, ``DIR``). A form is refused when it left before the first
    stable version, or when its command left the wheel for ``tools/`` of a checkout."""


_FORMS_REFUSED_AT_2_0: tuple[tuple[str, str], ...] = (
    # Verbs that fold into another.
    ("hmp replay", "hmp publish REF --to DIR --with inputs"),
    (
        "hmp project export",
        "hmp publish PROJECT --package --to FILE [--container tar|dir] [--with runs]",
    ),
    ("hmp viz regen", "hmp export REF --regen figures"),
    ("hmp doctor --toml", "hmp config check FILE -v"),
    ("hmp dev lock archive", "hmp data archive --to FILE"),
    ("hmp dev lock restore", "hmp data restore FILE --to DIR"),
    # Verbs that moved.
    ("hmp test", "python -m tools.dev test"),
    ("hmp project case", "hmp campaign case"),
    ("hmp project array", "hmp campaign array"),
    ("hmp project collect", "hmp campaign collect"),
    ("hmp project prune", "hmp campaign prune"),
    ("hmp project promote", "hmp campaign promote"),
    ("hmp dev completion", "hmp completion"),
    ("hmp dev lock update", "hmp lock update"),
    ("hmp dev lock verify", "hmp lock verify"),
    ("hmp dev rank", "hmp catalog rank --project PROJECT"),
    ("hmp dev schema export", "hmp config schema --bundle --to DIR"),
    ("hmp dev schema validate-field", "hmp config check --partial"),
    # One option for what a program reads.
    ("hmp workspace list --json", "hmp workspace list --format json"),
    ("hmp doctor --json", "hmp doctor --format json"),
    ("hmp config targets --json", "hmp config targets FILE --format json"),
    # A destination is --to.
    ("hmp export --folder", "hmp export REF NAME --to FOLDER/"),
    ("hmp export --file", "hmp export REF NAME --to FILE"),
    ("hmp catalog point --output", "hmp catalog point REF --to FILE"),
    ("hmp catalog point -o", "hmp catalog point REF --to FILE"),
    ("hmp viz show --output", "hmp viz show REF FIGURE --to FILE"),
    ("hmp config schema --out", "hmp config schema --to FILE"),
    ("hmp data get --out", "hmp data get TARGET --to DIR"),
    ("hmp report compare --out", "hmp report compare REF REF --to DIR"),
    ("hmp install-binaries --bindir", "hmp install-binaries --to DIR"),
    ("hmp workspace init --path", "hmp workspace init PATH"),
    ("hmp config template FILE", "hmp config template --to FILE"),
    ("hmp config wizard FILE", "hmp config wizard --to FILE"),
    ("hmp data archive FILE", "hmp data archive --to FILE"),
    # It changed nothing: every run has the same step order.
    ("hmp run --no-parallel", "hmp run FILE"),
    # A preview is --dry-run, and doing it is -y.
    ("hmp catalog gc --apply", "hmp catalog gc -y"),
    # --force goes past a refusal, and --upgrade downloads again.
    ("hmp install-binaries --force", "hmp install-binaries --upgrade"),
    # A file format is --as, so a name is --name.
    ("hmp catalog import --as", "hmp catalog import SOURCE --name NAME"),
    ("hmp project import --as", "hmp project import SOURCE --name NAME"),
    ("hmp campaign promote --as", "hmp campaign promote CASE --trial N --name NAME"),
)

_FORMS_REFUSED_AT_2_1: tuple[tuple[str, str], ...] = (
    # The developer commands left the wheel: a source checkout runs them from tools/.
    ("hmp dev", "python -m tools.dev"),
    ("hmp dev test", "python -m tools.dev test"),
    ("hmp dev run-script", "python -m tools.dev run-script SCRIPT"),
    ("hmp dev examples", "python -m tools.dev examples manifest"),
    ("hmp dev manage", "(no replacement yet)"),
    ("hmp data check", "hmp data ls"),
    ("hmp config validate-field", "hmp config check --partial"),
)

OLD_CLI_FORMS: tuple[OldCliForm, ...] = tuple(
    OldCliForm(old, new, "2.0.0", refused=True) for old, new in _FORMS_REFUSED_AT_2_0
) + tuple(OldCliForm(old, new, "2.1.0", refused=True) for old, new in _FORMS_REFUSED_AT_2_1)
"""The old forms :func:`install_old_cli_forms` puts on the tree.

At 2.0.0 it only held the forms refused because they left before that version. From
then on ``tools/surface_snapshot.py`` refuses a command or a flag that leaves ``hmp``
without an entry here, and a test fails once an entry outlives its delay.
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


def _refusal(form: OldCliForm) -> str:
    return f"{form.old} is gone. Write: {form.new}"


class RefusedFlag(OldFlag):
    """Stands for a flag that left before the first stable version: names the new form, stops."""

    def __init__(self, option_strings: Sequence[str], dest: str, *, form: OldCliForm) -> None:
        argparse.Action.__init__(
            self,
            option_strings,
            dest,
            nargs="?",
            default=argparse.SUPPRESS,
            help=argparse.SUPPRESS,
        )
        self.form = form

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        parser.error(_refusal(self.form))


class RefusedPositional(RefusedFlag):
    """Stands for a destination that was a positional: says what it is now, when one is typed."""

    def __init__(self, option_strings: Sequence[str], dest: str, *, form: OldCliForm, **_: Any):
        super().__init__(option_strings, dest, form=form)

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        if values is not None:
            parser.error(_refusal(self.form))


class RefusedVerb(OldVerb):
    """Stands for a command that left before the first stable version: names the new form, stops.

    One stands for a whole old group, ``hmp dev lock``. The words typed after it
    choose the form to name: the form typed whole, else every form of the group typed,
    else the longest form the words start with, else them all.
    """

    def __init__(self, first: OldCliForm, *, prog: str) -> None:
        argparse.ArgumentParser.__init__(self, prog=prog, add_help=False)
        self.forms = [first]

    def error(self, message: str) -> NoReturn:
        self.exit(2, f"{CommandUsageError.code}: {message}\n")

    def parse_known_args(self, args=None, namespace=None) -> tuple[argparse.Namespace, list[str]]:
        typed = " ".join([self.prog, *(args or ())])
        self.error(" ".join(_refusal(form) + "." for form in self.chosen(typed)))

    def chosen(self, typed: str) -> list[OldCliForm]:
        """Return the forms the refusal of *typed* names."""
        exact = [form for form in self.forms if form.old == typed]
        if exact:
            return exact
        under = [form for form in self.forms if form.old.startswith(f"{typed} ")]
        if under:
            return under
        heads = [form for form in self.forms if f"{typed} ".startswith(f"{form.old} ")]
        if heads:
            return [max(heads, key=lambda form: len(form.old))]
        return self.forms


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
    """Put each form of :data:`OLD_CLI_FORMS` on the parser tree of ``hmp``.

    A form that names a command or a flag the tree does not hold raises when the
    tree is built, so the gate of the surfaces finds it before a user does.
    """
    for form in OLD_CLI_FORMS:
        if form.refused:
            _install_refusal(root, form)
            continue
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


def _install_refusal(root: argparse.ArgumentParser, form: OldCliForm) -> None:
    """Refuse *form* on the tree, at its flag, or at the first of its words the tree lost."""
    words = form.old.split()[1:]
    if words[-1].startswith("-"):
        _parser_of(root, words[:-1]).add_argument(words[-1], action=RefusedFlag, form=form)
        return
    if words[-1].isupper():
        _parser_of(root, words[:-1]).add_argument(
            "was_positional", action=RefusedPositional, nargs="?", form=form
        )
        return
    parser = root
    for depth, word in enumerate(words):
        commands = _commands_of(parser)
        found = commands.get(word)
        if isinstance(found, RefusedVerb):
            found.forms.append(form)
            return
        if found is None:
            prog = " ".join(["hmp", *words[: depth + 1]])
            commands[word] = RefusedVerb(form, prog=prog)
            return
        parser = found
    raise KeyError(f"{form.old} is still a command: an old form cannot stand for it.")


WORKSPACE_ROOT_DEST = "workspace_before_the_verb"
"""Where ``hmp -w W <verb>`` keeps W, so that the default of the verb does not overwrite it."""


def add_workspace_before_the_verb(parser: argparse.ArgumentParser) -> None:
    """Accept ``-w`` before the verb too: ``hmp -w W catalog ls``."""
    parser.add_argument(
        "-w",
        "--workspace",
        dest=WORKSPACE_ROOT_DEST,
        metavar="WORKSPACE",
        default=None,
        help="Workspace root or project directory, for the command that follows",
    )


def workspace_parser(*, reads_none: bool = False) -> argparse.ArgumentParser:
    """Parent parser exposing the shared ``-w/--workspace`` selector.

    Accepts a workspace root or a project directory. A project verb resolves
    it through :func:`hydromodpy.cli.helpers.resolve_project`, a workspace
    verb through :func:`hydromodpy.cli.helpers.resolve_workspace`. Without
    ``-w`` the verb looks above the current directory and stops when it finds
    nothing: it never falls back on ``~/hydromodpy``.

    Every verb takes ``-w``, so a script can always write ``hmp -w W <verb>``.
    A verb that reads no workspace says so in its help (*reads_none*).
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "-w",
        "--workspace",
        metavar="WORKSPACE",
        default=None,
        help=(
            "Accepted on every command. This one reads no workspace"
            if reads_none
            else "Workspace root or project directory "
            "(default: the one that holds the current directory)"
        ),
    )
    return parser


def dry_run_parser() -> argparse.ArgumentParser:
    """Parent parser exposing ``--dry-run``: say what the verb would do, and change nothing."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Say what would change, and change nothing",
    )
    return parser


def add_destination(
    parser: argparse.ArgumentParser, *, help: str, required: bool = False, metavar: str = "DEST"
) -> None:
    """Add ``--to``, the one spelling of where a verb writes."""
    parser.add_argument("--to", default=None, required=required, metavar=metavar, help=help)


def confirm_parser(*, help: str = "Skip the confirmation prompt") -> argparse.ArgumentParser:
    """Parent parser exposing the shared ``-y/--yes`` confirmation flag."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-y", "--yes", action="store_true", help=help)
    return parser


def format_parser(*, default: str = "table", not_for: str = "") -> argparse.ArgumentParser:
    """Parent parser exposing ``--format``: what :func:`hydromodpy.cli.output.emit` writes.

    *not_for* is what to say to a value that is not one of the three, on a verb
    where ``--format`` used to name something else.
    """

    def _format(value: str) -> str:
        if not_for and value not in FORMAT_CHOICES:
            raise argparse.ArgumentTypeError(
                f"{value!r} is not an output of this command, which is one of "
                f"{', '.join(FORMAT_CHOICES)}. {not_for}"
            )
        return value

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--format",
        type=_format,
        choices=FORMAT_CHOICES,
        default=default,
        help=f"What the command prints: a table for people, json or csv (default: {default})",
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
    exits 2. The fallback handler keeps that behavior explicit even if a
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
    "WORKSPACE_ROOT_DEST",
    "HmpParser",
    "OldCliForm",
    "OldFlag",
    "OldVerb",
    "RefusedFlag",
    "RefusedPositional",
    "RefusedVerb",
    "add_action_subparsers",
    "add_destination",
    "add_sim_ref",
    "add_workspace_before_the_verb",
    "confirm_parser",
    "dry_run_parser",
    "format_parser",
    "install_old_cli_forms",
    "profile_parser",
    "workspace_parser",
)
