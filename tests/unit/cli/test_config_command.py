"""Unit tests for ``hmp config``."""

from __future__ import annotations

import tomllib
from pathlib import Path

from tests._helpers.cli_runner import CliRunner


def test_config_check_refuses_a_retired_mode_with_its_replacement(tmp_path) -> None:
    config = tmp_path / "comparison.toml"
    config.write_text('[workflow]\nmode = "comparison"\n', encoding="utf-8")

    result = CliRunner().invoke(["config", "check", str(config)])

    assert result.exit_code == 14
    assert f"Config invalid: {config.resolve()}" in result.stderr
    assert "hmp report compare" in result.stderr


def test_config_check_expands_a_sites_project_and_counts_its_cases(tmp_path) -> None:
    from tests.unit.config.test_sites_plan import write_sites_project

    project = write_sites_project(tmp_path)

    result = CliRunner().invoke(["config", "check", str(project / "project.toml")])

    assert result.exit_code == 0, result.stderr
    assert f"OK: {project / 'project.toml'} (4 case(s))" in result.stdout


def test_config_check_names_the_cell_of_a_sites_project_error(tmp_path) -> None:
    from tests.unit.config.test_sites_plan import write_sites_project

    project = write_sites_project(tmp_path, k_cells=("5e-5", "not_a_number"))

    result = CliRunner().invoke(["config", "check", str(project / "project.toml")])

    assert result.exit_code == 14
    assert "sites.csv:3 column k -> flow.param.K.field.value" in result.stderr


def test_config_check_invalid_toml_maps_to_config_exit(tmp_path) -> None:
    config = tmp_path / "broken.toml"
    config.write_text("not = [valid", encoding="utf-8")

    result = CliRunner().invoke(["config", "check", str(config)])

    assert result.exit_code == 14
    assert "Invalid TOML syntax:" in result.stderr


def test_config_schema_forwards_section_profile_and_output(monkeypatch, tmp_path) -> None:
    out = tmp_path / "schema.json"
    calls: dict[str, object] = {}

    def fake_write_schema(path: str, *, section: str | None, profile: str | None) -> Path:
        calls["write_schema"] = {"path": path, "section": section, "profile": profile}
        out.write_text("{}", encoding="utf-8")
        return out

    monkeypatch.setattr("hydromodpy.config.schema_export.write_schema", fake_write_schema)

    result = CliRunner().invoke(
        [
            "config",
            "schema",
            "--section",
            "flow",
            "--profile",
            "expert",
            "--to",
            str(out),
        ]
    )

    assert result.exit_code == 0
    assert calls == {
        "write_schema": {"path": str(out), "section": "flow", "profile": "expert"},
    }
    assert result.stdout == ""
    assert f"Written to: {out}" in result.stderr


def test_config_schema_editor_writes_the_published_editor_schema(monkeypatch, tmp_path) -> None:
    out = tmp_path / "editor.json"
    monkeypatch.setattr(
        "hydromodpy.config.schema_export.editor_schema",
        lambda: {"$comment": "editor", "properties": {"base_config": {}}},
    )

    result = CliRunner().invoke(["config", "schema", "--editor", "--to", str(out)])

    assert result.exit_code == 0
    assert f"Written to: {out}" in result.stderr
    assert out.read_text(encoding="utf-8") == (
        '{\n  "$comment": "editor",\n  "properties": {\n    "base_config": {}\n  }\n}\n'
    )


def test_config_schema_editor_refuses_a_section() -> None:
    result = CliRunner().invoke(["config", "schema", "--editor", "--section", "flow"])

    assert result.exit_code == 2
    assert "--editor describes a whole TOML file" in result.stderr


