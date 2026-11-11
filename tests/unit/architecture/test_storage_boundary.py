"""Storage-boundary checks: who may open DuckDB, who may write a DuckDB file, and who never opens the index.

Three guards. An AST guard on ``duckdb.connect``: it is called in a short
list of modules, the public API and the user-facing commands are not on it,
and ``results/catalog/index_file.py``, the one module that opens the project
index, opens it through ``connect_with_retry``; every other module, the
reader, the indexer, the doctor and the diagnostics included, goes through
it. An AST guard on writing: a DuckDB file is opened without
``read_only=True`` by its owner only, ``index_file.py`` for the staging copy
of ``.hmp/index.duckdb``; every other opener reads.
``hydromodpy/data`` opens no DuckDB file at all: the data cache is the sidecars
next to the files, and the database of HydroModPy 2.0.0 is refused by name.
A runtime guard: the verbs that watch a project read its ``outcome.json``
and ``logs/heartbeat.json`` with ``Catalog.__init__`` patched to raise, so a
status answers while the index is being rebuilt, or when the project has
none.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = REPO_ROOT / "hydromodpy"

CHECKED_FILES = (
    PACKAGE / "_api.py",
    *sorted((PACKAGE / "cli" / "commands").rglob("*.py")),
)

CLI_DIAGNOSTIC_FILES = (
    PACKAGE / "cli" / "commands" / "doctor.py",
    PACKAGE / "display" / "catalog_figures.py",
    PACKAGE / "results" / "catalog" / "listing.py",
    PACKAGE / "results" / "catalog" / "liveness.py",
    PACKAGE / "results" / "catalog" / "privacy.py",
)

ALLOWED_DIRECT_DUCKDB_FILES: set[str] = set()
"""Public API and command modules allowed to call ``duckdb.connect``: none."""

INDEX_OPENERS = {
    "hydromodpy/results/catalog/index_file.py",
}
"""The one module that opens ``.hmp/index.duckdb``, through ``connect_with_retry``."""

DUCKDB_CONNECT_FILES = {
    "hydromodpy/core/io/db_retry.py",
}
"""Every module allowed to call ``duckdb.connect``; a new one is a new DuckDB scope to justify."""

RETRY_HELPER = "hydromodpy/core/io/db_retry.py"
"""Where ``connect_with_retry`` wraps ``duckdb.connect``: its own call is the helper, not an opener."""

WRITE_CAPABLE_OPENERS = {
    "hydromodpy/results/catalog/adapters/duckdb.py",
    "hydromodpy/results/catalog/index_file.py",
}
"""The modules that may open a DuckDB file without ``read_only=True``.

