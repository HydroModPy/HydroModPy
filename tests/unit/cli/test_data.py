"""``hmp data``: list, prune, remove, archive and restore the data cache, and get a request served.

The cache is a folder ``data/`` of a workspace. Each fetched file has a JSON sidecar that records its
variable, source and sha256, and ``data ls`` reads those sidecars. ``data get`` serves a request
(a variable, an extent in the CRS of the bbox, a period) into a folder and writes ``request.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.cli.commands.data.get import _parse_bbox
from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.provenance.sidecars import (
    FORMER_CACHE_DATABASE,
    CacheIndex,
    CacheRow,
    ScanReport,
)
from hydromodpy.data.source.port import FetchRequest, FetchResult
from hydromodpy.data.variables.hydrometry.apis.hubeau import HubeauHydrometry
from tests._helpers.cli_runner import CliRunner

from ._hmp import run_main as _run

LIST_CACHE = "hydromodpy.data.request.cache_verbs.list_data_cache"
PERIOD = ["--start", "2020-01-01", "--end", "2020-01-31"]

# Requests that are refused before anything is fetched: (words after "data get", exit code).
REFUSED_REQUESTS = [
    pytest.param(["dem"], 14, id="no extent"),
    pytest.param(["dem", "--bbox", "0,0,1,1"], 14, id="bbox without crs"),
    pytest.param(["dem", "--mask", "absent.gpkg"], 10, id="mask not there"),
    pytest.param(["dem", "--bbox", "not-floats"], 2, id="bbox not floats"),
    pytest.param(["dem", "--bbox", "0,1,2"], 2, id="bbox of three numbers"),
]


def make_workspace(tmp_path: Path) -> Path:
    """Make ``tmp_path`` a workspace: the commands resolve it before they call a verb."""
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path.resolve()


def cache_row(data_root: Path, **fields: object) -> CacheRow:
    return CacheRow(path=data_root / "hydrometry" / "h.csv", **fields)  # type: ignore[arg-type]


def cached_dem(workspace: Path) -> Path:
    tif = workspace / "data" / "dem" / "dem_ign_a.tif"
    tif.parent.mkdir()
    tif.write_bytes(b"tif")
    return tif


def hubeau_station(station_id: str) -> PointRecord:
    dates = pd.date_range("2019-12-01", periods=120, freq="D")
    return PointRecord(
        station_id=station_id,
        variable="hydrometry",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": np.arange(120, dtype=float)}),
        date_start=dates[0].to_pydatetime(),
        date_end=dates[-1].to_pydatetime(),
        location=StationLocation(id=station_id, x=-1.7, y=48.1, crs="EPSG:4326"),
    )


@pytest.fixture
def hubeau_stub(monkeypatch) -> list[dict]:
    """Replace the Hub'Eau hydrometry fetch and record what each call asked."""
    calls: list[dict] = []

    def fake_hubeau(self, request: FetchRequest) -> FetchResult:
        calls.append(
            {
                "bbox": request.extent.bbox if request.extent is not None else None,
                "station_ids": list(request.station_ids),
            }
        )
        return FetchResult(
            source_id="hubeau",
            kind="points",
            variables=self.variables,
            extent=request.extent,
            period=request.period,
            points=(hubeau_station("J0001"),),
        )

    monkeypatch.setattr(HubeauHydrometry, "fetch", fake_hubeau)
    return calls


def data_cache_check(workspace: Path) -> dict:
    result = CliRunner().invoke(["doctor", "-w", str(workspace), "--format", "json"])
    checks = json.loads(result.stdout)["data"]["checks"]
    return next(check for check in checks if check["name"] == "data_cache")


def test_ls_filters_and_columns(monkeypatch, tmp_path) -> None:
    workspace = make_workspace(tmp_path)
    calls: dict[str, object] = {}
    row = cache_row(
        workspace / "data",
        variable="hydrometry",
        source="hubeau",
        station_id="H1",
        product="Q",
        license="Licence Ouverte",
    )

    def fake_list_data_cache(root, *, variable, provider):
        calls.update({"workspace": root, "variable": variable, "provider": provider})
        return ScanReport(data_root=workspace / "data", rows=(row,))

    monkeypatch.setattr(LIST_CACHE, fake_list_data_cache)

    result = CliRunner().invoke(
        ["data", "ls", "-w", str(tmp_path), "--variable", "hydrometry", "--provider", "hubeau"]
    )

    assert result.exit_code == 0, result.stderr
    assert calls == {"workspace": workspace, "variable": "hydrometry", "provider": "hubeau"}
    for word in ("hydrometry", "hubeau", "H1", "Licence Ouverte", "hydrometry/h.csv"):
        assert word in result.stdout
    assert "sha256" not in result.stdout


