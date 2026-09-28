"""Round-trip for ``hmp export <run> all --format package`` / ``hmp catalog import``."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hydromodpy.cli._workers.catalog import import_package_run
from hydromodpy.results.catalog import Catalog
from tests._helpers.cli_runner import CliRunner


def _sealed_run(workspace: Path, name: str = "baseline") -> str:
    sid = str(uuid.uuid4())
    with Catalog(workspace) as catalog:
        catalog.register_simulation(
            sid,
            project="cheze",
            solver="modflow6",
            name=name,
            n_cells=4,
            n_layers=1,
            config={"k": 1},
        )
        catalog.finalize(sid, status="completed")
    return sid


def test_export_import_preserves_identity(tmp_path: Path) -> None:
    src = tmp_path / "src"
    sid = _sealed_run(src)
    archive = tmp_path / "paper.hmp"

    result = CliRunner().invoke(
        ["export", "baseline", "all", "--format", "package", "--file", str(archive), "-w", str(src)]
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == str(archive)
    assert archive.is_file()

    dst = tmp_path / "dst"
    imported = import_package_run(archive, workspace=dst)
    assert imported["sim_ids"] == [sid]

    with Catalog(dst, read_only=True) as fresh:
        assert fresh["baseline"].sim_id == sid


def test_import_missing_archive_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        import_package_run(tmp_path / "absent.hmp", workspace=tmp_path / "ws")


def test_the_package_is_recorded_in_the_export_log(tmp_path: Path) -> None:
    src = tmp_path / "src"
    sid = _sealed_run(src)

    result = CliRunner().invoke(
        ["export", "baseline", "all", "--format", "package", "-w", str(src)]
    )
    assert result.exit_code == 0, result.stderr

    with Catalog(src, read_only=True) as fresh:
        exports = fresh.list_exports(sid)
    assert [entry["kind"] for entry in exports] == ["package"]
    assert exports[0]["rel_path"] == "share/baseline/baseline.hmp"
