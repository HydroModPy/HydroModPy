"""The input files of a run, each with its SHA-256, resolved from the project config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.contracts.file_record import FileRecord
from hydromodpy.data.loading.inputs import ResolvedInputs, resolve_inputs


@dataclass
class _DummySource:
    source: str
    path: str | None = None
    url: str | None = None
    sha256: str | None = None
    license: str | None = None


@dataclass
class _DummySection:
    sources: list[_DummySource]


@dataclass
class _DummyData:
    piezometry: _DummySection | None = None
    climate: _DummySection | None = None


@dataclass
class _DummyWorkspace:
    project_root: Path


@dataclass
class _DummyConfig:
    workspace: _DummyWorkspace
    data: _DummyData


def test_resolved_inputs():
    rec1 = FileRecord(path=Path("/tmp/a.csv"), sha256="0" * 64, origin="file")
    rec2 = FileRecord(path=Path("/tmp/b.csv"), sha256="1" * 64, origin="file")
    rec_dem = FileRecord(path=Path("/tmp/dem.tif"), sha256="2" * 64, origin="file")

    ri = ResolvedInputs(dem=rec_dem, records={"piezometry": (rec1,), "climate": (rec2,)})
    assert ri.dem == rec_dem
    assert ri.for_variable("piezometry") == (rec1,)
    assert ri.for_variable("unknown") == ()
    assert ri.all_records == (rec_dem, rec1, rec2)


def test_file_source_resolved(tmp_path: Path):
    proj_dir = tmp_path / "project"
    proj_dir.mkdir()
    input_file = proj_dir / "inputs" / "piezo.csv"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    input_file.write_text("date,head\n2020-01-01,10.5\n", encoding="utf-8")

    cfg = _DummyConfig(
        workspace=_DummyWorkspace(project_root=proj_dir),
        data=_DummyData(
            piezometry=_DummySection(sources=[_DummySource(source="file", path="inputs/piezo.csv")])
        ),
    )

    out_data = tmp_path / "data"
    bounds = Bounds(allowed_roots=(tmp_path,))
    resolved = resolve_inputs(cfg, bounds=bounds, data_dir=out_data)

    records = resolved.for_variable("piezometry")
    assert len(records) == 1
    rec = records[0]
    assert rec.origin == "file"
    assert len(rec.sha256) == 64
    assert rec.path == input_file
    assert rec.path.is_file()
