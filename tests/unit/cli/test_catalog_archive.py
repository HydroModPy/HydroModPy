"""Round-trip for ``hmp catalog export`` / ``hmp catalog import``."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hydromodpy.cli._workers.catalog import (
    export_package_run,
    export_package_runs,
    import_package_run,
)
from hydromodpy.results.catalog import Catalog


def test_export_import_preserves_identity(tmp_path: Path) -> None:
    src = tmp_path / "src"
    sid = str(uuid.uuid4())
    with Catalog(src) as catalog:
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
    assert imported["sim_ids"] == [sid]

    with Catalog(dst, read_only=True) as fresh:
        assert fresh["baseline"].sim_id == sid


def test_import_missing_archive_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        import_package_run(tmp_path / "absent.hmp", workspace=tmp_path / "ws")


def test_export_package_run_records_in_export_log(tmp_path: Path) -> None:
    src = tmp_path / "src"
    sid = str(uuid.uuid4())
    with Catalog(src) as catalog:
        catalog.register_simulation(
            sid, project="cheze", solver="modflow6", name="baseline", n_cells=4, n_layers=1
        )
        catalog.finalize(sid, status="completed", duration_s=1.0)

    export_package_run("baseline", workspace=src, output=str(tmp_path / "paper.hmp"))

    with Catalog(src, read_only=True) as fresh:
        kinds = [e["kind"] for e in fresh.list_exports(sid)]
    assert "hmp" in kinds


def test_export_multiple_runs_roundtrips_as_one_container(tmp_path: Path) -> None:
    src = tmp_path / "src"
    names = ["trial-007", "trial-013"]
    sids = []
    with Catalog(src) as catalog:
        for name in names:
            sid = str(uuid.uuid4())
            catalog.register_simulation(
                sid,
                project="cheze",
                solver="modflow6",
                name=name,
                n_cells=4,
                n_layers=1,
                config={"k": 1},
            )
            catalog.finalize(sid, status="completed", duration_s=1.0)
            sids.append(sid)

    archive = tmp_path / "paper2026.hmp"
    result = export_package_runs(names, workspace=src, output=str(archive))

    # one container holding both runs
    assert Path(result["path"]) == archive
    assert archive.is_file()
    assert sorted(result["sim_ids"]) == sorted(sids)

    # import restores both runs into a fresh workspace, identities preserved
    dst = tmp_path / "dst"
    imported = import_package_run(str(archive), workspace=dst)
    assert sorted(imported["sim_ids"]) == sorted(sids)
    with Catalog(dst, read_only=True) as fresh:
        assert {fresh["trial-007"].sim_id, fresh["trial-013"].sim_id} == set(sids)
