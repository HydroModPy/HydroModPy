"""Unit tests for the machine-wide :class:`GlobalIndex`.

Each test passes an explicit ``tmp_path`` for the index DB so the global
machine state directory is never touched. Workspaces are seeded with the
real V1 catalog DDL via :func:`ensure_schema` so the federation sees the
production ``v_simulation_summary`` view.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.state.global_index import GlobalIndex, WorkspaceRecord
from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.catalog.migrations import ensure_schema as _ensure_catalog


def _seed_workspace(
    workspace: Path,
    *,
    rows: list[tuple[str, str, str]] | None = None,
) -> Path:
    """Create a project index with rows in the ``simulations`` table.

    Each ``rows`` tuple is ``(sim_id, description, solver_code)``. ``sim_id``
    may be a short opaque label, it is hashed into a UUID before insertion
    so the catalog UUID column stays well-formed.
    """
    catalog_path = catalog_path_for(workspace)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(catalog_path))
    try:
        _ensure_catalog(conn)
        if rows:
            for sim_label, description, solver_code in rows:
                sim_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, sim_label))
                conn.execute(
                    """
                    INSERT INTO simulations
                        (sim_id, name, project, solver_id, status_id,
                         description, zarr_path, storage_basename)
                    VALUES (
                        ?, ?, 'lab',
                        (SELECT id FROM solvers WHERE code = ?),
                        (SELECT id FROM statuses WHERE code = 'completed'),
                        ?, ?, ?
                    )
                    """,
                    [
                        sim_uuid,
                        sim_label,
                        solver_code,
                        description,
                        f"sim/{sim_label}.zarr",
                        sim_label,
                    ],
                )
    finally:
        conn.close()
    return catalog_path


def _label_to_uuid(label: str) -> str:
    """Reverse of the UUID derivation used in :func:`_seed_workspace`."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, label))


def _index_db(tmp_path: Path) -> Path:
    return tmp_path / "state" / "index.duckdb"


def test_register_workspace_persists_record(tmp_path: Path) -> None:
    ws = tmp_path / "ws_a"
    _seed_workspace(ws)
    with GlobalIndex(_index_db(tmp_path)) as index:
        workspace_id = index.register_workspace(str(ws), label="alpha")
        records = index.list_workspaces()

    assert len(records) == 1
    record = records[0]
    assert isinstance(record, WorkspaceRecord)
    assert record.workspace_id == workspace_id
    assert record.workspace_uri == str(ws)
    assert record.label == "alpha"


def test_register_workspace_unique_uri_raises(tmp_path: Path) -> None:
    ws = tmp_path / "ws_a"
    _seed_workspace(ws)
    with GlobalIndex(_index_db(tmp_path)) as index:
        index.register_workspace(str(ws))
        with pytest.raises(duckdb.ConstraintException):
            index.register_workspace(str(ws))


def test_unregister_removes_record_and_detaches(tmp_path: Path) -> None:
    ws = tmp_path / "ws_a"
    _seed_workspace(ws, rows=[("s1", "desc", "modflow6")])
    with GlobalIndex(_index_db(tmp_path)) as index:
        workspace_id = index.register_workspace(str(ws))
        assert len(index.list_workspaces()) == 1

        df_before = index.find()
        assert not df_before.empty
        assert {str(s) for s in df_before["sim_id"]} == {_label_to_uuid("s1")}

        index.unregister_workspace(workspace_id)
        assert index.list_workspaces() == []

        df_after = index.find()
        assert df_after.empty


def test_find_federates_across_two_workspaces(tmp_path: Path) -> None:
    ws_a = tmp_path / "ws_a"
    ws_b = tmp_path / "ws_b"
    _seed_workspace(
        ws_a,
        rows=[("s_a1", "Bretagne run", "modflow6"), ("s_a2", "control", "modflow_nwt")],
    )
    _seed_workspace(ws_b, rows=[("s_b1", "Normandie run", "modflow6")])

    with GlobalIndex(_index_db(tmp_path)) as index:
        id_a = index.register_workspace(str(ws_a), label="alpha")
        id_b = index.register_workspace(str(ws_b), label="beta")

        df = index.find(solver="modflow6")

    assert {str(s) for s in df["sim_id"]} == {_label_to_uuid("s_a1"), _label_to_uuid("s_b1")}
    workspace_ids = set(df["workspace_id"].astype(str))
    assert workspace_ids == {id_a, id_b}


