"""``hmp publish --package`` and ``hmp project import``: a whole project on the brick of a run.

The package carries the files the author wrote and the data the TOML files
reference, on the install index of a run; on demand the sealed runs, the
sessions, the mesh cache entries the runs read and the files a provider
delivered. The import lands the project as ``projects/<name>``, its data with
the rules of ``hmp catalog import``, its runs under their own names, and
refuses a name already taken unless ``--as`` gives another one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ImportConflictError
from hydromodpy.core.payload import PayloadConflictError, read_index
from hydromodpy.project.exchange.install import import_project
from hydromodpy.project.exchange.share import inputs_of
from hydromodpy.results.export.project_package import consumed_mesh_entries, export_project
from hydromodpy.results.export.publish import verify
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
)

PROJECT_TOML = """\
[site]
name = "nancon"

[geographic.catchment]
kind = "from_outlet_coord"
dem_init_path = "dem.tif"

[data]
types = ["hydrometry"]

[[data.hydrometry.sources]]
source = "custom"
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
        project, tmp_path / "nancon.tar", with_=extras, bundle_of=inputs_of(project)
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


def _mesh_entry(cache: Path, key: str, request_hash: str) -> None:
    entry = cache / key
    entry.mkdir(parents=True)
    (entry / "mesh.npz").write_bytes(b"arrays")
    (entry / "mesh.json").write_text(
        json.dumps(
            {
                "identity": {
                    "engine_id": "gmsh",
                    "engine_version": "1.0",
                    "request_hash": request_hash,
                }
            }
        ),
        encoding="utf-8",
    )


def test_with_mesh_the_package_takes_the_cache_entries_the_runs_read(tmp_path) -> None:
    import zarr

    project = _project(tmp_path)
    run = project / "runs" / RUN_NAME
    root = zarr.open_group(str(run / "fields.zarr"), mode="w")
    root.attrs["zarr_schema_version"] = ZARR_SCHEMA_VERSION
    mesh = root.create_group("mesh")
    mesh.attrs.update(engine="gmsh", engine_version="1.0", mesh_request_hash="r1")
    cache = project / ".hmp" / "mesh_cache"
    _mesh_entry(cache, "a" * 64, "r1")
    _mesh_entry(cache, "b" * 64, "r2")

    assert [entry.name for entry in consumed_mesh_entries(project, [run])] == ["a" * 64]
    package = export_project(
        project,
        tmp_path / "nancon.tar",
        with_=("runs", "mesh", "sessions"),
        bundle_of=inputs_of(project),
    )
    workspace = tmp_path / "colleague"
    make_workspace(workspace, project="other")
    imported = import_project(package, workspace)

    assert imported.mesh_entries == ("a" * 64,)
    assert (imported.project_dir / ".hmp" / "mesh_cache" / ("a" * 64) / "mesh.npz").is_file()
    assert not (imported.project_dir / ".hmp" / "mesh_cache" / ("b" * 64)).exists()


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
