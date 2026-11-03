"""Install a package into a workspace: its files under ``data/``, its rows, its sites.

What an install does
--------------------
Every file of the install index goes to ``<workspace>/<dest>`` (or under the
project for ``root = "project"``). Identical bytes already there cost
nothing; an absent file is copied with its sidecar; the same path with other
bytes is refused by name with both sha256. Station rows are merged into
``data/<variable>/<prefix>_<provider>_LOC.csv``. A file a provider delivered
is registered in ``data/cache.duckdb`` with its provider and its key, so a
run finds it instead of fetching it again; a station the cache already
serves from other bytes is refused. Each site is merged into
``data/sites/catalog.csv``: a name the catalog holds with another outlet,
or an outlet close to a site of another name, is refused by name.

Everything is planned first and refused as a whole: a refused install writes
nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from hydromodpy.core.payload import (
    InstallIndex,
    PayloadFile,
    Placement,
    plan_files,
    plan_stations,
    refuse_conflicts,
    sidecar_name,
    stored_name,
    write_file,
    write_stations,
)
from hydromodpy.core.payload.install import sha256_of
from hydromodpy.core.site import SiteRow

DATA_CACHE_FILENAME: Final[str] = "cache.duckdb"

_ADVICE: Final[str] = (
    "Nothing of the package was written. Move the file of your workspace aside, or import "
    "the package into another workspace."
)


@dataclass(slots=True)
class InstallReport:
    """What one install wrote, and what it found already there."""

    written: list[str] = field(default_factory=list)
    """Destinations copied, relative to the workspace (or ``<project>/...``)."""
    unchanged: list[str] = field(default_factory=list)
    """Destinations already holding the same bytes."""
    stations_written: list[str] = field(default_factory=list)
    """Station rows added to a registry."""
    cache_registered: list[str] = field(default_factory=list)
    """Destinations registered in ``data/cache.duckdb``."""
    sites_added: list[str] = field(default_factory=list)
    """Sites added to ``data/sites/catalog.csv``."""


@dataclass(frozen=True, slots=True)
class _CacheRow:
    item: PayloadFile
    path: Path
    row: Mapping[str, Any]


def install_index(
    index: InstallIndex,
    *,
    blobs: Path,
    workspace: Path,
    project: Path | None = None,
    dry_run: bool = False,
) -> InstallReport:
    """Install *index* into *workspace*, its bytes read from the folder *blobs*.

    With *dry_run* every check runs, the conflicts are refused as usual, and nothing is
    written: the report lists what a real install would write.

    Raises
    ------
    PayloadConflictError
        A file, a station row, a data cache key or a site would replace
        another one; nothing was written.
    """
    roots = {"workspace": Path(workspace).resolve()}
    if project is not None:
        roots["project"] = Path(project).resolve()
    _check_blobs(index, blobs)
    placements = plan_files(roots, index.files)
    merges = plan_stations(roots["workspace"], index.stations)
    cache_rows, cache_conflicts = _plan_cache(roots["workspace"], placements)
    sites, site_conflicts = _plan_sites(roots["workspace"], index.sites)
    refuse_conflicts(placements, merges, others=[*cache_conflicts, *site_conflicts], advice=_ADVICE)

    report = InstallReport()
    if dry_run:
        for placement in placements:
            target = report.unchanged if placement.status == "unchanged" else report.written
            target.append(placement.label)
        for merge in merges:
            if merge.changed:
                report.stations_written += merge.added
        report.cache_registered = [row.item.dest for row in cache_rows]
        report.sites_added = _new_sites(roots["workspace"], sites)
        return report
    for placement in placements:
        if placement.status == "unchanged":
            report.unchanged.append(placement.label)
            continue
        item = placement.item
        sidecar = None
        if item.sidecar_sha256 is not None:
            sidecar = blobs / sidecar_name(item.sidecar_sha256)
        write_file(placement, blobs / stored_name(item.sha256, item.dest), sidecar=sidecar)
        report.written.append(placement.label)
    report.stations_written = write_stations(merges)
    report.cache_registered = _register(roots["workspace"], cache_rows)
    report.sites_added = _write_sites(roots["workspace"], sites)
    return report


def _check_blobs(index: InstallIndex, blobs: Path) -> None:
    """Refuse a package whose stored bytes are missing or have another digest."""
    from hydromodpy.core.exceptions import ImportConflictError

    for item in index.files:
        wanted = [(stored_name(item.sha256, item.dest), item.sha256)]
        if item.sidecar_sha256 is not None:
            wanted.append((sidecar_name(item.sidecar_sha256), item.sidecar_sha256))
        for name, sha256 in wanted:
            path = Path(blobs) / name
            if not path.is_file() or sha256_of(path) != sha256:
                raise ImportConflictError(
                    f"{item.dest}: the package does not hold its bytes ({name}) with the "
                    "digest its INSTALL.toml states. Nothing was written."
                )


def _plan_cache(
    workspace: Path, placements: Sequence[Placement]
) -> tuple[list[_CacheRow], list[str]]:
    """Return the data cache rows to register, and the keys served by other bytes."""
    rows = [
        _CacheRow(placement.item, placement.path, placement.item.cache)
        for placement in placements
        if placement.item.cache
    ]
    if not rows:
        return [], []
    catalog_path = workspace / "data" / DATA_CACHE_FILENAME
    if not catalog_path.is_file():
        return rows, []
    from hydromodpy.data.registry import DataCatalogDuckDB

    kept: list[_CacheRow] = []
    conflicts: list[str] = []
    catalog = DataCatalogDuckDB(catalog_path, read_only=True)
    try:
        for row in rows:
            station = row.row.get("station_id")
            if station is None:
                kept.append(row)
                continue
            entry = catalog.find_cached(
                variable=str(row.row["variable"]), source=str(row.row["source"]), station_id=station
            )
            served = None if entry is None else _served_file(catalog, entry, row.row)
            if served is None or served.resolve() == row.path:
                kept.append(row)
                continue
            found = sha256_of(served) if served.is_file() else entry.sha256
            if found == row.item.sha256:
                continue
            conflicts.append(
                f"{row.row['source']} {row.row['variable']} station {station}: the data cache "
                f"serves {served.name} (sha256 {found}), the package brings {row.item.dest} "
                f"(sha256 {row.item.sha256})"
            )
    finally:
        catalog.close()
    return kept, conflicts


def _served_file(catalog: Any, entry: Any, row: Mapping[str, Any]) -> Path | None:
    """Return the file a cache entry names, or None for a sentinel."""
    from hydromodpy.data.registry.constants import SENTINEL_CUSTOM, SENTINEL_EMPTY

    if entry.file_path in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
        return None
    return catalog.resolve_path(entry.file_path, variable=str(row["variable"]))


def _register(workspace: Path, rows: Sequence[_CacheRow]) -> list[str]:
    """Register each delivered file in ``data/cache.duckdb``, its own sidecar kept."""
    if not rows:
        return []
    from hydromodpy.data.registry import DataCatalogDuckDB

    registered: list[str] = []
    catalog = DataCatalogDuckDB(workspace / "data" / DATA_CACHE_FILENAME)
    try:
        for row in rows:
            values = row.row
            bbox = values.get("bbox")
            catalog.register(
                variable=str(values["variable"]),
                source=str(values["source"]),
                file_path=row.path,
                station_id=values.get("station_id"),
                bbox=tuple(float(value) for value in bbox) if bbox else None,
                crs=values.get("crs"),
                date_start=values.get("date_start"),
                date_end=values.get("date_end"),
                frequency=values.get("frequency"),
                unit=values.get("unit"),
                source_unit=values.get("source_unit"),
                is_custom=False,
                file_sha256=row.item.sha256,
                fetch_metadata=_plain(values.get("fetch_metadata")),
                write_sidecar=False,
            )
            registered.append(row.item.dest)
    finally:
        catalog.close()
    return registered


def _plain(value: Any) -> Any:
    """Return a TOML table as plain dicts and lists, the form the cache stores as JSON."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _plan_sites(workspace: Path, sites: Sequence[SiteRow]) -> tuple[list[SiteRow], list[str]]:
    """Return the catalog with the sites of the package merged in, and the conflicts.

    A site of a name the catalog holds is the same catalog row when its outlet
    lies within ``near_site_m``; farther, it is another catchment under one
    name, as :func:`hydromodpy.config.sites.single_site.resolve_single_site`
    refuses. A new name goes through
    :func:`hydromodpy.data.sites.catalog.add_sites`, which refuses an outlet
    close to a site of another name.
    """
    if not sites:
        return [], []
    from hydromodpy.core.workspace.workspace_toml import near_site_m
    from hydromodpy.data.sites.catalog import (
        SITE_CATALOG_RELPATH,
        SiteConflictError,
        add_sites,
        nearest_site,
        read_catalog,
    )

    existing = read_catalog(workspace)
    distance = near_site_m(workspace)
    by_name = {row.site: row for row in existing}
    conflicts: list[str] = []
    new: list[SiteRow] = []
    for row in sites:
        held = by_name.get(row.site)
        if held is None:
            new.append(row)
            continue
        if row.x_outlet is None or row.y_outlet is None:
            continue
        found = nearest_site([held], x=row.x_outlet, y=row.y_outlet, crs=row.crs)
        if found is not None and found[1] > distance:
            conflicts.append(
                f"site {row.site}: {SITE_CATALOG_RELPATH} declares it with an outlet "
                f"{found[1]:.0f} m away (near_site_m = {distance:g} m): another catchment "
                "under one name"
            )
    if not new:
        return [], conflicts
    try:
        merged = add_sites(existing, new, near_site_m=distance)
    except SiteConflictError as exc:
        return [], [*conflicts, *exc.conflicts]
    return merged, conflicts


