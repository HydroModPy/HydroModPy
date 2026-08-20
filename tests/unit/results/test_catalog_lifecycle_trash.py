"""Trash / restore / tag / note lifecycle for the simulation catalog."""

from __future__ import annotations

import uuid

import pytest

from hydromodpy.core.state.paths import share_dir_for
from hydromodpy.results.catalog import (
    AmbiguousReferenceError,
    DuplicateSimulationNameError,
)
from hydromodpy.results.catalog.lifecycle import PinnedRunError
from hydromodpy.results.storage.contract import TABLES_DIRNAME
from hydromodpy.results.trash_marker import read_trash_marker
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _register(catalog, name):
    sid = str(uuid.uuid4())
    catalog.register_simulation(sid, project="p", solver="modflow6", name=name)
    catalog._backend.execute(
        "UPDATE simulations SET status_id = (SELECT id FROM statuses WHERE code = 'completed'), "
        "ended_at = current_timestamp WHERE sim_id = ?",
        [sid],
    )
    return sid


def test_add_tag_is_idempotent_and_write_tags_skips_blanks(catalog):
    sid = _register(catalog, "r")
    assert catalog.add_tag(sid, "paper") is True
    assert catalog.add_tag(sid, "paper") is False
    catalog.write_tags(sid, ["2019", "", "  "])
    tags = {
        r[0] for r in catalog._backend.fetch_all("SELECT tag FROM tags WHERE sim_id = ?", [sid])
    }
    assert tags == {"paper", "2019"}


def test_add_note_appends_to_sim_notes(catalog):
    sid = _register(catalog, "r")
    catalog.add_note(sid, "first")
    catalog.add_note(sid, "second")
    notes = [
        r[0]
        for r in catalog._backend.fetch_all("SELECT note FROM sim_notes WHERE sim_id = ?", [sid])
    ]
    assert sorted(notes) == ["first", "second"]


def test_trash_frees_name_keeps_storage_and_restore_versions(catalog):
    sid = _register(catalog, "baseline")
    catalog.trash(sid)
    row = catalog._backend.fetch_one(
        "SELECT name, original_name, st.code FROM simulations s "
        "JOIN statuses st ON s.status_id = st.id WHERE sim_id = ?",
        [sid],
    )
    assert row == (None, "baseline", "trashed")
    assert [e["original_name"] for e in catalog.list_trash()] == ["baseline"]

    # the freed name can be reused; restore then version-bumps
    _register(catalog, "baseline")
    assert catalog.restore(sid) == "baseline.v2"
    assert catalog.list_trash() == []


def _register_failed(catalog, name):
    sid = str(uuid.uuid4())
    catalog.register_simulation(sid, project="p", solver="modflow6", name=name)
    catalog.finalize(sid, status="failed")
    return sid


def test_trash_marks_the_run_directory_and_restore_clears_it(catalog):
    sid = _register(catalog, "baseline")
    catalog.run_dir_for(sid).mkdir(parents=True, exist_ok=True)

    catalog.trash(sid)
    marker = read_trash_marker(catalog.run_dir_for(sid))
    assert marker is not None
    assert marker.original_name == "baseline"
    assert marker.original_status == "completed"

    catalog.restore(sid)
    assert read_trash_marker(catalog.run_dir_for(sid)) is None


def test_restore_preserves_failed_status(catalog):
    sid = _register_failed(catalog, "boom")
    status = catalog._backend.fetch_one(
        "SELECT st.code FROM simulations s JOIN statuses st ON s.status_id = st.id "
        "WHERE sim_id = ?",
        [sid],
    )
    assert status[0] == "failed"
    catalog.trash(sid)
    catalog.restore(sid)
    restored = catalog._backend.fetch_one(
        "SELECT st.code FROM simulations s JOIN statuses st ON s.status_id = st.id "
        "WHERE sim_id = ?",
        [sid],
    )
    assert restored[0] == "failed"


def test_rename_into_versioned_stem_keeps_registration_working(catalog):
    # foo.v1 and foo.v2 live; renaming a third run to bare 'foo' must not create
    # a duplicate (stem='foo', version=1) that later poisons version registration.
    _register(catalog, "foo.v1")
    _register(catalog, "foo.v2")
    third = _register(catalog, "other")

    with pytest.raises(DuplicateSimulationNameError):
        catalog.rename_simulation(third, "foo")

    # version-mode registration of the stem still works afterwards.
    fresh = str(uuid.uuid4())
    result = catalog.register_simulation(
        fresh, project="p", solver="modflow6", name="foo", if_exists="version"
    )
    assert result.name == "foo.v3"


