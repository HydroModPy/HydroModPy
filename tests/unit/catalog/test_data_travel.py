"""Tests of data travel."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.exceptions import ImportConflictError
from hydromodpy.core.payload import PayloadConflictError, read_index, sidecar_name, stored_name
from hydromodpy.core.site import SiteRow
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.data.sites.catalog import read_catalog, write_catalog
from hydromodpy.project.exchange.install import import_project, import_run
from hydromodpy.project.exchange.share import inputs_of, run_bundle
from hydromodpy.results.export.project_package import cited_mesh_products, export_project
from hydromodpy.results.export.publish import publish, verify
from hydromodpy.results.products.cited import CitedProduct, write_cited
from hydromodpy.results.products.store import products_root
from hydromodpy.results.publication import read_publication
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
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

# The package carries the files the author wrote and the data the TOML files
# reference, on the install index of a run; on demand the sealed runs, the
# sessions, the mesh cache entries the runs read and the files a provider
# delivered. The import lands the project as ``projects/<name>``, its data with
# the rules of ``hmp catalog import``, its runs under their own names, and
# refuses a name already taken unless ``--as`` gives another one.
PROJECT_TOML = """\
[site]
name = "nancon"

[geographic.catchment]
kind = "from_outlet_coord"

[data]
types = ["hydrometry", "dem"]

[[data.dem.sources]]
source = "file"
path = "dem.tif"

[[data.hydrometry.sources]]
source = "file"
path = "hydrometry"
station_ids = ["NANCON"]
"""


def _project(tmp_path: Path) -> Path:
    """The project of a workspace whose run read Hub'Eau, with TOML files that read user data."""
    run_dir = make_shared_run(tmp_path / "author")
    project = run_dir.parent.parent
    (project / "project.toml").write_text(PROJECT_TOML, encoding="utf-8")
    (project / "step1.toml").write_text('base_config = "project.toml"\n', encoding="utf-8")
    (project / "README.md").write_text("# Nancon\n", encoding="utf-8")
    (project / "_scratch.toml").write_text("# not shipped\n", encoding="utf-8")
    (project / "sites.csv").write_text("site\nnancon\n", encoding="utf-8")
    (project / "site_overrides").mkdir()
    (project / "site_overrides" / "nancon.toml").write_text("[flow]\n", encoding="utf-8")
    return project


def _package(tmp_path: Path, *extras: str) -> Path:
    project = _project(tmp_path)
    return export_project(
        project,
        tmp_path / "nancon.tar",
        with_=extras,
        bundle_of=inputs_of(project),
        root_config=ROOT_CONFIG,
    )


def test_the_package_carries_the_authored_files_and_the_data_they_reference(tmp_path) -> None:
    package = _package(tmp_path)
    unpacked = tmp_path / "unpacked"
    import tarfile

    with tarfile.open(package) as archive:
        archive.extractall(unpacked, filter="data")
    copy = unpacked / "nancon"

    index = read_index(copy)
    authored = sorted(item.dest for item in index.files if item.root == "project")
    assert authored == [
        "README.md",
        "project.toml",
        "site_overrides/nancon.toml",
        "sites.csv",
        "step1.toml",
    ]
    data = sorted(item.dest for item in index.files if item.root == "workspace")
    assert data == ["data/dem/dem.tif", f"data/hydrometry/{CUSTOM_FILE}"]
    assert not any(UNREAD_FILE in dest or HUBEAU_FILE in dest for dest in data)
    assert [(station.dest, station.id) for station in index.stations] == [
        ("data/hydrometry/hydrometry_custom_LOC.csv", "NANCON")
    ]
    publication = read_publication(copy)
    assert publication.kind == "project"
    assert verify(copy) == []
    assert verify(package) == []


def test_with_runs_and_fetched_the_package_takes_the_runs_and_what_the_providers_gave(
    tmp_path,
) -> None:
    package = _package(tmp_path, "runs", "fetched")
    workspace = tmp_path / "colleague"
    make_workspace(workspace, project="other")

    imported = import_project(package, workspace)

    project = workspace / "projects" / "nancon"
    assert imported.project_dir == project
    assert imported.runs == (RUN_NAME,)
    assert (project / "runs" / RUN_NAME / "manifest.json").is_file()
    assert not (project / "runs" / RUN_NAME / "PUBLICATION.json").exists()
    assert (project / "project.toml").read_text(encoding="utf-8") == PROJECT_TOML
    assert (project / "site_overrides" / "nancon.toml").is_file()
    assert not (project / "_scratch.toml").exists()
    for relative in ("dem/dem.tif", f"hydrometry/{CUSTOM_FILE}", f"hydrometry/{HUBEAU_FILE}"):
        assert (workspace / "data" / relative).is_file(), relative
    assert imported.install.cache_registered == [f"data/hydrometry/{HUBEAU_FILE}"]
    assert imported.install.sites_added == ["J0014010"]