def test_ls_json_fields(monkeypatch, tmp_path) -> None:
    workspace = make_workspace(tmp_path)
    row = cache_row(workspace / "data", variable="dem", source="ign", sha256="ab" * 32, bytes=3)
    monkeypatch.setattr(
        LIST_CACHE, lambda *a, **k: ScanReport(data_root=workspace / "data", rows=(row,))
    )

    result = CliRunner().invoke(["data", "ls", "-w", str(tmp_path), "--format", "json"])

    document = json.loads(result.stdout)
    (item,) = document["data"]
    assert document["schema"] == "hmp.data.ls.v2"
    assert item["sha256"] == "ab" * 32 and item["bytes"] == 3 and item["license"] is None
    assert not {"id", "file_mtime", "is_custom", "file_path"} & set(item)


def test_ls_user_files_orphans(monkeypatch, tmp_path) -> None:
    workspace = make_workspace(tmp_path)
    report = ScanReport(
        data_root=workspace / "data",
        user_files=(workspace / "data" / "mine.csv",),
        orphans=(workspace / "data" / "gone.csv.json",),
    )
    monkeypatch.setattr(LIST_CACHE, lambda *a, **k: report)

    result = CliRunner().invoke(["data", "ls", "-w", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    assert "(empty cache" in result.stdout
    assert "1 user file(s)" in result.stdout
    assert "gone.csv.json: its file is gone" in result.stderr


def test_ls_missing_or_empty(tmp_path) -> None:
    (tmp_path / "projects").mkdir()
    missing = CliRunner().invoke(["data", "ls", "-w", str(tmp_path)])
    empty = CliRunner().invoke(["data", "ls", "-w", str(make_workspace(tmp_path))])

    assert missing.exit_code == 0
    assert "(no cache found)" in missing.stdout
    assert empty.exit_code == 0
    assert "(empty cache" in empty.stdout


def test_ls_reads_sidecars(tmp_path) -> None:
    workspace = make_workspace(tmp_path)
    CacheIndex(workspace / "data").record(cached_dem(workspace), variable="dem", source="ign")

    result = CliRunner().invoke(["data", "ls", "-w", str(tmp_path), "--format", "csv"])

    assert result.exit_code == 0, result.stderr
    assert "dem,ign" in result.stdout


def test_ls_former_database(tmp_path) -> None:
    workspace = make_workspace(tmp_path)
    (workspace / "data" / FORMER_CACHE_DATABASE).write_bytes(b"duckdb")

    result = CliRunner().invoke(["data", "ls", "-w", str(tmp_path)])

    assert result.exit_code != 0
    assert "hmp workspace clean --data-cache" in result.stderr


def test_prune_keeps_cited(monkeypatch, tmp_path) -> None:
    workspace = make_workspace(tmp_path)
    cited = cached_dem(workspace)
    row = CacheIndex(workspace / "data").record(cited, variable="dem", source="ign")
    monkeypatch.setattr(
        "hydromodpy.project.data_cache.cited_input_digests", lambda root: frozenset({row.sha256})
    )

    result = CliRunner().invoke(
        ["data", "prune", "--older-than", "0", "--delete-files", "-y", "-w", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stderr
    assert "Pruned 0 row(s)" in result.stdout
    assert "Kept 1 file(s) that a run or a lockfile cites" in result.stdout
    assert str(cited.resolve()) in result.stdout
    assert cited.exists()


def test_prune_unreadable_run(monkeypatch, tmp_path) -> None:
    workspace = make_workspace(tmp_path)
    old = cached_dem(workspace)
    CacheIndex(workspace / "data").record(old, variable="dem", source="ign")

    def unreadable(root):
        raise DataCacheError("The inputs of the run r cannot be read, so nothing was pruned.")

    monkeypatch.setattr("hydromodpy.project.data_cache.cited_input_digests", unreadable)

    result = CliRunner().invoke(
        ["data", "prune", "--older-than", "0", "--delete-files", "-y", "-w", str(tmp_path)]
    )

    assert result.exit_code != 0
    assert "nothing was pruned" in result.stderr
    assert old.exists()


def test_remove_forwards_the_filters(monkeypatch, tmp_path) -> None:
    workspace = make_workspace(tmp_path)
    calls: dict[str, object] = {}

    def fake_remove(root, **kwargs):
        calls.update({"workspace": root, **kwargs})
        return 2

    monkeypatch.setattr("hydromodpy.data.request.cache_verbs.remove_data_entries", fake_remove)

    result = CliRunner().invoke(
        ["data", "remove", "--variable", "dem", "--station-id", "S1", "--delete-files", "-y"]
        + ["-w", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stderr
    assert calls == {
        "workspace": workspace,
        "variable": "dem",
        "provider": None,
        "station_id": "S1",
        "delete_files": True,
        "dry_run": False,
    }
    assert "Removed 2 row(s)" in result.stdout


def test_archive_forwards(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_archive_data_cache(output, *, workspace_root):
        calls.update({"output": output, "workspace_root": workspace_root})
        return tmp_path / "cache.tar.gz"

    monkeypatch.setattr(
        "hydromodpy.data.request.cache_verbs.archive_data_cache", fake_archive_data_cache
    )
    workspace = make_workspace(tmp_path)

    result = CliRunner().invoke(
        ["data", "archive", "--to", "cache.tar.gz", "--workspace", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stderr
    assert calls == {"output": "cache.tar.gz", "workspace_root": workspace}
    assert "Archived cache to" in result.stdout


def test_restore_forwards(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_restore_data_cache(source, *, workspace_root, to):
        calls.update({"source": source, "workspace_root": workspace_root, "to": to})
        return workspace_root / "data"

    monkeypatch.setattr(
        "hydromodpy.data.request.cache_verbs.restore_data_cache", fake_restore_data_cache
    )
    workspace = make_workspace(tmp_path)

    result = CliRunner().invoke(["data", "restore", "cache.tar.gz", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    assert calls == {"source": "cache.tar.gz", "workspace_root": workspace, "to": None}


def test_doctor_former_database(tmp_path) -> None:
    workspace = make_workspace(tmp_path)
    database = workspace / "data" / FORMER_CACHE_DATABASE
    database.write_bytes(b"duckdb")

    check = data_cache_check(workspace)

    assert check["status"] == "WARN"
    assert "hmp workspace clean --data-cache" in check["detail"]
    assert database.exists(), "the doctor reads and never repairs"


def test_doctor_bad_sidecar(tmp_path) -> None:
    workspace = make_workspace(tmp_path)
    (workspace / "data" / "dem").mkdir()
    (workspace / "data" / "dem" / "dem_ign_a.tif.json").write_text("not json", encoding="utf-8")

    check = data_cache_check(workspace)

    assert check["status"] == "WARN"
    assert "dem_ign_a.tif.json" in check["detail"]


def test_get_request_document(monkeypatch, tmp_path, hubeau_stub) -> None:
    document = tmp_path / "ask.json"
    document.write_text(
        json.dumps(
            {
                "data": {"hydrometry": {"sources": [{"source": "hubeau"}]}},
                "extent": {"station_ids": ["J0001"]},
                "period": {"start": "2020-01-01", "end": "2020-01-31"},
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"

    code = _run(monkeypatch, ["hmp", "data", "get", str(document), "--to", str(out)])

    assert code == 0
    report = json.loads((out / "request.json").read_text(encoding="utf-8"))
    assert report["files"][0]["path"] is not None


def test_get_negative_bbox(monkeypatch, tmp_path, hubeau_stub) -> None:
    argv = ["hmp", "data", "get", "hydrometry", "--bbox=-1.8,48.0,-1.6,48.2", "--crs", "EPSG:4326"]

    code = _run(monkeypatch, [*argv, *PERIOD, "--to", str(tmp_path / "out")])

    assert code == 0
    assert hubeau_stub, "the source was asked"


def test_get_failed_variable(monkeypatch, tmp_path, capsys) -> None:
    def broken(self, request: FetchRequest) -> FetchResult:
        raise RuntimeError("upstream down")

    monkeypatch.setattr(HubeauHydrometry, "fetch", broken)
    argv = ["hmp", "data", "get", "hydrometry", "--stations", "J0001", *PERIOD]

    code = _run(monkeypatch, [*argv, "--to", str(tmp_path / "out")])

    assert code == 16
    assert "FAILED" in capsys.readouterr().err
    assert (tmp_path / "out" / "request.json").is_file()


def test_get_unknown_variable(monkeypatch, tmp_path, capsys) -> None:
    argv = ["hmp", "data", "get", "not_a_var", "--stations", "X", "--to", str(tmp_path)]

    assert _run(monkeypatch, argv) == 14
    assert "Unknown variable" in capsys.readouterr().err


@pytest.mark.parametrize(("words", "code"), REFUSED_REQUESTS)
def test_get_refusals(monkeypatch, tmp_path, words, code) -> None:
    out = tmp_path / "out"

    assert _run(monkeypatch, ["hmp", "data", "get", *words, "--to", str(out)]) == code
    assert not out.exists()


def test_parse_bbox_non_floats() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_bbox("a,b,c,d")