def test_replace_collision_emits_sim_trash_audit(catalog):
    first = _register(catalog, "dup")
    second = str(uuid.uuid4())
    catalog.register_simulation(
        second, project="p", solver="modflow6", name="dup", if_exists="replace"
    )
    rows = catalog._backend.fetch_all(
        "SELECT CAST(sim_id AS VARCHAR), payload FROM audit_log "
        "WHERE event_type = 'sim.trash' AND CAST(sim_id AS VARCHAR) = ?",
        [first],
    )
    assert len(rows) == 1
    import json

    payload = rows[0][1]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert payload["replaced_by"] == second


def test_cascade_delete_removes_workflow_ledger(catalog):
    sid = _register(catalog, "wf")
    if catalog._table_exists("workflow_steps"):
        catalog._backend.execute(
            "INSERT INTO workflow_steps (step_id, run_id, step_order, step_name, status_id) "
            "VALUES (gen_random_uuid(), ?, 0, 'solve', "
            "(SELECT id FROM statuses WHERE code = 'completed'))",
            [sid],
        )
    catalog.delete(sid, remove_storage=False)
    if catalog._table_exists("workflow_steps"):
        left = catalog._backend.fetch_one("SELECT 1 FROM workflow_steps WHERE run_id = ?", [sid])
        assert left is None


def test_resolve_exact_name_beats_prefix_or_raises(catalog):
    # A run NAMED like a hex prefix and a different run whose UUID starts the same
    # must not silently resolve to the prefix hit.
    prefix = "beef1234"
    hex_id = f"{prefix}-0000-0000-0000-000000000000"
    catalog.register_simulation(hex_id, project="p", solver="modflow6", name="by_id")
    catalog._backend.execute(
        "UPDATE simulations SET status_id = (SELECT id FROM statuses WHERE code = 'completed'), "
        "ended_at = current_timestamp WHERE sim_id = ?",
        [hex_id],
    )
    named = _register(catalog, prefix)
    with pytest.raises(AmbiguousReferenceError):
        catalog.resolve(prefix)
    # The exact-name-only case (no prefix collision) resolves to the name.
    assert catalog.resolve("by_id") == hex_id
    assert named != hex_id


def test_read_only_catalog_write_raises_read_only_error(catalog):
    from hydromodpy.core.exceptions import ReadOnlyError
    from hydromodpy.results.catalog import Catalog

    sid = _register(catalog, "ro")
    catalog.close()
    with Catalog(catalog.catalog_path, read_only=True) as ro:
        with pytest.raises(ReadOnlyError):
            ro.add_tag(sid, "paper")
        with pytest.raises(ReadOnlyError):
            ro.trash(sid)


def test_pinned_run_is_protected_from_trash(catalog):
    sid = _register(catalog, "keep")
    catalog.add_tag(sid, "pinned")
    with pytest.raises(PinnedRunError):
        catalog.trash(sid)
    catalog.trash(sid, force=True)
    assert len(catalog.list_trash()) == 1


def test_empty_trash_purges_unpinned_only(catalog):
    a = _register(catalog, "a")
    b = _register(catalog, "b")
    catalog.add_tag(b, "pinned")
    catalog.trash(a)
    catalog.trash(b, force=True)
    purged = catalog.empty_trash()  # force=False: skip pinned b
    assert purged == [a]
    assert {e["sim_id"] for e in catalog.list_trash()} == {b}


def test_diff_reports_param_and_metric_deltas(catalog):
    a = _register(catalog, "base.v2")
    b = _register(catalog, "base.v3")
    catalog.write_parameters(
        a, [{"param_name": "K", "value": 1e-4}, {"param_name": "Sy", "value": 0.05}]
    )
    catalog.write_parameters(
        b, [{"param_name": "K", "value": 2e-4}, {"param_name": "Sy", "value": 0.05}]
    )
    catalog._backend.execute(
        "INSERT INTO metrics (sim_id, station_id, variable, metric_name, value) "
        "VALUES (?, '__outlet__', 'discharge', 'nse', 0.7)",
        [a],
    )
    catalog._backend.execute(
        "INSERT INTO metrics (sim_id, station_id, variable, metric_name, value) "
        "VALUES (?, '__outlet__', 'discharge', 'nse', 0.8)",
        [b],
    )
    result = catalog.diff("base.v2", "base.v3")
    assert result["params"] == {("K", "__global__"): (1e-4, 2e-4)}
    assert result["metrics"] == {("nse", "__outlet__"): (0.7, 0.8)}


