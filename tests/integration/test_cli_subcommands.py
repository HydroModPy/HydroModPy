"""Integration smoke tests for the ``hmp`` CLI subcommand dispatch.

Each new or reorganised CLI subcommand must at minimum surface in
``hmp --help`` and expose a ``--help`` string without importing the heavy
domain modules. The tests invoke ``hmp`` in-process to avoid spinning a
subprocess per assertion.
"""

from __future__ import annotations

import sys

import pytest

from hydromodpy._cli.main import main

SUBCOMMANDS = (
    "init",
    "new",
    "config",
    "schema",
    "run",
    "display",
    "list",
    "export",
    "test",
    "data",
    "lock",
    "show",
    "compare",
    "import",
    "doctor",
    "inspect",
    "rank",
    "delete",
    "completion",
)


def _run_cli(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        main()
    return int(exc_info.value.code or 0)


def test_top_level_help_lists_every_subcommand(monkeypatch, capsys) -> None:
    code = _run_cli(monkeypatch, ["hmp", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    for name in SUBCOMMANDS:
        assert name in out, f"'{name}' missing from --help"


@pytest.mark.parametrize("name", SUBCOMMANDS)
def test_subcommand_help_exits_zero(monkeypatch, capsys, name: str) -> None:
    code = _run_cli(monkeypatch, ["hmp", name, "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_version_flag_prints_version(monkeypatch, capsys) -> None:
    code = _run_cli(monkeypatch, ["hmp", "--version"])
    assert code == 0
    out = capsys.readouterr().out
    assert "hydromodpy" in out.lower()


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_emits_script(monkeypatch, capsys, shell: str) -> None:
    monkeypatch.setattr(sys, "argv", ["hmp", "completion", shell])
    main()
    out = capsys.readouterr().out
    assert "hmp" in out
    # Each completion script should mention at least one of our subcommands.
    assert any(name in out for name in ("run", "init", "doctor"))


def test_run_dry_run_lists_steps(monkeypatch, capsys, tmp_path) -> None:
    config = tmp_path / "cfg.toml"
    config.write_text('[simulation]\nname = "dry"\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["hmp", "run", "--dry-run", str(config)])

    main()
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "workflow: simulation" in out


def test_config_check_reports_missing_file(monkeypatch, capsys, tmp_path) -> None:
    missing = tmp_path / "nope.toml"
    code = _run_cli(monkeypatch, ["hmp", "config", "check", str(missing)])
    assert code == 3


def test_config_check_reports_invalid_toml(monkeypatch, capsys, tmp_path) -> None:
    """Invalid TOML syntax must exit with EXIT_CONFIG=1."""
    bad = tmp_path / "bad.toml"
    bad.write_text("[section\nmissing = close_bracket\n", encoding="utf-8")
    code = _run_cli(monkeypatch, ["hmp", "config", "check", str(bad)])
    assert code == 1
    err = capsys.readouterr().err
    assert "invalid toml" in err.lower() or "config" in err.lower()


def test_config_template_writes_toml(monkeypatch, tmp_path) -> None:
    """``hmp config template FILE`` creates a non-empty TOML file."""
    out = tmp_path / "cfg.toml"
    monkeypatch.setattr(
        sys,
        "argv",
        ["hmp", "config", "template", str(out), "--profile", "user"],
    )
    main()
    assert out.is_file()
    content = out.read_text(encoding="utf-8")
    assert "[workspace]" in content or "[flow]" in content