def test_attach_is_read_only(tmp_path: Path) -> None:
    ws = tmp_path / "ws_a"
    _seed_workspace(ws, rows=[("s1", "desc", "modflow6")])
    with GlobalIndex(_index_db(tmp_path)) as index:
        index.register_workspace(str(ws))
        alias = next(iter(index._attached_aliases))
        with pytest.raises(duckdb.Error):
            index.connection.execute(f"DELETE FROM {alias}.simulations WHERE sim_id IS NOT NULL")


def test_prune_removes_dead_workspaces(tmp_path: Path) -> None:
    ws_a = tmp_path / "ws_a"
    ws_b = tmp_path / "ws_b"
    _seed_workspace(ws_a, rows=[("s_a", "live", "modflow6")])
    _seed_workspace(ws_b, rows=[("s_b", "dead", "modflow6")])
    catalog_b = catalog_path_for(ws_b)

    with GlobalIndex(_index_db(tmp_path)) as index:
        id_a = index.register_workspace(str(ws_a))
        id_b = index.register_workspace(str(ws_b))
        catalog_b.unlink()

        removed = index.prune()
        remaining = {r.workspace_id for r in index.list_workspaces()}

    assert removed == [id_b]
    assert remaining == {id_a}


def test_search_fts_finds_term(tmp_path: Path) -> None:
    ws = tmp_path / "ws_a"
    _seed_workspace(
        ws,
        rows=[
            ("s1", "Bretagne hydrology baseline", "modflow6"),
            ("s2", "Pyrenees control run", "modflow_nwt"),
        ],
    )
    with GlobalIndex(_index_db(tmp_path)) as index:
        index.register_workspace(str(ws))
        df = index.search("Bretagne")

    sim_ids = {str(s) for s in df["sim_id"]} if not df.empty else set()
    assert _label_to_uuid("s1") in sim_ids


def test_workspace_without_v_simulation_summary_is_skipped(tmp_path: Path) -> None:
    """A workspace without the V1 view must be skipped, not crash."""
    ws = tmp_path / "ws_empty"
    catalog_path = catalog_path_for(ws)
    catalog_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(catalog_path))
    conn.execute("CREATE TABLE other_table (x INTEGER)")
    conn.close()

    with GlobalIndex(_index_db(tmp_path)) as index:
        workspace_id = index.register_workspace(str(ws))
        assert {r.workspace_id for r in index.list_workspaces()} == {workspace_id}
        assert index.find().empty


def test_index_path_uses_hmp_state_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The default index path resolves under ``$HMP_STATE_HOME/hydromodpy``."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "hmp_state"))
    from hydromodpy.core.state.global_index import _default_index_path

    expected = (tmp_path / "hmp_state").resolve() / "index.duckdb"
    assert _default_index_path() == expected


def test_read_only_open_returns_existing_records(tmp_path: Path) -> None:
    """``GlobalIndex(read_only=True)`` exposes search/find/list without writes."""
    ws = tmp_path / "ws_a"
    _seed_workspace(ws, rows=[("s1", "Bretagne baseline run", "modflow6")])
    index_db = _index_db(tmp_path)

    with GlobalIndex(index_db) as writer:
        writer.register_workspace(str(ws))

    with GlobalIndex(index_db, read_only=True) as reader:
        assert reader.read_only is True
        records = reader.list_workspaces()
        assert len(records) == 1
        df = reader.find(solver="modflow6")
        assert not df.empty
        assert {str(s) for s in df["sim_id"]} == {_label_to_uuid("s1")}


def test_read_only_register_raises_runtime_error(tmp_path: Path) -> None:
    """Mutations on a read-only handle raise ``RuntimeError``."""
    ws = tmp_path / "ws_a"
    _seed_workspace(ws)
    with GlobalIndex(_index_db(tmp_path)) as writer:
        writer.register_workspace(str(ws), label="seed")

    with GlobalIndex(_index_db(tmp_path), read_only=True) as ro:
        with pytest.raises(RuntimeError, match="read-only"):
            ro.register_workspace(str(ws / "ignored"))
        with pytest.raises(RuntimeError, match="read-only"):
            ro.unregister_workspace("nonexistent")
        with pytest.raises(RuntimeError, match="read-only"):
            ro.prune()


def test_read_only_bootstraps_missing_db(tmp_path: Path) -> None:
    """A read-only open on a missing DB seeds an empty schema instead of crashing."""
    index_db = tmp_path / "state" / "missing.duckdb"
    with GlobalIndex(index_db, read_only=True) as ro:
        assert ro.read_only is True
        assert ro.list_workspaces() == []
        assert ro.find().empty


