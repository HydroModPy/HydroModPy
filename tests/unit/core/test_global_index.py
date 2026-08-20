"""Unit tests for the machine-wide :class:`GlobalIndex`.

Each test passes an explicit ``tmp_path`` for the index DB so the global
machine state directory is never touched. Projects are seeded with the real
V1 catalog DDL via :func:`ensure_schema` so the federation sees the production
``v_simulation_summary`` view.

The admission rule these tests pin down: a workspace root expands to the marked
projects it holds, any other existing directory is one project root whether or
not it carries a marker yet, and a path that is not on disk is refused. The
middle clause is what lets the workflow register its project root during setup,
before the run writes ``project.toml`` or the index database.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.state.global_index import GlobalIndex, ProjectRecord
from hydromodpy.core.state.paths import (
    PROJECT_MARKER_FILENAME,
    PROJECTS_DIRNAME,
    WORKSPACE_TOML_FILENAME,
    catalog_path_for,
)
from hydromodpy.results.catalog.migrations import ensure_schema as _ensure_catalog


def _seed_project(
    project_root: Path,
    *,
    rows: list[tuple[str, str, str]] | None = None,
) -> Path:
    """Create a project index with rows in the ``simulations`` table.

    Each ``rows`` tuple is ``(sim_id, description, solver_code)``. ``sim_id``
    may be a short opaque label, it is hashed into a UUID before insertion
    so the catalog UUID column stays well-formed.
    """
    catalog_path = catalog_path_for(project_root)
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


def _seed_workspace(workspace_root: Path, *, projects: tuple[str, ...] = ()) -> list[Path]:
    """Create a workspace root holding ``projects``, each with its own catalog."""
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / WORKSPACE_TOML_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    (workspace_root / PROJECTS_DIRNAME).mkdir(exist_ok=True)
    roots: list[Path] = []
    for name in projects:
        project_root = workspace_root / PROJECTS_DIRNAME / name
        project_root.mkdir(parents=True, exist_ok=True)
        (project_root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
        _seed_project(project_root)
        roots.append(project_root)
    return roots


def _label_to_uuid(label: str) -> str:
    """Reverse of the UUID derivation used in :func:`_seed_project`."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, label))


def _index_db(tmp_path: Path) -> Path:
    return tmp_path / "state" / "index.duckdb"


def test_register_project_persists_record(tmp_path: Path) -> None:
    project = tmp_path / "cheze"
    _seed_project(project)
    with GlobalIndex(_index_db(tmp_path)) as index:
        project_ids = index.register(str(project), label="alpha")
        records = index.list_projects()

    assert len(project_ids) == 1
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, ProjectRecord)
    assert record.project_id == project_ids[0]
    assert record.project_uri == str(project.resolve())
    assert record.label == "alpha"


def test_a_workspace_root_never_lands_as_a_project_row(tmp_path: Path) -> None:
    """The two granularities must not be interchangeable rows.

    A workspace holds many projects and owns no index database, so registering
    its root must expand to the project roots it contains. Landing the
    workspace URI in the same column as a project URI is the confusion this
    guards against: the row would never attach and would shadow the projects.
    """
    workspace = tmp_path / "ws"
    alpha, beta = _seed_workspace(workspace, projects=("alpha", "beta"))

    with GlobalIndex(_index_db(tmp_path)) as index:
        from_workspace = index.register(str(workspace), label="ws")
        uris = {record.project_uri for record in index.list_projects()}
        again = index.register(str(alpha))

    assert len(from_workspace) == 2
    assert uris == {str(alpha.resolve()), str(beta.resolve())}
    assert str(workspace.resolve()) not in uris
    assert again == []


def test_expanding_a_workspace_adds_only_its_unknown_projects(tmp_path: Path) -> None:
    """A conflict on one project must not abort the rest of the expansion."""
    workspace = tmp_path / "ws"
    alpha, beta = _seed_workspace(workspace, projects=("alpha", "beta"))

    with GlobalIndex(_index_db(tmp_path)) as index:
        index.register(str(alpha))
        added = index.register(str(workspace))
        records = {r.project_uri: r.project_id for r in index.list_projects()}

    assert added == [records[str(beta.resolve())]]
    assert set(records) == {str(alpha.resolve()), str(beta.resolve())}


