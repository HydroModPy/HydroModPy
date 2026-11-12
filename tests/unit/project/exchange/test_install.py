"""Install of a shared package (run or project) into another workspace.

The package holds the files a run read, the station rows of the gauges, files a
provider delivered and the site. Identical bytes cost nothing, an absent file is
copied with its sidecar, and every conflict is collected and refused as a whole
before anything is written. ``dry_run`` reports what a real install would do.
"""

from __future__ import annotations

import dataclasses
import json
import tarfile
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.exceptions import ImportConflictError
from hydromodpy.core.payload.index import read_index, stored_name
from hydromodpy.core.payload.install import PayloadConflictError
from hydromodpy.core.site.row import SiteRow
from hydromodpy.data.provenance.sidecars import (
    FORMER_CACHE_DATABASE,
    CacheIndex,
    empty_path_for,
    load_sidecar,
)
from hydromodpy.data.sites.catalog import read_catalog, write_catalog
from hydromodpy.project.exchange.install import (
    _mesh_members,
    import_project,
    import_run,
    install_index,
)
from hydromodpy.project.exchange.share import inputs_of
from hydromodpy.results.export.project_package import export_project
from hydromodpy.results.export.publish import INPUTS_DIRNAME, publish
from hydromodpy.results.products.store import ProductStore
from tests.unit.catalog._shared_run import (
    CUSTOM_FILE,
    HUBEAU_FILE,
    RUN_NAME,
    make_shared_run,
    make_workspace,
    sha256_of,
)

DEM = "data/dem/dem.tif"
CUSTOM_REGISTRY = "data/hydrometry/hydrometry_custom_LOC.csv"
THE_THREE_FILES = [DEM, f"data/hydrometry/{CUSTOM_FILE}", f"data/hydrometry/{HUBEAU_FILE}"]


PROJECT_TOML = """\
[site]
name = "nancon"

[geographic.catchment]
kind = "from_outlet_coord"

[[data.dem.sources]]
source = "file"
path = "dem.tif"
"""


def _author_project(tmp_path: Path) -> Path:
    run_dir = make_shared_run(tmp_path / "author")
    return run_dir.parent.parent


def _shared_run_folder(tmp_path: Path) -> Path:
    """The published copy of the run, as a folder holding INSTALL.toml and inputs/."""
    project = _author_project(tmp_path)
    return publish(
        project / "runs" / RUN_NAME,
        tmp_path / "published" / RUN_NAME,
        project_root=project,
        format="dir",
        with_=("inputs",),
        inputs=inputs_of(project),
    )


def _colleague(tmp_path: Path, name: str = "colleague") -> tuple[Path, Path]:
    workspace = tmp_path / name
    return workspace, make_workspace(workspace, project="lab")


