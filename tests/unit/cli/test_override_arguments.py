"""``--set``, ``--overlay`` and ``HMP_SET_*`` become a mapping of dotted paths in the request.

Nothing is written beside the file the user named. Every refusal is given by the command.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.cli import conventions, refs
from hydromodpy.cli.conventions import changes_of_args
from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_NOT_FOUND
from hydromodpy.cli.profiling import profile_output_of
from hydromodpy.cli.refs import toml_target
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


@pytest.mark.parametrize(
    ("item", "said"),
    [("foo", "--set expects PATH=VALUE"), ("a..b=1", "unexpected"), ("a[0]=1", "no index")],
    ids=["no equal sign", "empty part", "an index"],
)
def test_malformed_set_item(item: str, said: str) -> None:
    with pytest.raises(ValueError, match=said):
        changes_of_args(_args(set_overrides=[item]), {})


def test_toml_target(tmp_path: Path) -> None:
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


def test_no_environment_write() -> None:
    # The base is an argument: the helpers write no variable of the environment.
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
def test_profile_output(
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


def _leftovers(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.rglob("*") if ".effective." in path.name)


def test_syntax_error_in_a_base(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text("[workflow\nmode = 'simulation'\n", encoding="utf-8")
    child = tmp_path / "child.toml"
    child.write_text('base_config = "base.toml"\n', encoding="utf-8")

    result = CliRunner().invoke(["run", str(child), "--set", "a.b=1"])

    assert result.exit_code == EXIT_CONFIG
    assert "Invalid TOML in" in result.stderr
    assert "base.toml" in result.stderr
    assert _leftovers(tmp_path) == []


def test_circular_base_chain(tmp_path: Path) -> None:
    (tmp_path / "a.toml").write_text('base_config = "b.toml"\n', encoding="utf-8")
    (tmp_path / "b.toml").write_text('base_config = "a.toml"\n', encoding="utf-8")

    result = CliRunner().invoke(["run", str(tmp_path / "a.toml")])

    assert result.exit_code == EXIT_CONFIG
    assert "circular base_config chain" in result.stderr


def test_bad_set_item_is_an_override_error(tmp_path: Path) -> None:
    config = tmp_path / "ok.toml"
    config.write_text("[workflow]\nmode = 'simulation'\n", encoding="utf-8")

    result = CliRunner().invoke(["run", str(config), "--set", "foo"])

    assert result.exit_code == EXIT_CONFIG
    assert "Invalid override" in result.stderr
    assert "--set expects PATH=VALUE" in result.stderr
    assert _leftovers(tmp_path) == []


def _seen_by_the_calibration(monkeypatch: pytest.MonkeyPatch, config: Path, *flags: str) -> dict:
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


def test_case_names_the_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "cal.toml"
    config.write_text(
        '[workflow]\nmode = "calibration"\n[simulation]\nname = "declared"\n' + _CAL,
        encoding="utf-8",
    )

    seen = _seen_by_the_calibration(monkeypatch, config, "--case", "x")

    assert seen["request"].name == "x"
    assert seen["request"].config["simulation"]["name"] == "declared"


def test_calibration_request_without_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "cal.toml"
    config.write_text('[workflow]\nmode = "calibration"\n' + _CAL, encoding="utf-8")

    seen = _seen_by_the_calibration(monkeypatch, config)

    request = seen["request"]
    assert (request.set, request.overlays, request.name) == ({}, (), None)
    assert request.form == "toml"
    assert request.source.endswith("cal.toml")
