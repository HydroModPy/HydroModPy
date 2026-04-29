"""Round-trip: export then `hmp add` into a clean workspace."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

import hydromodpy as hmp
from hydromodpy.results.importers import InputCollisionError


@dataclass
class _E:
    role: str
    category: str
    original_path: str
    canonical_path: Path
    portable: bool = True


def _populate_simulation(
    catalog,
    *,
    sim_id: str,
    project: str,
    dem_file: Path,
    original_path: str | None = None,
) -> None:
    catalog.register_simulation(
        sim_id=sim_id,
        project=project,
        solver="modflow_nwt",
        name="round_trip_sim",
        n_cells=2,
        n_layers=1,
        config={"dummy_path": original_path or str(dem_file)},
    )
    catalog.register_tracked_files(
        sim_id,
        [
            _E(
                role="dem",
                category="data",
                original_path=original_path or str(dem_file),
                canonical_path=dem_file.resolve(),
            )
        ],
    )
    sz = catalog.open_zarr(sim_id)
    sz.write_field(
        variable="head",
        timestep=0,
        values=np.full((1, 2), 1.0, dtype="float32"),
        n_timesteps=1,
    )
    catalog.finalize(sim_id, status="completed")


def test_add_copies_inputs_and_rewrites_paths(tmp_path: Path) -> None:
    src_ws = tmp_path / "source"
    dst_ws = tmp_path / "target"
    dem_file = tmp_path / "shared" / "dem_source.tif"
    dem_file.parent.mkdir(parents=True)
    dem_file.write_bytes(b"DEM_PAYLOAD")
    original_path = str(dem_file)

    sim_id = str(uuid4())
    with hmp.open(src_ws) as catalog:
        _populate_simulation(
            catalog,
            sim_id=sim_id,
            project="alpha",
            dem_file=dem_file,
            original_path=original_path,
        )
        archive = catalog.export_package(sim_id, tmp_path / "share.hmp")

    with hmp.open(dst_ws) as target:
        imported = target.import_package(archive)
        assert imported == sim_id

        row = target._connection.execute(
            "SELECT project, config_toml FROM simulations WHERE sim_id = ?",
            [sim_id],
        ).fetchone()
        assert row[0] == "alpha"
        cfg = json.loads(row[1]) if row[1] else {}
        assert cfg.get("dummy_path", "").startswith(str(dst_ws / "data"))

        tf = target._connection.execute(
            "SELECT role, canonical_path, sha256 FROM tracked_files WHERE sim_id = ?",
            [sim_id],
        ).fetchone()
        assert tf[0] == "dem"
        assert Path(tf[1]).read_bytes() == b"DEM_PAYLOAD"


def test_add_dedupes_reimport_of_same_archive(tmp_path: Path) -> None:
    src_ws = tmp_path / "source"
    dst_ws = tmp_path / "target"
    dem_file = tmp_path / "dem.tif"
    dem_file.write_bytes(b"DEM")

    sim_id = str(uuid4())
    with hmp.open(src_ws) as catalog:
        _populate_simulation(
            catalog,
            sim_id=sim_id,
            project="alpha",
            dem_file=dem_file,
        )
        archive = catalog.export_package(sim_id, tmp_path / "share.hmp")

    with hmp.open(dst_ws) as target:
        target.import_package(archive)
        # Re-import requires force=True and a rename (or overwrite) because
        # project 'alpha' already exists. Use --as and force.
        target.import_package(
            archive,
            force=True,
            as_project="alpha_v2",
        )
        rows = target._connection.execute(
            "SELECT DISTINCT role, canonical_path FROM tracked_files"
        ).fetchall()
    # File was reused on the second import (same SHA). Only one physical copy.
    assert len(rows) == 1


def test_add_aborts_on_hash_collision(tmp_path: Path) -> None:
    src_ws = tmp_path / "source"
    dst_ws = tmp_path / "target"
    dem_file = tmp_path / "dem.tif"
    dem_file.write_bytes(b"DEM_v1")

    sim_id = str(uuid4())
    with hmp.open(src_ws) as catalog:
        _populate_simulation(
            catalog,
            sim_id=sim_id,
            project="alpha",
            dem_file=dem_file,
        )
        archive = catalog.export_package(sim_id, tmp_path / "share.hmp")

    # Pre-seed the target workspace with a same-named file but different bytes
    target_data = dst_ws / "data" / "dem"
    target_data.mkdir(parents=True)
    (target_data / "dem.tif").write_bytes(b"DEM_v2_different")

    with hmp.open(dst_ws) as target:
        with pytest.raises(InputCollisionError):
            target.import_package(archive)


def test_add_project_name_conflict_requires_as(tmp_path: Path) -> None:
    src_ws = tmp_path / "source"
    dst_ws = tmp_path / "target"
    dem_file = tmp_path / "dem.tif"
    dem_file.write_bytes(b"DEM")

    sim_id_a = str(uuid4())
    sim_id_b = str(uuid4())
    with hmp.open(src_ws) as catalog:
        _populate_simulation(
            catalog,
            sim_id=sim_id_a,
            project="alpha",
            dem_file=dem_file,
        )
        archive = catalog.export_package(sim_id_a, tmp_path / "share.hmp")

    with hmp.open(dst_ws) as target:
        _populate_simulation(
            target,
            sim_id=sim_id_b,
            project="alpha",
            dem_file=dem_file,
        )

    with hmp.open(dst_ws) as target:
        with pytest.raises(ValueError, match="already exists"):
            target.import_package(archive)
        target.import_package(archive, as_project="alpha_imported")
        rows = target._connection.execute(
            "SELECT project FROM simulations ORDER BY project"
        ).fetchall()
    assert [r[0] for r in rows] == ["alpha", "alpha_imported"]


def test_add_dry_run_writes_nothing(tmp_path: Path) -> None:
    src_ws = tmp_path / "source"
    dst_ws = tmp_path / "target"
    dem_file = tmp_path / "dem.tif"
    dem_file.write_bytes(b"DEM")

    sim_id = str(uuid4())
    with hmp.open(src_ws) as catalog:
        _populate_simulation(
            catalog,
            sim_id=sim_id,
            project="alpha",
            dem_file=dem_file,
        )
        archive = catalog.export_package(sim_id, tmp_path / "share.hmp")

    with hmp.open(dst_ws) as target:
        reported = target.import_package(archive, dry_run=True)
        rows = target._connection.execute("SELECT COUNT(*) FROM simulations").fetchone()
    assert reported == sim_id
    assert rows[0] == 0
    assert not (dst_ws / "data").exists()
