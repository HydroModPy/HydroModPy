"""Integration of the tracked-files table and registration helper."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from hydromodpy.results.catalog import SimulationCatalog


@dataclass
class _Entry:
    role: str
    category: str
    original_path: str
    canonical_path: Path
    portable: bool = True


def _make_catalog(tmp_path: Path) -> SimulationCatalog:
    catalog = SimulationCatalog(tmp_path / "ws")
    return catalog


def test_tracked_files_table_exists(tmp_path: Path) -> None:
    with _make_catalog(tmp_path) as catalog:
        rows = catalog.connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = 'tracked_files'"
        ).fetchall()
    assert len(rows) == 1


def test_register_tracked_files_writes_rows(tmp_path: Path) -> None:
    src = tmp_path / "dem.tif"
    src.write_bytes(b"hello world")
    sid = str(uuid4())

    with _make_catalog(tmp_path) as catalog:
        catalog.register_simulation(
            sim_id=sid,
            project="proj",
            solver="modflow_nwt",
        )
        n = catalog.register_tracked_files(
            sid,
            [
                _Entry(
                    role="dem",
                    category="data",
                    original_path="dem.tif",
                    canonical_path=src.resolve(),
                )
            ],
        )
        assert n == 1
        df = catalog.list_tracked_files(sid)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["role"] == "dem"
    assert row["size_bytes"] == len(b"hello world")
    assert isinstance(row["sha256"], str) and len(row["sha256"]) == 64


def test_register_tracked_files_writes_directory_rows(tmp_path: Path) -> None:
    src = tmp_path / "hydrometry"
    src.mkdir()
    (src / "hydrometry_custom_LOC.csv").write_text("id,x,y\nA,0,0\n")
    (src / "hydrometry_custom_A_20200101_20200101_D.csv").write_text(
        "datetime,value\n2020-01-01,1.0\n"
    )
    sid = str(uuid4())

    with _make_catalog(tmp_path) as catalog:
        catalog.register_simulation(
            sim_id=sid,
            project="proj",
            solver="modflow_nwt",
        )
        n = catalog.register_tracked_files(
            sid,
            [
                _Entry(
                    role="hydrometry",
                    category="data",
                    original_path="hydrometry",
                    canonical_path=src.resolve(),
                )
            ],
        )
        assert n == 1
        df = catalog.list_tracked_files(sid)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["role"] == "hydrometry"
    assert row["size_bytes"] > 0
    assert isinstance(row["sha256"], str) and len(row["sha256"]) == 64


def test_register_tracked_files_is_idempotent(tmp_path: Path) -> None:
    src = tmp_path / "dem.tif"
    src.write_bytes(b"x")
    sid = str(uuid4())

    with _make_catalog(tmp_path) as catalog:
        catalog.register_simulation(
            sim_id=sid,
            project="proj",
            solver="modflow_nwt",
        )
        entry = _Entry(
            role="dem",
            category="data",
            original_path="dem.tif",
            canonical_path=src.resolve(),
        )
        catalog.register_tracked_files(sid, [entry])
        catalog.register_tracked_files(sid, [entry])
        df = catalog.list_tracked_files(sid)
    assert len(df) == 1


def test_register_tracked_files_skips_missing(tmp_path: Path) -> None:
    sid = str(uuid4())
    with _make_catalog(tmp_path) as catalog:
        catalog.register_simulation(
            sim_id=sid,
            project="proj",
            solver="modflow_nwt",
        )
        n = catalog.register_tracked_files(
            sid,
            [
                _Entry(
                    role="dem",
                    category="data",
                    original_path="missing.tif",
                    canonical_path=tmp_path / "does-not-exist.tif",
                )
            ],
        )
        assert n == 0
        df = catalog.list_tracked_files(sid)
    assert df.empty


def test_sha256_is_deterministic(tmp_path: Path) -> None:
    src = tmp_path / "file.bin"
    src.write_bytes(b"deterministic-payload")
    sid = str(uuid4())

    import hashlib

    expected = hashlib.sha256(b"deterministic-payload").hexdigest()

    with _make_catalog(tmp_path) as catalog:
        catalog.register_simulation(
            sim_id=sid,
            project="proj",
            solver="modflow_nwt",
        )
        catalog.register_tracked_files(
            sid,
            [
                _Entry(
                    role="dem",
                    category="data",
                    original_path="file.bin",
                    canonical_path=src.resolve(),
                )
            ],
        )
        row = catalog.connection.execute(
            "SELECT sha256 FROM tracked_files WHERE sim_id = ?",
            [sid],
        ).fetchone()
    assert row[0] == expected