def test_register_a_workspace_without_project_registers_nothing(tmp_path: Path) -> None:
    """A freshly scaffolded workspace has nothing to federate yet."""
    workspace = tmp_path / "ws_empty"
    _seed_workspace(workspace)

    with GlobalIndex(_index_db(tmp_path)) as index:
        assert index.register(str(workspace)) == []
        assert index.list_projects() == []


def test_register_accepts_a_project_root_before_anything_is_written(tmp_path: Path) -> None:
    """A directory with no marker at all is still a project root.

    This is literally what the workflow setup step hands over: ``Workspace``
    creates the project directory, then the registration runs, and only the run
    that follows writes ``project.toml`` and the index database. Demanding a
    marker here would drop that registration without a word.
    """
    fresh = tmp_path / "brand_new"
    fresh.mkdir()
    assert not (fresh / PROJECT_MARKER_FILENAME).exists()
    assert not catalog_path_for(fresh).exists()

    with GlobalIndex(_index_db(tmp_path)) as index:
        assert len(index.register(str(fresh))) == 1
        assert [r.project_uri for r in index.list_projects()] == [str(fresh.resolve())]


def test_expanding_a_workspace_skips_the_unmarked_directories(tmp_path: Path) -> None:
    """Expansion is not a sweep of ``projects/``.

    Naming a directory is an explicit act and needs no marker. Expanding a
    workspace is not, so it only takes the entries that say they are projects,
    and a stray sibling folder stays out of the registry.
    """
    workspace = tmp_path / "ws"
    (alpha,) = _seed_workspace(workspace, projects=("alpha",))
    (workspace / PROJECTS_DIRNAME / "notes").mkdir()

    with GlobalIndex(_index_db(tmp_path)) as index:
        assert len(index.register(str(workspace))) == 1
        assert [r.project_uri for r in index.list_projects()] == [str(alpha.resolve())]


def test_register_refuses_a_missing_directory(tmp_path: Path) -> None:
    """A mistyped path is the one case a filesystem can call a mistake."""
    missing = tmp_path / "typo"
    with GlobalIndex(_index_db(tmp_path)) as index:
        with pytest.raises(FileNotFoundError, match="typo"):
            index.register(str(missing))
        assert index.list_projects() == []


def test_register_accepts_a_project_marked_before_its_first_run(tmp_path: Path) -> None:
    """``project.toml`` alone makes a project registrable, catalog or not."""
    project = tmp_path / "fresh"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")

    with GlobalIndex(_index_db(tmp_path)) as index:
        assert len(index.register(str(project))) == 1
        assert [r.project_uri for r in index.list_projects()] == [str(project.resolve())]


def test_register_normalizes_the_uri_to_one_row(tmp_path: Path) -> None:
    """The same directory spelled two ways stays a single registration."""
    project = tmp_path / "cheze"
    _seed_project(project)

    with GlobalIndex(_index_db(tmp_path)) as index:
        first = index.register(str(project))
        second = index.register(project.resolve().as_uri())
        records = index.list_projects()

    assert len(first) == 1
    assert second == []
    assert [record.project_uri for record in records] == [str(project.resolve())]


def test_register_is_idempotent_on_a_known_project(tmp_path: Path) -> None:
    project = tmp_path / "cheze"
    _seed_project(project)
    with GlobalIndex(_index_db(tmp_path)) as index:
        assert len(index.register(str(project))) == 1
        assert index.register(str(project)) == []


def test_unregister_removes_record_and_detaches(tmp_path: Path) -> None:
    project = tmp_path / "cheze"
    _seed_project(project, rows=[("s1", "desc", "modflow6")])
    with GlobalIndex(_index_db(tmp_path)) as index:
        (project_id,) = index.register(str(project))
        assert len(index.list_projects()) == 1

        df_before = index.find()
        assert not df_before.empty
        assert {str(s) for s in df_before["sim_id"]} == {_label_to_uuid("s1")}

        index.unregister(project_id)
        assert index.list_projects() == []

        df_after = index.find()
        assert df_after.empty


