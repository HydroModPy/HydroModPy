"""Structural guard for the hmp CLI grammar (interface refactor).

Introspects the argparse tree built by :func:`hydromodpy.cli.main._build_parser`
and the shared builders in :mod:`hydromodpy.cli.conventions`. These tests are
the anti-drift gate: a command that diverges from the canonical grammar breaks
here instead of silently shipping.

Phase 0 locks the "bare group exits 2" rule and the parent-parser builders.
Later phases extend this module with per-command flag conventions (``sim_ref``,
``-y/--yes``, ``--format``, ``epilog``).
"""

from __future__ import annotations

import argparse

import pytest

from hydromodpy.cli import conventions
from hydromodpy.cli.commands import ls
from hydromodpy.cli.main import _build_parser

# Family groups whose bare invocation must be a usage error (exit 2).
REQUIRED_GROUPS = (
    "campaign",
    "catalog",
    "data",
    "project",
    "site",
    "workspace",
    "privacy",
)

# (group, action) leaf commands that reference a single simulation: positional sim_ref.
SIM_REF_COMMANDS = (
    ("catalog", "delete"),
    ("privacy", "purge"),
)

# Destructive leaf commands that must offer -y/--yes.
DESTRUCTIVE_COMMANDS = (
    ("catalog", "delete"),
    ("project", "delete"),
    ("privacy", "purge"),
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


# --- Shared builders -------------------------------------------------------


# --- Per-command grammar (Phase 3 sweep) -----------------------------------


OLD_FORMS = (
    (
        "hmp ls --stale",
        "hmp ls --stale-minutes",
        ["ls", "--stale", "7"],
        ("stale_minutes", 7.0),
    ),
    (
        "hmp ls --json",
        "hmp ls --format json",
        ["ls", "--json"],
        ("format", "json"),
    ),
    (
        "hmp ls --silent",
        "hmp ls --quiet",
        ["ls", "--silent"],
        ("verbosity", "quiet"),
    ),
    (
        "hmp project state",
        "hmp ls",
        ["project", "state", "--format", "csv"],
        ("format", "csv"),
    ),
    ("hmp status", "hmp ls", ["status", "--format", "csv"], ("format", "csv")),
)


@pytest.mark.parametrize(
    ("old", "new", "argv", "expected"), OLD_FORMS, ids=[row[0] for row in OLD_FORMS]
)
def test_an_old_form_warns_and_does_what_the_new_form_does(
    old: str,
    new: str,
    argv: list[str],
    expected: tuple[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    form = conventions.OldCliForm(old, new, "2.3.0")
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", (form,))

    with pytest.warns(FutureWarning, match=f"{old} is now {new}.*2.3.0"):
        args = _parse(argv)

    dest, value = expected
    assert getattr(args, dest) == value
    assert args._handler is ls.run


def test_a_required_flag_is_answered_by_either_form(monkeypatch: pytest.MonkeyPatch) -> None:
    form = conventions.OldCliForm(
        "hmp campaign array --sched", "hmp campaign array --scheduler", "2.3.0"
    )
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", (form,))

    assert _parse(["campaign", "array", "--scheduler", "slurm"]).scheduler == "slurm"
    with pytest.warns(FutureWarning, match="--sched is now"):
        assert _parse(["campaign", "array", "--sched", "slurm"]).scheduler == "slurm"
    with pytest.raises(SystemExit):
        _parse(["campaign", "array"])


def test_an_old_form_that_names_nothing_stops_the_build(monkeypatch: pytest.MonkeyPatch) -> None:
    form = conventions.OldCliForm("hmp ls --old", "hmp ls --none", "2.3.0")
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", (form,))

    with pytest.raises(KeyError, match="--none"):
        _build_parser()


REFUSED = [form for form in conventions.OLD_CLI_FORMS if form.refused]


@pytest.mark.parametrize("form", REFUSED, ids=lambda form: form.old)
def test_a_form_that_left_before_the_tag_is_refused_and_names_the_new_one(
    form: conventions.OldCliForm, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as refused:
        _parse([*form.old.split()[1:], "x"])
    assert refused.value.code == 2
    assert f"Write: {form.new}" in capsys.readouterr().err


@pytest.mark.parametrize("form", REFUSED, ids=lambda form: form.old)
def test_the_new_form_of_a_refused_one_exists(form: conventions.OldCliForm) -> None:
    if not form.new.startswith("hmp "):
        pytest.skip(f"{form.new} is not a form of hmp")
    parser: argparse.ArgumentParser = _build_parser()
    for word in form.new.split()[1:]:
        if word.startswith("-"):
            assert word in _option_strings(parser), form.new
            continue
        commands = _subparsers_action(parser)
        if commands is not None and word in commands.choices:
            parser = commands.choices[word]
            assert not isinstance(parser, conventions.OldVerb), form.new


def test_the_static_completion_scripts_left_with_their_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as refused:
        _parse(["completion", "--argcomplete", "bash"])
    assert refused.value.code == 2
    assert "Write: hmp completion SHELL" in capsys.readouterr().err


def test_a_bare_old_group_names_each_of_its_new_forms(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        _parse(["dev", "lock"])
    err = capsys.readouterr().err
    assert "hmp data lock" in err and "hmp data lock --check" in err
    assert "hmp data archive --to FILE" in err


@pytest.mark.parametrize(
    ("typed", "named"),
    [
        ("hmp dev", ["hmp dev"]),
        ("hmp dev x", ["hmp dev"]),
        (
            "hmp dev lock",
            [
                "hmp dev lock archive",
                "hmp dev lock restore",
                "hmp dev lock update",
                "hmp dev lock verify",
            ],
        ),
        ("hmp dev lock update x", ["hmp dev lock update"]),
        ("hmp dev test -k foo", ["hmp dev test"]),
        ("hmp dev manage", ["hmp dev manage"]),
        ("hmp dev schema", ["hmp dev schema export", "hmp dev schema validate-field"]),
    ],
)
def test_a_refused_group_names_the_forms_the_typed_words_choose(
    typed: str, named: list[str]
) -> None:
    refused = _subparsers_action(_build_parser()).choices["dev"]
    assert sorted(form.old for form in refused.chosen(typed)) == named


def test_a_refused_group_without_its_bare_form_names_them_all_on_an_unknown_word() -> None:
    forms = [
        conventions.OldCliForm("hmp gone a", "hmp new a", "2.1.0", refused=True),
        conventions.OldCliForm("hmp gone b", "hmp new b", "2.1.0", refused=True),
    ]
    refused = conventions.RefusedVerb(forms[0], prog="hmp gone")
    refused.forms.append(forms[1])
    assert refused.chosen("hmp gone c") == forms


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["export", "r", "head", "--format", "netcdf"], "--as"),
        (["publish", "r", "--to", "d", "--format", "tar"], "--container"),
    ],
)
def test_format_says_where_its_old_meaning_went(
    argv: list[str], says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as refused:
        _parse(argv)
    assert refused.value.code == 2
    assert says in capsys.readouterr().err