def _write_sites(workspace: Path, merged: Sequence[SiteRow]) -> list[str]:
    """Write the merged site catalog; return the names it added."""
    if not merged:
        return []
    from hydromodpy.data.sites.catalog import write_catalog

    added = _new_sites(workspace, merged)
    write_catalog(workspace, merged)
    return added


def _new_sites(workspace: Path, merged: Sequence[SiteRow]) -> list[str]:
    """Return the names of *merged* that the site catalog of *workspace* does not hold yet."""
    if not merged:
        return []
    from hydromodpy.data.sites.catalog import read_catalog

    before = {row.site for row in read_catalog(workspace)}
    return [row.site for row in merged if row.site not in before]


@dataclass(frozen=True, slots=True)
class ImportedRun:
    """A run brought in by ``hmp catalog import``, and what its inputs installed."""

    rel_dir: str
    """``runs/<name>`` of the imported run."""
    install: InstallReport | None
    """What the install of its inputs did; None for a copy that carries none."""


def import_run(
    project_root: Path, source: Path, *, name: str | None = None, dry_run: bool = False
) -> ImportedRun:
    """Import a published run into *project_root* and install its inputs into its workspace.

    The copy is checked against its ``PUBLICATION.json`` first
    (:func:`hydromodpy.results.catalog.registration.import_publication`). Its
    inputs are installed (:func:`install_index`) before the run enters
    ``runs/``: a conflict refuses the whole import and leaves the project and
    the workspace as they were. With *dry_run* the checks run and nothing is written.
    """
    from hydromodpy.core.payload import INSTALL_FILENAME, read_index
    from hydromodpy.project.share import workspace_of
    from hydromodpy.results.catalog.registration import import_publication
    from hydromodpy.results.export.publish import INPUTS_DIRNAME

    root = Path(project_root).resolve()
    reports: list[InstallReport] = []

    def install(copy: Path) -> None:
        if not (copy / INSTALL_FILENAME).is_file():
            return
        reports.append(
            install_index(
                read_index(copy),
                blobs=copy / INPUTS_DIRNAME,
                workspace=workspace_of(root),
                project=root,
                dry_run=dry_run,
            )
        )

    rel_dir = import_publication(root, Path(source), name=name, admit=install, dry_run=dry_run)
    return ImportedRun(rel_dir=rel_dir, install=reports[0] if reports else None)


