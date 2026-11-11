"""Installing a shared package into a workspace: what lands, what is refused, and why.

A colleague shares a sealed run or a whole project. Its package holds the
files the run read (a DEM, discharge series), the station rows that locate
the gauges, a file a provider delivered, and the site. Installing it into
another workspace follows three rules the tests below read out loud:

* identical bytes already there cost nothing, an absent file is copied with
  its sidecar;
* every conflict (same path with other bytes, a station declared with another
  position, a data cache key served by other bytes, a site with another
  outlet) is collected, named, and refused as a whole: nothing is written;
* a delivered file whose sidecar lacks its row of the data cache gets it from
  the cache table of the package;
* ``dry_run`` runs every check and reports what a real install would do.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.exceptions import ImportConflictError
from hydromodpy.core.payload import PayloadConflictError, read_index, stored_name
from hydromodpy.core.site import SiteRow
from hydromodpy.data.provenance.sidecars import (
    FORMER_CACHE_DATABASE,
    CacheIndex,
    empty_path_for,
    load_sidecar,
)
from hydromodpy.data.sites.catalog import read_catalog, write_catalog
from hydromodpy.project.exchange.install import (
    ImportedProject,
    ImportedRun,
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


# --- share -> install round trip ---------------------------------------------------


def test_a_shared_run_installs_every_file_row_cache_entry_and_site(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)

    report = _install(folder, workspace)

    assert sorted(report.written) == sorted(THE_THREE_FILES)
    assert report.unchanged == []
    assert len(report.stations_written) == 2
    assert report.cache_registered == [f"data/hydrometry/{HUBEAU_FILE}"]
    assert report.sites_added == ["J0014010"]
    author = tmp_path / "author"
    for relative in THE_THREE_FILES:
        assert (workspace / relative).read_bytes() == (author / relative).read_bytes()
    assert (workspace / f"data/hydrometry/{HUBEAU_FILE}.json").is_file()
    assert [row.site for row in read_catalog(workspace)] == ["J0014010"]


def test_files_restricts_the_install_to_those_files_and_their_registries(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    delivered = read_index(folder).file_at(f"data/hydrometry/{HUBEAU_FILE}")

    report = _install(folder, workspace, files=[delivered])

    assert report.written == [delivered.dest]
    assert report.cache_registered == [delivered.dest]
    assert report.sites_added == []
    assert len(report.stations_written) == 1
    registries = sorted(p.name for p in (workspace / "data" / "hydrometry").glob("*_LOC.csv"))
    assert registries == ["hydrometry_hubeau_LOC.csv"]
    assert sorted(p.name for p in (workspace / "data").rglob("*") if p.is_file()) == sorted(
        [HUBEAU_FILE, f"{HUBEAU_FILE}.json", "hydrometry_hubeau_LOC.csv"]
    )


def test_files_still_refuses_a_conflict_on_its_own_files_only(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    delivered = read_index(folder).file_at(f"data/hydrometry/{HUBEAU_FILE}")
    other = workspace / DEM
    other.parent.mkdir(parents=True)
    other.write_bytes(b"another DEM")
    held = workspace / delivered.dest
    held.parent.mkdir(parents=True)
    held.write_text("other bytes\n", encoding="utf-8")

    with pytest.raises(PayloadConflictError) as refused:
        _install(folder, workspace, files=[delivered])

    assert HUBEAU_FILE in str(refused.value)
    assert DEM not in str(refused.value)
    assert other.read_bytes() == b"another DEM"


def test_files_names_a_file_the_index_does_not_list(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    unlisted = dataclasses.replace(read_index(folder).files[0], dest="data/dem/unlisted.tif")

    with pytest.raises(ValueError, match="unlisted.tif"):
        _install(folder, workspace, files=[unlisted])

    assert not (workspace / "data" / "dem").exists()


def test_installing_twice_the_second_time_changes_nothing(tmp_path) -> None:
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


def test_a_dry_run_reports_what_would_land_and_writes_nothing(tmp_path) -> None:
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


def test_a_dry_run_still_refuses_a_conflict(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    (workspace / "data" / "dem").mkdir(parents=True)
    (workspace / DEM).write_bytes(b"mine")

    with pytest.raises(PayloadConflictError, match="data/dem/dem.tif"):
        _install(folder, workspace, dry_run=True)


# --- the table of conflicts, named before anything is written -------------------------


def test_every_conflict_is_named_in_one_refusal_and_nothing_is_written(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    mine = b"the colleague's own DEM"
    (workspace / "data" / "dem").mkdir(parents=True)
    (workspace / DEM).write_bytes(mine)
    registry = workspace / CUSTOM_REGISTRY
    registry.parent.mkdir(parents=True)
    registry.write_text("id,x,y,crs,unit\nNANCON,1,1,EPSG:2154,m3/s\n", encoding="utf-8")
    write_catalog(
        workspace, [SiteRow(site="J0014010", x_outlet=0.0, y_outlet=0.0, crs="EPSG:2154")]
    )
    before = _snapshot(workspace)

    with pytest.raises(PayloadConflictError) as refused:
        _install(folder, workspace)

    message = str(refused.value)
    assert "data/dem/dem.tif" in message
    assert hashlib.sha256(mine).hexdigest() in message
    assert sha256_of(tmp_path / "author" / DEM) in message
    assert "station NANCON" in message
    assert "site J0014010" in message
    assert "another catchment under one name" in message
    assert "Nothing of the package was written" in message
    assert _snapshot(workspace) == before


def test_a_data_cache_key_served_by_other_bytes_is_refused_by_name(tmp_path) -> None:
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


def test_a_data_cache_key_served_by_the_same_bytes_elsewhere_is_left_alone(tmp_path) -> None:
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


def test_a_data_cache_entry_at_the_destination_itself_is_registered_again(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    _install(folder, workspace)

    report = _install(folder, workspace)

    assert report.cache_registered == [f"data/hydrometry/{HUBEAU_FILE}"]


def test_an_empty_row_for_the_station_does_not_block_the_install(tmp_path) -> None:
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


def test_a_sidecar_without_the_row_is_completed_from_the_cache_table(tmp_path) -> None:
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
    ("held", "refused"),
    [
        pytest.param(None, False, id="same-outlet"),
        pytest.param(dict(x_outlet=None, y_outlet=None), False, id="no-outlet-declared"),
        pytest.param(dict(x_outlet=0.0, y_outlet=0.0), True, id="far-outlet"),
    ],
)
def test_a_site_name_the_catalog_holds_is_refused_only_with_another_outlet(
    tmp_path, held, refused
) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    shared_site = _site_of(folder)
    if held is None:
        held = {"x_outlet": shared_site.x_outlet, "y_outlet": shared_site.y_outlet}
    write_catalog(workspace, [SiteRow(site=shared_site.site, crs=shared_site.crs, **held)])

    if refused:
        with pytest.raises(PayloadConflictError, match=f"site {shared_site.site}"):
            _install(folder, workspace)
    else:
        report = _install(folder, workspace)
        assert report.sites_added == []


def _site_of(folder: Path) -> SiteRow:
    (site,) = read_index(folder).sites
    return site


def test_a_site_whose_outlet_is_next_to_another_name_is_refused(tmp_path) -> None:
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


# --- a package that does not hold its bytes ------------------------------------------


def test_a_missing_blob_refuses_the_install_naming_the_file(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    dem = next(item for item in read_index(folder).files if item.dest == DEM)
    (folder / INPUTS_DIRNAME / stored_name(dem.sha256, dem.dest)).unlink()

    with pytest.raises(ImportConflictError, match="data/dem/dem.tif: the package does not hold"):
        _install(folder, workspace)

    assert not (workspace / "data" / "dem").exists()


def test_a_blob_with_another_digest_refuses_the_install(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    dem = next(item for item in read_index(folder).files if item.dest == DEM)
    (folder / INPUTS_DIRNAME / stored_name(dem.sha256, dem.dest)).write_bytes(b"tampered")

    with pytest.raises(ImportConflictError, match="digest its INSTALL.toml states"):
        _install(folder, workspace)


def test_a_missing_sidecar_blob_refuses_the_install(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)
    (item,) = [i for i in read_index(folder).files if i.sidecar_sha256 is not None]
    sidecars = [p for p in (folder / INPUTS_DIRNAME).iterdir() if item.sidecar_sha256 in p.name]
    assert sidecars
    sidecars[0].unlink()

    with pytest.raises(ImportConflictError, match="does not hold its bytes"):
        _install(folder, workspace)


# --- import_run -------------------------------------------------------------------------


def test_import_run_brings_the_run_and_installs_its_inputs(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, project = _colleague(tmp_path)

    imported = import_run(project, folder)

    assert isinstance(imported, ImportedRun)
    assert imported.rel_dir == f"runs/{RUN_NAME}"
    assert (project / imported.rel_dir / "manifest.json").is_file()
    assert sorted(imported.install.written) == sorted(THE_THREE_FILES)
    assert (workspace / DEM).is_file()


def test_import_run_dry_run_checks_everything_and_writes_nothing(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, project = _colleague(tmp_path)
    before = _snapshot(workspace)

    imported = import_run(project, folder, dry_run=True)

    assert imported.rel_dir == f"runs/{RUN_NAME}"
    assert sorted(imported.install.written) == sorted(THE_THREE_FILES)
    assert _snapshot(workspace) == before
    assert not (project / "runs").exists()


def test_import_run_refuses_on_a_conflict_and_leaves_the_project_as_it_was(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, project = _colleague(tmp_path)
    (workspace / "data" / "dem").mkdir(parents=True)
    (workspace / DEM).write_bytes(b"mine")

    with pytest.raises(PayloadConflictError):
        import_run(project, folder)

    assert not (project / "runs").exists() or not any((project / "runs").iterdir())


def test_a_run_published_without_inputs_installs_nothing(tmp_path) -> None:
    project = _author_project(tmp_path)
    bare = publish(
        project / "runs" / RUN_NAME,
        tmp_path / "bare" / RUN_NAME,
        project_root=project,
        format="dir",
        with_=("results",),
    )
    workspace, target = _colleague(tmp_path)

    imported = import_run(target, bare)

    assert imported.install is None
    assert (target / imported.rel_dir / "manifest.json").is_file()
    assert not (workspace / "data" / "dem").exists()


# --- import_project ---------------------------------------------------------------------


def test_import_project_lands_the_project_beside_the_others(tmp_path) -> None:
    package = _project_package(tmp_path, "runs")
    workspace, _ = _colleague(tmp_path)

    imported = import_project(package, workspace)

    assert isinstance(imported, ImportedProject)
    assert imported.project_dir == workspace / "projects" / "nancon"
    assert (imported.project_dir / "project.toml").read_text(encoding="utf-8").startswith("[site]")
    assert imported.runs == (RUN_NAME,)
    assert imported.sessions == ()
    assert imported.mesh_entries == ()
    assert imported.mesh_present == ()
    assert imported.mesh_skipped == ()
    assert imported.legacy_mesh_cache == ()
    assert (workspace / DEM).is_file()
    assert not list((workspace / "projects").glob(".*import*"))
    assert not list((workspace / ".hmp").glob("import-*"))


def test_import_project_reads_an_unpacked_folder_as_well_as_a_tar(tmp_path) -> None:
    package = _project_package(tmp_path)
    unpacked = tmp_path / "unpacked"
    with tarfile.open(package) as archive:
        archive.extractall(unpacked, filter="data")
    workspace, _ = _colleague(tmp_path)

    imported = import_project(unpacked / "nancon", workspace, name="from_folder")

    assert imported.project_dir == workspace / "projects" / "from_folder"
    assert (imported.project_dir / "project.toml").is_file()


def test_import_project_dry_run_lists_the_runs_and_writes_nothing(tmp_path) -> None:
    package = _project_package(tmp_path, "runs")
    workspace, _ = _colleague(tmp_path)
    before = _snapshot(workspace)

    imported = import_project(package, workspace, dry_run=True)

    assert imported.runs == (RUN_NAME,)
    assert "project.toml" in " ".join(imported.install.written)
    assert not imported.project_dir.exists()
    assert _snapshot(workspace) == before


def test_import_project_dry_run_still_refuses_a_name_already_taken(tmp_path) -> None:
    package = _project_package(tmp_path)
    workspace = tmp_path / "colleague"
    make_workspace(workspace, project="nancon")

    with pytest.raises(ImportConflictError, match="--name"):
        import_project(package, workspace, dry_run=True)


# --- every error raised to the user by import_project -----------------------------------


def test_a_package_that_does_not_exist_is_reported(tmp_path) -> None:
    workspace, _ = _colleague(tmp_path)

    with pytest.raises(FileNotFoundError, match="No project package"):
        import_project(tmp_path / "absent.tar", workspace)


def test_a_folder_without_publication_json_was_not_written_by_hmp(tmp_path) -> None:
    workspace, _ = _colleague(tmp_path)
    stray = tmp_path / "stray"
    (stray / "one").mkdir(parents=True)
    (stray / "two").mkdir()

    with pytest.raises(FileNotFoundError, match="holds no PUBLICATION.json"):
        import_project(stray, workspace)

    assert not list((workspace / ".hmp").glob("import-*"))


def test_a_published_run_is_no_project_package(tmp_path) -> None:
    folder = _shared_run_folder(tmp_path)
    workspace, _ = _colleague(tmp_path)

    with pytest.raises(ImportConflictError, match="hmp catalog import"):
        import_project(folder, workspace)


def test_a_package_with_a_changed_file_is_refused_with_its_name(tmp_path) -> None:
    package = _project_package(tmp_path)
    unpacked = tmp_path / "unpacked"
    with tarfile.open(package) as archive:
        archive.extractall(unpacked, filter="data")
    (unpacked / "nancon" / "INSTALL.toml").write_text("# edited\n", encoding="utf-8")
    workspace, _ = _colleague(tmp_path)

    with pytest.raises(ImportConflictError, match="does not match its PUBLICATION.json"):
        import_project(unpacked / "nancon", workspace)

    assert not (workspace / "projects" / "nancon").exists()


def test_a_name_already_taken_is_refused_unless_name_gives_another(tmp_path) -> None:
    package = _project_package(tmp_path)
    workspace = tmp_path / "colleague"
    make_workspace(workspace, project="nancon")

    with pytest.raises(ImportConflictError, match="projects/nancon exists"):
        import_project(package, workspace)

    assert import_project(package, workspace, name="nancon_lab").project_dir.is_dir()


def test_a_conflict_in_the_data_leaves_no_project_and_no_staging_folder(tmp_path) -> None:
    package = _project_package(tmp_path)
    workspace, _ = _colleague(tmp_path)
    (workspace / "data" / "dem").mkdir(parents=True)
    (workspace / DEM).write_bytes(b"another DEM")

    with pytest.raises(PayloadConflictError, match="data/dem/dem.tif"):
        import_project(package, workspace)

    assert not (workspace / "projects" / "nancon").exists()
    assert not list((workspace / "projects").glob(".*import*"))
    assert not list((workspace / ".hmp").glob("import-*"))


# --- the mesh products of a package ---------------------------------------------------


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
def test_a_mesh_member_is_installed_counted_or_skipped(tmp_path, name, kind, seed, bucket) -> None:
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


def test_the_mesh_cache_of_a_legacy_package_is_counted_and_never_installed(tmp_path) -> None:
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
