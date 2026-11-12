"""``hmp config``: write a schema or a template, resolve a ``base_config`` chain, list the targets.

``config targets`` answers what a project can calibrate. The catalog comes from the resolved
configuration, so it lists what this project carries, with the value it holds today (K in m/s).
"""

from __future__ import annotations

import argparse
import textwrap
import tomllib
from pathlib import Path

import pytest

from hydromodpy.cli.commands import config as config_cmd
from tests._helpers.cli_runner import CliRunner

PROJECT_TOML = textwrap.dedent(
    """
    [workspace]

    [workflow]
    mode = "simulation"

    [geographic]
    source_mode = "synthetic"

    [flow.param.K.field]
    id = "K"
    kind = "homogeneous"
    unit = "m/s"
    value = 6.4e-5

    [flow.param.Sy.field]
    id = "Sy"
    kind = "homogeneous"
    unit = "-"
    value = 0.05
    """
)

LAKE_TOML = textwrap.dedent(
    """
    [workspace]

    [workflow]
    mode = "calibration"

    [geographic]
    source_mode = "synthetic"

    [flow]

    [flow.param.K.field]
    id = "K"
    kind = "homogeneous"
    unit = "m/s"
    value = 6.4e-5

    [flow.sinks_sources.lakes.mylake]
    bedleak = 1e-6
    initial_stage = "10 m"

    [calibration]
    method = "optuna"
    max_trials = 4

    [calibration.parameters.bedleak]
    bounds = [1e-8, 1e-5]
    """
)


def run_targets(path: Path, **fields) -> None:
    args = argparse.Namespace(config_command="targets", file=str(path), workspace=None, **fields)
    config_cmd.run(args)


def write_project(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "project.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_schema_forwards_section_profile_and_output(monkeypatch, tmp_path) -> None:
    out = tmp_path / "schema.json"
    calls: dict[str, object] = {}

    def fake_write_schema(
        path: str,
        model_cls: object = None,
        *,
        section: str | None = None,
        profile: str | None = None,
    ) -> Path:
        calls["write_schema"] = {"path": path, "section": section, "profile": profile}
        out.write_text("{}", encoding="utf-8")
        return out

    monkeypatch.setattr("hydromodpy.schema.config_schema.write_schema", fake_write_schema)

    result = CliRunner().invoke(
        ["config", "schema", "--section", "flow", "--profile", "expert", "--to", str(out)]
    )

    assert result.exit_code == 0
    assert calls == {"write_schema": {"path": str(out), "section": "flow", "profile": "expert"}}
    assert result.stdout == ""
    assert f"Written to: {out}" in result.stderr


def test_editor_schema_is_the_published_one(monkeypatch, tmp_path) -> None:
    out = tmp_path / "editor.json"
    monkeypatch.setattr(
        "hydromodpy.schema.config_schema.editor_schema",
        lambda _model_cls=None: {"$comment": "editor", "properties": {"base_config": {}}},
    )

    result = CliRunner().invoke(["config", "schema", "--editor", "--to", str(out)])

    assert result.exit_code == 0
    assert f"Written to: {out}" in result.stderr
    assert out.read_text(encoding="utf-8") == (
        '{\n  "$comment": "editor",\n  "properties": {\n    "base_config": {}\n  }\n}\n'
    )


def test_editor_schema_refuses_a_section() -> None:
    result = CliRunner().invoke(["config", "schema", "--editor", "--section", "flow"])

    assert result.exit_code == 2
    assert "--editor describes a whole TOML file" in result.stderr


def test_template_list_modules_generates_nothing(monkeypatch) -> None:
    calls: dict[str, bool] = {}

    def fake_generate_toml(*args: object, **kwargs: object) -> str:
        calls["generated"] = True
        return ""

    monkeypatch.setattr(
        "hydromodpy.core.toml_io.generator.available_modules",
        lambda _root=None: ["workspace", "flow"],
    )
    monkeypatch.setattr("hydromodpy.core.toml_io.generator.generate_toml", fake_generate_toml)

    result = CliRunner().invoke(["config", "template", "--list-modules"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["workspace", "flow"]
    assert calls == {}


def test_template_without_modules_holds_no_sites_section(tmp_path) -> None:
    template = tmp_path / "tpl.toml"

    result = CliRunner().invoke(["config", "template", "--to", str(template)])

    assert result.exit_code == 0, result.stderr
    assert "[sites" not in template.read_text(encoding="utf-8")
    checked = CliRunner().invoke(["check", str(template)])
    assert "[sites]" not in checked.stderr + checked.stdout
    assert "anchored by project.toml" not in checked.stderr + checked.stdout


def test_template_writes_sites_only_when_asked(tmp_path) -> None:
    template = tmp_path / "sites.toml"

    result = CliRunner().invoke(["config", "template", "--to", str(template), "--modules", "sites"])

    assert result.exit_code == 0, result.stderr
    assert "[sites" in template.read_text(encoding="utf-8")


def test_resolve_prints_the_merged_chain(tmp_path) -> None:
    (tmp_path / "base.toml").write_text(
        '[[export]]\nvariables = "head"\ntime = "last"\n\n[flow]\nflow_regime = "steady"\n',
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        'base_config = "base.toml"\n\n[[export]]\nvariables = "budget"\n', encoding="utf-8"
    )

    result = CliRunner().invoke(["config", "resolve", str(child)])

    assert result.exit_code == 0
    assert tomllib.loads(result.stdout) == {
        "export": [{"variables": "budget"}],
        "flow": {"flow_regime": "steady"},
    }


def test_resolve_names_a_broken_chain(tmp_path) -> None:
    child = tmp_path / "child.toml"
    child.write_text('base_config = "child.toml"\n', encoding="utf-8")

    result = CliRunner().invoke(["config", "resolve", str(child)])

    assert result.exit_code == 14
    assert "Detected circular base_config chain" in result.stderr


def test_targets_show_the_value_the_project_holds_today(tmp_path, capsys) -> None:
    run_targets(write_project(tmp_path, PROJECT_TOML), format="table")

    out = capsys.readouterr().out
    assert "6.4e-05" in out or "6.4e-5" in out


def test_targets_of_a_file_that_does_not_load_exit_on_the_config_code(tmp_path) -> None:
    broken = tmp_path / "broken.toml"
    broken.write_text("[flow]\nnot_a_field = 1\n", encoding="utf-8")

    with pytest.raises(SystemExit) as caught:
        run_targets(broken)

    assert caught.value.code != 0


def test_targets_print_the_catalog_beside_an_unresolvable_name(tmp_path, capsys) -> None:
    # Loading is lenient about a name the catalog does not carry. The refusal that a bad name gets
    # elsewhere points the reader at this command, so it must not refuse to run.
    text = PROJECT_TOML + "\n[calibration.parameters.not_a_real_name]\nbounds = [1e-6, 1e-3]\n"

    run_targets(write_project(tmp_path, text))

    out = capsys.readouterr().out
    assert "flow.param.K.field.value" in out
    assert "Config invalid" not in out


def test_a_name_that_resolves_by_suffix_is_named_with_its_canonical_spelling(
    tmp_path, capsys
) -> None:
    # "bedleak" reaches "mylake.bedleak" only because it is the only target ending in ".bedleak".
    # The canonical spelling keeps the file valid when a second lake is declared.
    run_targets(write_project(tmp_path, LAKE_TOML))

    err = capsys.readouterr().err
    assert "calibration.parameters.bedleak" in err
    assert "mylake.bedleak" in err
