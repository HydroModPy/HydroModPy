"""``--set``, ``--overlay`` and ``HMP_SET_*``: what a command hands the loader, with no copy of the file.

The flags and the variables become a mapping of dotted paths that rides in the
request. Nothing is written beside the file the user named, and every refusal a
copy used to give is given by the command.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.cli import conventions, refs
from hydromodpy.cli.conventions import add_override_arguments, changes_of_args, with_changes
from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_NOT_FOUND
from hydromodpy.cli.profiling import profile_output_of
from hydromodpy.cli.refs import base_named_by_w, toml_target
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.config.loading import read_document
from tests._helpers.cli_runner import CliRunner

_CAL = """\
[calibration]
seed = 3

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
path = "flow.param.K.field.value"
"""


def _args(**fields: Any) -> argparse.Namespace:
    given = {"overlay": [], "set_overrides": [], "case": None, **fields}
    return argparse.Namespace(**given)


# -- the mapping of changes ---------------------------------------------------------------------

CHANGES = [
    ("nothing", [], {}, {}),
    ("one item", ["flow.param.K.field.value=2e-5"], {}, {"flow.param.K.field.value": 2e-5}),
    ("a text value", ['calibration.save_runs="all"'], {}, {"calibration.save_runs": "all"}),
    ("a list", ["a.b=[1, 2]"], {}, {"a.b": [1, 2]}),
    ("a bare word is text", ["a.b=word"], {}, {"a.b": "word"}),
    ("the last item wins", ["a.b=1", "a.b=2"], {}, {"a.b": 2}),
    ("a variable", [], {"HMP_SET_flow__param__K": "1e-5"}, {"flow.param.K": 1e-5}),
    ("the case of a key is kept", [], {"HMP_SET_flow__param__K": "1"}, {"flow.param.K": 1}),
    (
        "a variable wins over an item",
        ["a.b=1"],
        {"HMP_SET_a__b": "3"},
        {"a.b": 3},
    ),
    ("other variables are not read", [], {"HMP_VERBOSITY": "debug"}, {}),
]


@pytest.mark.parametrize(
    ("items", "env", "expected"),
    [row[1:] for row in CHANGES],
    ids=[row[0] for row in CHANGES],
)
def test_the_items_and_the_variables_are_one_mapping_of_dotted_paths(
    items: list[str], env: dict[str, str], expected: dict[str, Any]
) -> None:
    assert changes_of_args(_args(set_overrides=items), env) == expected


@pytest.mark.parametrize(
    ("item", "said"),
    [("foo", "--set expects PATH=VALUE"), ("a..b=1", "unexpected"), ("a[0]=1", "no index")],
    ids=["no equal sign", "empty part", "an index"],
)
def test_a_malformed_item_is_a_value_error(item: str, said: str) -> None:
    with pytest.raises(ValueError, match=said):
        changes_of_args(_args(set_overrides=[item]), {})


def test_the_trace_names_the_key_the_override_set(tmp_path: Path) -> None:
    from hydromodpy.project.request import request_of

    config = tmp_path / "project.toml"
    config.write_text('[simulation]\nname = "case"\n', encoding="utf-8")
    env = {"HMP_SET_flow__param__K__field__value": "1e-5"}

    changes = changes_of_args(_args(), env)
    request = request_of(config, set=changes, dry_run=True)

    assert changes == {"flow.param.K.field.value": 1e-5}
    assert request.overrides() == {"flow.param.K.field.value": 1e-5}
    # The document the request holds is the file: the change rides beside it.
    assert "flow" not in request.config
    assert sorted(path.name for path in tmp_path.iterdir()) == ["project.toml"]


def test_the_changes_land_on_a_copy_of_the_document() -> None:
    document = {"a": {"b": 1}}

    changed = with_changes(document, {"a.b": 2, "a.c.d": 3})

    assert changed == {"a": {"b": 2, "c": {"d": 3}}}
    assert document == {"a": {"b": 1}}


# -- the flags -----------------------------------------------------------------------------------


def test_the_flags_are_repeatable_and_an_overlay_is_a_path() -> None:
    parser = argparse.ArgumentParser()
    add_override_arguments(parser)

    parsed = parser.parse_args(
        ["--overlay", "a.toml", "--overlay", "b.toml", "--set", "x.y=1", "--set", "x.z=2"]
    )

    assert parsed.overlay == [Path("a.toml"), Path("b.toml")]
    assert parsed.set_overrides == ["x.y=1", "x.z=2"]
    assert parser.parse_args([]).overlay == []


# -- the file and the base a verb is given ------------------------------------------------------


def test_a_verb_takes_a_toml_file_and_says_what_it_was_given_otherwise(tmp_path: Path) -> None:
    config = tmp_path / "run.toml"
    config.write_text("[workflow]\n", encoding="utf-8")
    other = tmp_path / "run.json"
    other.write_text("{}", encoding="utf-8")

    assert toml_target(config) == config.resolve()
    with pytest.raises(SystemExit) as missing:
        toml_target(tmp_path / "absent.toml")
    with pytest.raises(SystemExit) as wrong:
        toml_target(other)

    assert missing.value.code == EXIT_NOT_FOUND
    assert wrong.value.code == EXIT_CONFIG


def test_w_names_the_project_and_without_it_the_file_gives_the_base(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    assert base_named_by_w(None) is None
    assert base_named_by_w(str(project)) == project.resolve()
    with pytest.raises(SystemExit) as refused:
        base_named_by_w(str(elsewhere))
    assert refused.value.code == EXIT_NOT_FOUND


def test_no_command_writes_a_variable_of_the_environment_for_the_base() -> None:
    """The base is an argument: the helpers write no variable of the environment."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(conventions) + inspect.getsource(refs))
    written = [
        ast.unparse(target)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete))
        for target in (
            node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
        )
        if isinstance(target, ast.Subscript) and ast.unparse(target.value) == "os.environ"
    ]
    called = [
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func)
        in {"os.environ.update", "os.environ.setdefault", "os.environ.pop", "os.putenv"}
    ]
    assert written == [] and called == []


