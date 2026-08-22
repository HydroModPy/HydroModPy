"""A calibration phase chain survives the index: on disk first, in SQL after.

A calibration run in phases writes one session per phase. What links them
lives in ``session.json``, so ``hmp catalog reindex`` gives the chain back
instead of flattening it into unrelated calibrations.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.migrations import (
    apply_migrations,
    current_version,
    discover_migrations,
    target_version,
)
from hydromodpy.results.catalog.reindex import rebuild_index
from hydromodpy.results.session_journal import (
    SessionJournal,
    SessionTrial,
    read_descriptor,
    session_dirs_for,
)
from hydromodpy.results.storage.contract import SESSION_DESCRIPTOR_FILENAME

CHAIN_COLUMNS = ("parent_session_id", "root_session_id", "phase_name", "phase_index")

SEARCH_SPACE = {"K_aquifer": {"bounds": [1e-6, 1e-3], "transform": "log"}}


def _start(project_root, session_id: str, **chain) -> SessionJournal:
    """Open a journal for one phase of the synthetic calibration."""
    return SessionJournal.start(
        project_root,
        session_id=session_id,
        project="demo",
        method="optuna",
        objective_name="rmse",
        search_space=SEARCH_SPACE,
        config={"method": "optuna", "variable": "head"},
        started_at=datetime.now(UTC),
        **chain,
    )


def _trial(number: int, objective: float) -> SessionTrial:
    """One completed trial of the synthetic session."""
    return SessionTrial(
        trial=number,
        parameters={"K_aquifer": {"value": 1e-4 * (number + 1)}},
        objective_value=objective,
        status="completed",
        duration_s=0.5,
        metrics={"rmse": objective},
    )


@pytest.fixture
def coarse_id() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def refine_id() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def project(tmp_path, coarse_id, refine_id):
    """A project holding a two-phase calibration: a sweep, then a refinement."""
    root = tmp_path / "demo"
    root.mkdir()
    coarse = _start(root, coarse_id, phase_name="coarse", phase_index=0, root_session_id=coarse_id)
    coarse.append(_trial(0, 0.42))
    coarse.finish(
        status="completed",
        duration_s=1.0,
        ended_at=datetime.now(UTC),
        best_trial=0,
        best_objective=0.42,
    )
    refine = _start(
        root,
        refine_id,
        parent_session_id=coarse_id,
        root_session_id=coarse_id,
        phase_name="refine",
        phase_index=1,
    )
    refine.append(_trial(0, 0.19))
    refine.finish(
        status="completed",
        duration_s=2.0,
        ended_at=datetime.now(UTC),
        best_trial=0,
        best_objective=0.19,
    )
    return root


def _directory_of(project_root, session_id: str):
    """Return the session directory holding ``session_id``."""
    for directory in session_dirs_for(project_root):
        if read_descriptor(directory).session_id == session_id:
            return directory
    raise AssertionError(f"no session directory for {session_id}")


# -- what the journal writes ------------------------------------------------


def test_the_descriptor_carries_the_phase_chain(project, coarse_id, refine_id):
    directory = _directory_of(project, refine_id)

    payload = json.loads((directory / SESSION_DESCRIPTOR_FILENAME).read_text(encoding="utf-8"))
    assert payload["parent_session_id"] == coarse_id
    assert payload["root_session_id"] == coarse_id
    assert payload["phase_name"] == "refine"
    assert payload["phase_index"] == 1

    descriptor = read_descriptor(directory)
    assert descriptor.parent_session_id == coarse_id
    assert descriptor.root_session_id == coarse_id
    assert descriptor.phase_name == "refine"
    assert descriptor.phase_index == 1


def test_the_first_phase_declares_a_root_and_no_parent(project, coarse_id):
    descriptor = read_descriptor(_directory_of(project, coarse_id))

    assert descriptor.parent_session_id is None
    assert descriptor.root_session_id == coarse_id
    assert (descriptor.phase_name, descriptor.phase_index) == ("coarse", 0)


def test_the_outcome_does_not_erase_the_chain(project, refine_id):
    """``finish`` rewrites the descriptor; the chain must come through it."""
    descriptor = read_descriptor(_directory_of(project, refine_id))

    assert descriptor.status == "completed"
    assert descriptor.best_objective == pytest.approx(0.19)
    assert descriptor.parent_session_id is not None


def test_a_standalone_session_declares_an_empty_chain(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    journal = _start(root, uuid.uuid4().hex)

    descriptor = read_descriptor(journal.directory)

    assert descriptor.parent_session_id is None
    assert descriptor.root_session_id is None
    assert descriptor.phase_name is None
    assert descriptor.phase_index is None


def test_a_descriptor_written_without_the_chain_keys_still_reads(tmp_path):
    """A session.json from before the chain existed must not become illegible."""
    root = tmp_path / "demo"
    root.mkdir()
    journal = _start(root, uuid.uuid4().hex, phase_name="coarse", phase_index=0)
    target = journal.directory / SESSION_DESCRIPTOR_FILENAME
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["journal_version"] = 1
    for key in CHAIN_COLUMNS:
        del payload[key]
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    descriptor = read_descriptor(journal.directory)

    assert descriptor.objective_name == "rmse"
    assert descriptor.parent_session_id is None
    assert descriptor.root_session_id is None
    assert descriptor.phase_name is None
    assert descriptor.phase_index is None


# -- what the rebuild gives back --------------------------------------------


def _chain_rows(project_root) -> dict[str, tuple]:
    """Return the chain columns of every indexed session, keyed by session id."""
    with Catalog(project_root, read_only=True) as catalog:
        rows = catalog.backend.fetch_all(
            "SELECT CAST(session_id AS VARCHAR), CAST(parent_session_id AS VARCHAR), "
            "CAST(root_session_id AS VARCHAR), phase_name, phase_index "
            "FROM calibration_sessions"
        )
    return {uuid.UUID(row[0]).hex: row[1:] for row in rows}


def test_the_rebuild_puts_the_phase_chain_back_in_the_index(project, coarse_id, refine_id):
    report = rebuild_index(project)

    assert report.rows["calibration_sessions"] == 2
    rows = _chain_rows(project)
    assert uuid.UUID(rows[refine_id][0]).hex == coarse_id
    assert uuid.UUID(rows[refine_id][1]).hex == coarse_id
    assert rows[refine_id][2] == "refine"
    assert rows[refine_id][3] == 1
    assert rows[coarse_id][0] is None
    assert uuid.UUID(rows[coarse_id][1]).hex == coarse_id
    assert rows[coarse_id][2] == "coarse"
    assert rows[coarse_id][3] == 0


def test_two_rebuilds_describe_the_same_chain(project):
    rebuild_index(project)
    first = _chain_rows(project)

    rebuild_index(project)

    assert len(first) == 2
    assert _chain_rows(project) == first


# -- what the garbage collector must not take -------------------------------


def _insert_dangling_session(catalog: Catalog, session_id: str, **chain) -> None:
    """Insert one finished session row whose best run is already gone."""
    catalog.backend.execute(
        "INSERT INTO calibration_sessions "
        "(session_id, project, method, objective_name, config, started_at, "
        " best_sim_id, parent_session_id) "
        "VALUES (?, 'demo', 'optuna', 'rmse', '{}', current_timestamp, ?, ?)",
        [
            uuid.UUID(session_id),
            uuid.UUID(uuid.uuid4().hex),
            None if chain.get("parent") is None else uuid.UUID(chain["parent"]),
        ],
    )


@pytest.fixture
def catalog(tmp_path):
    cat = Catalog(tmp_path / "workspace")
    try:
        yield cat
    finally:
        cat.close()


def test_a_parent_session_is_not_an_orphan_while_a_child_continues_it(
    catalog, coarse_id, refine_id
):
    _insert_dangling_session(catalog, coarse_id)
    _insert_dangling_session(catalog, refine_id, parent=coarse_id)

    orphans = {uuid.UUID(sid).hex for sid in catalog.list_orphan_calibration_sessions()}

    assert coarse_id not in orphans
    assert refine_id in orphans


def test_the_parent_becomes_an_orphan_once_no_child_references_it(catalog, coarse_id, refine_id):
    _insert_dangling_session(catalog, coarse_id)
    _insert_dangling_session(catalog, refine_id, parent=coarse_id)
    catalog.backend.execute(
        "DELETE FROM calibration_sessions WHERE session_id = ?", [uuid.UUID(refine_id)]
    )

    orphans = {uuid.UUID(sid).hex for sid in catalog.list_orphan_calibration_sessions()}

    assert orphans == {coarse_id}


# -- what the schema declares -----------------------------------------------


@pytest.fixture
def migrated_db(tmp_path) -> Path:
    """A catalog database migrated to the bundled target version."""
    db_path = tmp_path / "index.duckdb"
    apply_migrations(db_path)
    return db_path


def _columns(db_path: Path, table: str) -> set[str]:
    """Return the column names of ``table``."""
    connection = duckdb.connect(str(db_path))
    try:
        rows = connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]
        ).fetchall()
    finally:
        connection.close()
    return {str(row[0]) for row in rows}


def test_the_migration_brings_a_fresh_database_to_the_target_version(migrated_db):
    connection = duckdb.connect(str(migrated_db))
    try:
        assert current_version(connection) == target_version()
    finally:
        connection.close()
    assert set(CHAIN_COLUMNS) <= _columns(migrated_db, "calibration_sessions")


def test_the_chain_columns_are_indexed(migrated_db):
    connection = duckdb.connect(str(migrated_db))
    try:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT index_name FROM duckdb_indexes() WHERE table_name = 'calibration_sessions'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert {"ix_cal_session_parent", "ix_cal_session_root"} <= names


def test_a_database_stuck_at_v1_reaches_the_target_version(tmp_path):
    """The chain columns are added by ALTER, on a table that already has a row."""
    only_v1 = tmp_path / "v1"
    only_v1.mkdir()
    initial = next(m for m in discover_migrations() if m.version == 1)
    (only_v1 / initial.sql_path.name).write_text(initial.upgrade_sql, encoding="utf-8")
    db_path = tmp_path / "index.duckdb"
    assert apply_migrations(db_path, only_v1) == 1
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            "INSERT INTO calibration_sessions "
            "(session_id, project, method, objective_name, config, started_at) "
            "VALUES (?, 'demo', 'optuna', 'rmse', '{}', current_timestamp)",
            [uuid.uuid4()],
        )
    finally:
        connection.close()

    assert apply_migrations(db_path) == target_version()

    connection = duckdb.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT parent_session_id, root_session_id, phase_name, phase_index "
            "FROM calibration_sessions"
        ).fetchone()
    finally:
        connection.close()
    assert row == (None, None, None, None)
