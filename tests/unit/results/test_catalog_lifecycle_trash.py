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


def test_run_python_api_params_metrics_tag_note_lineage(catalog):
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
    catalog.write_parameters(child, [{"param_name": "K", "value": 8.6e-5}])
    catalog._backend.execute(
        "INSERT INTO metrics (sim_id, station_id, variable, metric_name, value) "
        "VALUES (?, '__outlet__', 'discharge', 'nse', 0.86)",
        [child],
    )

    run = catalog["child"]
    assert run.params == {"K": 8.6e-5}
    assert run.metrics == {"nse": 0.86}
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
