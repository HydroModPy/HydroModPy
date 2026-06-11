"""Round-trip for ``hmp catalog export`` / ``hmp catalog import``."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hydromodpy.cli._workers.catalog import export_package_run, import_package_run
from hydromodpy.results.catalog import SimulationCatalog


def test_export_import_preserves_identity(tmp_path: Path) -> None:
    src = tmp_path / "src"
    sid = str(uuid.uuid4())
    with SimulationCatalog(src) as catalog:
        catalog.register_simulation(
            sid,
            project="cheze",
            solver="modflow6",
            name="baseline",
            n_cells=4,
            n_layers=1,
            config={"k": 1},
        )
        catalog.finalize(sid, status="completed", duration_s=1.0)

    archive = tmp_path / "paper.hmp"
    exported = export_package_run("baseline", workspace=src, output=str(archive))
    assert Path(exported["path"]).is_file()
    assert exported["sim_id"] == sid

    dst = tmp_path / "dst"
    imported = import_package_run(exported["path"], workspace=dst)
    assert imported["sim_id"] == sid

    with SimulationCatalog(dst, read_only=True) as fresh:
        assert fresh["baseline"].sim_id == sid


def test_import_missing_archive_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        import_package_run(tmp_path / "absent.hmp", workspace=tmp_path / "ws")
