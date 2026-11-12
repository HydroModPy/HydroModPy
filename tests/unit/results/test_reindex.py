"""The catalog index is a diff of the tree: what is on disk is what gets indexed, only what moved
is rewritten, and one writer at a time swaps the file. Sizes are in bytes, times in seconds.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

import hydromodpy.results.catalog.index_file as index_file_module
import hydromodpy.results.catalog.indexer as indexer_module
from hydromodpy.core.io.db_retry import HMP_DUCKDB_BLOCK_SIZE
from hydromodpy.core.io.lock_file import LockFile
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import catalog_path_for, runs_dir_for
from hydromodpy.results.annotations import Annotations, write_annotations
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.index_file import (
    INDEX_ALIAS,
    index_lock,
    index_lock_path,
    new_staging,
    open_index,
    open_staging,
    publish_staging,
)
from hydromodpy.results.catalog.index_schema import (
    INDEX_META_TABLE,
    INDEX_SCHEMA_VERSION,
    META_KNOWN_ISSUES_DIGEST,
    META_RULE_VERSION,
    META_SCHEMA_VERSION,
)
from hydromodpy.results.catalog.indexer import (
    index_after_run,
    index_is_current,
    index_new_runs,
    known_issues_digest,
    rebuild_index,
    reindex_if_indexed,
    scan_tree,
)
from hydromodpy.results.catalog.views import V_CASES_FIXED_COLUMNS
from hydromodpy.results.record.checks import CalibratedBy
from hydromodpy.results.record.manifest import read_seal
from hydromodpy.results.session.descriptor import BestCase, BestTrial, write_session
from hydromodpy.results.session.journal import append_trial
from hydromodpy.results.storage.contract import (
    RUN_ATTEMPTS_DIRNAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
    RUN_PURGED_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.digests import path_size_bytes
from hydromodpy.results.validity_rules import RULE_VERSION
from hydromodpy.schema.changes import REGISTER, Bug
from tests._helpers.sealed_runs import (
    CONFIG_HASH,
    make_project,
    seal_run,
    write_attempt,
    write_session_dir,
)
from tests._helpers.session_documents import joint_session, joint_trial, trial_line

SESSION_ID = "sess0001"


@pytest.fixture
def project(tmp_path) -> Path:
    # Two sealed runs, a failed attempt, a running one, a session with a promoted run and a kept trial.
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    seal_run(root, "beta", parameters={"K": 2e-5, "Sy": 0.02}, tags=("pinned",))
    write_attempt(root, "runs/gamma", status="failed")
    write_attempt(root, "runs/delta", status="running", heartbeat_age_s=5)
    promoted = seal_run(
        root,
        "calib",
        calibrated_by=CalibratedBy(
            session_id=SESSION_ID, phase="steady_k", trial=2, session_status="completed"
        ),
    )
    seal_run(root, "calib_t2", rel_dir="sessions/calib/trials/0002")
    write_session_dir(
        root,
        "calib",
        session_id=SESSION_ID,
        best_trial=2,
        best_sim_id=promoted,
        best_rel_dir="runs/calib",
    )
    return root


def _rows(root: Path, sql: str) -> list[tuple]:
    with Catalog(root) as catalog:
        return sorted(tuple(row) for row in catalog.backend.fetch_all(sql))


def _restamp(root: Path, key: str, value: str) -> None:
    # Change one index_meta value of the published index, the way a pass writes it.
    index_path = catalog_path_for(root)
    with index_lock(root) as lock:
        staging = new_staging(index_path, copy_of=index_path)
        connection = open_staging(staging)
        connection.execute(f"UPDATE {INDEX_META_TABLE} SET value = ? WHERE key = ?", [value, key])
        connection.execute("CHECKPOINT")
        connection.close()
        publish_staging(staging, index_path, lock)


def _block_size(root: Path) -> int:
    connection = open_index(root)
    try:
        row = connection.execute(
            "SELECT block_size FROM pragma_database_size() WHERE database_name = ?",
            [INDEX_ALIAS],
        ).fetchone()
    finally:
        connection.close()
    return int(row[0])


def _hold_the_lock_from_another_process(root: Path) -> None:
    # A fresh lock in the name of a live process of this host that is not this one.
    path = index_lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": os.getppid(), "host": socket.gethostname(), "created": time.time()}),
        encoding="utf-8",
    )


@pytest.fixture
def warnings_said(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    # caplog must see the hydromodpy warnings, which stop propagating by default.
    parent = get_logger("hydromodpy")
    propagate = parent.propagate
    parent.propagate = True
    caplog.set_level(logging.WARNING, logger="hydromodpy")
    try:
        yield caplog
    finally:
        parent.propagate = propagate


def _index_content(root: Path, tables: tuple[str, ...]) -> dict[str, list[str]]:
    with Catalog(root) as catalog:
        return {
            table: sorted(str(row) for row in catalog.backend.fetch_all(f"SELECT * FROM {table}"))
            for table in tables
        }


def test_cases_and_runs_of_a_tree(project):
    report = rebuild_index(project)

    assert report.full
    assert set(report.indexed) == {
        "runs/alpha",
        "runs/beta",
        "runs/calib",
        "runs/gamma",
        "runs/delta",
        "sessions/calib/trials/0002",
    }
    assert report.sessions == ("sessions/calib",)
    assert report.skipped == ()
    assert _rows(project, "SELECT rel_dir, kind, status FROM cases") == [
        ("runs/alpha", "run", "completed"),
        ("runs/beta", "run", "completed"),
        ("runs/calib", "run", "completed"),
        ("runs/delta", "run", "running"),
        ("runs/gamma", "run", "failed"),
        ("sessions/calib", "session", "completed"),
        ("sessions/calib/trials/0002", "trial", "completed"),
    ]
    assert _rows(project, "SELECT name, rel_dir FROM simulations") == [
        ("alpha", "runs/alpha"),
        ("beta", "runs/beta"),
        ("calib", "runs/calib"),
        ("calib_t2", "sessions/calib/trials/0002"),
    ]


def test_attempt_without_a_seal(project):
    rebuild_index(project)

    rows = _rows(
        project,
        "SELECT rel_dir, status, error_type, error_message, sim_id FROM cases "
        "WHERE rel_dir = 'runs/gamma'",
    )
    assert rows == [
        ("runs/gamma", "failed", "SolverError", "mf6 did not converge at stress period 51", None)
    ]
    assert _rows(project, "SELECT rel_dir FROM simulations WHERE rel_dir = 'runs/gamma'") == []


def test_stale_pulse(project):
    write_attempt(project, "runs/epsilon", status="running", heartbeat_age_s=3600)

    rebuild_index(project)

    assert _rows(project, "SELECT status FROM cases WHERE rel_dir = 'runs/epsilon'") == [("stale",)]


def test_directory_without_outcome_or_manifest(project):
    (runs_dir_for(project) / "scratch_only").mkdir()
    (runs_dir_for(project) / "scratch_only" / "note.txt").write_text("x")

    report = rebuild_index(project)

    assert "runs/scratch_only" not in report.indexed
    assert report.skipped == ()


def test_seal_without_its_index_row(project):
    (runs_dir_for(project) / "beta" / TABLES_DIRNAME / "simulation.parquet").unlink()

    report = rebuild_index(project)

    assert [item.rel_dir for item in report.skipped] == ["runs/beta"]
    assert "simulation.parquet" in report.skipped[0].reason
    assert "runs/beta" not in report.indexed


def test_manifest_of_another_run(project):
    beta = runs_dir_for(project) / "beta"
    alpha_manifest = (runs_dir_for(project) / "alpha" / RUN_MANIFEST_FILENAME).read_text()
    (beta / RUN_MANIFEST_FILENAME).write_text(alpha_manifest)

    report = rebuild_index(project)

    assert [item.rel_dir for item in report.skipped] == ["runs/beta"]
    assert "two identities" in report.skipped[0].reason


def test_label_at_indexing(project):
    rebuild_index(project)

    rows = _rows(project, "SELECT name, label, rule_version FROM simulations")
    assert rows == [
        ("alpha", "exploratory", "3"),
        ("beta", "exploratory", "3"),
        ("calib", "calibrated", "3"),
        ("calib_t2", "exploratory", "3"),
    ]
    assert _rows(project, "SELECT COUNT(*) FROM simulations WHERE label_date IS NULL") == [(0,)]


def test_label_of_a_diverged_run(tmp_path):
    root = make_project(tmp_path / "demo")
    seal_run(root, "diverged", converged=False)

    rebuild_index(root)

    assert _rows(root, "SELECT label, label_reasons FROM simulations") == [
        ("failed", "solver did not converge")
    ]


def test_known_issue_declasses_the_run(tmp_path):
    root = make_project(tmp_path / "demo")
    seal_run(root, "old", hydromodpy_version="1.9.0")

    rebuild_index(root)

    (label, issues) = _rows(root, "SELECT label, known_issues FROM simulations")[0]
    assert label == "exploratory"
    assert issues


def test_session_trials_and_phases(project):
    rebuild_index(project)

    assert _rows(
        project,
        "SELECT session_id, case_id, n_trials, best_trial, status FROM calibration_sessions",
    ) == [(SESSION_ID, "calib", 2, 2, "completed")]
    assert _rows(project, "SELECT trial, phase, status FROM calibration_iterations") == [
        (1, "steady_k", "completed"),
        (2, "steady_k", "completed"),
    ]
    assert _rows(project, "SELECT name, phase_index FROM calibration_phases") == [("steady_k", 0)]
    assert _rows(project, "SELECT session_id FROM simulations WHERE name = 'calib'") == [
        (SESSION_ID,)
    ]


def test_session_cases_and_trial_cases(project):
    rebuild_index(project)

    assert _rows(
        project,
        "SELECT case_id, site, config_hash, best_rel_dir FROM calibration_session_cases",
    ) == [("calib", "J0014010", CONFIG_HASH, "runs/calib")]
    assert _rows(
        project,
        "SELECT trial, case_id, status, from_cache, rel_dir FROM calibration_trial_cases",
    ) == [(1, "calib", "completed", False, None), (2, "calib", "completed", False, "runs/calib")]
    assert _rows(project, "SELECT site, sim_id IS NOT NULL FROM cases WHERE kind = 'session'") == [
        ("J0014010", True)
    ]


def test_joint_session(tmp_path):
    root = make_project(tmp_path / "demo")
    directory = root / "sessions" / "joint"
    directory.mkdir(parents=True)
    best = BestTrial(
        trial=1, cost=0.4, cases={"a": BestCase(sim_id="x" * 32, cost=0.3), "b": BestCase(cost=0.5)}
    )
    write_session(directory, joint_session(best=best))
    append_trial(directory, joint_trial())

    rebuild_index(root)

    assert _rows(root, "SELECT site, sim_id FROM cases WHERE kind = 'session'") == [(None, None)]
    assert _rows(
        root, "SELECT case_id, site, best_sim_id, best_cost FROM calibration_session_cases"
    ) == [
        ("a", "S1", "x" * 32, 0.3),
        ("b", "S2", None, 0.5),
    ]
    assert _rows(root, "SELECT trial, case_id, cost FROM calibration_trial_cases") == [
        (1, "a", 0.3),
        (1, "b", 0.5),
    ]
    assert _rows(root, "SELECT cost FROM calibration_iterations") == [(0.4,)]
    ((sites, windows),) = _rows(root, "SELECT sites, windows FROM calibration_sessions")
    assert json.loads(sites) == ["S1", "S2"]
    assert set(json.loads(windows)["calibration"]["by_case"]) == {"a", "b"}


def test_session_with_a_proposed_trial(tmp_path):
    # A stopped or running session journals trials that only have their
    # proposed line, with no started_at: they are not iterations yet.
    root = make_project(tmp_path / "demo")
    write_session_dir(root, "calib", session_id="calib001", status="running")
    proposed = trial_line(3, cost=None, status="running", started_at=None, event="proposed")
    append_trial(root / "sessions" / "calib", proposed.model_copy(update={"cases": {}}))

    rebuild_index(root)

    assert _rows(root, "SELECT session_id, n_trials FROM calibration_sessions") == [("calib001", 3)]
    assert _rows(root, "SELECT trial FROM calibration_iterations ORDER BY trial") == [(1,), (2,)]


def test_session_root_search(tmp_path):
    root = make_project(tmp_path / "demo")
    closed_with = {"bracket": [1e-7, 1e-5], "roots": [2.1e-6, 2.3e-6]}
    write_session_dir(root, "bisect", session_id="bisect01", root_search=closed_with)
    write_session_dir(root, "tpe", session_id="tpe00001")

    rebuild_index(root)

    rows = _rows(root, "SELECT session_id, root_search FROM calibration_sessions")
    assert [(sid, None if raw is None else json.loads(raw)) for sid, raw in rows] == [
        ("bisect01", closed_with),
        ("tpe00001", None),
    ]


def test_sites_table(project):
    rebuild_index(project)

    assert _rows(project, "SELECT site, gauge, n_cases, n_runs FROM sites") == [
        ("J0014010", "J0014010", 6, 4)
    ]


def test_tags(project):
    rebuild_index(project)

    assert _rows(
        project,
        "SELECT s.name, t.tag FROM tags t JOIN simulations s ON s.sim_id = t.sim_id",
    ) == [("beta", "pinned")]


def test_v_cases(project):
    rebuild_index(project)

    rows = _rows(project, "SELECT rel_dir, status, label, nse FROM v_cases")
    assert ("runs/calib", "completed", "calibrated", 0.71) in rows
    assert ("runs/gamma", "failed", None, None) in rows
    assert ("sessions/calib", "completed", None, None) in rows


def test_v_cases_parameter_columns(project):
    seal_run(project, "odd", parameters={"K": 3e-5, "hk zone 1": 2.0, "status": 3.0})

    rebuild_index(project)

    with Catalog(project) as catalog:
        columns = [str(row[0]) for row in catalog.backend.fetch_all("DESCRIBE v_cases")]
    assert columns == [*V_CASES_FIXED_COLUMNS, "K", "Sy"]
    assert _rows(project, "SELECT name, K, Sy FROM v_cases WHERE name IN ('beta', 'odd')") == [
        ("beta", 2e-5, 0.02),
        ("odd", 3e-5, None),
    ]
    assert _rows(project, "SELECT status FROM v_cases WHERE name = 'odd'") == [("completed",)]
    assert _rows(
        project,
        "SELECT p.param_key FROM v_params_long p JOIN simulations s ON s.sim_id = p.sim_id "
        "WHERE s.name = 'odd'",
    ) == [("K",), ("hk zone 1",), ("status",)]


def test_best_calibrated_run_per_site(project):
    seal_run(
        project,
        "calib_b",
        site="J0014020",
        parameters={"K": 4e-5},
        nse=0.8,
        calibrated_by=CalibratedBy(
            session_id=SESSION_ID, phase="steady_k", trial=2, session_status="completed"
        ),
    )

    rebuild_index(project)

    rows = _rows(
        project,
        "SELECT site, arg_max(case_id, nse), max(nse), arg_max(K, nse) FROM v_cases "
        "WHERE label = 'calibrated' AND metric_rule_version = '1' GROUP BY site",
    )
    assert rows == [("J0014010", "calib", 0.71, 1e-5), ("J0014020", "calib_b", 0.8, 4e-5)]


def test_two_rebuilds_agree(project):
    tables = (
        "simulations",
        "parameters",
        "metrics",
        "runs_environment",
        "geographic_metadata",
        "tags",
        "attempts",
        "calibration_sessions",
        "calibration_iterations",
    )
    rebuild_index(project)
    first = _index_content(project, tables)

    rebuild_index(project)

    assert _index_content(project, tables) == first


def test_unchanged_tree_writes_nothing(project):
    rebuild_index(project)
    before = catalog_path_for(project).stat().st_ino

    report = index_new_runs(project)

    assert report.unchanged
    assert not report.full
    assert catalog_path_for(project).stat().st_ino == before
    assert index_is_current(project)


def test_new_run_is_the_only_one_written(project):
    rebuild_index(project)
    stamps = dict(_rows(project, "SELECT rel_dir, indexed_at FROM cases"))
    seal_run(project, "epsilon")

    report = index_new_runs(project)

    assert not report.full
    assert report.indexed == ("runs/epsilon",)
    assert report.removed == ()
    after = dict(_rows(project, "SELECT rel_dir, indexed_at FROM cases"))
    assert {rel: after[rel] for rel in stamps} == stamps
    assert "runs/epsilon" in after


def test_renamed_directory(project):
    rebuild_index(project)
    (sim_id,) = _rows(
        project, "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE name = 'alpha'"
    )[0]
    (runs_dir_for(project) / "alpha").rename(runs_dir_for(project) / "alpha_renamed")

    report = index_new_runs(project)

    assert report.removed == ("runs/alpha",)
    assert report.indexed == ("runs/alpha_renamed",)
    assert _rows(
        project,
        "SELECT name, name_stem, rel_dir FROM simulations WHERE CAST(sim_id AS VARCHAR) = "
        f"'{sim_id}'",
    ) == [("alpha_renamed", "alpha_renamed", "runs/alpha_renamed")]
    assert _rows(project, "SELECT rel_dir FROM cases WHERE rel_dir LIKE 'runs/alpha%'") == [
        ("runs/alpha_renamed",)
    ]


def test_retry_of_an_attempt(project):
    rebuild_index(project)
    gamma = runs_dir_for(project) / "gamma"
    first = json.loads((gamma / RUN_OUTCOME_FILENAME).read_text(encoding="utf-8"))
    earlier = gamma / RUN_ATTEMPTS_DIRNAME / "1"
    earlier.mkdir(parents=True)
    shutil.move(gamma / RUN_OUTCOME_FILENAME, earlier / RUN_OUTCOME_FILENAME)
    write_attempt(project, "runs/gamma", status="running", attempt=2, heartbeat_age_s=1)

    report = index_new_runs(project)

    assert report.indexed == ("runs/gamma",)
    assert _rows(project, "SELECT attempt, status FROM cases WHERE rel_dir = 'runs/gamma'") == [
        (2, "running")
    ]
    attempts = _rows(
        project, "SELECT attempt, attempt_id, status FROM attempts WHERE rel_dir = 'runs/gamma'"
    )
    assert [(row[0], row[2]) for row in attempts] == [(1, "failed"), (2, "running")]
    assert attempts[0][1] == first["attempt_id"]


def test_removed_directory(project):
    rebuild_index(project)
    shutil.rmtree(runs_dir_for(project) / "beta")

    report = index_new_runs(project)

    assert report.removed == ("runs/beta",)
    assert _rows(project, "SELECT rel_dir FROM simulations WHERE rel_dir = 'runs/beta'") == []
    assert _rows(
        project,
        "SELECT COUNT(*) FROM parameters p WHERE NOT EXISTS "
        "(SELECT 1 FROM simulations s WHERE s.sim_id = p.sim_id)",
    ) == [(0,)]
    assert _rows(project, "SELECT rel_dir FROM cases WHERE rel_dir = 'runs/beta'") == []


def test_changed_annotation(project):
    rebuild_index(project)
    alpha = runs_dir_for(project) / "alpha"
    (sim_id,) = _rows(
        project, "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE name = 'alpha'"
    )[0]
    write_annotations(alpha, Annotations(sim_id=sim_id, tags=("keep",)))

    report = index_new_runs(project)

    assert report.indexed == ("runs/alpha",)
    assert _rows(project, f"SELECT tag FROM tags WHERE CAST(sim_id AS VARCHAR) = '{sim_id}'") == [
        ("keep",)
    ]


def test_pass_without_an_index(project):
    report = index_new_runs(project)

    assert report.full
    assert catalog_path_for(project).is_file()


@pytest.mark.parametrize(
    ("key", "current"),
    [
        pytest.param(META_SCHEMA_VERSION, INDEX_SCHEMA_VERSION, id="schema version"),
        pytest.param(META_RULE_VERSION, RULE_VERSION, id="label rule version"),
        pytest.param(META_KNOWN_ISSUES_DIGEST, known_issues_digest(), id="known issues"),
    ],
)
def test_index_of_another_build_is_rebuilt(project, key, current):
    rebuild_index(project)
    _restamp(project, key, "other")
    assert not index_is_current(project)

    report = index_new_runs(project)

    assert report.full
    assert _rows(project, f"SELECT value FROM {INDEX_META_TABLE} WHERE key = '{key}'") == [
        (current,)
    ]


def test_scan_keys(project):
    entries = scan_tree(project)

    assert entries["runs/alpha"].key.startswith("sim:")
    assert entries["runs/gamma"].key.startswith("attempt:")
    assert entries["sessions/calib"].key == f"session:{SESSION_ID}"
    assert entries["sessions/calib/trials/0002"].kind == "trial"


def test_opening_builds_a_missing_index(tmp_path):
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")

    with Catalog(root) as catalog:
        assert sorted(catalog.list_simulations()["name"]) == ["alpha"]
    assert catalog_path_for(root).is_file()


def test_reader_rebuilds_an_old_index(project):
    rebuild_index(project)
    _restamp(project, META_SCHEMA_VERSION, "0")

    with Catalog(project) as catalog:
        assert "alpha" in set(catalog.list_simulations()["name"])
    assert _rows(
        project, f"SELECT value FROM {INDEX_META_TABLE} WHERE key = '{META_SCHEMA_VERSION}'"
    ) == [(INDEX_SCHEMA_VERSION,)]


def test_failed_publish_keeps_the_index(project, monkeypatch):
    rebuild_index(project)
    index_before = catalog_path_for(project).read_bytes()

    def _boom(*_args, **_kwargs):
        raise OSError("publish refused")

    monkeypatch.setattr(index_file_module, "rename_over_open_file", _boom)
    with pytest.raises(OSError, match="publish refused") as refused:
        rebuild_index(project)

    assert "still readable" in str(refused.value)
    assert catalog_path_for(project).read_bytes() == index_before
    assert list(catalog_path_for(project).parent.glob("*.rebuild-*")) == []
    assert not index_lock_path(project).exists()


def test_reader_across_the_swap(project, monkeypatch):
    rebuild_index(project)
    reader = Catalog(project)

    def _publish_under_a_live_reader(staging: Path, target: Path, lock: LockFile) -> None:
        reader.list_simulations()
        publish_staging(staging, target, lock)

    monkeypatch.setattr(indexer_module, "publish_staging", _publish_under_a_live_reader)
    try:
        before = sorted(reader.list_simulations()["name"])
        seal_run(project, "epsilon")

        index_new_runs(project)

        assert sorted(reader.list_simulations()["name"]) == before
    finally:
        reader.close()

    with Catalog(project) as reopened:
        assert sorted(reopened.list_simulations()["name"]) == [*before, "epsilon"]


def test_index_replaced_in_one_step(project):
    rebuild_index(project)
    index_path = catalog_path_for(project)
    file_id_before = index_path.stat().st_ino
    seal_run(project, "epsilon")

    index_new_runs(project)

    assert index_path.stat().st_ino != file_id_before
    assert list(index_path.parent.glob("*.rebuild-*")) == []


def test_no_lock_without_a_write(project, monkeypatch):
    rebuild_index(project)

    def _refuse(*_args, **_kwargs):
        raise AssertionError("the lock was taken")

    monkeypatch.setattr(indexer_module, "index_lock", _refuse)

    assert index_new_runs(project).unchanged
    assert not index_lock_path(project).exists()


def test_two_passes_at_once(project, monkeypatch):
    # A slow pass holds the lock, the fast one waits, reads the diff again and adds its run.
    rebuild_index(project)
    seal_run(project, "slow")
    holding = threading.Event()
    index_entry = indexer_module._IndexWriter.index_entry

    def _slow_index_entry(self, entry):
        if entry.rel_dir == "runs/slow":
            holding.set()
            time.sleep(1.0)
        return index_entry(self, entry)

    monkeypatch.setattr(indexer_module._IndexWriter, "index_entry", _slow_index_entry)
    reports: dict[str, object] = {}

    def _pass(name: str) -> None:
        reports[name] = index_new_runs(project)

    slow = threading.Thread(target=_pass, args=("slow",))
    slow.start()
    assert holding.wait(30)
    seal_run(project, "fast")
    fast = threading.Thread(target=_pass, args=("fast",))
    fast.start()
    slow.join(60)
    fast.join(60)

    assert reports["slow"].indexed == ("runs/slow",)
    assert reports["fast"].indexed == ("runs/fast",)
    names = {name for (name,) in _rows(project, "SELECT name FROM simulations")}
    assert {"slow", "fast"} <= names
    assert index_is_current(project)
    assert not index_lock_path(project).exists()


def test_old_empty_lock(project):
    lock = index_lock_path(project)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b"")
    yesterday = time.time() - 86400
    os.utime(lock, (yesterday, yesterday))

    started = time.monotonic()
    report = index_new_runs(project)

    assert report.full
    assert time.monotonic() - started < 30
    assert not lock.exists()


@pytest.mark.parametrize("refresh", [reindex_if_indexed, index_after_run])
def test_held_lock_warns(project, monkeypatch, warnings_said, refresh):
    rebuild_index(project)
    seal_run(project, "epsilon")
    _hold_the_lock_from_another_process(project)
    monkeypatch.setattr(indexer_module, "index_lock", functools.partial(index_lock, wait_s=0.05))

    assert refresh(project) is None
    said = " ".join(record.getMessage() for record in warnings_said.records)
    assert "Index not refreshed" in said
    assert f"process {os.getppid()}" in said
    assert "hmp catalog reindex brings it up to date" in said
    assert not index_is_current(project)


def test_index_after_run_builds_an_index(project):
    report = index_after_run(project)

    assert report is not None and report.full
    assert index_is_current(project)


def test_block_size(project):
    rebuild_index(project)
    assert _block_size(project) == HMP_DUCKDB_BLOCK_SIZE == 16384

    seal_run(project, "epsilon")
    index_new_runs(project)
    assert _block_size(project) == 16384


def test_case_bytes(project):
    rebuild_index(project)

    rows = dict(_rows(project, "SELECT rel_dir, bytes FROM cases"))

    assert rows["runs/alpha"] == path_size_bytes(project / "runs" / "alpha")
    assert rows["runs/gamma"] == path_size_bytes(project / "runs" / "gamma")
    assert rows["sessions/calib"] == path_size_bytes(project / "sessions" / "calib")


def test_bytes_after_figures_and_exports(project):
    run_dir = project / "runs" / "alpha"
    (run_dir / "figures").mkdir(exist_ok=True)
    index_new_runs(project)
    time.sleep(0.05)
    (run_dir / "figures" / "heads.png").write_bytes(b"x" * 1000)
    (run_dir / "exports").mkdir(exist_ok=True)
    (run_dir / "exports" / "heads.csv").write_bytes(b"y" * 500)
    index_new_runs(project)
    live = dict(_rows(project, "SELECT rel_dir, bytes FROM cases"))

    catalog_path_for(project).unlink()
    rebuild_index(project)

    assert dict(_rows(project, "SELECT rel_dir, bytes FROM cases")) == live
    assert live["runs/alpha"] == path_size_bytes(run_dir)


def test_purged_json_changes_the_stamp(project):
    before = scan_tree(project)["runs/alpha"].mtime_ns
    purged = project / "runs" / "alpha" / RUN_PURGED_FILENAME
    purged.write_text("{}", encoding="utf-8")
    later = time.time() + 60
    os.utime(purged, (later, later))

    assert scan_tree(project)["runs/alpha"].mtime_ns > before


def test_metric_column_name(project):
    rebuild_index(project)

    connection = open_index(project)
    try:
        columns = {row[0] for row in connection.execute("DESCRIBE metrics").fetchall()}
    finally:
        connection.close()
    assert "metric" in columns
    assert "metric_name" not in columns


def test_identifiers_from_the_seal(project):
    # Read from the seal, not from simulation.parquet, which carries neither column.
    seal_run(project, "alpha")
    rebuild_index(project)

    seal = read_seal(project / "runs" / "alpha")
    assert seal.identity.solution_key is not None
    assert seal.identity.request_id is not None
    rows = _rows(project, "SELECT name, solution_key, request_id FROM simulations ORDER BY name")
    assert rows
    assert all(key and request for _, key, request in rows)
    assert {name: (key, request) for name, key, request in rows}["alpha"] == (
        seal.identity.solution_key,
        seal.identity.request_id,
    )


def test_known_issues_digest(monkeypatch):
    # A bug row added to the register changes the digest, so the index is relabelled.
    before = known_issues_digest()
    added = Bug(id="x", since="3.0.0", versions="<3.0.0", quantities=("metrics",), text="t")
    monkeypatch.setattr(indexer_module, "REGISTER", replace(REGISTER, bugs=(*REGISTER.bugs, added)))

    assert known_issues_digest() != before
    monkeypatch.setattr(indexer_module, "REGISTER", replace(REGISTER, recipes=()))
    assert known_issues_digest() == before, "only the bugs label a run"