def test_a_name_already_taken_is_refused_and_as_gives_another_one(tmp_path) -> None:
    package = _package(tmp_path)
    workspace = tmp_path / "colleague"
    make_workspace(workspace, project="nancon")

    with pytest.raises(ImportConflictError, match="--name"):
        import_project(package, workspace)
    imported = import_project(package, workspace, name="nancon_from_lab")

    assert imported.project_dir == workspace / "projects" / "nancon_from_lab"
    assert (imported.project_dir / "step1.toml").is_file()
    assert not list((workspace / "projects").glob(".*import*"))


def test_a_data_file_with_other_bytes_refuses_the_import_and_leaves_no_project(tmp_path) -> None:
    package = _package(tmp_path)
    workspace = tmp_path / "colleague"
    make_workspace(workspace, project="other")
    dem = workspace / "data" / "dem" / "dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes(b"another DEM")

    with pytest.raises(PayloadConflictError, match="data/dem/dem.tif"):
        import_project(package, workspace)

    assert not (workspace / "projects" / "nancon").exists()
    assert not list((workspace / "projects").glob(".*import*"))
    assert dem.read_bytes() == b"another DEM"


def _mesh_product(store: Path, key: str, *, kind: str = "mesh") -> None:
    entry = store / key[:2] / key
    entry.mkdir(parents=True)
    (entry / "mesh.npz").write_bytes(b"arrays")
    (entry / "mesh.json").write_text(
        json.dumps({"identity": {"engine_id": "gmsh", "engine_version": "1.0"}}),
        encoding="utf-8",
    )
    (entry / "meta.json").write_text(
        json.dumps({"key": key, "kind": kind, "bytes": 12, "written_at": 1.0}),
        encoding="utf-8",
    )


def test_with_mesh_the_package_takes_the_mesh_products_the_runs_cite(tmp_path) -> None:
    project = _project(tmp_path)
    run = project / "runs" / RUN_NAME
    write_cited(run, [CitedProduct(kind="mesh", key="a" * 64)])
    store = products_root(project)
    _mesh_product(store, "a" * 64)
    _mesh_product(store, "b" * 64)

    cited = cited_mesh_products(project, [run])
    assert [product.name for product in cited.products] == ["a" * 64]
    assert cited.missing == ()
    package = export_project(
        project,
        tmp_path / "nancon.tar",
        with_=("runs", "mesh", "sessions"),
        bundle_of=inputs_of(project),
        root_config=ROOT_CONFIG,
    )
    workspace = tmp_path / "colleague"
    make_workspace(workspace, project="other")
    imported = import_project(package, workspace)

    assert imported.mesh_entries == ("a" * 64,)
    assert (
        imported.project_dir / ".hmp" / "products" / ("a" * 64)[:2] / ("a" * 64) / "mesh.npz"
    ).is_file()
    assert not (imported.project_dir / ".hmp" / "products" / ("b" * 64)[:2]).exists()
    assert imported.mesh_present == ()
    assert imported.mesh_skipped == ()
    assert imported.legacy_mesh_cache == ()


def test_with_mesh_a_cited_key_missing_from_the_store_is_skipped(tmp_path, caplog) -> None:
    project = _project(tmp_path)
    run = project / "runs" / RUN_NAME
    write_cited(run, [CitedProduct(kind="mesh", key="a" * 64)])

    cited = cited_mesh_products(project, [run])
    assert cited.products == ()
    assert cited.missing == ("a" * 64,)
    package = export_project(
        project,
        tmp_path / "nancon.tar",
        with_=("mesh",),
        bundle_of=inputs_of(project),
        root_config=ROOT_CONFIG,
    )

    import tarfile

    unpacked = tmp_path / "unpacked"
    with tarfile.open(package) as archive:
        archive.extractall(unpacked, filter="data")
    assert not (unpacked / "nancon" / "products").exists()
    assert "Skipped 1 mesh product" in caplog.text


def test_the_commands_export_and_import_a_project(tmp_path) -> None:
    project = _project(tmp_path)
    workspace = tmp_path / "colleague"
    make_workspace(workspace, project="other")
    package = tmp_path / "nancon.tar"

    exported = CliRunner().invoke(
        ["publish", str(project), "--package", "--to", str(package), "--with", "runs"]
    )
    imported = CliRunner().invoke(
        ["project", "import", str(package), "-w", str(workspace), "--name", "lab"]
    )

    assert exported.exit_code == 0, exported.stderr
    assert "hmp project import" in exported.stderr
    assert imported.exit_code == 0, imported.stderr
    assert "runs: 1" in imported.stdout
    assert (workspace / "projects" / "lab" / ".hmp" / "index.duckdb").is_file()


# Each file is named by its destination relative to the workspace, with its
# variable, provider, request, licence and the digest of its sidecar. A station
# series brings its registry row, a file a provider delivered the cache row its
# sidecar holds, the run its ``[site]``. A declared folder is never
# taken whole: a station the run did not read stays out.
def test_the_index_lists_every_file_the_run_read_and_nothing_else(tmp_path) -> None:
    run_dir = make_shared_run(tmp_path / "ws")

    bundle = run_bundle(run_dir, project_root=run_dir.parent.parent)

    dests = [item.dest for item in bundle.index.files]
    assert dests == [
        "data/dem/dem.tif",
        f"data/hydrometry/{CUSTOM_FILE}",
        f"data/hydrometry/{HUBEAU_FILE}",
    ]
    assert not any(UNREAD_FILE in dest for dest in dests)
    dem = bundle.index.file_at("data/dem/dem.tif")
    assert (dem.variable, dem.provider, dem.license) == ("dem", "file", "LicenseRef-undetermined")
    for item in bundle.index.files:
        assert bundle.blobs[stored_name(item.sha256, item.dest)].is_file()


