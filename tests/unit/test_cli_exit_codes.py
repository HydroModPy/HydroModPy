"""P10 standardised exit codes.

Contract (see ``architecture_cible/10_ux_cli_api.md`` + the P10 phase brief):
- 0 success
- 1 invalid config
- 2 run failed
- 3 not found (file, sim_id, workspace)
- 4 user abort
"""

from __future__ import annotations

import importlib

import pytest


def _load_module():
    return importlib.import_module("hydromodpy.__main__")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_module()
    monkeypatch.setattr(module.sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def test_exit_code_constants_exposed() -> None:
    module = _load_module()
    assert module.EXIT_OK == 0
    assert module.EXIT_CONFIG == 1
    assert module.EXIT_RUN_FAILED == 2
    assert module.EXIT_NOT_FOUND == 3
    assert module.EXIT_USER_ABORT == 4


def test_run_missing_file_returns_not_found(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "run", "/nonexistent/config.toml"])
    assert code == 3
    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_run_unsupported_extension_returns_config(monkeypatch, tmp_path, capsys) -> None:
    bad = tmp_path / "config.xml"
    bad.write_text("<?xml version='1.0'?>\n")
    code = _run(monkeypatch, ["hmp", "run", str(bad)])
    assert code == 1
    err = capsys.readouterr().err
    assert "unsupported" in err.lower()


def test_show_missing_workspace_returns_not_found(monkeypatch, tmp_path, capsys) -> None:
    # Point --workspace at a directory with no hydromodpy.duckdb
    missing = tmp_path / "empty_ws"
    missing.mkdir()
    code = _run(monkeypatch, ["hmp", "show", "abcd", "--workspace", str(missing)])
    assert code == 3


def test_compare_missing_workspace_returns_not_found(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "empty_ws"
    missing.mkdir()
    code = _run(
        monkeypatch,
        ["hmp", "compare", "sim_a", "sim_b", "--workspace", str(missing)],
    )
    assert code == 3


def test_import_missing_package_returns_not_found(monkeypatch, tmp_path) -> None:
    code = _run(
        monkeypatch,
        ["hmp", "import", str(tmp_path / "no_such.hmp"), "-w", str(tmp_path)],
    )
    assert code == 3