def _install(folder: Path, workspace: Path, project: Path | None = None, **kwargs):
    return install_index(
        read_index(folder),
        blobs=folder / INPUTS_DIRNAME,
        workspace=workspace,
        project=project,
        **kwargs,
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    """Every file under *root* with its bytes."""
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def _project_package(tmp_path: Path, *extras: str) -> Path:
    project = _author_project(tmp_path)
    (project / "project.toml").write_text(PROJECT_TOML, encoding="utf-8")
    return export_project(
        project,
        tmp_path / "nancon.tar",
        with_=extras,
        bundle_of=inputs_of(project),
        root_config=ROOT_CONFIG,
    )


def test_unlisted_file_refused(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    unlisted = dataclasses.replace(read_index(folder).files[0], dest="data/dem/unlisted.tif")

    with pytest.raises(ValueError, match="unlisted.tif"):
        _install(folder, workspace, files=[unlisted])

    assert not (workspace / "data" / "dem").exists()


def test_second_install_changes_nothing(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    _install(folder, workspace)
    before = _snapshot(workspace)

    report = _install(folder, workspace)

    assert report.written == []
    assert sorted(report.unchanged) == sorted(THE_THREE_FILES)
    assert report.stations_written == []
    assert report.sites_added == []
    assert _snapshot(workspace) == before


def test_dry_run_reports_and_writes_nothing(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    kept = workspace / "data" / "dem" / "dem.tif"
    kept.parent.mkdir(parents=True)
    kept.write_bytes((tmp_path / "author" / DEM).read_bytes())
    before = _snapshot(workspace)

    report = _install(folder, workspace, dry_run=True)

    assert report.unchanged == [DEM]
    assert sorted(report.written) == sorted(THE_THREE_FILES[1:])
    assert len(report.stations_written) == 2
    assert report.cache_registered == [f"data/hydrometry/{HUBEAU_FILE}"]
    assert report.sites_added == ["J0014010"]
    assert _snapshot(workspace) == before
    assert not (workspace / "data" / FORMER_CACHE_DATABASE).exists()


def test_cache_key_with_other_bytes_refused(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    theirs = workspace / "data" / "hydrometry" / "hydrometry_hubeau_J0014010_theirs.csv"
    theirs.parent.mkdir(parents=True)
    theirs.write_text("datetime,value\n1990-01-01,9.9\n", encoding="utf-8")
    CacheIndex(workspace / "data").record(
        theirs, variable="hydrometry", source="hubeau", station_id="J0014010"
    )

    with pytest.raises(PayloadConflictError) as refused:
        _install(folder, workspace)

    message = str(refused.value)
    assert "hubeau hydrometry station J0014010" in message
    assert "hydrometry_hubeau_J0014010_theirs.csv" in message
    assert not (workspace / f"data/hydrometry/{HUBEAU_FILE}").exists()


def test_cache_key_with_same_bytes_left_alone(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    same = workspace / "data" / "hydrometry" / "hydrometry_hubeau_J0014010_other_name.csv"
    same.parent.mkdir(parents=True)
    same.write_bytes((tmp_path / "author" / "data/hydrometry" / HUBEAU_FILE).read_bytes())
    CacheIndex(workspace / "data").record(
        same, variable="hydrometry", source="hubeau", station_id="J0014010"
    )

    report = _install(folder, workspace)

    assert report.cache_registered == []


def test_cache_entry_at_destination_registered(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    _install(folder, workspace)

    report = _install(folder, workspace)

    assert report.cache_registered == [f"data/hydrometry/{HUBEAU_FILE}"]


def test_empty_station_row_does_not_block(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    hydrometry = workspace / "data" / "hydrometry"
    hydrometry.mkdir(parents=True)
    empty = empty_path_for(hydrometry, "hydrometry_hubeau_J0014010")
    CacheIndex(workspace / "data").record_empty(
        empty, variable="hydrometry", source="hubeau", station_id="J0014010"
    )

    report = _install(folder, workspace)

    assert report.cache_registered == [f"data/hydrometry/{HUBEAU_FILE}"]
    assert not empty.with_name(empty.name + ".json").exists()


def test_sidecar_row_completed_from_cache(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    index = read_index(folder)
    bare = dataclasses.replace(
        index,
        files=tuple(dataclasses.replace(item, sidecar_sha256=None) for item in index.files),
    )

    report = install_index(bare, blobs=folder / INPUTS_DIRNAME, workspace=workspace)

    assert report.cache_registered == [f"data/hydrometry/{HUBEAU_FILE}"]
    delivered = workspace / "data" / "hydrometry" / HUBEAU_FILE
    sidecar = load_sidecar(delivered)
    assert (sidecar.variable, sidecar.source, sidecar.station_id) == (
        "hydrometry",
        "hubeau",
        "J0014010",
    )
    assert sidecar.frequency == "D"
    assert sidecar.asked_window == ("2000-01-01T00:00:00", "2002-12-31T00:00:00")
    assert (sidecar.sha256, sidecar.bytes) == (sha256_of(delivered), delivered.stat().st_size)
    row = CacheIndex(workspace / "data").find("hydrometry", "hubeau", station_id="J0014010")
    assert row is not None
    assert row.path == delivered.resolve()


@pytest.mark.parametrize(
    "held",
    [
        pytest.param("same", id="same outlet"),
        pytest.param({"x_outlet": None, "y_outlet": None}, id="no outlet declared"),
    ],
)
def test_held_site_name_is_kept(tmp_path, held) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    shared_site = _site_of(folder)
    if held == "same":
        held = {"x_outlet": shared_site.x_outlet, "y_outlet": shared_site.y_outlet}
    write_catalog(workspace, [SiteRow(site=shared_site.site, crs=shared_site.crs, **held)])

    assert _install(folder, workspace).sites_added == []


def test_site_with_other_outlet_refused(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    shared_site = _site_of(folder)
    far = SiteRow(site=shared_site.site, crs=shared_site.crs, x_outlet=0.0, y_outlet=0.0)
    write_catalog(workspace, [far])

    with pytest.raises(PayloadConflictError, match=f"site {shared_site.site}"):
        _install(folder, workspace)


def _site_of(folder: Path) -> SiteRow:
    (site,) = read_index(folder).sites
    return site


def test_outlet_under_another_name_refused(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    shared_site = _site_of(folder)
    write_catalog(
        workspace,
        [
            SiteRow(
                site="a_neighbour",
                x_outlet=shared_site.x_outlet,
                y_outlet=shared_site.y_outlet,
                crs=shared_site.crs,
            )
        ],
    )

    with pytest.raises(PayloadConflictError, match="J0014010"):
        _install(folder, workspace)

    assert [row.site for row in read_catalog(workspace)] == ["a_neighbour"]


def test_blob_with_other_digest_refused(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    dem = next(item for item in read_index(folder).files if item.dest == DEM)
    (folder / INPUTS_DIRNAME / stored_name(dem.sha256, dem.dest)).write_bytes(b"tampered")

    with pytest.raises(ImportConflictError, match="digest its INSTALL.toml states"):
        _install(folder, workspace)


def test_missing_sidecar_blob_refused(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    (item,) = [i for i in read_index(folder).files if i.sidecar_sha256 is not None]
    sidecars = [p for p in (folder / INPUTS_DIRNAME).iterdir() if item.sidecar_sha256 in p.name]
    assert sidecars
    sidecars[0].unlink()

    with pytest.raises(ImportConflictError, match="does not hold its bytes"):
        _install(folder, workspace)


def test_import_run_dry_run(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, project = _colleague(tmp_path)
    before = _snapshot(workspace)

    imported = import_run(project, folder, dry_run=True)

    assert imported.rel_dir == f"runs/{RUN_NAME}"
    assert sorted(imported.install.written) == sorted(THE_THREE_FILES)
    assert _snapshot(workspace) == before
    assert not (project / "runs").exists()


def test_import_project_dry_run(tmp_path) -> None:
    package = _project_package(tmp_path, "runs")
    workspace, _ = _colleague(tmp_path)
    before = _snapshot(workspace)

    imported = import_project(package, workspace, dry_run=True)

    assert imported.runs == (RUN_NAME,)
    assert "project.toml" in " ".join(imported.install.written)
    assert not imported.project_dir.exists()
    assert _snapshot(workspace) == before


def test_dry_run_refuses_taken_name(tmp_path) -> None:
    package = _project_package(tmp_path)
    workspace = tmp_path / "colleague"
    make_workspace(workspace, project="nancon")

    with pytest.raises(ImportConflictError, match="--name"):
        import_project(package, workspace, dry_run=True)


def test_absent_package_reported(tmp_path) -> None:
    workspace, _ = _colleague(tmp_path)

    with pytest.raises(FileNotFoundError, match="No project package"):
        import_project(tmp_path / "absent.tar", workspace)


def test_folder_without_publication_refused(tmp_path) -> None:
    workspace, _ = _colleague(tmp_path)
    stray = tmp_path / "stray"
    (stray / "one").mkdir(parents=True)
    (stray / "two").mkdir()

    with pytest.raises(FileNotFoundError, match="holds no PUBLICATION.json"):
        import_project(stray, workspace)

    assert not list((workspace / ".hmp").glob("import-*"))


def test_run_copy_is_no_project_package(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)

    with pytest.raises(ImportConflictError, match="hmp catalog import"):
        import_project(folder, workspace)


def test_changed_package_file_refused(tmp_path) -> None:
    package = _project_package(tmp_path)
    unpacked = tmp_path / "unpacked"
    with tarfile.open(package) as archive:
        archive.extractall(unpacked, filter="data")
    (unpacked / "nancon" / "INSTALL.toml").write_text("# edited\n", encoding="utf-8")
    workspace, _ = _colleague(tmp_path)

    with pytest.raises(ImportConflictError, match="does not match its PUBLICATION.json"):
        import_project(unpacked / "nancon", workspace)

    assert not (workspace / "projects" / "nancon").exists()


def test_taken_name_needs_another_name(tmp_path) -> None:
    package = _project_package(tmp_path)
    workspace = tmp_path / "colleague"
    make_workspace(workspace, project="nancon")

    with pytest.raises(ImportConflictError, match="projects/nancon exists"):
        import_project(package, workspace)

    assert import_project(package, workspace, name="nancon_lab").project_dir.is_dir()


def test_data_conflict_leaves_nothing(tmp_path) -> None:
    package = _project_package(tmp_path)
    workspace, _ = _colleague(tmp_path)
    (workspace / "data" / "dem").mkdir(parents=True)
    (workspace / DEM).write_bytes(b"another DEM")

    with pytest.raises(PayloadConflictError, match="data/dem/dem.tif"):
        import_project(package, workspace)

    assert not (workspace / "projects" / "nancon").exists()
    assert not list((workspace / "projects").glob(".*import*"))
    assert not list((workspace / ".hmp").glob("import-*"))


def _mesh_member(copy: Path, name: str, kind: str | None) -> None:
    """Write one product directory under ``products/`` of a package folder."""
    entry = copy / "products" / name
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "mesh.npz").write_bytes(b"arrays")
    if kind is not None:
        (entry / "meta.json").write_text(
            json.dumps({"key": name, "kind": kind, "bytes": 6, "written_at": 1.0}),
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    ("name", "kind", "seed", "bucket"),
    [
        pytest.param("a" * 64, "mesh", False, "installed", id="fresh-mesh"),
        pytest.param("a" * 64, "mesh", True, "present", id="already-present"),
        pytest.param("not-a-key", "mesh", False, "skipped", id="not-a-key"),
        pytest.param("b" * 64, "topography", False, "skipped", id="not-a-mesh"),
        pytest.param("c" * 64, None, False, "skipped", id="no-meta"),
    ],
)
def test_mesh_member_bucket(tmp_path, name, kind, seed, bucket) -> None:
    copy = tmp_path / "package"
    _mesh_member(copy, name, kind)
    store_root = tmp_path / "store"
    if seed:
        ProductStore(store_root).put(
            name, "mesh", lambda tmp: (tmp / "mesh.npz").write_bytes(b"held")
        )

    installed, present, skipped, legacy = _mesh_members(copy, store_root, install=True)

    assert installed == ((name,) if bucket == "installed" else ())
    assert present == ((name,) if bucket == "present" else ())
    assert skipped == ((name,) if bucket == "skipped" else ())
    assert legacy == ()
    if bucket in ("installed", "present"):
        assert (store_root / name[:2] / name / "meta.json").is_file()
    if bucket == "installed":
        assert (store_root / name[:2] / name / "mesh.npz").read_bytes() == b"arrays"
    if bucket == "present":
        assert (store_root / name[:2] / name / "mesh.npz").read_bytes() == b"held"
    if bucket == "skipped":
        assert not store_root.exists()


def test_legacy_mesh_cache_counted_only(tmp_path) -> None:
    copy = tmp_path / "package"
    for name in ("entry_one", "entry_two"):
        entry = copy / "mesh_cache" / name
        entry.mkdir(parents=True)
        (entry / "mesh.npz").write_bytes(b"old")
    store_root = tmp_path / "store"

    installed, present, skipped, legacy = _mesh_members(copy, store_root, install=True)

    assert installed == ()
    assert present == ()
    assert skipped == ()
    assert legacy == ("entry_one", "entry_two")
    assert not store_root.exists()