``index_file.py`` owns ``.hmp/index.duckdb``: it writes its staging copy and
attaches the published file read-only to an in-memory connection;
``DuckDBBackend(path)`` owns the connection it opens. Nothing else writes.
"""


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


def _retry_helper_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "connect_with_retry":
            calls.append(node)
    return calls


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _duckdb_connect_lines(path: Path) -> list[int]:
    return [node.lineno for node in _duckdb_connect_calls(_parse(path))]


def _has_read_only_true(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg != "read_only":
            continue
        return isinstance(keyword.value, ast.Constant) and keyword.value.value is True
    return False


def _opens_a_file(call: ast.Call) -> bool:
    """Whether a ``duckdb.connect`` call names a database file, not an in-memory one."""
    database = call.args[0] if call.args else None
    if database is None:
        for keyword in call.keywords:
            if keyword.arg == "database":
                database = keyword.value
    if database is None:
        return False
    return not (isinstance(database, ast.Constant) and database.value == ":memory:")


def _write_capable_lines(path: Path) -> list[int]:
    """Lines of ``path`` that open a DuckDB file without ``read_only=True``."""
    tree = _parse(path)
    calls = [call for call in _duckdb_connect_calls(tree) if _opens_a_file(call)]
    calls.extend(_retry_helper_calls(tree))
    return [call.lineno for call in calls if not _has_read_only_true(call)]


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


# -- AST guards -------------------------------------------------------------


def test_public_api_and_cli_commands_do_not_open_duckdb_directly() -> None:
    """Block new direct DuckDB opens in public API and user-facing commands."""
    offenders: list[str] = []
    for path in CHECKED_FILES:
        rel = _rel(path)
        if rel in ALLOWED_DIRECT_DUCKDB_FILES:
            continue
        for line in _duckdb_connect_lines(path):
            offenders.append(f"{rel}:{line}")
    assert offenders == []


def test_the_data_package_opens_no_duckdb_file_and_does_not_import_it() -> None:
    """The data cache is the sidecars: nothing under ``data`` knows DuckDB."""
    offenders: list[str] = []
    for path in sorted((PACKAGE / "data").rglob("*.py")):
        tree = _parse(path)
        for node in ast.walk(tree):
            imported = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(name.split(".")[0] == "duckdb" for name in imported):
                offenders.append(f"{_rel(path)}:{node.lineno}")
        for line in _duckdb_connect_lines(path):
            offenders.append(f"{_rel(path)}:{line}")
    assert offenders == []


def test_cli_diagnostic_duckdb_connections_are_read_only() -> None:
    """Direct CLI DuckDB connections are only accepted for read-only diagnostics."""
    offenders: list[str] = []
    for path in CLI_DIAGNOSTIC_FILES:
        rel = _rel(path)
        for node in _duckdb_connect_calls(_parse(path)):
            if not _has_read_only_true(node):
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


def test_duckdb_is_opened_only_where_a_scope_is_declared() -> None:
    """A module calling ``duckdb.connect`` is one of the declared DuckDB scopes."""
    offenders: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = _rel(path)
        if rel in DUCKDB_CONNECT_FILES:
            continue
        for line in _duckdb_connect_lines(path):
            offenders.append(f"{rel}:{line}")
    assert offenders == []


def test_the_index_is_opened_through_the_retry_helper_by_its_openers() -> None:
    """The opener of the index goes through ``connect_with_retry``, never raw."""
    for rel in sorted(INDEX_OPENERS):
        path = REPO_ROOT / rel
        text = path.read_text(encoding="utf-8")
        assert "connect_with_retry(" in text, rel
        assert _duckdb_connect_lines(path) == [], rel


def test_the_catalog_opens_duckdb_only_through_the_index_file() -> None:
    """Under ``results/catalog``, only the index file and the backend call ``connect_with_retry``.

    The reader, the indexer and the listings open the index by
    ``open_index`` or write it by ``open_staging``.
    """
    offenders: list[str] = []
    for path in sorted((PACKAGE / "results" / "catalog").rglob("*.py")):
        rel = _rel(path)
        if rel in INDEX_OPENERS or rel in WRITE_CAPABLE_OPENERS:
            continue
        for call in _retry_helper_calls(_parse(path)):
            offenders.append(f"{rel}:{call.lineno}")
    assert offenders == []


def test_a_duckdb_file_is_opened_for_writing_by_its_owner_only() -> None:
    """The data cache and the index are written by their owners; every other opener reads.

    Both ways: a module outside the owners opens read-only, and every declared
    owner still opens for writing, so the list cannot rot.
    """
    found: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = _rel(path)
        if rel == RETRY_HELPER:
            continue
        lines = _write_capable_lines(path)
        if lines:
            found[rel] = lines
    offenders = {rel: lines for rel, lines in found.items() if rel not in WRITE_CAPABLE_OPENERS}
    assert offenders == {}
    assert set(found) == WRITE_CAPABLE_OPENERS


CATALOG_FAMILY_FILES = (
    *sorted((PACKAGE / "cli" / "commands" / "catalog").rglob("*.py")),
    *sorted((PACKAGE / "results" / "catalog").rglob("*.py")),
)


def test_the_catalog_family_names_none_of_the_retired_tables() -> None:
    """The workflow journal and the audit log left the index: nothing of the catalog names them."""
    offenders: list[str] = []
    for path in CATALOG_FAMILY_FILES:
        text = path.read_text(encoding="utf-8")
        for token in ("workflow_events", "workflow_steps", "v_workflow_heartbeats", "audit_log"):
            if token in text:
                offenders.append(f"{_rel(path)}:{token}")
    assert offenders == []


# -- runtime guard ------------------------------------------------------------


@pytest.fixture
def no_index_opening(monkeypatch):
    """Make any opening of the index fail loudly."""
    from hydromodpy.results.catalog import facade

    def _refuse(self, *_args, **_kwargs):
        raise AssertionError("the index was opened")

    monkeypatch.setattr(facade.Catalog, "__init__", _refuse)


def test_watch_reads_the_outcomes_and_never_the_index(tmp_path, no_index_opening) -> None:
    from hydromodpy.core.state.layout import catalog_path_for
    from hydromodpy.results.catalog.liveness import stale_running_sim_ids, watch_running
    from tests._helpers.sealed_runs import make_project, seal_run, write_attempt

    root = make_project(tmp_path / "demo")
    seal_run(root, "done")
    write_attempt(root, "runs/live", status="running", heartbeat_age_s=2)
    write_attempt(root, "runs/dead", status="running", heartbeat_age_s=3600)
    write_attempt(root, "runs/broken", status="failed")
    catalog_path_for(root).parent.mkdir(parents=True)
    catalog_path_for(root).write_bytes(b"not a database")

    rows = {row["rel_dir"]: row for row in watch_running(root)}

    assert set(rows) == {"runs/live", "runs/dead"}
    assert rows["runs/live"]["stale"] is False
    assert rows["runs/dead"]["stale"] is True
    assert stale_running_sim_ids(root) == ["runs/dead"]


def test_the_doctor_counts_read_the_sessions_and_never_the_index(
    tmp_path, no_index_opening
) -> None:
    from datetime import UTC, datetime, timedelta

    from hydromodpy.results.catalog.liveness import (
        abandoned_calibration_session_count,
        orphan_calibration_session_count,
    )
    from tests._helpers.sealed_runs import make_project, write_session_dir

    root = make_project(tmp_path / "demo")
    write_session_dir(root, "fresh", status="running", started_at=datetime.now(UTC))
    write_session_dir(
        root, "old", status="running", started_at=datetime.now(UTC) - timedelta(days=2)
    )
    write_session_dir(root, "orphan", best_trial=1, best_rel_dir="runs/gone")

    assert abandoned_calibration_session_count(root) == 1
    assert orphan_calibration_session_count(root) == 1
