"""The index is a diff of the tree: what is on disk is what gets indexed, and only what moved is rewritten."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb
import pytest

import hydromodpy.results.catalog.indexer as indexer_module
from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.state.layout import catalog_path_for, runs_dir_for
from hydromodpy.results.annotations import Annotations, write_annotations
from hydromodpy.results.catalog import Catalog, index_new_runs, rebuild_index
from hydromodpy.results.catalog.index_schema import (
    INDEX_META_TABLE,
    INDEX_SCHEMA_VERSION,
    META_KNOWN_ISSUES_DIGEST,
    META_RULE_VERSION,
    META_SCHEMA_VERSION,
)
from hydromodpy.results.catalog.indexer import index_is_current, known_issues_digest, scan_tree
from hydromodpy.results.catalog.views import V_CASES_FIXED_COLUMNS
from hydromodpy.results.checks import CalibratedBy
from hydromodpy.results.session.descriptor import BestCase, BestTrial, write_session
from hydromodpy.results.session.journal import append_trial
from hydromodpy.results.storage.contract import (
    RUN_ATTEMPTS_DIRNAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.validity_rules import RULE_VERSION
from tests._helpers.sealed_runs import (
    CONFIG_HASH,
    make_project,
    seal_run,
    write_attempt,
    write_session_dir,
)
from tests._helpers.session_documents import joint_session, joint_trial

SESSION_ID = "sess0001"


@pytest.fixture
def project(tmp_path) -> Path:
    """Two sealed runs, a failed attempt, a running one, a session with a promoted run and a kept trial."""
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


def _index_content(root: Path, tables: tuple[str, ...]) -> dict[str, list[str]]:
    with Catalog(root) as catalog:
        return {
            table: sorted(str(row) for row in catalog.backend.fetch_all(f"SELECT * FROM {table}"))
            for table in tables
        }


# -- the tree is the set of cases -------------------------------------------


def test_every_result_directory_is_a_case_and_every_seal_a_run(project):
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


def test_an_attempt_without_a_seal_is_indexed_from_its_outcome(project):
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


def test_a_stale_pulse_reads_as_stale(project):
    write_attempt(project, "runs/epsilon", status="running", heartbeat_age_s=3600)

    rebuild_index(project)

    assert _rows(project, "SELECT status FROM cases WHERE rel_dir = 'runs/epsilon'") == [("stale",)]


def test_a_directory_with_neither_outcome_nor_manifest_is_not_a_case(project):
    (runs_dir_for(project) / "scratch_only").mkdir()
    (runs_dir_for(project) / "scratch_only" / "note.txt").write_text("x")

    report = rebuild_index(project)

    assert "runs/scratch_only" not in report.indexed
    assert report.skipped == ()


def test_a_seal_without_its_index_row_is_reported(project):
    (runs_dir_for(project) / "beta" / TABLES_DIRNAME / "simulation.parquet").unlink()

    report = rebuild_index(project)

    assert [item.rel_dir for item in report.skipped] == ["runs/beta"]
    assert "simulation.parquet" in report.skipped[0].reason
    assert "runs/beta" not in report.indexed


def test_a_manifest_naming_another_run_is_refused(project):
    beta = runs_dir_for(project) / "beta"
    alpha_manifest = (runs_dir_for(project) / "alpha" / RUN_MANIFEST_FILENAME).read_text()
    (beta / RUN_MANIFEST_FILENAME).write_text(alpha_manifest)

    report = rebuild_index(project)

    assert [item.rel_dir for item in report.skipped] == ["runs/beta"]
    assert "two identities" in report.skipped[0].reason


# -- the label is computed at indexing ---------------------------------------


def test_the_label_is_computed_and_dated_at_indexing(project):
    rebuild_index(project)

    rows = _rows(project, "SELECT name, label, rule_version FROM simulations")
    assert rows == [
        ("alpha", "exploratory", "2"),
        ("beta", "exploratory", "2"),
        ("calib", "calibrated", "2"),
        ("calib_t2", "exploratory", "2"),
    ]
    assert _rows(project, "SELECT COUNT(*) FROM simulations WHERE label_date IS NULL") == [(0,)]


def test_a_run_that_did_not_converge_is_labelled_failed(tmp_path):
    root = make_project(tmp_path / "demo")
    seal_run(root, "diverged", converged=False)

    rebuild_index(root)

    assert _rows(root, "SELECT label, label_reasons FROM simulations") == [
        ("failed", "solver did not converge")
    ]


def test_a_known_issue_of_the_producing_version_declasses_the_run(tmp_path):
    root = make_project(tmp_path / "demo")
    seal_run(root, "old", hydromodpy_version="1.9.0")

    rebuild_index(root)

    (label, issues) = _rows(root, "SELECT label, known_issues FROM simulations")[0]
    assert label == "exploratory"
    assert issues


# -- sessions, sites, annotations --------------------------------------------


def test_a_session_comes_back_with_its_trials_and_phases(project):
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


def test_a_session_comes_back_with_its_cases_and_the_cases_of_each_trial(project):
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


def test_a_joint_session_names_no_single_site_or_run_in_cases(tmp_path):
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


def test_a_session_keeps_its_root_search_in_the_index(tmp_path):
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


def test_the_sites_table_counts_cases_and_sealed_runs(project):
    rebuild_index(project)

    assert _rows(project, "SELECT site, gauge, n_cases, n_runs FROM sites") == [
        ("J0014010", "J0014010", 6, 4)
    ]


def test_tags_and_notes_come_back_from_the_run_directory(project):
    rebuild_index(project)

    assert _rows(
        project,
        "SELECT s.name, t.tag FROM tags t JOIN simulations s ON s.sim_id = t.sim_id",
    ) == [("beta", "pinned")]


def test_v_cases_joins_the_seal_to_every_case(project):
    rebuild_index(project)

    rows = _rows(project, "SELECT rel_dir, status, label, nse FROM v_cases")
    assert ("runs/calib", "completed", "calibrated", 0.71) in rows
    assert ("runs/gamma", "failed", None, None) in rows
    assert ("sessions/calib", "completed", None, None) in rows


def test_v_cases_carries_one_column_per_global_parameter(project):
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


def test_the_hundred_basins_query_runs_on_v_cases(project):
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


# -- rebuilding twice describes the same project ----------------------------


def test_two_rebuilds_produce_the_same_index(project):
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


# -- the incremental pass is a diff ------------------------------------------


def test_a_tree_that_did_not_move_writes_nothing(project):
    rebuild_index(project)
    before = catalog_path_for(project).stat().st_ino

    report = index_new_runs(project)

    assert report.unchanged
    assert not report.full
    assert catalog_path_for(project).stat().st_ino == before
    assert index_is_current(project)


def test_a_new_run_is_the_only_one_written(project):
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


def test_a_renamed_directory_keeps_its_id_under_the_new_name(project):
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


def test_a_retry_moves_the_previous_attempt_to_attempts(project):
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


def test_a_directory_removed_from_disk_loses_its_rows(project):
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


def test_a_changed_annotation_is_picked_up(project):
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


def test_without_an_index_the_pass_is_a_full_rebuild(project):
    report = index_new_runs(project)

    assert report.full
    assert catalog_path_for(project).is_file()


def test_an_index_of_another_schema_version_is_rebuilt_whole(project):
    rebuild_index(project)
    connection = duckdb.connect(str(catalog_path_for(project)))
    connection.execute(
        f"UPDATE {INDEX_META_TABLE} SET value = '0' WHERE key = ?", [META_SCHEMA_VERSION]
    )
    connection.close()

    report = index_new_runs(project)

    assert report.full
    assert _rows(
        project, f"SELECT value FROM {INDEX_META_TABLE} WHERE key = '{META_SCHEMA_VERSION}'"
    ) == [(INDEX_SCHEMA_VERSION,)]


@pytest.mark.parametrize(
    ("key", "current"),
    [(META_RULE_VERSION, RULE_VERSION), (META_KNOWN_ISSUES_DIGEST, known_issues_digest())],
)
def test_an_index_labelled_by_another_build_is_rebuilt_whole(project, key, current):
    rebuild_index(project)
    connection = duckdb.connect(str(catalog_path_for(project)))
    connection.execute(f"UPDATE {INDEX_META_TABLE} SET value = 'other' WHERE key = ?", [key])
    connection.close()
    assert not index_is_current(project)

    report = index_new_runs(project)

    assert report.full
    assert _rows(project, f"SELECT value FROM {INDEX_META_TABLE} WHERE key = '{key}'") == [
        (current,)
    ]


def test_the_scan_keys_a_directory_by_its_seal_or_its_attempt(project):
    entries = scan_tree(project)

    assert entries["runs/alpha"].key.startswith("sim:")
    assert entries["runs/gamma"].key.startswith("attempt:")
    assert entries["sessions/calib"].key == f"session:{SESSION_ID}"
    assert entries["sessions/calib/trials/0002"].kind == "trial"


# -- the reader refuses what it cannot read ---------------------------------


def test_a_project_without_an_index_names_the_command_that_builds_it(tmp_path):
    root = make_project(tmp_path / "demo")

    with pytest.raises(FileNotFoundError, match="hmp catalog reindex"):
        Catalog(root)


def test_an_index_of_another_schema_version_is_refused_by_the_reader(project):
    rebuild_index(project)
    connection = duckdb.connect(str(catalog_path_for(project)))
    connection.execute(
        f"UPDATE {INDEX_META_TABLE} SET value = '0' WHERE key = ?", [META_SCHEMA_VERSION]
    )
    connection.close()

    with pytest.raises(SchemaVersionMismatchError, match="hmp catalog reindex"):
        Catalog(project)


# -- the live index survives ------------------------------------------------


def test_the_previous_index_survives_a_failed_publish(project, monkeypatch):
    rebuild_index(project)
    index_before = catalog_path_for(project).read_bytes()

    def _boom(*_args, **_kwargs):
        raise OSError("publish refused")

    monkeypatch.setattr(indexer_module, "rename_over_open_file", _boom)
    with pytest.raises(OSError, match="publish refused") as refused:
        rebuild_index(project)

    assert "still readable" in str(refused.value)
    assert catalog_path_for(project).read_bytes() == index_before
    assert list(catalog_path_for(project).parent.glob("*.rebuild-*")) == []


def test_a_reader_keeps_reading_across_the_swap(project, monkeypatch):
    rebuild_index(project)
    reader = Catalog(project)
    publish = indexer_module._publish

    def _publish_under_a_live_reader(staging: Path, target: Path) -> None:
        reader.list_simulations()
        publish(staging, target)

    monkeypatch.setattr(indexer_module, "_publish", _publish_under_a_live_reader)
    try:
        before = sorted(reader.list_simulations()["name"])
        seal_run(project, "epsilon")

        index_new_runs(project)

        assert sorted(reader.list_simulations()["name"]) == before
    finally:
        reader.close()

    with Catalog(project) as reopened:
        assert sorted(reopened.list_simulations()["name"]) == [*before, "epsilon"]


def test_the_index_is_replaced_in_one_step(project):
    rebuild_index(project)
    index_path = catalog_path_for(project)
    file_id_before = index_path.stat().st_ino
    seal_run(project, "epsilon")

    index_new_runs(project)

    assert index_path.stat().st_ino != file_id_before
    assert list(index_path.parent.glob("*.rebuild-*")) == []