def test_run_python_api_tag_note_lineage_delete(catalog):
    parent = _register(catalog, "parent")
    child = str(uuid.uuid4())
    catalog.register_simulation(
        child, project="p", solver="modflow6", name="child", parent_sim_id=parent
    )
    catalog._backend.execute(
        "UPDATE simulations SET status_id = (SELECT id FROM statuses WHERE code = 'completed'), "
        "ended_at = current_timestamp WHERE sim_id = ?",
        [child],
    )

    run = catalog["child"]
    assert run.parent.sim_id == parent
    assert run.parent.name == "parent"

    run.tag("+draft", "keep", "-draft").note("a note")
    assert sorted(catalog["child"].tags or []) == ["keep"]

    run.delete()  # not pinned -> trash
    assert [e["original_name"] for e in catalog.list_trash()] == ["child"]


def _write_metric(catalog, sid, station, metric, value):
    catalog._backend.execute(
        "INSERT INTO metrics (sim_id, station_id, variable, metric_name, value) "
        "VALUES (?, ?, 'discharge', ?, ?)",
        [sid, station, metric, value],
    )


def test_best_selector_falls_back_to_any_station(catalog):
    # No outlet metric exists, only a lake-scoped one -> @best must still resolve.
    sid = _register(catalog, "lakebest")
    _write_metric(catalog, sid, "lake:forebay", "kge", 0.9)
    assert catalog.resolve("@best:kge") == sid


def test_best_selector_scoped_to_station(catalog):
    a = _register(catalog, "sa")
    b = _register(catalog, "sb")
    _write_metric(catalog, a, "lake:forebay", "kge", 0.4)
    _write_metric(catalog, b, "lake:forebay", "kge", 0.8)
    assert catalog.resolve("@best:kge@lake:forebay") == b
    assert catalog.resolve("@worst:kge@lake:forebay") == a


def test_find_lte_filter(catalog):
    a = _register(catalog, "la")
    b = _register(catalog, "lb")
    _write_metric(catalog, a, "__outlet__", "nse", 0.3)
    _write_metric(catalog, b, "__outlet__", "nse", 0.9)
    names = {run.name for run in catalog.find(nse_lte=0.5)}
    assert names == {"la"}


def test_find_excludes_trashed_by_default(catalog):
    a = _register(catalog, "a")
    _register(catalog, "b")
    catalog.trash(a)
    live = {run.name for run in catalog.find(project="p")}
    assert live == {"b"}
    trashed = list(catalog.find(project="p", status="trashed"))
    assert len(trashed) == 1


# ---------------------------------------------------------------------------
# Journaled two-phase hard purge (crash safety)
# ---------------------------------------------------------------------------


def _give_storage(catalog, sid):
    """Create real Parquet + Zarr storage for a sim and wire its zarr_path."""
    pq = catalog.tables_dir_for(sid)
    pq.mkdir(parents=True, exist_ok=True)
    (pq / "data.parquet").write_bytes(b"x")
    zz = catalog.fields_path_for(sid)
    zz.mkdir(parents=True, exist_ok=True)
    (zz / ".zgroup").write_text("{}")
    rel = zz.relative_to(catalog._workspace)
    catalog._backend.execute(
        "UPDATE simulations SET zarr_path = ? WHERE sim_id = ?", [str(rel), sid]
    )
    return pq, zz


def _journal_phases(catalog, sid):
    return [
        r[0]
        for r in catalog._backend.fetch_all(
            "SELECT phase FROM purge_journal WHERE sim_id = ?", [sid]
        )
    ]


def test_empty_trash_removes_storage_and_clears_journal(catalog):
    sid = _register(catalog, "doomed")
    pq, zz = _give_storage(catalog, sid)
    catalog.trash(sid)

    assert catalog.empty_trash() == [sid]
    # bytes gone, row gone, journal empty -> nothing left behind, nothing dangling
    assert not pq.exists()
    assert not zz.exists()
    assert _journal_phases(catalog, sid) == []
    assert catalog._backend.fetch_one("SELECT 1 FROM simulations WHERE sim_id = ?", [sid]) is None


