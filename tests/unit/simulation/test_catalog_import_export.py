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
    reg = catalog.register_simulation(
        sid,
        project=project,
        solver="modflow6",
        n_cells=10,
        n_layers=1,
    )
    if reg.zarr is not None:
        reg.zarr.close()
    catalog.write_parameters(
        sid,
        [
            {"param_name": "K", "value": 1.5, "unit": "m/d"},
        ],
    )
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
        produced = catalog.export_package(sid, out)
        assert produced.is_file()
        assert produced.suffix == ".hmp"
        # tar.zst magic: first 4 bytes are 0x28B52FFD
        assert produced.read_bytes()[:4] == b"\x28\xb5\x2f\xfd"

    def test_package_contains_sim_data(self, catalog, tmp_path):
        import io
        import json
        import tarfile

        import zstandard as zstd

        sid = _sid()
        _populate(catalog, sid)
        out = tmp_path / "export.hmp"
        catalog.export_package(sid, out)

        dctx = zstd.ZstdDecompressor()
        with open(out, "rb") as fh:
            raw = dctx.decompress(fh.read())
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar:
            names = tar.getnames()
            expected = {
                f"{sid}/manifest.json",
                f"{sid}/catalog_snapshot.duckdb",
                f"{sid}/simulation.zarr.zip",
                f"{sid}/README.md",
            }
            assert expected <= set(names)

            manifest_bytes = tar.extractfile(f"{sid}/manifest.json").read()
            manifest = json.loads(manifest_bytes)
            assert manifest["sim_id"] == sid
            assert manifest["format"].startswith("hydromodpy/hmp")
            assert len(manifest["files"]) >= 3
            for entry in manifest["files"]:
                assert len(entry["sha256"]) == 64

    def test_not_found_raises(self, catalog, tmp_path):
        with pytest.raises(KeyError):
            catalog.export_package("nonexistent", tmp_path / "nope.hmp")


class TestImportSimulation:
    def test_import_roundtrip(self, tmp_path):
        ws1 = tmp_path / "ws1"
        ws2 = tmp_path / "ws2"

        cat1 = SimulationCatalog(ws1)
        sid = _sid()
        _populate(cat1, sid)
        pkg = cat1.export_package(sid, tmp_path / "transfer.hmp")
        cat1.close()

        cat2 = SimulationCatalog(ws2)
        imported_sid = cat2.import_package(pkg)
        assert imported_sid == sid

        count = cat2.connection.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
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
        produced = catalog.export_package(sid, pkg)

        with pytest.raises(ValueError, match="already exists"):
            catalog.import_package(produced)

    def test_import_rejects_tampered_archive(self, tmp_path):
        """Flip a byte in the archive — SHA-256 verification must fail."""
        ws1 = tmp_path / "ws1"
        ws2 = tmp_path / "ws2"

        cat1 = SimulationCatalog(ws1)
        sid = _sid()
        _populate(cat1, sid)
        pkg = cat1.export_package(sid, tmp_path / "tampered.hmp")
        cat1.close()

        # Corrupt a byte in the middle of the archive
        raw = bytearray(pkg.read_bytes())
        raw[len(raw) // 2] ^= 0xFF
        pkg.write_bytes(bytes(raw))

        cat2 = SimulationCatalog(ws2)
        with pytest.raises((ValueError, Exception)):
            cat2.import_package(pkg)
        cat2.close()

    def test_import_force_overwrites(self, catalog, tmp_path):
        sid = _sid()
        _populate(catalog, sid)
        pkg = tmp_path / "force.hmp"
        produced = catalog.export_package(sid, pkg)

        imported = catalog.import_package(produced, force=True)
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
        pkg = cat1.export_package(sid, tmp_path / "path_test.hmp")
        cat1.close()

        cat2 = SimulationCatalog(ws2)
        cat2.import_package(pkg)
        zarr_path, basename = cat2.connection.execute(
            "SELECT zarr_path, storage_basename FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert basename  # non-null basename populated on import
        assert zarr_path == f"simulations/{basename}.zarr.zip"
        assert (ws2 / zarr_path).exists()
        cat2.close()


class TestCalibrationPersist:
    @pytest.mark.skip(reason="legacy persist_to_catalog superseded by P09 hydromodpy/calibration")
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
            "SELECT method, n_iterations, best_objective, best_sim_id FROM calibration_sessions"
        ).fetchone()
        assert sessions[0] == "scipy_minimize"
        assert sessions[1] == 3
        assert sessions[2] == pytest.approx(0.15)
        assert str(sessions[3]) == sid

        iterations = catalog.connection.execute(
            "SELECT COUNT(*) FROM calibration_iterations"
        ).fetchone()[0]
        assert iterations == 3
