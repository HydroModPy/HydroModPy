"""Tests for ``hmp catalog gc``."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.state.paths import RUNS_DIRNAME, catalog_path_for, runs_dir_for
from hydromodpy.results.manifest import RUN_MANIFEST_FILENAME
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME, TABLES_DIRNAME


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def _make_minimal_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "projects").mkdir()
    (workspace / "data").mkdir()
    return workspace


def _age_path(path: Path, hours: float = 2.0) -> None:
    """Backdate ``path`` past the gc staging grace window so it is swept."""
    import os
    import time

    old = time.time() - hours * 3600
    os.utime(path, (old, old))


def _make_project_with_catalog(workspace: Path, project_name: str = "demo") -> Path:
    from hydromodpy.results.catalog import Catalog

    project = workspace / "projects" / project_name
    project.mkdir(parents=True)
    # touch a catalog by opening it once
    with Catalog(project):
        pass
    return project


def _make_orphan_run(project: Path, name: str) -> Path:
    """Create an aged run directory that no index row claims."""
    run_dir = runs_dir_for(project) / name
    (run_dir / FIELDS_STORE_NAME).mkdir(parents=True)
    (run_dir / FIELDS_STORE_NAME / ".zgroup").write_text("{}")
    _age_path(run_dir / FIELDS_STORE_NAME)
    _age_path(run_dir)
    return run_dir


def test_gc_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()
    assert "--apply" in out


def test_gc_plan_on_empty_workspace(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace)])
    assert code == 0
    out = capsys.readouterr().out
    assert "[plan]" in out
    assert "calibration_sessions" in out
    assert "geographic_cache" in out
    assert "tmp_parquet" in out
    assert "stale_running_sims" in out
    assert "expired_trash" in out
    assert "orphan_stores" in out
    assert "pending_purges" in out


def test_gc_apply_invocation_no_targets(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Summary" in out


def test_gc_removes_tmp_parquet(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    tmp_file = workspace / "data" / "spurious.tmp-abc.parquet"
    tmp_file.write_bytes(b"x")
    _age_path(tmp_file)
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    assert not tmp_file.exists()


def test_gc_removes_orphan_geographic_cache(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    cache_dir = workspace / "geographic" / "deadbeef"
    cache_dir.mkdir(parents=True)
    (cache_dir / "blob.bin").write_bytes(b"y")

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    assert not cache_dir.exists()


def test_gc_plan_does_not_remove_anything(monkeypatch, tmp_path) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    tmp_file = workspace / "data" / "still.tmp-keep.parquet"
    tmp_file.write_bytes(b"keep")
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace)])
    assert code == 0
    assert tmp_file.exists()


def test_gc_marks_stale_running_simulation(monkeypatch, tmp_path) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")

    # Force a running sim with an old event-stream heartbeat.
    cat_path = catalog_path_for(project)
    conn = duckdb.connect(str(cat_path))
    try:
        conn.execute(
            """
            INSERT INTO simulations
                (sim_id, name, project, solver_id, status_id, zarr_path,
                 storage_basename, mesh_topology_id)
            VALUES (?, ?, ?,
                    (SELECT id FROM solvers WHERE code = 'modflow6'),
                    (SELECT id FROM statuses WHERE code = 'running'),
                    ?, ?,
                    (SELECT id FROM mesh_topologies WHERE code = 'structured_3d'))
            """,
            [
                "00000000-0000-0000-0000-000000000001",
                "stale",
                "demo",
                f"{RUNS_DIRNAME}/stale/{FIELDS_STORE_NAME}",
                "stale",
            ],
        )
        conn.execute(
            """
            INSERT INTO workflow_events (run_id, step_name, event_type, ts)
            VALUES (?, 'pipeline', 'heartbeat', TIMESTAMP '2000-01-01 00:00:00+00')
            """,
            ["00000000-0000-0000-0000-000000000001"],
        )
    finally:
        conn.close()

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0

    conn = duckdb.connect(str(cat_path), read_only=True)
    try:
        row = conn.execute(
            "SELECT st.code FROM simulations s "
            "JOIN statuses st ON s.status_id = st.id "
            "WHERE s.sim_id = ?",
            ["00000000-0000-0000-0000-000000000001"],
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "failed"


# ---------------------------------------------------------------------------
# Absorbed vacuum + expiry + orphan stores + purge replay
# ---------------------------------------------------------------------------


def _register_completed(catalog, sid, name):
    catalog.register_simulation(sid, project="demo", solver="modflow6", name=name)
    catalog._backend.execute(
        "UPDATE simulations SET status_id = (SELECT id FROM statuses WHERE code = 'completed'), "
        "ended_at = current_timestamp WHERE sim_id = ?",
        [sid],
    )


def test_gc_apply_runs_maintenance(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    _make_project_with_catalog(workspace, "demo")
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    out = capsys.readouterr().out
    assert "catalog_checkpoints" in out
    assert "zarr_consolidated" in out


def test_gc_purges_expired_trash_but_keeps_pinned(monkeypatch, tmp_path) -> None:
    import uuid

    from hydromodpy.results.catalog import Catalog

    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    old, pinned = str(uuid.uuid4()), str(uuid.uuid4())
    with Catalog(project) as cat:
        _register_completed(cat, old, "old")
        _register_completed(cat, pinned, "keep")
        cat.add_tag(pinned, "pinned")
        cat.trash(old)
        cat.trash(pinned, force=True)
        cat._backend.execute(
            "UPDATE simulations SET trashed_at = current_timestamp - INTERVAL '60 days' "
            "WHERE sim_id IN (?, ?)",
            [old, pinned],
        )

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    with Catalog(project) as cat:
        assert cat._backend.fetch_one("SELECT 1 FROM simulations WHERE sim_id = ?", [old]) is None
        assert (
            cat._backend.fetch_one("SELECT 1 FROM simulations WHERE sim_id = ?", [pinned])
            is not None
        )


def test_gc_quarantines_orphan_store(monkeypatch, tmp_path) -> None:
    """An orphan run directory leaves ``runs/`` for the trash, bytes intact."""
    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    orphan = _make_orphan_run(project, "ghost_run")

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    assert not orphan.exists()
    quarantined = sorted((project / ".hmp" / "trash").glob("*/ghost_run"))
    assert len(quarantined) == 1
    assert (quarantined[0] / FIELDS_STORE_NAME / ".zgroup").read_text() == "{}"


def test_gc_plan_keeps_orphan_store_in_place(monkeypatch, tmp_path, capsys) -> None:
    """Without ``--apply`` the orphan run is only listed, never moved."""
    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    orphan = _make_orphan_run(project, "ghost_run")

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace)])
    assert code == 0
    assert orphan.exists()
    assert not (project / ".hmp" / "trash").exists()
    out = capsys.readouterr().out
    assert "ghost_run" in out
    assert "never deleted" in out


def test_gc_keeps_recent_orphan_store(monkeypatch, tmp_path) -> None:
    """A fresh (in-flight) run is never swept: the mtime grace guard protects it."""
    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    fresh = runs_dir_for(project) / "fresh_run"
    (fresh / FIELDS_STORE_NAME).mkdir(parents=True)
    (fresh / FIELDS_STORE_NAME / ".zgroup").write_text("{}")  # young mtime

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    assert fresh.exists()


def test_gc_keeps_a_sealed_orphan_run(monkeypatch, tmp_path) -> None:
    """A sealed run is re-indexable, so gc leaves it where reindex will find it."""
    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    store = runs_dir_for(project) / "sealed_run"
    tables = store / TABLES_DIRNAME
    tables.mkdir(parents=True)
    (tables / "simulation.parquet").write_bytes(b"snapshot")
    (store / RUN_MANIFEST_FILENAME).write_text("{}")
    _age_path(store / RUN_MANIFEST_FILENAME)
    _age_path(tables / "simulation.parquet")
    _age_path(tables)
    _age_path(store)

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    assert store.exists()


def test_gc_keeps_recent_tmp_parquet(monkeypatch, tmp_path) -> None:
    """A fresh tmp-* staging file (a live atomic write) is never swept."""
    workspace = _make_minimal_workspace(tmp_path)
    tmp_file = workspace / "data" / "live.tmp-write.parquet"
    tmp_file.write_bytes(b"x")  # freshly written -> young mtime
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    assert tmp_file.exists()


def test_gc_replays_pending_purge(monkeypatch, tmp_path) -> None:
    import uuid

    from hydromodpy.results.catalog import Catalog

    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    sid = str(uuid.uuid4())
    with Catalog(project) as cat:
        _register_completed(cat, sid, "halfpurged")
        cat._backend.execute(
            "INSERT INTO purge_journal (sim_id, phase) VALUES (?, 'pending')", [sid]
        )

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    with Catalog(project) as cat:
        assert cat._backend.fetch_one("SELECT 1 FROM purge_journal WHERE sim_id = ?", [sid]) is None
        assert cat._backend.fetch_one("SELECT 1 FROM simulations WHERE sim_id = ?", [sid]) is None


# ---------------------------------------------------------------------------
# Retention policy
# ---------------------------------------------------------------------------


def _make_lineage(project: Path, stem: str, count: int) -> list[str]:
    """Register and finalize ``count`` versions of one run name, oldest first.

    Each version is sealed, so it owns a directory on disk: that is what a
    trash marker needs to be written next to.
    """
    import uuid

    from hydromodpy.results.catalog import Catalog

    sids = [str(uuid.uuid4()) for _ in range(count)]
    with Catalog(project) as cat:
        for sid in sids:
            reg = cat.register_simulation(sid, project="demo", solver="modflow6", name=stem)
            if reg.zarr is not None:
                reg.zarr.close()
            cat.write_parameters(sid, [{"param_name": "K", "value": 1e-5}])
            cat.finalize(sid, status="completed", duration_s=1.0)
    return sids


def _status_of(project: Path, sid: str) -> str:
    from hydromodpy.results.catalog import Catalog

    with Catalog(project, read_only=True) as cat:
        row = cat._backend.fetch_one(
            "SELECT st.code FROM simulations s JOIN statuses st ON s.status_id = st.id "
            "WHERE s.sim_id = ?",
            [sid],
        )
    return "" if row is None else str(row[0])


def test_gc_plans_the_versions_beyond_the_retention_window(monkeypatch, tmp_path, capsys) -> None:
    """Only the newest versions of a lineage survive the policy; the plan says so."""
    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    sids = _make_lineage(project, "cheze", 5)

    code = _run(
        monkeypatch,
        ["hmp", "catalog", "gc", "--workspace", str(workspace), "--keep-versions", "2"],
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "superseded_runs: 3 candidate(s)" in out
    for sid in sids[:3]:
        assert sid in out
    for sid in sids[3:]:
        assert sid not in out
    # A plan changes nothing.
    assert all(_status_of(project, sid) == "completed" for sid in sids)


def test_gc_default_policy_keeps_a_short_lineage(monkeypatch, tmp_path, capsys) -> None:
    """Prudent default: a lineage shorter than the window is never touched."""
    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    _make_lineage(project, "cheze", 3)

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace)])
    assert code == 0
    assert "superseded_runs: 0 candidate(s)" in capsys.readouterr().out


def test_gc_keep_versions_all_disables_the_rule(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    _make_lineage(project, "cheze", 6)

    code = _run(
        monkeypatch,
        ["hmp", "catalog", "gc", "--workspace", str(workspace), "--keep-versions", "all"],
    )
    assert code == 0
    assert "superseded_runs: 0 candidate(s)" in capsys.readouterr().out


def test_gc_apply_moves_superseded_runs_to_the_trash(monkeypatch, tmp_path) -> None:
    """Retention trashes, it does not delete: marker on disk, bytes still there."""
    from hydromodpy.results.storage.contract import RUN_TRASH_FILENAME

    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    sids = _make_lineage(project, "cheze", 4)

    code = _run(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "gc",
            "--workspace",
            str(workspace),
            "--keep-versions",
            "2",
            "--apply",
        ],
    )
    assert code == 0
    assert [_status_of(project, sid) for sid in sids] == [
        "trashed",
        "trashed",
        "completed",
        "completed",
    ]
    assert (runs_dir_for(project) / "cheze" / RUN_TRASH_FILENAME).is_file()
    assert (runs_dir_for(project) / "cheze" / RUN_MANIFEST_FILENAME).is_file()
    assert (runs_dir_for(project) / "cheze.v4").is_dir()
    assert not (runs_dir_for(project) / "cheze.v4" / RUN_TRASH_FILENAME).exists()


def test_gc_retention_spares_a_protected_run(monkeypatch, tmp_path) -> None:
    """A ``pinned`` run survives every retention rule."""
    from hydromodpy.results.catalog import Catalog

    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    sids = _make_lineage(project, "cheze", 4)
    with Catalog(project) as cat:
        cat.add_tag(sids[0], "pinned")

    code = _run(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "gc",
            "--workspace",
            str(workspace),
            "--keep-versions",
            "2",
            "--apply",
        ],
    )
    assert code == 0
    assert _status_of(project, sids[0]) == "completed"
    assert _status_of(project, sids[1]) == "trashed"


def test_gc_expires_runs_past_the_age_limit(monkeypatch, tmp_path) -> None:
    from hydromodpy.results.catalog import Catalog

    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    old, recent = _make_lineage(project, "aged", 1)[0], _make_lineage(project, "fresh", 1)[0]
    with Catalog(project) as cat:
        cat._backend.execute(
            "UPDATE simulations SET created_at = current_timestamp - INTERVAL '400 days' "
            "WHERE sim_id = ?",
            [old],
        )

    code = _run(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "gc",
            "--workspace",
            str(workspace),
            "--max-age-days",
            "365",
            "--apply",
        ],
    )
    assert code == 0
    assert _status_of(project, old) == "trashed"
    assert _status_of(project, recent) == "completed"


def test_gc_quarantines_regenerable_figures_only_on_request(monkeypatch, tmp_path) -> None:
    """Figures are rebuildable, so they may be swept, but only when asked."""
    from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME

    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")
    _make_lineage(project, "cheze", 1)
    figures = runs_dir_for(project) / "cheze" / RUN_FIGURES_DIRNAME
    figures.mkdir(parents=True)
    (figures / "head.png").write_bytes(b"png")
    _age_path(figures / "head.png")
    _age_path(figures)

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--apply"])
    assert code == 0
    assert (figures / "head.png").is_file()

    code = _run(
        monkeypatch,
        ["hmp", "catalog", "gc", "--workspace", str(workspace), "--purge-figures", "--apply"],
    )
    assert code == 0
    assert not figures.exists()
    quarantined = sorted((project / ".hmp" / "trash").glob(f"*/cheze/{RUN_FIGURES_DIRNAME}"))
    assert len(quarantined) == 1
    assert (quarantined[0] / "head.png").read_bytes() == b"png"


def test_gc_rejects_a_retention_window_of_zero(monkeypatch, tmp_path) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    code = _run(
        monkeypatch,
        ["hmp", "catalog", "gc", "--workspace", str(workspace), "--keep-versions", "0"],
    )
    assert code == 2