def test_purge_crash_before_cascade_leaves_reachable_state(catalog, monkeypatch):
    """A crash after rmtree but before the row delete must leave the row + a
    journal entry so no byte is orphaned and replay can finish."""
    sid = _register(catalog, "doomed")
    pq, zz = _give_storage(catalog, sid)
    catalog.trash(sid)

    def _boom(_sid):
        raise RuntimeError("crash in phase 3")

    monkeypatch.setattr(catalog, "_cascade_delete_rows", _boom)
    with pytest.raises(RuntimeError, match="crash in phase 3"):
        catalog.delete(sid, audit_event_type="sim.purge")

    # bytes are gone (phase 2 ran) but the row survives and the journal records
    # the in-flight purge -> the (now empty) storage location is still reachable
    assert not pq.exists()
    assert not zz.exists()
    assert _journal_phases(catalog, sid) == ["rmtree_done"]
    assert (
        catalog._backend.fetch_one("SELECT 1 FROM simulations WHERE sim_id = ?", [sid]) is not None
    )

    # gc-style replay finishes the purge: row gone, journal cleared
    monkeypatch.undo()
    assert catalog.replay_purge_journal() == [sid]
    assert _journal_phases(catalog, sid) == []
    assert catalog._backend.fetch_one("SELECT 1 FROM simulations WHERE sim_id = ?", [sid]) is None


def test_replay_finishes_a_pending_purge_with_storage_intact(catalog):
    """A crash right after phase 1 leaves storage on disk; replay removes it."""
    sid = _register(catalog, "doomed")
    pq, zz = _give_storage(catalog, sid)
    catalog.trash(sid)
    # simulate a phase-1-only crash: journal 'pending', storage + row intact
    catalog._backend.execute(
        "INSERT INTO purge_journal (sim_id, phase) VALUES (?, 'pending')", [sid]
    )
    assert pq.exists() and zz.exists()

    assert catalog.replay_purge_journal() == [sid]
    assert not pq.exists()
    assert not zz.exists()
    assert _journal_phases(catalog, sid) == []
    assert catalog._backend.fetch_one("SELECT 1 FROM simulations WHERE sim_id = ?", [sid]) is None


# ---------------------------------------------------------------------------
# export_log bookkeeping
# ---------------------------------------------------------------------------


def test_record_export_logs_artifact_with_checksum(catalog):
    sid = _register(catalog, "r")
    artifact = catalog.project_path / "exports" / "r" / "timeseries.csv"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("a,b\n1,2\n")
    catalog.record_export(sid, kind="csv", path=artifact)

    exports = catalog.list_exports(sid)
    assert len(exports) == 1
    assert exports[0]["kind"] == "csv"
    assert exports[0]["rel_path"] == "exports/r/timeseries.csv"
    assert exports[0]["bytes"] == artifact.stat().st_size
    assert len(exports[0]["sha256"]) == 64


def test_record_export_is_noop_when_persistence_off(catalog):
    sid = _register(catalog, "r")
    artifact = share_dir_for(catalog.project_path) / "r" / "x.csv"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("x\n")
    catalog._persistence.save_catalog = False
    try:
        catalog.record_export(sid, kind="csv", path=artifact)
    finally:
        catalog._persistence.save_catalog = True
    assert catalog.list_exports(sid) == []


# ---------------------------------------------------------------------------
# Index-row snapshot (what a rebuilt index reads back)
# ---------------------------------------------------------------------------


def test_finalize_writes_the_index_row_snapshot(catalog):
    sid = _register(catalog, "r")
    catalog.finalize(sid, status="completed", duration_s=1.0)
    snapshot = catalog.run_dir_for(sid) / TABLES_DIRNAME / "simulation.parquet"

    assert snapshot.is_file()


# ---------------------------------------------------------------------------
# [export].package writes a .hmp while the store is open (regression: the step
# must package BEFORE finalize closes the store, never with store=None)
# ---------------------------------------------------------------------------


def test_auto_export_package_writes_hmp_and_logs_it(catalog):
    from hydromodpy.simulation.extraction.post_run import auto_export_package
    from hydromodpy.simulation.planning.export_config import ExportConfig

    sid = str(uuid.uuid4())
    catalog.register_simulation(
        sid, project="p", solver="modflow6", name="shareme", n_cells=4, n_layers=1, config={"k": 1}
    )
    auto_export_package(
        sim_id=sid,
        store=catalog,
        export_config=ExportConfig(package=True),
        save_catalog=True,
        run_id="shareme",
    )
    archive = share_dir_for(catalog.project_path) / "shareme" / "shareme.hmp"
    assert archive.is_file()
    assert "hmp" in [e["kind"] for e in catalog.list_exports(sid)]


def test_auto_export_package_noop_when_disabled(catalog):
    from hydromodpy.simulation.extraction.post_run import auto_export_package
    from hydromodpy.simulation.planning.export_config import ExportConfig

    sid = _register(catalog, "plain")
    auto_export_package(
        sim_id=sid,
        store=catalog,
        export_config=ExportConfig(package=False),
        save_catalog=True,
        run_id="plain",
    )
    assert not (catalog.project_path / "exports" / "plain").exists()
