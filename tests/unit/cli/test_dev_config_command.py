"""Unit tests for ``hmp dev config``."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

from tests._helpers.cli_runner import CliRunner


def test_dev_config_check_comparison_dispatches_to_comparison_config(
    monkeypatch,
    tmp_path,
) -> None:
    config = tmp_path / "comparison.toml"
    config.write_text('[workflow]\nmode = "comparison"\n', encoding="utf-8")
    raw_toml = {"workflow": {"mode": "comparison"}}
    calls: dict[str, object] = {}

    class FakeRootConfig:
        @classmethod
        def from_toml(cls, path: Path) -> None:
            calls["root_path"] = path

    class FakeComparisonConfig:
        @classmethod
        def from_toml(cls, payload: dict[str, object], *, config_path: Path) -> None:
            calls["comparison"] = {"payload": payload, "config_path": config_path}

    fake_module = SimpleNamespace(SimulationComparisonConfig=FakeComparisonConfig)

    monkeypatch.setattr(
        "hydromodpy.core.toml_io.loader.load_toml_with_base_config",
        lambda path: raw_toml,
    )
    monkeypatch.setattr("hydromodpy.config.HydroModPyConfig", FakeRootConfig)
    monkeypatch.setitem(
        sys.modules,
        "hydromodpy.analysis.comparison.experiment_config",
        fake_module,
    )

    result = CliRunner().invoke(["dev", "config", "check", str(config)])

    assert result.exit_code == 0
    assert calls == {
        "comparison": {"payload": raw_toml, "config_path": config.resolve()},
    }
    assert f"OK: {config.resolve()}" in result.stdout


def test_dev_config_check_invalid_toml_maps_to_config_exit(monkeypatch, tmp_path) -> None:
    config = tmp_path / "broken.toml"
    config.write_text("not = [valid", encoding="utf-8")

    def fake_load_toml(path: Path) -> dict[str, object]:
        del path
        raise tomllib.TOMLDecodeError("bad syntax", "not = [valid", 7)

    monkeypatch.setattr(
        "hydromodpy.core.toml_io.loader.load_toml_with_base_config",
        fake_load_toml,
    )

    result = CliRunner().invoke(["dev", "config", "check", str(config)])

    assert result.exit_code == 14
    assert "Invalid TOML syntax:" in result.stderr
    assert "bad syntax" in result.stderr


def test_dev_config_schema_forwards_section_profile_and_output(monkeypatch, tmp_path) -> None:
    out = tmp_path / "schema.json"
    calls: dict[str, object] = {}

    def fake_write_schema(path: str, *, section: str | None, profile: str | None) -> Path:
        calls["write_schema"] = {"path": path, "section": section, "profile": profile}
        out.write_text("{}", encoding="utf-8")
        return out

    monkeypatch.setattr("hydromodpy.config.schema_export.write_schema", fake_write_schema)

    result = CliRunner().invoke(
        [
            "dev",
            "config",
            "schema",
            "--section",
            "flow",
            "--profile",
            "expert",
            "--out",
            str(out),
        ]
    )

    assert result.exit_code == 0
    assert calls == {
        "write_schema": {"path": str(out), "section": "flow", "profile": "expert"},
    }
    assert result.stdout == ""
    assert f"Written to: {out}" in result.stderr


def test_dev_config_template_list_modules_prints_modules_without_generating(
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

    result = CliRunner().invoke(["dev", "config", "template", "--list-modules"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["workspace", "flow"]
    assert calls == {}
