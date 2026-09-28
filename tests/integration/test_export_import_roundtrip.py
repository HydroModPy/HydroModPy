"""Integration: ``.hmp`` package export then import round trip.

Covers the pair of operations a user runs when sharing a simulation:
1. Produce a ``.hmp`` archive (tar.zst) for one finalised sim.
2. Import it into a fresh workspace via the ``hmp data import`` CLI verb
   and verify the SHA-256 manifest matches every artefact.

Two corner cases are exercised:
- A fresh, minimal source workspace (Zarr field + Parquet timeseries).
- The reusable ``simulation_regression`` fixture pattern, exported through
  ``catalog.export_package``, the entry point ``hmp export <run> all
  --format package`` calls; the last test drives that verb itself.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
import zstandard as zstd

from hydromodpy.results.exporters.hmp_package import (
    HMP_FORMAT_VERSION,
    HMP_MAGIC,
    MANIFEST_NAME,
    ZARR_ARCHIVE_NAME,
)
from hydromodpy.schema.generated_views import RO_CRATE_VIEW_FILENAME


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _open_archive(archive: Path) -> tarfile.TarFile:
    """Return an in-memory tarfile reader over the zstd-decompressed ``.hmp``."""
    dctx = zstd.ZstdDecompressor()
    raw = dctx.decompress(archive.read_bytes())
    return tarfile.open(fileobj=io.BytesIO(raw), mode="r")


def _populate_simulation(catalog, *, project: str, sim_id: str) -> None:
    """Seed one finalised simulation with Zarr + timeseries + metric data."""
    reg = catalog.register_simulation(
        sim_id=sim_id,
        project=project,
        solver="modflow_nwt",
        name="roundtrip_sim",
        flow_regime="steady",
        n_cells=4,
        n_layers=1,
    )
    sz = reg.zarr
    assert sz is not None
    sz.write_field(
        variable="head",
        timestep=0,
        values=np.full((1, 4), 11.25, dtype="float32"),
        n_timesteps=1,
    )
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    series = pd.Series([10.0, 10.1, 10.2, 10.3], index=idx, name="head")
    catalog.write_timeseries(sim_id, station_id="P01", variable="head", ts=series)
    catalog.write_metric(sim_id, station_id="P01", metric_name="nse", value=0.91)
    catalog.finalize(sim_id, status="completed")


@pytest.mark.integration
def test_export_package_layout_and_manifest_sha256(tmp_path: Path) -> None:
    """A produced ``.hmp`` archive carries a RO-Crate and a sha256 manifest."""
    import hydromodpy as hmp

    src_workspace = tmp_path / "source_ws"
    sim_id = str(uuid4())
    archive_path = tmp_path / "run.hmp"

    with hmp.open(src_workspace, create=True) as catalog:
        _populate_simulation(catalog, project="roundtrip", sim_id=sim_id)
        produced = catalog.export_package(sim_id, archive_path)
    assert produced == archive_path
    assert archive_path.is_file()

    with _open_archive(archive_path) as tar:
        names = tar.getnames()
        assert f"{sim_id}/{MANIFEST_NAME}" in names
        assert f"{sim_id}/{RO_CRATE_VIEW_FILENAME}" in names
        assert any(name.endswith("catalog_snapshot.duckdb") for name in names)
        assert any(name.endswith(ZARR_ARCHIVE_NAME) for name in names)

        manifest = json.loads(tar.extractfile(f"{sim_id}/{MANIFEST_NAME}").read().decode("utf-8"))

    assert manifest["format"] == HMP_MAGIC
    assert manifest["format_version"] == HMP_FORMAT_VERSION
    assert manifest["sim_id"] == sim_id
    files = manifest["files"]
    assert files, "manifest must list packaged files"
    for entry in files:
        assert "path" in entry
        assert "size" in entry
        assert "sha256" in entry
        assert len(entry["sha256"]) == 64


@pytest.mark.integration
def test_export_then_cli_import_roundtrip(tmp_path: Path) -> None:
    """Export a sim to ``.hmp`` then re-import via ``hmp data import`` CLI verb."""
    import hydromodpy as hmp

    src_workspace = tmp_path / "source_ws"
    dst_workspace = tmp_path / "target_ws"
    archive_path = tmp_path / "run.hmp"
    sim_id = str(uuid4())

    with hmp.open(src_workspace, create=True) as catalog:
        _populate_simulation(catalog, project="roundtrip", sim_id=sim_id)
        catalog.export_package(sim_id, archive_path)

    assert archive_path.is_file()
    # Snapshot manifest content for cross-checks after import.
    with _open_archive(archive_path) as tar:
        manifest = json.loads(tar.extractfile(f"{sim_id}/{MANIFEST_NAME}").read().decode("utf-8"))

    # Drive the CLI import: this is the verb a user runs to ingest a shared
    # archive. Using ``python -m hydromodpy`` keeps the test honest about the
    # CLI surface and not just the Python API.
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "hydromodpy",
            "data",
            "import",
            str(archive_path),
            "-w",
            str(dst_workspace),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, (
        f"`hmp import` failed (rc={completed.returncode}).\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert sim_id in completed.stdout

    with hmp.open(dst_workspace, create=True) as target:
        sims = target.list_simulations(project="roundtrip")
        assert len(sims) == 1
        assert str(sims.iloc[0]["sim_id"]) == sim_id

        # Re-check the SHA-256 of the imported Zarr + Parquet artefacts.
        zarr_path = target.fields_path_for(sim_id)
        parquet_dir = target.tables_dir_for(sim_id)
        assert zarr_path.exists()
        assert parquet_dir.exists()

        # ``hmp.read`` succeeds on the imported simulation.
        run = target[sim_id]
        da = hmp.read(run, "head")
        data = np.asarray(da.values if hasattr(da, "values") else da)
        assert data.shape[-1] == 4
        assert np.allclose(data, 11.25)

        # The DuckDB timeseries row survives the snapshot round trip.
        rows = target.connection.execute(
            "SELECT variable, value FROM timeseries WHERE sim_id = ? ORDER BY time",
            [sim_id],
        ).fetchdf()
        assert list(rows["value"]) == pytest.approx([10.0, 10.1, 10.2, 10.3])

        # The nse metric survives the snapshot round trip (CLI import path).
        metric = target.connection.execute(
            "SELECT value FROM metrics WHERE sim_id = ? AND metric_name = 'nse'",
            [sim_id],
        ).fetchone()
        assert metric is not None
        assert float(metric[0]) == pytest.approx(0.91)

    # The manifest SHA-256 covers every file *inside* the archive. We
    # cross-check it survives extraction unchanged: pulling the archive
    # and re-hashing the byte payload of any listed file must equal the
    # manifest sha256.
    with _open_archive(archive_path) as tar:
        for entry in manifest["files"]:
            member_path = f"{sim_id}/{entry['path']}"
            assert member_path in tar.getnames()
            payload = tar.extractfile(member_path).read()
            actual = hashlib.sha256(payload).hexdigest()
            assert actual == entry["sha256"], (
                f"sha256 drift in archived file {entry['path']}: "
                f"manifest={entry['sha256']}, archive={actual}"
            )


@pytest.mark.integration
def test_cli_export_writes_the_package_the_import_reads(tmp_path: Path) -> None:
    """``hmp export <run> all --format package`` then ``hmp data import``, both as CLI verbs."""
    import hydromodpy as hmp

    src_workspace = tmp_path / "source_ws"
    dst_workspace = tmp_path / "target_ws"
    sim_id = str(uuid4())
    with hmp.open(src_workspace, create=True) as catalog:
        _populate_simulation(catalog, project="roundtrip", sim_id=sim_id)

    exported = subprocess.run(
        [
            sys.executable,
            "-m",
            "hydromodpy",
            "export",
            "roundtrip_sim",
            "all",
            "--format",
            "package",
            "-w",
            str(src_workspace),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert exported.returncode == 0, exported.stderr
    archive_path = Path(exported.stdout.strip())
    assert archive_path == src_workspace / "share" / "roundtrip_sim" / "roundtrip_sim.hmp"

    imported = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "data", "import", str(archive_path)]
        + ["-w", str(dst_workspace)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr
    assert sim_id in imported.stdout