@dataclass(frozen=True, slots=True)
class ImportedProject:
    """A project brought in by ``hmp project import``."""

    project_dir: Path
    """``<workspace>/projects/<name>``."""
    install: InstallReport
    """What the install of its files and data did."""
    runs: tuple[str, ...] = ()
    """Names of the runs it brought under ``runs/``."""
    sessions: tuple[str, ...] = ()
    """Names of the sessions it brought under ``sessions/``."""
    mesh_entries: tuple[str, ...] = ()
    """Keys of the mesh cache entries it brought under ``.hmp/mesh_cache/``."""


def import_project(
    source: Path, workspace: Path, *, name: str | None = None, dry_run: bool = False
) -> ImportedProject:
    """Import a package written by ``hmp publish --package`` as ``<workspace>/projects/<name>``.

    The package is checked against its ``PUBLICATION.json`` first. A name the
    workspace already holds is refused unless *name* gives another one. The
    files of the author and the data are installed by :func:`install_index`,
    a conflict refusing the whole import; the runs, sessions and mesh cache
    entries of the package keep their names. The project is built beside
    its destination and renamed into place in one step. With *dry_run* the package
    is checked and the report says what would land, the workspace staying as it is.

    Raises
    ------
    ImportConflictError
        The name is taken, a file or row of the package conflicts, or the
        package is no project package.
    """
    import os
    import shutil
    import tempfile
    import uuid

    from hydromodpy.core.exceptions import ImportConflictError
    from hydromodpy.core.payload import read_index
    from hydromodpy.core.state.paths import (
        INTERNAL_DIRNAME,
        PROJECTS_DIRNAME,
        runs_dir_for,
        sessions_dir_for,
    )
    from hydromodpy.results.export.project_package import (
        PACKAGE_MESH_DIRNAME,
        PACKAGE_RUNS_DIRNAME,
        PACKAGE_SESSIONS_DIRNAME,
    )
    from hydromodpy.results.export.publish import INPUTS_DIRNAME, verify
    from hydromodpy.results.publication import read_publication
    from hydromodpy.results.storage.contract import ALLOWED_RUN_ENTRIES

    root = Path(workspace).resolve()
    origin = Path(source).expanduser().resolve()
    if not origin.exists():
        raise FileNotFoundError(f"No project package at {origin}")
    if dry_run:
        staging = Path(tempfile.mkdtemp(prefix="import-"))
    else:
        staging = root / INTERNAL_DIRNAME / f"import-{uuid.uuid4().hex}"
        staging.mkdir(parents=True)
    built: Path | None = None
    try:
        copy = _unpacked(origin, staging)
        publication = read_publication(copy)
        if publication.kind != "project" or publication.members:
            raise ImportConflictError(
                f"{origin} is no project package: import a run with 'hmp catalog import', the "
                "members of a campaign copy one by one."
            )
        problems = verify(copy)
        if problems:
            raise ImportConflictError(
                f"{origin} does not match its PUBLICATION.json: {'; '.join(problems[:5])}. "
                "Nothing was written."
            )
        project_name = name or publication.source.project
        destination = root / PROJECTS_DIRNAME / project_name
        if destination.exists():
            raise ImportConflictError(
                f"{PROJECTS_DIRNAME}/{project_name} exists in {root}: pass --name <name> to "
                "import the project under another name."
            )
        if dry_run:
            return ImportedProject(
                project_dir=destination,
                install=install_index(
                    read_index(copy),
                    blobs=copy / INPUTS_DIRNAME,
                    workspace=root,
                    project=destination,
                    dry_run=True,
                ),
                runs=tuple(run.name for run in sorted((copy / PACKAGE_RUNS_DIRNAME).glob("*"))),
                sessions=tuple(
                    entry.name for entry in sorted((copy / PACKAGE_SESSIONS_DIRNAME).glob("*"))
                ),
                mesh_entries=tuple(
                    entry.name for entry in sorted((copy / PACKAGE_MESH_DIRNAME).glob("*"))
                ),
            )
        built = destination.with_name(f".{project_name}.import-{uuid.uuid4().hex[:8]}")
        built.mkdir(parents=True)
        report = install_index(
            read_index(copy), blobs=copy / INPUTS_DIRNAME, workspace=root, project=built
        )
        runs: list[str] = []
        for run in sorted((copy / PACKAGE_RUNS_DIRNAME).glob("*")):
            for entry in sorted(run.iterdir()):
                if entry.name in ALLOWED_RUN_ENTRIES:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            runs_dir_for(built).mkdir(parents=True, exist_ok=True)
            os.rename(run, runs_dir_for(built) / run.name)
            runs.append(run.name)
        sessions: list[str] = []
        for session in sorted((copy / PACKAGE_SESSIONS_DIRNAME).glob("*")):
            sessions_dir_for(built).mkdir(parents=True, exist_ok=True)
            os.rename(session, sessions_dir_for(built) / session.name)
            sessions.append(session.name)
        mesh: list[str] = []
        for entry in sorted((copy / PACKAGE_MESH_DIRNAME).glob("*")):
            cache = built / INTERNAL_DIRNAME / "mesh_cache"
            cache.mkdir(parents=True, exist_ok=True)
            os.rename(entry, cache / entry.name)
            mesh.append(entry.name)
        os.rename(built, destination)
        built = None
        return ImportedProject(
            project_dir=destination,
            install=report,
            runs=tuple(runs),
            sessions=tuple(sessions),
            mesh_entries=tuple(mesh),
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if built is not None:
            shutil.rmtree(built, ignore_errors=True)


def _unpacked(origin: Path, staging: Path) -> Path:
    """Copy or extract *origin* under *staging*; return the folder holding its publication."""
    import shutil
    import tarfile

    from hydromodpy.results.publication import publication_path

    landing = staging / "package"
    if origin.is_dir():
        shutil.copytree(origin, landing, symlinks=True)
    else:
        landing.mkdir()
        with tarfile.open(origin) as archive:
            archive.extractall(landing, filter="data")
    if publication_path(landing).is_file():
        return landing
    children = [entry for entry in landing.iterdir() if entry.is_dir()]
    if len(children) == 1 and publication_path(children[0]).is_file():
        return children[0]
    raise FileNotFoundError(f"{origin} holds no PUBLICATION.json: it was not written by hmp")


__all__ = [
    "ImportedProject",
    "ImportedRun",
    "InstallReport",
    "import_project",
    "import_run",
    "install_index",
]
