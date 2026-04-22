"""End-to-end: export bundles tracked inputs into the .hmp archive."""

from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import zstandard as zstd

import hydromodpy as hmp
from hydromodpy.results.exporters.hmp_package import (
    INPUTS_MANIFEST_NAME,
    INPUTS_SUBDIR,
    MANIFEST_NAME,
)


def _inspect_archive(archive_path: Path) -> dict:
    """Extract archive into a temp dir and return the manifest dict."""
    dctx = zstd.ZstdDecompressor()
    with open(archive_path, "rb") as fh:
        raw = dctx.decompress(fh.read())
    tmp = Path(tempfile.mkdtemp(prefix="hmp_inspect_"))
    import io
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar:
        tar.extractall(str(tmp), filter="data")
    roots = [p for p in tmp.iterdir() if p.is_dir()]
    assert len(roots) == 1
    pkg = roots[0]
    manifest = json.loads((pkg / MANIFEST_NAME).read_text())
    return {"pkg": pkg, "manifest": manifest}


def test_export_bundles_registered_inputs(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    dem_file = tmp_path / "dem.tif"
    dem_file.write_bytes(b"fake-dem-bytes")
    expected_sha = hashlib.sha256(b"fake-dem-bytes").hexdigest()

    sim_id = str(uuid4())
    with hmp.open(workspace) as catalog:
        catalog.register_simulation(
            sim_id=sim_id,
            project="with_inputs",
            solver="modflow_nwt",
            name="with_inputs_sim",
            n_cells=4,
            n_layers=1,
        )

        from dataclasses import dataclass

        @dataclass
        class _E:
            role: str
            category: str
            original_path: str
            canonical_path: Path
            portable: bool = True

        catalog.register_tracked_files(
            sim_id,
            [_E("dem", "data", "~/data/dem.tif", dem_file.resolve())],
        )

        sz = catalog.open_zarr(sim_id)
        sz.write_field(
            variable="head", timestep=0,
            values=np.full((1, 4), 1.0, dtype="float32"),
            n_timesteps=1,
        )
        catalog.finalize(sim_id, status="completed")
        archive = catalog.export_package(sim_id, tmp_path / "out.hmp")

    assert archive.exists()
    result = _inspect_archive(archive)
    manifest = result["manifest"]
    pkg = result["pkg"]

    assert manifest["has_inputs"] is True
    assert len(manifest["inputs"]) == 1
    entry = manifest["inputs"][0]
    assert entry["role"] == "dem"
    assert entry["sha256"] == expected_sha

    archived = pkg / entry["archive_path"]
    assert archived.is_file()
    assert archived.read_bytes() == b"fake-dem-bytes"

    inputs_manifest_path = pkg / INPUTS_SUBDIR / INPUTS_MANIFEST_NAME
    assert inputs_manifest_path.is_file()
    parsed = json.loads(inputs_manifest_path.read_text())
    assert parsed == manifest["inputs"]


def test_export_without_inputs_still_succeeds(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    sim_id = str(uuid4())
    with hmp.open(workspace) as catalog:
        catalog.register_simulation(
            sim_id=sim_id,
            project="no_inputs",
            solver="modflow_nwt",
            name="no_inputs_sim",
            n_cells=4, n_layers=1,
        )
        sz = catalog.open_zarr(sim_id)
        sz.write_field(
            variable="head", timestep=0,
            values=np.full((1, 4), 1.0, dtype="float32"),
            n_timesteps=1,
        )
        catalog.finalize(sim_id, status="completed")
        archive = catalog.export_package(sim_id, tmp_path / "out.hmp")

    manifest = _inspect_archive(archive)["manifest"]
    assert manifest["has_inputs"] is False
    assert manifest["inputs"] == []


def test_export_bundles_shapefile_group(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    shp = tmp_path / "watershed.shp"
    shx = tmp_path / "watershed.shx"
    dbf = tmp_path / "watershed.dbf"
    prj = tmp_path / "watershed.prj"
    shp.write_bytes(b"shp")
    shx.write_bytes(b"shx")
    dbf.write_bytes(b"dbf")
    prj.write_text("GEOGCS[...]")

    sim_id = str(uuid4())
    with hmp.open(workspace) as catalog:
        catalog.register_simulation(
            sim_id=sim_id, project="shp", solver="modflow_nwt",
            name="shp_sim", n_cells=2, n_layers=1,
        )
        from dataclasses import dataclass

        @dataclass
        class _E:
            role: str
            category: str
            original_path: str
            canonical_path: Path
            portable: bool = True

        catalog.register_tracked_files(
            sim_id,
            [_E("watershed_polygon", "geometry",
                str(shp), shp.resolve())],
        )
        sz = catalog.open_zarr(sim_id)
        sz.write_field(
            variable="head", timestep=0,
            values=np.full((1, 2), 1.0, dtype="float32"),
            n_timesteps=1,
        )
        catalog.finalize(sim_id, status="completed")
        archive = catalog.export_package(sim_id, tmp_path / "out.hmp")

    result = _inspect_archive(archive)
    pkg = result["pkg"]
    manifest = result["manifest"]
    entry = manifest["inputs"][0]
    assert entry["archive_path"].endswith(".shp.zip")

    import zipfile
    with zipfile.ZipFile(str(pkg / entry["archive_path"]), "r") as zf:
        names = sorted(zf.namelist())
    assert names == ["watershed.dbf", "watershed.prj", "watershed.shp", "watershed.shx"]


def test_export_bundles_directory_input(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src_dir = tmp_path / "hydrometry_dataset"
    (src_dir / "chronicles").mkdir(parents=True)
    (src_dir / "loc.csv").write_text("id,x,y\nA,0,0\n")
    (src_dir / "chronicles" / "A.csv").write_text("datetime,value\n2020-01-01,1.0\n")

    sim_id = str(uuid4())
    with hmp.open(workspace) as catalog:
        catalog.register_simulation(
            sim_id=sim_id, project="hydro", solver="modflow_nwt",
            name="hydro_sim", n_cells=2, n_layers=1,
        )

        # Directory inputs need a workaround: the registry uses is_file for hash,
        # so we register a synthetic tar entry by packaging the dir ourselves.
        # For the walker this is irrelevant: the real pipeline registers
        # directory-typed inputs via the walker -> catalog.register_tracked_files
        # after sha256 on individual files. For this test we instead insert
        # a row manually with a sentinel sha256.
        import hashlib as _h
        sha = _h.sha256(b"dir").hexdigest()
        catalog.connection.execute(
            """INSERT INTO tracked_files
               (sim_id, role, category, original_path, canonical_path,
                sha256, size_bytes, portable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [sim_id, "hydrometry", "data", str(src_dir), str(src_dir.resolve()),
             sha, 0, True],
        )
        sz = catalog.open_zarr(sim_id)
        sz.write_field(
            variable="head", timestep=0,
            values=np.full((1, 2), 1.0, dtype="float32"),
            n_timesteps=1,
        )
        catalog.finalize(sim_id, status="completed")
        archive = catalog.export_package(sim_id, tmp_path / "out.hmp")

    result = _inspect_archive(archive)
    pkg = result["pkg"]
    manifest = result["manifest"]
    entry = manifest["inputs"][0]
    assert entry["is_directory"] is True
    bundled_dir = pkg / entry["archive_path"]
    assert bundled_dir.is_dir()
    assert (bundled_dir / "loc.csv").is_file()
    assert (bundled_dir / "chronicles" / "A.csv").is_file()
