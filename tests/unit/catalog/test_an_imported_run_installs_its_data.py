"""``hmp catalog import`` installs the data a run read into the ``data/`` of the workspace.

The run lands under ``runs/``; every file it read lands at its destination.
Identical bytes already there cost nothing, an absent file comes with its
sidecar, the same path with other bytes is refused by name with both digests
and nothing is written. Station rows merge into their registry, a delivered
file is registered in ``data/cache.duckdb`` so a run finds it, the ``[site]``
merges into the site catalog, and a conflict on any of them refuses the import.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

import pytest

from hydromodpy.core.payload import PayloadConflictError
from hydromodpy.core.site import SiteRow
from hydromodpy.data.registry import DataCatalogDuckDB
from hydromodpy.data.sites.catalog import read_catalog, write_catalog
from hydromodpy.project.install import import_run
from hydromodpy.project.share import inputs_of
from hydromodpy.results.export.publish import publish
from tests._helpers.cli_runner import CliRunner
from tests.unit.catalog._shared_run import (
    CUSTOM_FILE,
    HUBEAU_FILE,
    RUN_NAME,
    UNREAD_FILE,
    make_shared_run,
    make_workspace,
    sha256_of,
)


def _copy(tmp_path: Path) -> Path:
    run_dir = make_shared_run(tmp_path / "source")
    project = run_dir.parent.parent
    return publish(
        run_dir,
        tmp_path / "published" / RUN_NAME,
        project_root=project,
        format="tar",
        with_=("inputs",),
        inputs=inputs_of(project),
    )


def _target(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "colleague"
    return workspace, make_workspace(workspace, project="lab")


def test_every_file_lands_in_data_with_its_sidecar_and_nothing_unread(tmp_path) -> None:
    copy = _copy(tmp_path)
    workspace, project = _target(tmp_path)

    imported = import_run(project, copy)

    assert imported.rel_dir == f"runs/{RUN_NAME}"
    assert (project / "runs" / RUN_NAME / "manifest.json").is_file()
    data = workspace / "data"
    source = tmp_path / "source" / "data"
    for relative in (f"hydrometry/{HUBEAU_FILE}", f"hydrometry/{CUSTOM_FILE}", "dem/dem.tif"):
        assert (data / relative).read_bytes() == (source / relative).read_bytes()
    assert (data / "hydrometry" / f"{HUBEAU_FILE}.json").read_bytes() == (
        source / "hydrometry" / f"{HUBEAU_FILE}.json"
    ).read_bytes()
    assert not (data / "hydrometry" / UNREAD_FILE).exists()
    assert sorted(imported.install.written) == [
        "data/dem/dem.tif",
        f"data/hydrometry/{CUSTOM_FILE}",
        f"data/hydrometry/{HUBEAU_FILE}",
    ]
    assert not (project / "runs" / RUN_NAME / "inputs").exists()


def test_identical_bytes_already_there_cost_nothing(tmp_path) -> None:
    copy = _copy(tmp_path)
    workspace, project = _target(tmp_path)
    dem = workspace / "data" / "dem" / "dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes((tmp_path / "source" / "data" / "dem" / "dem.tif").read_bytes())
    os.utime(dem, (1_000_000_000, 1_000_000_000))

    imported = import_run(project, copy)

    assert imported.install.unchanged == ["data/dem/dem.tif"]
    assert "data/dem/dem.tif" not in imported.install.written
    assert dem.stat().st_mtime == 1_000_000_000


def test_the_same_path_with_other_bytes_is_refused_and_nothing_is_written(tmp_path) -> None:
    copy = _copy(tmp_path)
    workspace, project = _target(tmp_path)
    dem = workspace / "data" / "dem" / "dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes(b"the colleague's own DEM")

    with pytest.raises(PayloadConflictError) as refused:
        import_run(project, copy)

    message = str(refused.value)
    assert "data/dem/dem.tif" in message
    assert hashlib.sha256(b"the colleague's own DEM").hexdigest() in message
    assert sha256_of(tmp_path / "source" / "data" / "dem" / "dem.tif") in message
    assert dem.read_bytes() == b"the colleague's own DEM"
    assert not (workspace / "data" / "hydrometry").exists()
    assert not (project / "runs").exists() or not any((project / "runs").iterdir())


def test_station_rows_merge_into_the_registry_of_the_workspace(tmp_path) -> None:
    copy = _copy(tmp_path)
    workspace, project = _target(tmp_path)
    registry = workspace / "data" / "hydrometry" / "hydrometry_custom_LOC.csv"
    registry.parent.mkdir(parents=True)
    registry.write_text("id,x,y,crs,unit\nEXAMPLE,1,1,EPSG:2154,m3/s\n", encoding="utf-8")

    imported = import_run(project, copy)

    assert registry.read_text(encoding="utf-8").splitlines() == [
        "id,x,y,crs,unit",
        "EXAMPLE,1,1,EPSG:2154,m3/s",
        "NANCON,389285.9,6816518.7,EPSG:2154,m3/s",
    ]
    hubeau = workspace / "data" / "hydrometry" / "hydrometry_hubeau_LOC.csv"
    assert hubeau.read_text(encoding="utf-8").splitlines()[1].startswith("J0014010,")
    assert len(imported.install.stations_written) == 2


def test_a_station_row_the_registry_holds_otherwise_refuses_the_import(tmp_path) -> None:
    copy = _copy(tmp_path)
    workspace, project = _target(tmp_path)
    registry = workspace / "data" / "hydrometry" / "hydrometry_custom_LOC.csv"
    registry.parent.mkdir(parents=True)
    registry.write_text("id,x,y,crs,unit\nNANCON,1,1,EPSG:2154,m3/s\n", encoding="utf-8")

    with pytest.raises(PayloadConflictError, match="station NANCON"):
        import_run(project, copy)
    assert not (workspace / "data" / "dem").exists()


def test_a_delivered_file_is_registered_so_a_run_finds_it_in_the_cache(tmp_path) -> None:
    copy = _copy(tmp_path)
    workspace, project = _target(tmp_path)

    imported = import_run(project, copy)

    assert imported.install.cache_registered == [f"data/hydrometry/{HUBEAU_FILE}"]
    catalog = DataCatalogDuckDB(workspace / "data" / "cache.duckdb", read_only=True)
    try:
        entry = catalog.find_cached(
            variable="hydrometry",
            source="hubeau",
            station_id="J0014010",
            date_start=datetime(2000, 1, 1),
            date_end=datetime(2002, 12, 31),
        )
        served = catalog.resolve_path(entry.file_path, variable="hydrometry")
    finally:
        catalog.close()
    assert served == (workspace / "data" / "hydrometry" / HUBEAU_FILE).resolve()
    assert entry.sha256 == sha256_of(served)
    assert entry.frequency == "D"
    assert entry.bbox_xmin == pytest.approx(-1.19645)
    assert '"asked_window"' in entry.fetch_metadata
    assert abs(entry.file_mtime - served.stat().st_mtime) < 1e-6


def test_a_station_the_cache_serves_from_other_bytes_refuses_the_import(tmp_path) -> None:
    copy = _copy(tmp_path)
    workspace, project = _target(tmp_path)
    theirs = (
        workspace / "data" / "hydrometry" / "hydrometry_hubeau_J0014010_19900101_20201231_D.csv"
    )
    theirs.parent.mkdir(parents=True)
    theirs.write_text("datetime,value\n1990-01-01,9.9\n", encoding="utf-8")
    catalog = DataCatalogDuckDB(workspace / "data" / "cache.duckdb")
    catalog.register(
        variable="hydrometry", source="hubeau", station_id="J0014010", file_path=theirs
    )
    catalog.close()

    with pytest.raises(PayloadConflictError, match="hubeau hydrometry station J0014010"):
        import_run(project, copy)
    assert not (workspace / "data" / "hydrometry" / HUBEAU_FILE).exists()


def test_the_site_merges_into_the_catalog_and_another_outlet_is_refused(tmp_path) -> None:
    copy = _copy(tmp_path)
    workspace, project = _target(tmp_path)

    imported = import_run(project, copy)

    assert imported.install.sites_added == ["J0014010"]
    (row,) = read_catalog(workspace)
    assert (row.site, row.gauge, row.uri) == ("J0014010", "J0014010", "hubeau:J0014010")

    other_workspace, other_project = tmp_path / "third", None
    other_project = make_workspace(other_workspace, project="lab")
    write_catalog(
        other_workspace,
        [SiteRow(site="J0014010", x_outlet=0.0, y_outlet=0.0, crs=row.crs)],
    )
    with pytest.raises(PayloadConflictError, match="site J0014010"):
        import_run(other_project, copy)


def test_the_command_says_what_it_installed_and_how_to_replay(tmp_path) -> None:
    copy = _copy(tmp_path)
    _, project = _target(tmp_path)

    result = CliRunner().invoke(["catalog", "import", str(copy), "-w", str(project)])

    assert result.exit_code == 0, result.stderr
    assert f"as runs/{RUN_NAME}" in result.stdout
    assert "3 file(s) written" in result.stdout
    assert f"hmp catalog rerun {RUN_NAME} -w" in result.stdout
    assert f"hmp catalog diff {RUN_NAME} {RUN_NAME}.v2 -w" in result.stdout
