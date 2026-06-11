"""Trash / restore / tag / note lifecycle for the simulation catalog."""

from __future__ import annotations

import uuid

import pytest

from hydromodpy.results.catalog.lifecycle import PinnedRunError
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
    pq = catalog.parquet_dir_for(sid)
    pq.mkdir(parents=True, exist_ok=True)
    (pq / "data.parquet").write_bytes(b"x")
    zz = catalog.zarr_path_for(sid)
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