def test_find_federates_across_two_projects(tmp_path: Path) -> None:
    project_a = tmp_path / "naizin"
    project_b = tmp_path / "lez"
    _seed_project(
        project_a,
        rows=[("s_a1", "Bretagne run", "modflow6"), ("s_a2", "control", "modflow_nwt")],
    )
    _seed_project(project_b, rows=[("s_b1", "Normandie run", "modflow6")])

    with GlobalIndex(_index_db(tmp_path)) as index:
        (id_a,) = index.register(str(project_a), label="alpha")
        (id_b,) = index.register(str(project_b), label="beta")

        df = index.find(solver="modflow6")

    assert {str(s) for s in df["sim_id"]} == {_label_to_uuid("s_a1"), _label_to_uuid("s_b1")}
    assert set(df["project_id"].astype(str)) == {id_a, id_b}


def test_find_federates_the_projects_of_a_registered_workspace(tmp_path: Path) -> None:
    """Expansion is what makes a workspace registration queryable at all."""
    workspace = tmp_path / "ws"
    alpha, beta = _seed_workspace(workspace, projects=("alpha", "beta"))
    _seed_project(alpha, rows=[("s_alpha", "Bretagne run", "modflow6")])
    _seed_project(beta, rows=[("s_beta", "Normandie run", "modflow6")])

    with GlobalIndex(_index_db(tmp_path)) as index:
        index.register(str(workspace))
        df = index.find(solver="modflow6")

    assert {str(s) for s in df["sim_id"]} == {
        _label_to_uuid("s_alpha"),
        _label_to_uuid("s_beta"),
    }


def test_attach_is_read_only(tmp_path: Path) -> None:
    project = tmp_path / "cheze"
    _seed_project(project, rows=[("s1", "desc", "modflow6")])
    with GlobalIndex(_index_db(tmp_path)) as index:
        index.register(str(project))
        alias = next(iter(index._attached_aliases))
        with pytest.raises(duckdb.Error):
            index.connection.execute(f"DELETE FROM {alias}.simulations WHERE sim_id IS NOT NULL")


def test_prune_removes_dead_projects(tmp_path: Path) -> None:
    project_a = tmp_path / "naizin"
    project_b = tmp_path / "lez"
    _seed_project(project_a, rows=[("s_a", "live", "modflow6")])
    _seed_project(project_b, rows=[("s_b", "dead", "modflow6")])
    catalog_b = catalog_path_for(project_b)

    with GlobalIndex(_index_db(tmp_path)) as index:
        (id_a,) = index.register(str(project_a))
        (id_b,) = index.register(str(project_b))
        catalog_b.unlink()

        removed = index.prune()
        remaining = {r.project_id for r in index.list_projects()}

    assert removed == [id_b]
    assert remaining == {id_a}


def test_search_fts_finds_term(tmp_path: Path) -> None:
    project = tmp_path / "cheze"
    _seed_project(
        project,
        rows=[
            ("s1", "Bretagne hydrology baseline", "modflow6"),
            ("s2", "Pyrenees control run", "modflow_nwt"),
        ],
    )
    with GlobalIndex(_index_db(tmp_path)) as index:
        index.register(str(project))
        df = index.search("Bretagne")

    sim_ids = {str(s) for s in df["sim_id"]} if not df.empty else set()
    assert _label_to_uuid("s1") in sim_ids


def test_project_without_v_simulation_summary_is_skipped(tmp_path: Path) -> None:
    """A project without the V1 view must be skipped, not crash."""
    project = tmp_path / "cheze_empty"
    catalog_path = catalog_path_for(project)
    catalog_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(catalog_path))
    conn.execute("CREATE TABLE other_table (x INTEGER)")
    conn.close()

    with GlobalIndex(_index_db(tmp_path)) as index:
        (project_id,) = index.register(str(project))
        assert {r.project_id for r in index.list_projects()} == {project_id}
        assert index.find().empty


def test_index_path_uses_hmp_state_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The default index path resolves under ``$HMP_STATE_HOME/hydromodpy``."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "hmp_state"))
    from hydromodpy.core.state.global_index import _default_index_path

    expected = (tmp_path / "hmp_state").resolve() / "index.duckdb"
    assert _default_index_path() == expected