def test_config_template_list_modules_prints_modules_without_generating(
    monkeypatch,
) -> None:
    calls: dict[str, bool] = {}

    def fake_generate_toml(*args: object, **kwargs: object) -> str:
        calls["generated"] = True
        return ""

    monkeypatch.setattr(
        "hydromodpy.core.toml_io.generator.available_modules",
        lambda: ["workspace", "flow"],
    )
    monkeypatch.setattr("hydromodpy.core.toml_io.generator.generate_toml", fake_generate_toml)

    result = CliRunner().invoke(["config", "template", "--list-modules"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["workspace", "flow"]
    assert calls == {}


def test_config_resolve_prints_the_merged_chain(tmp_path) -> None:
    (tmp_path / "base.toml").write_text(
        '[[export]]\nvariables = "head"\ntime = "last"\n\n[flow]\nflow_regime = "steady"\n',
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        'base_config = "base.toml"\n\n[[export]]\nvariables = "budget"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(["config", "resolve", str(child)])

    assert result.exit_code == 0
    assert tomllib.loads(result.stdout) == {
        "export": [{"variables": "budget"}],
        "flow": {"flow_regime": "steady"},
    }


def test_config_resolve_names_a_broken_chain(tmp_path) -> None:
    child = tmp_path / "child.toml"
    child.write_text('base_config = "child.toml"\n', encoding="utf-8")

    result = CliRunner().invoke(["config", "resolve", str(child)])

    assert result.exit_code == 14
    assert "Detected circular base_config chain" in result.stderr


def test_config_check_names_a_recipe_that_cannot_be_read(tmp_path) -> None:
    from tests.unit.config.test_sites_plan import write_sites_project

    project = write_sites_project(tmp_path)
    (project / "bad.toml").write_text('base_config = "project.toml"\n[flow\n', encoding="utf-8")
    project_toml = project / "project.toml"
    project_toml.write_text(
        project_toml.read_text(encoding="utf-8").replace(
            "[sites.recipes]\n", '[sites.recipes]\nbad = "bad.toml"\n'
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(["config", "check", str(project_toml)])

    assert result.exit_code == 14
    assert "Traceback" not in result.stderr
    assert "[sites.recipes] bad: " in result.stderr and "invalid TOML" in result.stderr


def test_config_template_without_modules_holds_no_sites_section(tmp_path) -> None:
    template = tmp_path / "tpl.toml"

    result = CliRunner().invoke(["config", "template", "--to", str(template)])

    assert result.exit_code == 0, result.stderr
    assert "[sites" not in template.read_text(encoding="utf-8")
    checked = CliRunner().invoke(["config", "check", str(template)])
    assert "[sites]" not in checked.stderr + checked.stdout
    assert "anchored by project.toml" not in checked.stderr + checked.stdout


def test_config_template_writes_sites_only_when_asked(tmp_path) -> None:
    template = tmp_path / "sites.toml"

    result = CliRunner().invoke(["config", "template", "--to", str(template), "--modules", "sites"])

    assert result.exit_code == 0, result.stderr
    assert "[sites" in template.read_text(encoding="utf-8")


def test_the_full_template_fails_its_check_only_on_the_catchment_to_choose(tmp_path) -> None:
    template = tmp_path / "full.toml"
    assert CliRunner().invoke(["config", "template", "--to", str(template)]).exit_code == 0

    checked = CliRunner().invoke(["config", "check", str(template)])

    output = checked.stderr + checked.stdout
    assert checked.exit_code != 0
    assert "1 validation error(s)" in output, output
    assert "geographic.catchment.kind is required" in output
    assert "crossings" not in output


_BODY = """\
[workspace]

[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"

[simulation]
name = "baseline"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "transient"

"""


def _check(tmp_path: Path, extra: str):
    path = tmp_path / "project.toml"
    path.write_text(_BODY.format(root=tmp_path.as_posix()) + extra, encoding="utf-8")
    return CliRunner().invoke(["config", "check", str(path)])


def test_a_config_whose_requests_hold_passes(tmp_path: Path) -> None:
    result = _check(
        tmp_path,
        '[[export]]\nvariables = ["head", "watertable_depth"]\ntime = "2002-10-15"\n\n'
        '[display]\ntime = "2002-10-15"\n',
    )

    assert result.exit_code == 0, result.stderr
    assert "OK:" in result.stdout


def test_a_date_outside_the_record_is_refused(tmp_path: Path) -> None:
    result = _check(tmp_path, '[display]\ntime = "2005-01-01"\n')

    assert result.exit_code == 14
    assert "display.time: 2005-01-01 is outside the record" in result.stderr


def test_an_export_name_no_run_holds_is_refused(tmp_path: Path) -> None:
    result = _check(tmp_path, '[[export]]\nvariables = "hed"\n')

    assert result.exit_code == 14
    assert "export[0]: 'hed'" in result.stderr


def test_two_blocks_writing_one_file_are_refused(tmp_path: Path) -> None:
    result = _check(
        tmp_path,
        '[[export]]\nvariables = "discharge"\n\n[[export]]\nvariables = ["discharge"]\n',
    )

    assert result.exit_code == 14
    assert "export[0] and export[1] both write discharge.csv" in result.stderr