@pytest.mark.parametrize(
    ("flag", "document", "expected"),
    [
        (None, {}, None),
        ("", {}, "run.profile.html"),
        ("report.html", {}, "report.html"),
        (None, {"workflow": {"profile": True}}, "run.profile.html"),
        (None, {"workflow": {"profile": "from_file.html"}}, "from_file.html"),
    ],
    ids=["none", "bare flag", "named flag", "the file asks", "the file names it"],
)
def test_the_profile_is_where_the_flag_or_the_file_says(
    tmp_path: Path, flag: str | None, document: dict[str, Any], expected: str | None
) -> None:
    pytest.importorskip("pyinstrument")
    target = tmp_path / "run.toml"
    found = profile_output_of(SimpleNamespace(profile=flag), document, target)

    if expected is None:
        assert found is None
    elif "/" in expected or flag == "report.html" or "from_file" in expected:
        assert found is not None and found.name == expected
    else:
        assert found == tmp_path / expected


# -- the refusals a copy gave, given by the command ----------------------------------------------


def _leftovers(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.rglob("*") if ".effective." in path.name)


def test_a_syntax_error_in_a_base_file_names_that_file(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text("[workflow\nmode = 'simulation'\n", encoding="utf-8")
    child = tmp_path / "child.toml"
    child.write_text('base_config = "base.toml"\n', encoding="utf-8")

    result = CliRunner().invoke(["run", str(child), "--set", "a.b=1"])

    assert result.exit_code == EXIT_CONFIG
    assert "Invalid TOML in" in result.stderr
    assert "base.toml" in result.stderr
    assert _leftovers(tmp_path) == []


def test_a_circular_chain_is_a_file_error(tmp_path: Path) -> None:
    (tmp_path / "a.toml").write_text('base_config = "b.toml"\n', encoding="utf-8")
    (tmp_path / "b.toml").write_text('base_config = "a.toml"\n', encoding="utf-8")

    result = CliRunner().invoke(["run", str(tmp_path / "a.toml")])

    assert result.exit_code == EXIT_CONFIG
    assert "circular base_config chain" in result.stderr


def test_a_bad_set_item_is_an_override_error_and_not_a_file_error(tmp_path: Path) -> None:
    config = tmp_path / "ok.toml"
    config.write_text("[workflow]\nmode = 'simulation'\n", encoding="utf-8")

    result = CliRunner().invoke(["run", str(config), "--set", "foo"])

    assert result.exit_code == EXIT_CONFIG
    assert "Invalid override" in result.stderr
    assert "--set expects PATH=VALUE" in result.stderr
    assert _leftovers(tmp_path) == []


def test_an_overlay_is_read_with_its_own_chain_and_nothing_is_written(tmp_path: Path) -> None:
    config = tmp_path / "run.toml"
    config.write_text("[a]\nx = 1\ny = 1\n", encoding="utf-8")
    overlay = tmp_path / "over.toml"
    overlay.write_text("[a]\ny = 2\n", encoding="utf-8")

    document = read_document(config, overlays=[overlay], root=ROOT_CONFIG)

    assert document == {"a": {"x": 1, "y": 2}}
    assert sorted(path.name for path in tmp_path.iterdir()) == ["over.toml", "run.toml"]


# -- a calibration takes the changes in its request ---------------------------------------------


def _seen_by_the_calibration(monkeypatch: pytest.MonkeyPatch, config: Path, *flags: str) -> dict:
    """Run ``hmp run`` on a calibration file and return what the calibration runner is given."""
    from hydromodpy.project.dispatch import workflow

    seen: dict[str, Any] = {}

    def fake(request: Any, *, base: Path, environment: Any = None) -> dict:
        seen.update(request=request, base=base)
        return {}

    monkeypatch.setitem(workflow.DISPATCH, "calibration", fake)
    monkeypatch.setattr("hydromodpy.calibration.preflight.preflight_launch", lambda *a, **k: None)
    result = CliRunner().invoke(["run", str(config), *flags, "--format", "json"])
    assert result.exit_code == 0, result.stderr
    return seen


def test_a_variant_of_a_calibration_rides_in_the_request_and_names_no_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "cal.toml"
    config.write_text('[workflow]\nmode = "calibration"\n' + _CAL, encoding="utf-8")

    seen = _seen_by_the_calibration(monkeypatch, config, "--set", "calibration.seed=5")

    request = seen["request"]
    assert request.set == {"calibration.seed": 5}
    assert request.config["calibration"]["seed"] == 3
    assert request.name is None
    assert seen["base"] == tmp_path.resolve()
    assert _leftovers(tmp_path) == []


def test_case_names_the_variant_in_the_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "cal.toml"
    config.write_text(
        '[workflow]\nmode = "calibration"\n[simulation]\nname = "declared"\n' + _CAL,
        encoding="utf-8",
    )

    seen = _seen_by_the_calibration(monkeypatch, config, "--case", "x")

    assert seen["request"].name == "x"
    assert seen["request"].config["simulation"]["name"] == "declared"


def test_an_overlay_of_a_calibration_is_merged_into_the_document_of_its_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "cal.toml"
    config.write_text('[workflow]\nmode = "calibration"\n' + _CAL, encoding="utf-8")
    overlay = tmp_path / "all.toml"
    overlay.write_text('[calibration]\nsave_runs = "all"\n', encoding="utf-8")

    seen = _seen_by_the_calibration(monkeypatch, config, "--overlay", str(overlay))

    request = seen["request"]
    assert request.config["calibration"]["save_runs"] == "all"
    assert request.overlays == ("all.toml",)
    assert request.form == "toml"


def test_a_calibration_without_changes_has_a_request_that_is_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "cal.toml"
    config.write_text('[workflow]\nmode = "calibration"\n' + _CAL, encoding="utf-8")

    seen = _seen_by_the_calibration(monkeypatch, config)

    request = seen["request"]
    assert (request.set, request.overlays, request.name) == ({}, (), None)
    assert request.form == "toml"
    assert request.source.endswith("cal.toml")
