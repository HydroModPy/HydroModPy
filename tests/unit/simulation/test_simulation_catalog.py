from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog import registration as registration_mod
from hydromodpy.results.catalog.constants import GLOBAL_ZONE
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _sim_id():
    return str(uuid.uuid4())


def _register(catalog, sim_id=None, **kwargs):
    sid = sim_id or _sim_id()
    defaults = dict(project="test_project", solver="modflow6")
    defaults.update(kwargs)
    reg = catalog.register_simulation(sid, **defaults)
    return sid, reg.zarr


def test_staged_zarr_promotion_retries_transient_permission_error(tmp_path, monkeypatch):
    source = tmp_path / ".staging.zarr"
    target = tmp_path / "final.zarr"
    source.mkdir()
    (source / "marker").write_text("ok", encoding="utf-8")
    original_rename = Path.rename
    calls = 0

    def flaky_rename(self, target_path):
        nonlocal calls
        if self == source and calls == 0:
            calls += 1
            raise PermissionError(5, "Access denied")
        return original_rename(self, target_path)

    monkeypatch.setattr(registration_mod, "_windows_long_path", lambda path: path)
    monkeypatch.setattr(
        registration_mod,
        "_is_retryable_staged_zarr_rename_error",
        lambda exc: True,
    )
    monkeypatch.setattr(registration_mod.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(Path, "rename", flaky_rename)

    registration_mod._promote_staged_zarr(source, target)

    assert calls == 1
    assert not source.exists()
    assert (target / "marker").read_text(encoding="utf-8") == "ok"


_V2_SIM_SELECT = (
    "SELECT s.project, sv.code AS solver, st.code AS status, "
    "sv.category AS solver_category, s.duration_s "
    "FROM simulations s "
    "JOIN solvers sv ON s.solver_id = sv.id "
    "JOIN statuses st ON s.status_id = st.id "
    "WHERE s.sim_id = ?"
)


class TestRegisterAndFinalize:
    def test_register_creates_row(self, catalog):
        sid, _ = _register(catalog)
        row = catalog.connection.execute(_V2_SIM_SELECT, [sid]).fetchone()
        assert row[0] == "test_project"
        assert row[1] == "modflow6"
        assert row[2] == "running"

    def test_register_with_zarr(self, catalog):
        sid, sz = _register(catalog, n_cells=50, n_layers=2)
        assert sz is not None
        assert "mesh" in sz.root
        zarr_dir = catalog.zarr_path_for(sid)
        assert zarr_dir.exists()
        sz.close()

    def test_register_without_zarr(self, catalog):
        _, sz = _register(catalog)
        assert sz is None

    def test_solver_category_auto_distributed(self, catalog):
        sid, _ = _register(catalog, solver="modflow_nwt")
        row = catalog.connection.execute(_V2_SIM_SELECT, [sid]).fetchone()
        assert row[3] == "distributed"

    def test_solver_category_auto_integrated(self, catalog):
        sid, _ = _register(catalog, solver="boussinesq")
        row = catalog.connection.execute(_V2_SIM_SELECT, [sid]).fetchone()
        assert row[3] == "integrated"

    def test_solver_category_unknown(self, catalog):
        # v2 enforces solver_id NOT NULL via FK to ``solvers.code``; an
        # unknown name resolves to NULL via the INSERT subselect and the
        # NOT NULL constraint rejects the row. This is a behavioural change
        # from the v1 schema where the ``solver`` column was free-text.
        with pytest.raises(Exception):
            _register(catalog, solver="exotic_solver")

    def test_finalize_updates(self, catalog):
        sid, _ = _register(catalog)
        catalog.finalize(sid, status="completed", duration_s=42.5)
        row = catalog.connection.execute(_V2_SIM_SELECT, [sid]).fetchone()
        assert row[2] == "completed"
        assert row[4] == 42.5

    def test_config_hash_computed(self, catalog):
        sid, _ = _register(catalog, config={"flow": {"K": 1.5}})
        row = catalog.connection.execute(
            "SELECT config_hash FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row[0] is not None
        assert len(row[0]) == 64  # SHA-256 hex

    def test_if_exists_version_is_default(self, catalog):
        """``if_exists='version'`` (default) mints ``stem.vN`` and keeps every run.

        The bare name is version 1 for good: the first run is never renamed,
        so the stem grows as ``r1``, ``r1.v2``, ``r1.v3``.
        """
        sid1, _ = _register(catalog, name="r1", n_cells=10, n_layers=1)
        _register(catalog, name="r1", n_cells=10, n_layers=1)
        sid3, _ = _register(catalog, name="r1", n_cells=10, n_layers=1)
        count = catalog.connection.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
        assert count == 3
        names = {
            r[0] for r in catalog.connection.execute("SELECT name FROM simulations").fetchall()
        }
        assert names == {"r1", "r1.v2", "r1.v3"}
        first = catalog.connection.execute(
            "SELECT name, version_int FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?",
            [sid1],
        ).fetchone()
        assert first == ("r1", 1)
        latest = catalog.connection.execute(
            "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE name = 'r1.v3'"
        ).fetchone()
        assert latest[0] == sid3

    def test_registering_a_second_run_leaves_the_first_untouched(self, catalog):
        """A sealed run keeps its name, version and ``updated_at``."""
        sid1, _ = _register(catalog, name="r1", n_cells=10, n_layers=1)
        before = catalog.connection.execute(
            "SELECT name, version_int, updated_at FROM simulations "
            "WHERE CAST(sim_id AS VARCHAR) = ?",
            [sid1],
        ).fetchone()
        _register(catalog, name="r1", n_cells=10, n_layers=1)
        after = catalog.connection.execute(
            "SELECT name, version_int, updated_at FROM simulations "
            "WHERE CAST(sim_id AS VARCHAR) = ?",
            [sid1],
        ).fetchone()
        assert after == before

    def test_if_exists_replace_trashes_predecessor(self, catalog):
        """``if_exists='replace'`` trashes the predecessor, name and version kept."""
        sid1, _ = _register(catalog, name="solo", n_cells=10, n_layers=1)
        sid2, _ = _register(catalog, name="solo", if_exists="replace", n_cells=10, n_layers=1)
        successor = catalog.connection.execute(
            "SELECT name, version_int FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?",
            [sid2],
        ).fetchone()
        assert successor == ("solo.v2", 2)
        predecessor = catalog.connection.execute(
            "SELECT s.name, s.version_int, st.code, s.original_name "
            "FROM simulations s JOIN statuses st ON s.status_id = st.id "
            "WHERE CAST(s.sim_id AS VARCHAR) = ?",
            [sid1],
        ).fetchone()
        assert predecessor == ("solo", 1, "trashed", "solo")

    def test_if_exists_fail_raises(self, catalog):
        _register(catalog, name="solo", n_cells=10, n_layers=1)
        with pytest.raises(registration_mod.DuplicateSimulationNameError):
            _register(catalog, name="solo", if_exists="fail", n_cells=10, n_layers=1)

    def test_parent_sim_id(self, catalog):
        sid1, _ = _register(catalog)
        sid2, _ = _register(catalog, parent_sim_id=sid1)
        row = catalog.connection.execute(
            "SELECT parent_sim_id FROM simulations WHERE sim_id = ?",
            [sid2],
        ).fetchone()
        assert str(row[0]) == sid1


class TestWriteMethods:
    def test_write_parameters_bulk(self, catalog):
        sid, _ = _register(catalog)
        catalog.write_parameters(
            sid,
            [
                {
                    "param_name": "K",
                    "value": 1.728,
                    "unit": "m/d",
                    "parameterization": "homogeneous",
                },
                {"param_name": "Sy", "value": 0.05, "unit": "-", "parameterization": "homogeneous"},
                {
                    "param_name": "K",
                    "zone_id": "granite",
                    "value": 0.5,
                    "unit": "m/d",
                    "parameterization": "geology_mapped",
                },
            ],
        )
        count = catalog.connection.execute(
            "SELECT COUNT(*) FROM parameters WHERE sim_id = ?", [sid]
        ).fetchone()[0]
        assert count == 3

    def test_parameters_global_zone_default(self, catalog):
        sid, _ = _register(catalog)
        catalog.write_parameters(
            sid,
            [
                {"param_name": "K", "value": 1.0},
            ],
        )
        row = catalog.connection.execute(
            "SELECT zone_id FROM parameters WHERE sim_id = ? AND param_name = 'K'",
            [sid],
        ).fetchone()
        assert row[0] == GLOBAL_ZONE

    def test_write_timeseries(self, catalog):
        sid, _ = _register(catalog)
        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        ts = pd.Series(np.arange(30, dtype="float64"), index=idx, name="head")
        catalog.write_timeseries(sid, "P01", "head", ts, unit="m")
        count = catalog.connection.execute(
            "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", [sid]
        ).fetchone()[0]
        assert count == 30

    def test_write_timeseries_empty(self, catalog):
        sid, _ = _register(catalog)
        ts = pd.Series(dtype="float64")
        catalog.write_timeseries(sid, "P01", "head", ts)
        count = catalog.connection.execute(
            "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", [sid]
        ).fetchone()[0]
        assert count == 0

    def test_write_budget(self, catalog):
        sid, _ = _register(catalog)
        catalog.write_budget(sid, 0, "zone_1", "recharge", 100.0, 0.0)
        catalog.write_budget(sid, 0, "zone_1", "drain", 0.0, 80.0)
        count = catalog.connection.execute(
            "SELECT COUNT(*) FROM budgets WHERE sim_id = ?", [sid]
        ).fetchone()[0]
        assert count == 2

    def test_write_mass_balance(self, catalog):
        sid, _ = _register(catalog)
        catalog.write_mass_balance(sid, 0, 100.0, 95.0, 5.0)
        catalog.write_mass_balance(sid, 1, 110.0, 108.0, 1.8)
        rows = catalog.connection.execute(
            "SELECT timestep, percent_error FROM mass_balance WHERE sim_id = ? ORDER BY timestep",
            [sid],
        ).fetchall()
        assert len(rows) == 2
        assert rows[0] == (0, 5.0)

    def test_write_mass_balance_separates_water_and_solute(self, catalog):
        sid, _ = _register(catalog)
        catalog.write_mass_balances(sid, [{"timestep": 0, "percent_error": 1.0}])
        catalog.write_mass_balances(
            sid, [{"timestep": 0, "percent_error": 2.0, "quantity": "solute", "unit": "kg/s"}]
        )
        rows = catalog.connection.execute(
            "SELECT quantity, unit, percent_error FROM mass_balance "
            "WHERE sim_id = ? ORDER BY quantity",
            [sid],
        ).fetchall()
        # Both budgets coexist on the same (sim_id, timestep); no collision.
        assert rows == [("solute", "kg/s", 2.0), ("water", "m3/s", 1.0)]

    def test_update_simulation_grid_metadata_backfills_nulls(self, catalog):
        sid, _ = _register(catalog)
        catalog.update_simulation_grid_metadata(
            sid,
            n_cells=3600,
            n_layers=2,
            mesh_hash="abc123",
            mesh_topology="structured_3d",
            bbox=[10.0, 20.0, 110.0, 220.0],
        )
        row = catalog.connection.execute(
            "SELECT s.n_cells, s.n_layers, s.mesh_hash, mt.code, s.bbox_xmin, s.bbox_ymax "
            "FROM simulations s LEFT JOIN mesh_topologies mt ON mt.id = s.mesh_topology_id "
            "WHERE s.sim_id = ?",
            [sid],
        ).fetchone()
        assert row == (3600, 2, "abc123", "structured_3d", 10.0, 220.0)
        # COALESCE keeps existing values when None is passed.
        catalog.update_simulation_grid_metadata(sid, n_cells=None, mesh_hash=None)
        kept = catalog.connection.execute(
            "SELECT n_cells, mesh_hash FROM simulations WHERE sim_id = ?", [sid]
        ).fetchone()
        assert kept == (3600, "abc123")

    def test_write_metric_upsert(self, catalog):
        sid, _ = _register(catalog)
        catalog.write_metric(sid, "P01", "nse", 0.7)
        catalog.write_metric(sid, "P01", "nse", 0.85)
        count = catalog.connection.execute(
            "SELECT COUNT(*) FROM metrics WHERE sim_id = ?", [sid]
        ).fetchone()[0]
        assert count == 1
        val = catalog.connection.execute(
            "SELECT value FROM metrics WHERE sim_id = ? AND metric_name = 'nse'",
            [sid],
        ).fetchone()[0]
        assert val == pytest.approx(0.85)

    def test_write_provenance(self, catalog):
        sid, _ = _register(catalog)
        data = np.random.default_rng(0).random(100)
        catalog.write_provenance(sid, "recharge", "/data/recharge.nc", data)
        row = catalog.connection.execute(
            "SELECT payload_sha256, n_records FROM provenance WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row[0] is not None
        assert row[1] == 100


class TestDelete:
    def test_delete_cascades(self, catalog):
        sid, sz = _register(catalog, n_cells=10, n_layers=1)
        sz.close()

        catalog.write_parameters(sid, [{"param_name": "K", "value": 1.0}])
        idx = pd.date_range("2020-01-01", periods=5, freq="D")
        catalog.write_timeseries(sid, "P01", "head", pd.Series(np.ones(5), index=idx))
        catalog.write_budget(sid, 0, "z1", "recharge", 10.0, 0.0)
        catalog.write_mass_balance(sid, 0, 10.0, 9.5, 5.0)
        catalog.write_metric(sid, "P01", "nse", 0.8)
        catalog.write_provenance(sid, "dem", "dem.tif", np.ones(10))

        zarr_dir = catalog.zarr_path_for(sid)
        assert zarr_dir.exists()

        catalog.delete(sid)

        for table in (
            "simulations",
            "parameters",
            "timeseries",
            "budgets",
            "mass_balance",
            "metrics",
            "provenance",
        ):
            count = catalog.connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE sim_id = ?", [sid]
            ).fetchone()[0]
            assert count == 0, f"Rows remaining in {table}"

        assert not zarr_dir.exists()


class TestContextManager:
    def test_enter_exit(self, tmp_path):
        with Catalog(tmp_path / "ws") as cat:
            sid, _ = _register(cat)
            row = cat.connection.execute("SELECT COUNT(*) FROM simulations").fetchone()
            assert row[0] == 1


class TestMultipleProjects:
    def test_two_projects_same_db(self, catalog):
        sid1, _ = _register(catalog, project="canut")
        sid2, _ = _register(catalog, project="nancon")
        count = catalog.connection.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
        assert count == 2
        projects = catalog.connection.execute(
            "SELECT DISTINCT project FROM simulations ORDER BY project"
        ).fetchall()
        assert [r[0] for r in projects] == ["canut", "nancon"]
