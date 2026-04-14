from __future__ import annotations

import json
import uuid

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import SimulationCatalog


@pytest.fixture
def catalog(tmp_path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


def _sid():
    return str(uuid.uuid4())


def _populate(catalog, sid, project="test"):
    catalog.register_simulation(
        sid, project=project, solver="modflow6",
        n_cells=10, n_layers=1,
    )
    catalog.write_parameters(sid, [
        {"param_name": "K", "value": 1.5, "unit": "m/d"},
    ])
    idx = pd.date_range("2020-01-01", periods=5, freq="D")
    catalog.write_timeseries(sid, "P01", "head", pd.Series(np.ones(5), index=idx))
    catalog.write_budget(sid, 0, "z1", "recharge", 100.0, 0.0)
    catalog.write_mass_balance(sid, 0, 100.0, 95.0, 5.0)
    catalog.write_metric(sid, "P01", "nse", 0.85)
    catalog.write_provenance(sid, "dem", "dem.tif", np.ones(10))
    catalog.finalize(sid, "completed", 42.0)


class TestExportSimulation:
    def test_creates_package(self, catalog, tmp_path):
        sid = _sid()
        _populate(catalog, sid)
        out = tmp_path / "export.hmp"
        catalog.export_simulation(sid, out)
        assert (out / "simulation.duckdb").exists()
        assert (out / "results.zarr.zip").exists()

    def test_package_contains_sim_data(self, catalog, tmp_path):
        sid = _sid()
        _populate(catalog, sid)
        out = tmp_path / "export.hmp"
        catalog.export_simulation(sid, out)

        import duckdb
        pkg = duckdb.connect(str(out / "simulation.duckdb"), read_only=True)
        count = pkg.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
        assert count == 1
        params = pkg.execute("SELECT COUNT(*) FROM parameters").fetchone()[0]
        assert params == 1
        ts = pkg.execute("SELECT COUNT(*) FROM timeseries").fetchone()[0]
        assert ts == 5
        pkg.close()

    def test_not_found_raises(self, catalog, tmp_path):
        with pytest.raises(KeyError):
            catalog.export_simulation("nonexistent", tmp_path / "nope.hmp")


class TestImportSimulation:
    def test_import_roundtrip(self, tmp_path):
        ws1 = tmp_path / "ws1"
        ws2 = tmp_path / "ws2"

        cat1 = SimulationCatalog(ws1)
        sid = _sid()
        _populate(cat1, sid)
        pkg = tmp_path / "transfer.hmp"
        cat1.export_simulation(sid, pkg)
        cat1.close()

        cat2 = SimulationCatalog(ws2)
        imported_sid = cat2.import_simulation(pkg)
        assert imported_sid == sid

        count = cat2.connection.execute(
            "SELECT COUNT(*) FROM simulations"
        ).fetchone()[0]
        assert count == 1

        params = cat2.connection.execute(
            "SELECT COUNT(*) FROM parameters WHERE sim_id = ?", [sid]
        ).fetchone()[0]
        assert params == 1
        cat2.close()

    def test_import_duplicate_raises(self, catalog, tmp_path):
        sid = _sid()
        _populate(catalog, sid)
        pkg = tmp_path / "dup.hmp"
        catalog.export_simulation(sid, pkg)

        with pytest.raises(ValueError, match="already exists"):
            catalog.import_simulation(pkg)

    def test_import_force_overwrites(self, catalog, tmp_path):
        sid = _sid()
        _populate(catalog, sid)
        pkg = tmp_path / "force.hmp"
        catalog.export_simulation(sid, pkg)

        imported = catalog.import_simulation(pkg, force=True)
        assert imported == sid
        count = catalog.connection.execute(
            "SELECT COUNT(*) FROM simulations WHERE sim_id = ?", [sid]
        ).fetchone()[0]
        assert count == 1

    def test_import_updates_zarr_path(self, tmp_path):
        ws1 = tmp_path / "ws1"
        ws2 = tmp_path / "ws2"

        cat1 = SimulationCatalog(ws1)
        sid = _sid()
        _populate(cat1, sid)
        pkg = tmp_path / "path_test.hmp"
        cat1.export_simulation(sid, pkg)
        cat1.close()

        cat2 = SimulationCatalog(ws2)
        cat2.import_simulation(pkg)
        zarr_path = cat2.connection.execute(
            "SELECT zarr_path FROM simulations WHERE sim_id = ?", [sid]
        ).fetchone()[0]
        assert zarr_path == f"simulations/{sid}.zarr.zip"
        assert (ws2 / zarr_path).exists()
        cat2.close()


class TestCalibrationPersist:
    def test_persist_to_catalog(self, catalog, tmp_path):
        sid = _sid()
        _populate(catalog, sid)

        manifest_path = tmp_path / "session_manifest.json"
        history_path = tmp_path / "iteration_history.jsonl"

        manifest = {
            "method": "scipy_minimize",
            "iteration_count": 3,
            "cost_best": 0.15,
            "wall_seconds": 120.5,
            "core_settings": {"method": "scipy_minimize", "maxiter": 100},
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        records = [
            {"params": {"K": 1.0, "Sy": 0.05}, "cost": 0.5, "duration_s": 30.0},
            {"params": {"K": 1.5, "Sy": 0.03}, "cost": 0.3, "duration_s": 35.0},
            {"params": {"K": 1.8, "Sy": 0.04}, "cost": 0.15, "duration_s": 40.0},
        ]
        history_path.write_text(
            "\n".join(json.dumps(r) for r in records),
            encoding="utf-8",
        )

        from dataclasses import dataclass, field
        from pathlib import Path

        @dataclass(frozen=True)
        class FakeSession:
            session_manifest_path: Path
            iteration_history_path: Path

        fake = FakeSession(
            session_manifest_path=manifest_path,
            iteration_history_path=history_path,
        )

        from hydromodpy.analysis.calibration.engine.session import persist_to_catalog
        persist_to_catalog(fake, catalog, best_sim_id=sid)

        sessions = catalog.connection.execute(
            "SELECT method, n_iterations, best_objective, best_sim_id "
            "FROM calibration_sessions"
        ).fetchone()
        assert sessions[0] == "scipy_minimize"
        assert sessions[1] == 3
        assert sessions[2] == pytest.approx(0.15)
        assert str(sessions[3]) == sid

        iterations = catalog.connection.execute(
            "SELECT COUNT(*) FROM calibration_iterations"
        ).fetchone()[0]
        assert iterations == 3
