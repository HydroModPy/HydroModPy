"""Integration smoke tests for the ``hmp`` CLI subcommand dispatch.

Each new or reorganised CLI subcommand must at minimum surface in
``hmp --help`` and expose a ``--help`` string without importing the heavy
domain modules. The tests invoke ``hmp`` in-process to avoid spinning a
subprocess per assertion.
"""

from __future__ import annotations

import sys

import pytest

from hydromodpy.cli.commands import ALL_COMMANDS
from hydromodpy.cli.main import main

SUBCOMMANDS = tuple(command.NAME for command in ALL_COMMANDS)


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


def test_legacy_init_alias_is_not_a_top_level_subcommand(monkeypatch, capsys) -> None:
    assert "init" not in SUBCOMMANDS

    code = _run_cli(monkeypatch, ["hmp", "init", "--help"])

    assert code == 2
    err = capsys.readouterr().err.lower()
    assert "invalid choice" in err
    assert "workspace" in err


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
    monkeypatch.setattr(sys, "argv", ["hmp", "dev", "completion", shell])
    main()
    out = capsys.readouterr().out
    assert "hmp" in out
    # Each completion script should mention at least one of our subcommands.
    assert any(name in out for name in ("run", "workspace", "doctor"))


def test_run_dry_run_lists_steps(monkeypatch, capsys, tmp_path) -> None:
    config = tmp_path / "cfg.toml"
    config.write_text(
        '[workflow]\nmode = "simulation"\n[simulation]\nname = "dry"\n', encoding="utf-8"
    )
    monkeypatch.setattr(sys, "argv", ["hmp", "run", "--dry-run", str(config)])

    main()
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "workflow: simulation" in out


def test_dev_run_script_help(monkeypatch, capsys) -> None:
    code = _run_cli(monkeypatch, ["hmp", "dev", "run-script", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_config_check_reports_missing_file(monkeypatch, capsys, tmp_path) -> None:
    missing = tmp_path / "nope.toml"
    code = _run_cli(monkeypatch, ["hmp", "config", "check", str(missing)])
    assert code == 10


def test_config_check_reports_invalid_toml(monkeypatch, capsys, tmp_path) -> None:
    """Invalid TOML syntax must exit with EXIT_CONFIG=14."""
    bad = tmp_path / "bad.toml"
    bad.write_text("[section\nmissing = close_bracket\n", encoding="utf-8")
    code = _run_cli(monkeypatch, ["hmp", "config", "check", str(bad)])
    assert code == 14
    err = capsys.readouterr().err
    assert "invalid toml" in err.lower() or "config" in err.lower()


def test_config_check_accepts_site_selection_without_geographic(monkeypatch, capsys, tmp_path):
    config = tmp_path / "site_selection.toml"
    config.write_text(
        "\n".join(
            [
                "[workflow]",
                'mode = "site_selection"',
                "",
                "[site_selection]",
                'selection_id = "check_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "plan_only"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "argv", ["hmp", "config", "check", str(config)])

    main()
    out = capsys.readouterr().out
    assert "OK:" in out


def test_site_selection_plan_cli_can_write_report(monkeypatch, capsys, tmp_path):
    config = tmp_path / "site_selection.toml"
    config.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "cli_plan_report_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "plan_only"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
            ]
        ),
        encoding="utf-8",
    )

    code = _run_cli(
        monkeypatch,
        ["hmp", "site-selection", "plan", str(config), "--write-report"],
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "site_selection_report_html" in out
    assert (tmp_path / "out" / "site_selection_plan.json").is_file()
    assert (tmp_path / "out" / "review" / "index.html").is_file()


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
    assert "[workflow]" in content
    assert 'mode = "simulation"' in content
    assert "[workspace]" in content or "[flow]" in content


def test_new_project_scaffold_writes_valid_run_config(monkeypatch, tmp_path) -> None:
    from hydromodpy.config import HydroModPyConfig

    (tmp_path / "data").mkdir()
    monkeypatch.setattr(
        sys, "argv", ["hmp", "project", "new", "demo", "--workspace", str(tmp_path)]
    )

    main()

    run_config = tmp_path / "projects" / "demo" / "run_demo.toml"
    cfg = HydroModPyConfig.from_toml(run_config)
    assert cfg.workflow.mode == "simulation"
    assert cfg.geographic.source_mode == "synthetic"
    assert cfg.simulation.process[0].solvers == ["modflow_nwt"]
