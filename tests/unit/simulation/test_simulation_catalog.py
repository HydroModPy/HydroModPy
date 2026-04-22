from __future__ import annotations

import uuid

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.catalog_schema import GLOBAL_ZONE


@pytest.fixture
def catalog(tmp_path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


def _sim_id():
    return str(uuid.uuid4())


def _register(catalog, sim_id=None, **kwargs):
    sid = sim_id or _sim_id()
    defaults = dict(project="test_project", solver="modflow6")
    defaults.update(kwargs)
    reg = catalog.register_simulation(sid, **defaults)
    return sid, reg.zarr


class TestRegisterAndFinalize:
    def test_register_creates_row(self, catalog):
        sid, _ = _register(catalog)
        row = catalog.connection.execute(
            "SELECT project, solver, status FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row == ("test_project", "modflow6", "running")

    def test_register_with_zarr(self, catalog):
        sid, sz = _register(catalog, n_cells=50, n_layers=2)
        assert sz is not None
        assert "mesh" in sz.root
        zarr_dir = catalog.workspace_path / "simulations" / f"{sid}.zarr"
        assert zarr_dir.exists()
        sz.close()

    def test_register_without_zarr(self, catalog):
        _, sz = _register(catalog)
        assert sz is None

    def test_solver_category_auto_distributed(self, catalog):
        sid, _ = _register(catalog, solver="modflownwt")
        row = catalog.connection.execute(
            "SELECT solver_category FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row[0] == "distributed"

    def test_solver_category_auto_integrated(self, catalog):
        sid, _ = _register(catalog, solver="boussinesq")
        row = catalog.connection.execute(
            "SELECT solver_category FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row[0] == "integrated"

    def test_solver_category_unknown(self, catalog):
        sid, _ = _register(catalog, solver="exotic_solver")
        row = catalog.connection.execute(
            "SELECT solver_category FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row[0] is None

    def test_finalize_updates(self, catalog):
        sid, _ = _register(catalog)
        catalog.finalize(sid, status="completed", duration_s=42.5)
        row = catalog.connection.execute(
            "SELECT status, duration_s FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row == ("completed", 42.5)

    def test_config_hash_computed(self, catalog):
        sid, _ = _register(catalog, config={"flow": {"K": 1.5}})
        row = catalog.connection.execute(
            "SELECT config_hash FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row[0] is not None
        assert len(row[0]) == 64  # SHA-256 hex

    def test_on_collision_replace_is_soft(self, catalog):
        """``on_collision='replace'`` (default) moves the name pointer.

        The previous sim_id survives in the catalog but loses its name,
        preserving an immutable audit trail while keeping the name reusable.
        """
        sid1, _ = _register(catalog, name="r1", n_cells=10, n_layers=1)
        sid2, _ = _register(catalog, name="r1", n_cells=10, n_layers=1)
        count = catalog.connection.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
        assert count == 2
        current = catalog.connection.execute(
            "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE name = ?",
            ["r1"],
        ).fetchone()
        assert current is not None
        assert current[0] == sid2
        orphan_name = catalog.connection.execute(
            "SELECT name FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?",
            [sid1],
        ).fetchone()
        assert orphan_name[0] is None

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

        zarr_dir = catalog.workspace_path / "simulations" / f"{sid}.zarr"
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
        with SimulationCatalog(tmp_path / "ws") as cat:
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