def test_the_row_of_a_sealed_mesh_is_not_a_file_of_the_workspace(tmp_path) -> None:
    import json

    run_dir = make_shared_run(tmp_path / "ws")
    path = run_dir / "inputs.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["inputs"].append(
        {
            "variable": "mesh",
            "provider": "store",
            "product": "mesh",
            "path": "mesh",
            "sha256": "f" * 64,
        }
    )
    path.write_text(json.dumps(document), encoding="utf-8")

    bundle = run_bundle(run_dir, project_root=run_dir.parent.parent)

    assert "mesh" not in [item.variable for item in bundle.index.files]


def test_a_delivered_file_brings_its_sidecar_and_the_cache_row_it_holds(tmp_path) -> None:
    workspace = tmp_path / "ws"
    run_dir = make_shared_run(workspace)
    sidecar = workspace / "data" / "hydrometry" / f"{HUBEAU_FILE}.json"

    bundle = run_bundle(run_dir, project_root=run_dir.parent.parent)

    item = bundle.index.file_at(f"data/hydrometry/{HUBEAU_FILE}")
    assert (item.variable, item.provider, item.license) == ("hydrometry", "hubeau", "etalab-2.0")
    assert item.request == {"station": "J0014010", "period": ["2000-01-01T00:00:00", None]}
    assert item.sidecar_sha256 == sha256_of(sidecar)
    assert bundle.blobs[sidecar_name(item.sidecar_sha256)] == sidecar
    assert item.cache["source"] == "hubeau"
    assert item.cache["station_id"] == "J0014010"
    assert item.cache["frequency"] == "D"
    assert item.cache["bbox"] == [-1.19645, 48.37558, -1.19645, 48.37558]
    assert item.cache["asked_window"] == ["2000-01-01T00:00:00", "2002-12-31T00:00:00"]
    assert bundle.index.file_at(f"data/hydrometry/{CUSTOM_FILE}").cache is None


def test_each_station_series_brings_its_registry_row_and_the_run_its_site(tmp_path) -> None:
    run_dir = make_shared_run(tmp_path / "ws")

    bundle = run_bundle(run_dir, project_root=run_dir.parent.parent)

    rows = {(station.dest, station.id): dict(station.row) for station in bundle.index.stations}
    assert set(rows) == {
        ("data/hydrometry/hydrometry_custom_LOC.csv", "NANCON"),
        ("data/hydrometry/hydrometry_hubeau_LOC.csv", "J0014010"),
    }
    assert rows[("data/hydrometry/hydrometry_custom_LOC.csv", "NANCON")]["unit"] == "m3/s"
    (site,) = bundle.index.sites
    assert (site.site, site.gauge, site.uri) == ("J0014010", "J0014010", "hubeau:J0014010")


# The run lands under ``runs/``; every file it read lands at its destination.
# Identical bytes already there cost nothing, an absent file comes with its
# sidecar, the same path with other bytes is refused by name with both digests
# and nothing is written. Station rows merge into their registry, a delivered
# file has its sidecar complete so a run finds it in the cache, the ``[site]``
# merges into the site catalog, and a conflict on any of them refuses the import.
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
    entry = CacheIndex(workspace / "data").find(
        "hydrometry",
        "hubeau",
        station_id="J0014010",
        date_start=datetime(2000, 1, 1),
        date_end=datetime(2002, 12, 31),
    )
    assert entry is not None
    served = entry.path
    assert served == (workspace / "data" / "hydrometry" / HUBEAU_FILE).resolve()
    assert entry.sha256 == sha256_of(served)
    assert entry.frequency == "D"
    assert entry.bbox is not None
    assert entry.bbox[0] == pytest.approx(-1.19645)
    assert entry.asked_window == ("2000-01-01T00:00:00", "2002-12-31T00:00:00")
    assert entry.bytes == served.stat().st_size


def test_a_station_the_cache_serves_from_other_bytes_refuses_the_import(tmp_path) -> None:
    copy = _copy(tmp_path)
    workspace, project = _target(tmp_path)
    theirs = (
        workspace / "data" / "hydrometry" / "hydrometry_hubeau_J0014010_19900101_20201231_D.csv"
    )
    theirs.parent.mkdir(parents=True)
    theirs.write_text("datetime,value\n1990-01-01,9.9\n", encoding="utf-8")
    CacheIndex(workspace / "data").record(
        theirs, variable="hydrometry", source="hubeau", station_id="J0014010"
    )

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
    assert f"hmp diff {RUN_NAME} {RUN_NAME}.v2 -w" in result.stdout