def test_read_only_open_returns_existing_records(tmp_path: Path) -> None:
    """``GlobalIndex(read_only=True)`` exposes search/find/list without writes."""
    project = tmp_path / "cheze"
    _seed_project(project, rows=[("s1", "Bretagne baseline run", "modflow6")])
    index_db = _index_db(tmp_path)

    with GlobalIndex(index_db) as writer:
        writer.register(str(project))

    with GlobalIndex(index_db, read_only=True) as reader:
        assert reader.read_only is True
        records = reader.list_projects()
        assert len(records) == 1
        df = reader.find(solver="modflow6")
        assert not df.empty
        assert {str(s) for s in df["sim_id"]} == {_label_to_uuid("s1")}


def test_read_only_register_raises_runtime_error(tmp_path: Path) -> None:
    """Mutations on a read-only handle raise ``RuntimeError``."""
    project = tmp_path / "cheze"
    _seed_project(project)
    with GlobalIndex(_index_db(tmp_path)) as writer:
        writer.register(str(project), label="seed")

    with GlobalIndex(_index_db(tmp_path), read_only=True) as ro:
        with pytest.raises(RuntimeError, match="read-only"):
            ro.register(str(project / "ignored"))
        with pytest.raises(RuntimeError, match="read-only"):
            ro.unregister("nonexistent")
        with pytest.raises(RuntimeError, match="read-only"):
            ro.prune()


def test_read_only_bootstraps_missing_db(tmp_path: Path) -> None:
    """A read-only open on a missing DB seeds an empty schema instead of crashing."""
    index_db = tmp_path / "state" / "missing.duckdb"
    with GlobalIndex(index_db, read_only=True) as ro:
        assert ro.read_only is True
        assert ro.list_projects() == []
        assert ro.find().empty


def test_contended_writer_falls_back_to_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When ``connect_with_retry`` keeps raising lock errors, we degrade to read-only."""
    import duckdb as _duckdb

    from hydromodpy.core.state import global_index as gi_mod

    # Seed a real DB first via a normal writer so the file exists.
    project = tmp_path / "cheze"
    _seed_project(project)
    index_db = _index_db(tmp_path)
    with GlobalIndex(index_db) as writer:
        writer.register(str(project))

    def _always_contended(*_args: object, **_kwargs: object) -> _duckdb.DuckDBPyConnection:
        raise _duckdb.IOException(
            "IO Error: Could not set lock on file: another process is holding the lock"
        )

    monkeypatch.setattr(gi_mod, "connect_with_retry", _always_contended)

    with GlobalIndex(index_db) as gi:
        assert gi.read_only is True
        assert len(gi.list_projects()) == 1


def test_non_contention_io_error_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-lock IO errors are NOT swallowed by the read-only fallback."""
    import duckdb as _duckdb

    from hydromodpy.core.state import global_index as gi_mod

    project = tmp_path / "cheze"
    _seed_project(project)
    index_db = _index_db(tmp_path)
    with GlobalIndex(index_db) as writer:
        writer.register(str(project))

    def _other_io_error(*_args: object, **_kwargs: object) -> _duckdb.DuckDBPyConnection:
        raise _duckdb.IOException("IO Error: Permission denied")

    monkeypatch.setattr(gi_mod, "connect_with_retry", _other_io_error)

    with pytest.raises(_duckdb.IOException):
        GlobalIndex(index_db)


def test_an_index_from_the_workspace_era_keeps_its_registrations(tmp_path: Path) -> None:
    """A pre-rename index must not be emptied by the rebuild that renames its table.

    The registry table went from ``workspaces`` to ``projects`` inside the SAME
    migration version, so an index written by an older install fails the checksum
    and is rebuilt. Its rows are the one piece of state no disk scan can recover,
    and the rebuild announces it keeps them, so the salvage must read the old
    table too. Seeding the new schema and corrupting the checksum cannot cover
    this: it never produces a database whose registry table has the old name.
    """
    project = tmp_path / "cheze"
    _seed_project(project, rows=[("alpha", "first run", "modflow6")])
    index_db = _index_db(tmp_path)
    index_db.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(index_db))
    conn.execute(
        "CREATE TABLE workspaces ("
        " workspace_id UUID DEFAULT uuid() PRIMARY KEY,"
        " workspace_uri VARCHAR UNIQUE NOT NULL,"
        " label VARCHAR,"
        " created_at TIMESTAMPTZ DEFAULT now())"
    )
    conn.execute(
        "INSERT INTO workspaces (workspace_uri, label) VALUES (?, ?)",
        [str(project.resolve()), "lab"],
    )
    conn.execute(
        "CREATE TABLE schema_migrations ("
        " version INTEGER, component VARCHAR, slug VARCHAR,"
        " applied_at TIMESTAMPTZ DEFAULT now(), checksum VARCHAR)"
    )
    conn.execute(
        "INSERT INTO schema_migrations (version, component, slug, checksum)"
        " VALUES (1, 'index', 'initial', 'checksum-of-the-workspace-era-ddl')"
    )
    conn.execute("CHECKPOINT")
    conn.close()

    with GlobalIndex(index_db) as gi:
        assert [(p.project_uri, p.label) for p in gi.list_projects()] == [
            (str(project.resolve()), "lab")
        ]


