"""Storage-boundary checks for direct DuckDB access."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

CHECKED_FILES = (
    REPO_ROOT / "hydromodpy" / "_api.py",
    *sorted((REPO_ROOT / "hydromodpy" / "cli" / "commands").rglob("*.py")),
)

CLI_DIAGNOSTIC_FILES = (
    REPO_ROOT / "hydromodpy" / "cli" / "commands" / "doctor.py",
    *sorted((REPO_ROOT / "hydromodpy" / "cli" / "_workers").rglob("*.py")),
)

DATA_REGISTRY_FILES = (
    REPO_ROOT / "hydromodpy" / "data" / "registry" / "backend.py",
    REPO_ROOT / "hydromodpy" / "data" / "registry" / "catalog_duckdb.py",
)

ALLOWED_DIRECT_DUCKDB_FILES = {
    "hydromodpy/cli/commands/doctor.py",
    "hydromodpy/cli/commands/dev/manage/backend.py",
}


def _duckdb_connect_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in _duckdb_connect_calls(tree):
        lines.append(node.lineno)
    return lines


def _duckdb_connect_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "connect"
            and isinstance(func.value, ast.Name)
            and func.value.id == "duckdb"
        ):
            calls.append(node)
    return calls


def _has_read_only_true(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg != "read_only":
            continue
        return isinstance(keyword.value, ast.Constant) and keyword.value.value is True
    return False


def test_public_api_and_cli_commands_do_not_open_duckdb_directly() -> None:
    """Block new direct DuckDB opens in public API and user-facing commands."""
    offenders: list[str] = []
    for path in CHECKED_FILES:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWED_DIRECT_DUCKDB_FILES:
            continue
        for line in _duckdb_connect_lines(path):
            offenders.append(f"{rel}:{line}")
    assert offenders == []


def test_data_cache_file_connections_use_retry_helper() -> None:
    """Allow direct in-memory DuckDB only in the data-cache registry."""
    offenders: list[str] = []
    for path in DATA_REGISTRY_FILES:
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _duckdb_connect_calls(tree):
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == ":memory:"
            ):
                continue
            offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


def test_cli_diagnostic_duckdb_connections_are_read_only() -> None:
    """Direct CLI DuckDB connections are only accepted for read-only diagnostics."""
    offenders: list[str] = []
    for path in CLI_DIAGNOSTIC_FILES:
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _duckdb_connect_calls(tree):
            if not _has_read_only_true(node):
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


def test_cli_heartbeat_queries_use_workflow_events_view() -> None:
    """Do not revive ``simulations.last_heartbeat`` as the workflow heartbeat source."""
    offenders: list[str] = []
    for path in CLI_DIAGNOSTIC_FILES:
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if "s.last_heartbeat" in text:
            offenders.append(rel)
    assert offenders == []
