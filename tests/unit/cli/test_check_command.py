"""``hmp check``: the wiring of the command to the verb ``check``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.diagnostic import Diagnostic
from tests._helpers.cli_runner import CliRunner
from tests._helpers.sealed_runs import make_project

pytestmark = pytest.mark.fast


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "run.toml"
    path.write_text("[flow]\n", encoding="utf-8")
    return path


@pytest.fixture
def checked(monkeypatch) -> dict:
    """Replace the verb by a function that records its call and finds nothing."""
    seen: dict = {}

    def verb(source, **kwargs):
        seen.update(kwargs, source=source)
        return []

    monkeypatch.setattr("hydromodpy.project.api.check", verb)
    return seen


def test_the_flags_reach_the_verb(config: Path, checked: dict, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")

    result = CliRunner().invoke(["check", str(config), "--partial", "--inputs", "-w", str(project)])

    assert result.exit_code == 0, result.stderr
    assert checked["source"] == config.resolve()
    assert checked["partial"] is True
    assert checked["inputs"] is True
    assert Path(checked["base"]) == project.resolve()
    assert f"OK: {config.resolve()}" in result.stdout


def test_without_w_the_base_is_the_one_the_file_gives(config: Path, checked: dict) -> None:
    result = CliRunner().invoke(["check", str(config)])

    assert result.exit_code == 0, result.stderr
    assert checked["base"] is None
    assert checked["partial"] is False


def test_a_missing_file_exits_not_found(tmp_path: Path) -> None:
    result = CliRunner().invoke(["check", str(tmp_path / "gone.toml")])

    assert result.exit_code == 10
    assert "File not found" in result.stderr


def test_an_error_diagnostic_refuses_the_file_with_the_config_code(
    config: Path, monkeypatch
) -> None:
    fault = Diagnostic(code="to_fill", severity="error", path="geographic")
    monkeypatch.setattr("hydromodpy.project.api.check", lambda source, **kwargs: [fault])

    result = CliRunner().invoke(["check", str(config), "--format", "json"])

    document = json.loads(result.stdout)
    assert result.exit_code == 14
    assert document["schema"] == "hmp.check.v1"
    assert document["data"]["ok"] is False
    assert document["data"]["diagnostics"][0]["code"] == "to_fill"
    assert "phrase" in document["data"]["diagnostics"][0]


def test_a_warning_does_not_refuse_the_file(config: Path, monkeypatch) -> None:
    fault = Diagnostic(code="to_fill", severity="warning", path="geographic")
    monkeypatch.setattr("hydromodpy.project.api.check", lambda source, **kwargs: [fault])

    result = CliRunner().invoke(["check", str(config)])

    assert result.exit_code == 0
    assert f"OK: {config.resolve()}" in result.stdout


def test_the_lang_is_french_or_english_and_no_other(config: Path, checked: dict) -> None:
    assert CliRunner().invoke(["check", str(config), "--lang", "fr"]).exit_code == 0
    assert CliRunner().invoke(["check", str(config), "--lang", "de"]).exit_code == 2


def test_the_old_form_is_refused_with_the_new_one(config: Path) -> None:
    result = CliRunner().invoke(["config", "check", str(config)])

    assert result.exit_code == 2
    assert "Write: hmp check FILE" in result.stderr