def test_contended_writer_falls_back_to_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When ``connect_with_retry`` keeps raising lock errors, we degrade to read-only."""
    import duckdb as _duckdb

    from hydromodpy.core.state import global_index as gi_mod

    # Seed a real DB first via a normal writer so the file exists.
    ws = tmp_path / "ws_a"
    _seed_workspace(ws)
    index_db = _index_db(tmp_path)
    with GlobalIndex(index_db) as writer:
        writer.register_workspace(str(ws))

    def _always_contended(*_args: object, **_kwargs: object) -> _duckdb.DuckDBPyConnection:
        raise _duckdb.IOException(
            "IO Error: Could not set lock on file: another process is holding the lock"
        )

    monkeypatch.setattr(gi_mod, "connect_with_retry", _always_contended)

    with GlobalIndex(index_db) as gi:
        assert gi.read_only is True
        assert len(gi.list_workspaces()) == 1


def test_non_contention_io_error_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-lock IO errors are NOT swallowed by the read-only fallback."""
    import duckdb as _duckdb

    from hydromodpy.core.state import global_index as gi_mod

    ws = tmp_path / "ws_a"
    _seed_workspace(ws)
    index_db = _index_db(tmp_path)
    with GlobalIndex(index_db) as writer:
        writer.register_workspace(str(ws))

    def _other_io_error(*_args: object, **_kwargs: object) -> _duckdb.DuckDBPyConnection:
        raise _duckdb.IOException("IO Error: Permission denied")

    monkeypatch.setattr(gi_mod, "connect_with_retry", _other_io_error)

    with pytest.raises(_duckdb.IOException):
        GlobalIndex(index_db)


def test_a_stale_schema_ledger_is_rebuilt_not_fatal(tmp_path: Path) -> None:
    """The registry is reconstructible: an unmigratable ledger must not block boot."""
    ws = tmp_path / "ws_a"
    _seed_workspace(ws, rows=[("alpha", "first run", "modflow6")])
    index_db = _index_db(tmp_path)
    with GlobalIndex(index_db) as writer:
        writer.register_workspace(str(ws), label="lab")

    conn = duckdb.connect(str(index_db))
    conn.execute("UPDATE schema_migrations SET checksum = 'stale' WHERE component = 'index'")
    conn.execute("CREATE TABLE dropped_by_an_older_version (x INTEGER)")
    conn.close()

    with GlobalIndex(index_db) as gi:
        assert gi.read_only is False
        assert [(w.workspace_uri, w.label) for w in gi.list_workspaces()] == [(str(ws), "lab")]
        assert len(gi.find()) == 1
        tables = {row[0] for row in gi.connection.execute("SHOW TABLES").fetchall()}
        assert "dropped_by_an_older_version" not in tables


def test_a_failed_auto_registration_is_reported_not_hidden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A silent DEBUG made 'workspace list' answer from stale rows without a word."""
    import logging

    from hydromodpy.core.logging import get_logger
    from hydromodpy.core.state import global_index as gi_mod

    def _boom(*_args: object, **_kwargs: object) -> GlobalIndex:
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(gi_mod, "GlobalIndex", _boom)

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    # The ``hydromodpy`` logger does not propagate, so caplog never sees it.
    parent = get_logger("hydromodpy")
    handler = _Capture(level=logging.WARNING)
    parent.addHandler(handler)
    try:
        assert gi_mod.auto_register_workspace(tmp_path / "ws") is None
    finally:
        parent.removeHandler(handler)

    warnings = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
    assert any("global index" in message.lower() for message in warnings)


def test_a_read_only_open_says_the_index_is_stale(tmp_path: Path) -> None:
    """A read-only handle never migrates: silence would pass stale rows off as fact."""
    import logging

    from hydromodpy.core.logging import get_logger

    ws = tmp_path / "ws_a"
    _seed_workspace(ws)
    index_db = _index_db(tmp_path)
    with GlobalIndex(index_db) as writer:
        writer.register_workspace(str(ws))

    conn = duckdb.connect(str(index_db))
    conn.execute("UPDATE schema_migrations SET checksum = 'stale' WHERE component = 'index'")
    conn.close()

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    parent = get_logger("hydromodpy")
    handler = _Capture(level=logging.WARNING)
    parent.addHandler(handler)
    try:
        with GlobalIndex(index_db, read_only=True) as reader:
            assert reader.read_only is True
    finally:
        parent.removeHandler(handler)

    assert any("stale" in record.getMessage().lower() for record in records)
