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
from hydromodpy.cli.commands.project import status
from hydromodpy.cli.main import _build_parser
from tools.docs.api_registry import walk_parser

# Family groups whose bare invocation must be a usage error (exit 2).
REQUIRED_GROUPS = (
    "campaign",
    "catalog",
    "data",
    "lock",
    "project",
    "site",
    "viz",
    "workspace",
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


@pytest.mark.parametrize(
    ("builder", "argv", "dest", "expected"),
    [
        (conventions.workspace_parser, ["-w", "/x"], "workspace", "/x"),
        (conventions.workspace_parser, ["--workspace", "/y"], "workspace", "/y"),
        (conventions.workspace_parser, [], "workspace", None),
        (conventions.confirm_parser, ["-y"], "yes", True),
        (conventions.confirm_parser, [], "yes", False),
        (conventions.dry_run_parser, ["--dry-run"], "dry_run", True),
        (conventions.format_parser, [], "format", "table"),
        (conventions.format_parser, ["--format", "json"], "format", "json"),
        (conventions.profile_parser, [], "profile", None),
        (conventions.profile_parser, ["--profile"], "profile", ""),
        (conventions.profile_parser, ["--profile", "out.html"], "profile", "out.html"),
    ],
)
def test_a_shared_parser_reads_its_flag(builder, argv, dest, expected) -> None:
    parser = argparse.ArgumentParser(add_help=False, parents=[builder()])
    assert getattr(parser.parse_args(argv), dest) == expected


def test_format_refuses_what_is_not_an_output() -> None:
    parser = argparse.ArgumentParser(add_help=False, parents=[conventions.format_parser()])
    with pytest.raises(SystemExit):
        parser.parse_args(["--format", "yaml"])


def test_add_sim_ref_adds_positional() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    conventions.add_sim_ref(parser)
    assert parser.parse_args(["ab12cd34"]).sim_ref == "ab12cd34"


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


@pytest.mark.parametrize("verb", PROFILE_COMMANDS)
def test_workflow_verbs_offer_profile(verb: str) -> None:
    args = _parse([verb, "config.toml", "--profile"])
    assert args.profile == ""


def test_dev_doctor_removed() -> None:
    """``hmp dev`` only refuses; the canonical verb is ``hmp doctor``."""
    top = _subparsers_action(_build_parser())
    assert isinstance(top.choices["dev"], conventions.RefusedVerb)
    assert "doctor" in top.choices


OLD_FORMS = (
    (
        "hmp project status --stale",
        "hmp project status --stale-minutes",
        ["project", "status", "--stale", "7"],
        ("stale_minutes", 7.0),
    ),
    (
        "hmp project status --json",
        "hmp project status --format json",
        ["project", "status", "--json"],
        ("format", "json"),
    ),
    (
        "hmp project status --silent",
        "hmp project status --quiet",
        ["project", "status", "--silent"],
        ("verbosity", "quiet"),
    ),
    (
        "hmp project state",
        "hmp project status",
        ["project", "state", "--format", "csv"],
        ("format", "csv"),
    ),
    ("hmp status", "hmp project status", ["status", "--format", "csv"], ("format", "csv")),
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
    assert args._handler is status.run


def test_an_old_form_leaves_the_new_form_and_the_help_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    forms = tuple(conventions.OldCliForm(old, new, "2.3.0") for old, new, _, _ in OLD_FORMS)
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", forms)

    assert _parse(["project", "status"]).format == "table"
    with pytest.raises(SystemExit):
        _parse(["project", "status", "--help"])

    assert "--silent" not in capsys.readouterr().out
    commands = {" ".join(row["path"]): row for row in walk_parser(_build_parser(), ["hmp"])}
    assert not {"hmp status", "hmp project state"} & set(commands)
    flags = {flag for arg in commands["hmp project status"]["arguments"] for flag in arg["flags"]}
    assert not {"--stale", "--json", "--silent"} & flags


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
    form = conventions.OldCliForm("hmp project status --old", "hmp project status --none", "2.3.0")
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


def test_a_bare_old_group_names_each_of_its_new_forms(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        _parse(["dev", "lock"])
    err = capsys.readouterr().err
    assert "hmp lock update" in err and "hmp data archive --to FILE" in err


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
