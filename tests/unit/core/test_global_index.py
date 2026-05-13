"""Unit tests for the machine-wide :class:`GlobalIndex`.

Each test passes an explicit ``tmp_path`` for the index DB so the global
machine state directory is never touched. Workspaces are seeded as bare
DuckDB files matching the v2 layout (``<workspace>/catalog.duckdb`` with a
``simulations`` table).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.state.global_index import GlobalIndex, WorkspaceRecord
from hydromodpy.core.state.paths import CATALOG_FILENAME


def _seed_workspace(
    workspace: Path,
    *,
    rows: list[tuple[str, str, str]] | None = None,
    with_description: bool = True,
) -> Path:
    """Create a v2-style ``catalog.duckdb`` with one ``simulations`` table.

    Each ``rows`` tuple is ``(sim_id, description, solver)``.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    catalog_path = workspace / CATALOG_FILENAME
    conn = duckdb.connect(str(catalog_path))
    try:
        if with_description:
            conn.execute(
                "CREATE TABLE simulations ("
                "sim_id VARCHAR PRIMARY KEY, "
                "description VARCHAR, "
                "solver VARCHAR)"
            )
        else:
            conn.execute("CREATE TABLE simulations (sim_id VARCHAR PRIMARY KEY, solver VARCHAR)")
        if rows:
            if with_description:
                conn.executemany(
                    "INSERT INTO simulations (sim_id, description, solver) VALUES (?, ?, ?)",
                    rows,
                )
            else:
                conn.executemany(
                    "INSERT INTO simulations (sim_id, solver) VALUES (?, ?)",
                    [(r[0], r[2]) for r in rows],
                )
    finally:
        conn.close()
    return catalog_path


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
    _seed_workspace(ws, rows=[("s1", "desc", "mf6")])
    with GlobalIndex(_index_db(tmp_path)) as index:
        workspace_id = index.register_workspace(str(ws))
        assert len(index.list_workspaces()) == 1

        df_before = index.find()
        assert not df_before.empty
        assert df_before["sim_id"].tolist() == ["s1"]

        index.unregister_workspace(workspace_id)
        assert index.list_workspaces() == []

        df_after = index.find()
        assert df_after.empty


def test_find_federates_across_two_workspaces(tmp_path: Path) -> None:
    ws_a = tmp_path / "ws_a"
    ws_b = tmp_path / "ws_b"
    _seed_workspace(ws_a, rows=[("s_a1", "Bretagne run", "mf6"), ("s_a2", "control", "nwt")])
    _seed_workspace(ws_b, rows=[("s_b1", "Normandie run", "mf6")])

    with GlobalIndex(_index_db(tmp_path)) as index:
        id_a = index.register_workspace(str(ws_a), label="alpha")
        id_b = index.register_workspace(str(ws_b), label="beta")

        df = index.find(solver="mf6")

    assert set(df["sim_id"]) == {"s_a1", "s_b1"}
    workspace_ids = set(df["workspace_id"].astype(str))
    assert workspace_ids == {id_a, id_b}


def test_attach_is_read_only(tmp_path: Path) -> None:
    ws = tmp_path / "ws_a"
    _seed_workspace(ws, rows=[("s1", "desc", "mf6")])
    with GlobalIndex(_index_db(tmp_path)) as index:
        index.register_workspace(str(ws))
        alias = next(iter(index._attached_aliases))
        with pytest.raises(duckdb.Error):
            index.connection.execute(f"INSERT INTO {alias}.simulations VALUES ('s2', 'x', 'mf6')")


def test_prune_removes_dead_workspaces(tmp_path: Path) -> None:
    ws_a = tmp_path / "ws_a"
    ws_b = tmp_path / "ws_b"
    _seed_workspace(ws_a, rows=[("s_a", "live", "mf6")])
    _seed_workspace(ws_b, rows=[("s_b", "dead", "mf6")])
    catalog_b = ws_b / CATALOG_FILENAME

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
            ("s1", "Bretagne hydrology baseline", "mf6"),
            ("s2", "Pyrenees control run", "nwt"),
        ],
    )
    with GlobalIndex(_index_db(tmp_path)) as index:
        index.register_workspace(str(ws))
        df = index.search("Bretagne")

    sim_ids = set(df["sim_id"]) if not df.empty else set()
    assert "s1" in sim_ids


def test_workspace_without_simulations_table_is_skipped(tmp_path: Path) -> None:
    """A freshly created workspace (no ``simulations`` table) must not crash."""
    ws = tmp_path / "ws_empty"
    ws.mkdir(parents=True)
    conn = duckdb.connect(str(ws / CATALOG_FILENAME))
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
    _seed_workspace(ws, rows=[("s1", "Bretagne baseline run", "mf6")])
    index_db = _index_db(tmp_path)

    with GlobalIndex(index_db) as writer:
        writer.register_workspace(str(ws))

    with GlobalIndex(index_db, read_only=True) as reader:
        assert reader.read_only is True
        records = reader.list_workspaces()
        assert len(records) == 1
        df = reader.find(solver="mf6")
        assert not df.empty
        assert df["sim_id"].tolist() == ["s1"]


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