def test_a_stale_schema_ledger_is_rebuilt_not_fatal(tmp_path: Path) -> None:
    """The registry is reconstructible: an unmigratable ledger must not block boot."""
    project = tmp_path / "cheze"
    _seed_project(project, rows=[("alpha", "first run", "modflow6")])
    index_db = _index_db(tmp_path)
    with GlobalIndex(index_db) as writer:
        writer.register(str(project), label="lab")

    conn = duckdb.connect(str(index_db))
    conn.execute("UPDATE schema_migrations SET checksum = 'stale' WHERE component = 'index'")
    conn.execute("CREATE TABLE dropped_by_an_older_version (x INTEGER)")
    conn.close()

    with GlobalIndex(index_db) as gi:
        assert gi.read_only is False
        assert [(p.project_uri, p.label) for p in gi.list_projects()] == [
            (str(project.resolve()), "lab")
        ]
        assert len(gi.find()) == 1
        tables = {row[0] for row in gi.connection.execute("SHOW TABLES").fetchall()}
        assert "dropped_by_an_older_version" not in tables


def test_auto_registration_shares_the_register_granularity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The automatic path must produce the rows the manual one would."""
    from hydromodpy.core.state.global_index import auto_register_projects

    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state_home"))
    workspace = tmp_path / "ws"
    alpha, beta = _seed_workspace(workspace, projects=("alpha", "beta"))

    created = auto_register_projects(workspace, label="ws")
    again = auto_register_projects(workspace, label="ws")

    assert len(created) == 2
    assert again == []
    with GlobalIndex() as gi:
        assert {r.project_uri for r in gi.list_projects()} == {
            str(alpha.resolve()),
            str(beta.resolve()),
        }


def test_auto_registration_shares_the_register_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One contract: what ``register`` refuses, the hook reports instead of raising.

    The refusal is not a fact about the tree the caller can shrug off, it is a
    project missing from ``hmp workspace list``, so it goes out at WARNING like
    every other failed registration rather than into a debug log.
    """
    import logging

    from hydromodpy.core.logging import get_logger
    from hydromodpy.core.state.global_index import auto_register_projects

    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state_home"))
    missing = tmp_path / "typo"

    with GlobalIndex() as gi:
        with pytest.raises(FileNotFoundError):
            gi.register(str(missing))

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    parent = get_logger("hydromodpy")
    handler = _Capture(level=logging.WARNING)
    parent.addHandler(handler)
    try:
        assert auto_register_projects(missing) == []
    finally:
        parent.removeHandler(handler)

    assert [r.levelno for r in records] == [logging.WARNING]
    assert "typo" in records[0].getMessage()
    with GlobalIndex() as gi:
        assert gi.list_projects() == []


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
        assert gi_mod.auto_register_projects(tmp_path / "ws") == []
    finally:
        parent.removeHandler(handler)

    warnings = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
    assert any("global index" in message.lower() for message in warnings)


def test_a_read_only_open_says_the_index_is_stale(tmp_path: Path) -> None:
    """A read-only handle never migrates: silence would pass stale rows off as fact."""
    import logging

    from hydromodpy.core.logging import get_logger

    project = tmp_path / "cheze"
    _seed_project(project)
    index_db = _index_db(tmp_path)
    with GlobalIndex(index_db) as writer:
        writer.register(str(project))

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
