"""The old forms of ``hmp`` commands: each one warns and forwards, or is refused with its new name.

An old form is a flag or a verb that moved. Before its removal tag it warns (FutureWarning) and does
what the new form does. After, the parser exits with code 2 and writes the form to use instead.
"""

from __future__ import annotations

import argparse

import pytest

from hydromodpy.cli import conventions
from hydromodpy.cli.commands import ls
from hydromodpy.cli.main import _build_parser


def parse(argv: list[str]) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


def subparsers_of(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return {option for action in parser._actions for option in action.option_strings}


# (old form, new form, argv typed with the old form, attribute and value it must set)
OLD_FORMS = [
    pytest.param(
        "hmp ls --stale",
        "hmp ls --stale-minutes",
        ["ls", "--stale", "7"],
        ("stale_minutes", 7.0),
        id="ls --stale",
    ),
    pytest.param(
        "hmp ls --json",
        "hmp ls --format json",
        ["ls", "--json"],
        ("format", "json"),
        id="ls --json",
    ),
    pytest.param(
        "hmp ls --silent",
        "hmp ls --quiet",
        ["ls", "--silent"],
        ("verbosity", "quiet"),
        id="ls --silent",
    ),
    pytest.param(
        "hmp project state",
        "hmp ls",
        ["project", "state", "--format", "csv"],
        ("format", "csv"),
        id="project state",
    ),
    pytest.param(
        "hmp status", "hmp ls", ["status", "--format", "csv"], ("format", "csv"), id="status"
    ),
]

REFUSED = [form for form in conventions.OLD_CLI_FORMS if form.refused]

# (words typed after "hmp dev", old forms that the typed words choose)
DEV_FORMS = [
    pytest.param("hmp dev", ["hmp dev"], id="bare group"),
    pytest.param("hmp dev x", ["hmp dev"], id="unknown word"),
    pytest.param(
        "hmp dev lock",
        [
            "hmp dev lock archive",
            "hmp dev lock restore",
            "hmp dev lock update",
            "hmp dev lock verify",
        ],
        id="lock actions",
    ),
    pytest.param("hmp dev lock update x", ["hmp dev lock update"], id="lock update"),
    pytest.param("hmp dev test -k foo", ["hmp dev test"], id="test"),
    pytest.param("hmp dev manage", ["hmp dev manage"], id="manage"),
    pytest.param(
        "hmp dev schema",
        ["hmp dev schema export", "hmp dev schema validate-field"],
        id="schema actions",
    ),
]

FORMAT_MOVES = [
    pytest.param(["export", "r", "head", "--format", "netcdf"], "--as", id="export"),
    pytest.param(["publish", "r", "--to", "d", "--format", "tar"], "--container", id="publish"),
]


@pytest.mark.parametrize(("old", "new", "argv", "expected"), OLD_FORMS)
def test_old_form_forwards(
    old: str, new: str, argv: list[str], expected: tuple[str, object], monkeypatch
) -> None:
    form = conventions.OldCliForm(old, new, "2.3.0")
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", (form,))

    with pytest.warns(FutureWarning, match=f"{old} is now {new}.*2.3.0"):
        args = parse(argv)

    dest, value = expected
    assert getattr(args, dest) == value
    assert args._handler is ls.run


def test_required_flag_either_form(monkeypatch) -> None:
    form = conventions.OldCliForm(
        "hmp campaign array --sched", "hmp campaign array --scheduler", "2.3.0"
    )
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", (form,))

    assert parse(["campaign", "array", "--scheduler", "slurm"]).scheduler == "slurm"
    with pytest.warns(FutureWarning, match="--sched is now"):
        assert parse(["campaign", "array", "--sched", "slurm"]).scheduler == "slurm"
    with pytest.raises(SystemExit):
        parse(["campaign", "array"])


def test_old_form_without_target(monkeypatch) -> None:
    form = conventions.OldCliForm("hmp ls --old", "hmp ls --none", "2.3.0")
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", (form,))

    with pytest.raises(KeyError, match="--none"):
        _build_parser()


@pytest.mark.parametrize("form", REFUSED, ids=lambda form: form.old)
def test_refused_form_names_new(form, capsys) -> None:
    with pytest.raises(SystemExit) as refused:
        parse([*form.old.split()[1:], "x"])

    assert refused.value.code == 2
    assert f"Write: {form.new}" in capsys.readouterr().err


@pytest.mark.parametrize("form", REFUSED, ids=lambda form: form.old)
def test_new_form_exists(form) -> None:
    if not form.new.startswith("hmp "):
        pytest.skip(f"{form.new} is not a form of hmp")
    parser: argparse.ArgumentParser = _build_parser()
    for word in form.new.split()[1:]:
        if word.startswith("-"):
            assert word in option_strings(parser), form.new
            continue
        commands = subparsers_of(parser)
        if commands is not None and word in commands.choices:
            parser = commands.choices[word]
            assert not isinstance(parser, conventions.OldVerb), form.new


def test_completion_flag_refused(capsys) -> None:
    with pytest.raises(SystemExit) as refused:
        parse(["completion", "--argcomplete", "bash"])

    assert refused.value.code == 2
    assert "Write: hmp completion SHELL" in capsys.readouterr().err


def test_bare_old_group(capsys) -> None:
    with pytest.raises(SystemExit):
        parse(["dev", "lock"])

    err = capsys.readouterr().err
    assert "hmp data lock" in err and "hmp data lock --check" in err
    assert "hmp data archive --to FILE" in err


@pytest.mark.parametrize(("typed", "named"), DEV_FORMS)
def test_refused_group_choice(typed, named) -> None:
    refused = subparsers_of(_build_parser()).choices["dev"]

    assert sorted(form.old for form in refused.chosen(typed)) == named


def test_refused_group_unknown_word() -> None:
    forms = [
        conventions.OldCliForm("hmp gone a", "hmp new a", "2.1.0", refused=True),
        conventions.OldCliForm("hmp gone b", "hmp new b", "2.1.0", refused=True),
    ]
    refused = conventions.RefusedVerb(forms[0], prog="hmp gone")
    refused.forms.append(forms[1])

    assert refused.chosen("hmp gone c") == forms


@pytest.mark.parametrize(("argv", "says"), FORMAT_MOVES)
def test_format_moved(argv, says, capsys) -> None:
    with pytest.raises(SystemExit) as refused:
        parse(argv)

    assert refused.value.code == 2
    assert says in capsys.readouterr().err
