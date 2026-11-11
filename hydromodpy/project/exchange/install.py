"""Install a package into a workspace: its files under ``data/``, its rows, its sites.

What an install does
--------------------
Every file of the install index goes to ``<workspace>/<dest>`` (or under the
project for ``root = "project"``). Identical bytes already there cost
nothing; an absent file is copied with its sidecar; the same path with other
bytes is refused by name with both sha256. Station rows are merged into
``data/<variable>/<prefix>_<provider>_LOC.csv``. A file a provider delivered
gets its sidecar completed with its provider and its key, so a run finds it
instead of fetching it again; a station the cache already serves from other
bytes is refused. Each site is merged into
``data/sites/catalog.csv``: a name the catalog holds with another outlet,
or an outlet close to a site of another name, is refused by name.

Everything is planned first and refused as a whole: a refused install writes
nothing. A replay of a published copy installs only the files a provider
delivered, through the ``files`` argument.

``install_index`` places files, station rows, cache rows and sites, and it names every
conflict before anything is written. ``import_run`` serves ``hmp catalog import`` and
``import_project`` serves ``hmp project import``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Final

from hydromodpy.core.payload.index import InstallIndex, PayloadFile, sidecar_name, stored_name
from hydromodpy.core.payload.install import (
    Placement,
    plan_files,
    plan_stations,
    refuse_conflicts,
    sha256_of,
    write_file,
    write_stations,
)
from hydromodpy.core.site.row import SiteRow
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.data.provenance.lockfile import USER_FILE_SOURCE
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.results.products.store import META_FILENAME, ProductStore, products_root

DATA_DIRNAME: Final[str] = "data"

LEGACY_PACKAGE_MESH_DIRNAME: Final[str] = "mesh_cache"
"""Folder a 2.0 package used for the mesh cache entries; a 2.1 install skips it."""

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
    """Destinations whose sidecar now states their row of the data cache."""
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
    files: Sequence[PayloadFile] | None = None,
) -> InstallReport:
    """Install *index* into *workspace*, its bytes read from the folder *blobs*.

    With *dry_run* every check runs, the conflicts are refused as usual, and nothing is
    written: the report lists what a real install would write.

    With *files*, only those files of the index are installed, with their sidecars, their
    cache rows and the station rows of their registries. The other files, the other station
    rows and the sites stay out, and only the blobs of the files are checked. A replay uses
    it to install what a provider delivered and nothing else.

    Raises
    ------
    PayloadConflictError
        A file, a station row, a data cache key or a site would replace
        another one; nothing was written.
    ValueError
        A file of *files* the index does not list.
    """
    if files is not None:
        index = _restricted(index, files)
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


def _restricted(index: InstallIndex, files: Sequence[PayloadFile]) -> InstallIndex:
    """Return *index* cut down to *files*, the station rows of their registries and no site."""
    wanted = {(item.root, item.dest) for item in files}
    kept = tuple(item for item in index.files if (item.root, item.dest) in wanted)
    unknown = wanted - {(item.root, item.dest) for item in kept}
    if unknown:
        raise ValueError(f"the index lists no file at {sorted(dest for _, dest in unknown)}")
    registries = {
        (PurePosixPath(item.dest).parent, f"_{item.provider}_LOC.csv")
        for item in kept
        if item.provider is not None
    }
    stations = tuple(
        station
        for station in index.stations
        if any(
            PurePosixPath(station.dest).parent == folder
            and PurePosixPath(station.dest).name.endswith(suffix)
            for folder, suffix in registries
        )
    )
    return replace(index, files=kept, stations=stations, sites=())


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


def _cache_problem(row: _CacheRow, data_root: Path) -> str | None:
    """Return why the cache table of *row* cannot become a sidecar row, or None."""
    values = row.row
    if not values.get("variable") or not values.get("source"):
        return f"{row.item.dest}: its cache table names no variable or no source"
    if str(values["source"]) == USER_FILE_SOURCE:
        return f"{row.item.dest}: a user file is no row of the data cache"
    if not Path(row.path).resolve().is_relative_to(data_root):
        return f"{row.item.dest}: a row of the data cache lies under data/ only"
    return None


def _plan_cache(
    workspace: Path, placements: Sequence[Placement]
) -> tuple[list[_CacheRow], list[str]]:
    """Return the cache rows to complete, and the keys served by other bytes."""
    rows = [
        _CacheRow(placement.item, placement.path, placement.item.cache)
        for placement in placements
        if placement.item.cache
    ]
    if not rows:
        return [], []
    data_root = (workspace / DATA_DIRNAME).resolve()
    index = CacheIndex(data_root)
    kept: list[_CacheRow] = []
    conflicts: list[str] = []
    for row in rows:
        problem = _cache_problem(row, data_root)
        if problem is not None:
            conflicts.append(problem)
            continue
        station = row.row.get("station_id")
        if station is None:
            kept.append(row)
            continue
        held = [
            found
            for found in index.rows(
                variable=str(row.row["variable"]),
                source=str(row.row["source"]),
                station_id=str(station),
            )
            if not found.empty
        ]
        if not held or any(found.path == Path(row.path).resolve() for found in held):
            kept.append(row)
            continue
        served = held[0]
        found_sha256 = sha256_of(served.path) if served.path.is_file() else served.sha256
        if found_sha256 == row.item.sha256:
            continue
        conflicts.append(
            f"{row.row['source']} {row.row['variable']} station {station}: the data cache "
            f"serves {served.path.name} (sha256 {found_sha256}), the package brings "
            f"{row.item.dest} (sha256 {row.item.sha256})"
        )
    return kept, conflicts


def _register(workspace: Path, rows: Sequence[_CacheRow]) -> list[str]:
    """Complete the sidecar of each delivered file that lacks the row its package states."""
    if not rows:
        return []
    index = CacheIndex(workspace / DATA_DIRNAME)
    registered: list[str] = []
    for row in rows:
        values = row.row
        held = index.row_for(row.path)
        if (
            held is not None
            and held.variable == str(values["variable"])
            and held.source == str(values["source"])
            and held.station_id == values.get("station_id")
        ):
            # The sidecar the package carried already holds the row: its bytes stay as shipped.
            # One station keeps one row, so any other row of it leaves.
            for other in index.rows(held.variable, held.source, held.station_id):
                if other.path != held.path and held.station_id is not None:
                    index.forget(other, delete_file=True)
            registered.append(row.item.dest)
            continue
        bbox = values.get("bbox")
        window = values.get("asked_window")
        index.record(
            row.path,
            variable=str(values["variable"]),
            source=str(values["source"]),
            station_id=values.get("station_id"),
            product=values.get("product"),
            product_version=values.get("product_version"),
            bbox=tuple(float(value) for value in bbox) if bbox else None,
            crs=values.get("crs"),
            date_start=values.get("date_start"),
            date_end=values.get("date_end"),
            asked_window=tuple(window) if window else None,
            frequency=values.get("frequency"),
            unit=values.get("unit"),
            source_unit=values.get("source_unit"),
            fetch_metadata=_plain(values.get("fetch_metadata")),
        )
        registered.append(row.item.dest)
    return registered


def _plain(value: Any) -> Any:
    """Return a TOML table as plain dicts and lists, the form a sidecar stores as JSON."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _plan_sites(workspace: Path, sites: Sequence[SiteRow]) -> tuple[list[SiteRow], list[str]]:
    """Return the catalog with the sites of the package merged in, and the conflicts.

    A site of a name the catalog holds is the same catalog row when its outlet
    lies within ``near_site_m``; farther, it is another catchment under one
    name, as :func:`hydromodpy.data.sites.single_site.resolve_single_site`
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
    from hydromodpy.core.payload.index import INSTALL_FILENAME, read_index
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
                workspace=locate_workspace_root(root) or root,
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
    """Keys of the mesh products it installed under ``.hmp/products/``."""
    mesh_present: tuple[str, ...] = ()
    """Keys already in the product store of the destination."""
    mesh_skipped: tuple[str, ...] = ()
    """Names under ``products/`` not installed: no sha256 key, or not a mesh."""
    legacy_mesh_cache: tuple[str, ...] = ()
    """Names under ``mesh_cache/`` of a 2.0 package, never installed."""


def import_project(
    source: Path, workspace: Path, *, name: str | None = None, dry_run: bool = False
) -> ImportedProject:
    """Import a package written by ``hmp publish --package`` as ``<workspace>/projects/<name>``.

    The package is checked against its ``PUBLICATION.json`` first. A name the
    workspace already holds is refused unless *name* gives another one. The
    files of the author and the data are installed by :func:`install_index`,
    a conflict refusing the whole import; the runs and sessions of the package
    keep their names, and its mesh products land under ``.hmp/products/`` by
    :class:`~hydromodpy.results.products.store.ProductStore.put`. The project is
    built beside its destination and renamed into place in one step. With
    *dry_run* the package is checked and the report says what would land, the
    workspace staying as it is.

    Raises
    ------
    ImportConflictError
        The name is taken, a file or row of the package conflicts, or the
        package is no project package.
    """
    import shutil
    import tempfile
    import uuid

    from hydromodpy.core.exceptions import ImportConflictError
    from hydromodpy.core.payload.index import read_index
    from hydromodpy.core.state.layout import INTERNAL_DIRNAME, PROJECTS_DIRNAME
    from hydromodpy.results.export.publish import INPUTS_DIRNAME

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
        copy, project_name = _checked_package(origin, staging, name)
        destination = root / PROJECTS_DIRNAME / project_name
        if destination.exists():
            raise ImportConflictError(
                f"{PROJECTS_DIRNAME}/{project_name} exists in {root}: pass --name <name> to "
                "import the project under another name."
            )
        runs, sessions = _package_runs_and_sessions(copy)
        if dry_run:
            report = install_index(
                read_index(copy),
                blobs=copy / INPUTS_DIRNAME,
                workspace=root,
                project=destination,
                dry_run=True,
            )
            mesh = _mesh_members(copy, products_root(destination), install=False)
            return ImportedProject(destination, report, runs, sessions, *mesh)
        built = destination.with_name(f".{project_name}.import-{uuid.uuid4().hex[:8]}")
        built.mkdir(parents=True)
        report = install_index(
            read_index(copy), blobs=copy / INPUTS_DIRNAME, workspace=root, project=built
        )
        _move_members(copy, built)
        mesh = _mesh_members(copy, products_root(built), install=True)
        built.rename(destination)
        built = None
        return ImportedProject(destination, report, runs, sessions, *mesh)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if built is not None:
            shutil.rmtree(built, ignore_errors=True)


def _checked_package(origin: Path, staging: Path, name: str | None) -> tuple[Path, str]:
    """Unpack a project package under *staging*, check it, and return its folder and project name."""
    from hydromodpy.core.exceptions import ImportConflictError
    from hydromodpy.results.export.publish import verify
    from hydromodpy.results.publication import read_publication

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
    return copy, name or publication.source.project


def _package_runs_and_sessions(copy: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the names of the runs and sessions a package holds."""
    from hydromodpy.results.export.project_package import (
        PACKAGE_RUNS_DIRNAME,
        PACKAGE_SESSIONS_DIRNAME,
    )

    runs = tuple(entry.name for entry in sorted((copy / PACKAGE_RUNS_DIRNAME).glob("*")))
    sessions = tuple(entry.name for entry in sorted((copy / PACKAGE_SESSIONS_DIRNAME).glob("*")))
    return runs, sessions


def _mesh_members(
    copy: Path, store_root: Path, *, install: bool
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return what the mesh members of a package become, and install them with *install*.

    A product under ``products/`` goes into the store by
    :meth:`~hydromodpy.results.products.store.ProductStore.put` with a writer
    that copies its files. A key that is no sha256 or a product whose
    ``meta.json`` is no mesh is skipped, as is a key the store already holds.
    The ``mesh_cache/`` of a 2.0 package is never read, only counted.
    """
    from hydromodpy.results.export.project_package import PACKAGE_PRODUCTS_DIRNAME

    store = ProductStore(store_root)
    installed: list[str] = []
    present: list[str] = []
    skipped: list[str] = []
    source = copy / PACKAGE_PRODUCTS_DIRNAME
    for entry in sorted(source.glob("*")) if source.is_dir() else []:
        if not entry.is_dir():
            continue
        kind = _product_kind(entry)
        if kind != "mesh":
            skipped.append(entry.name)
            continue
        try:
            hit = store.get(entry.name)
        except ValueError:
            skipped.append(entry.name)
            continue
        if hit is not None:
            present.append(entry.name)
            continue
        if install:
            store.put(entry.name, "mesh", _copy_product_files(entry))
        installed.append(entry.name)
    legacy = copy / LEGACY_PACKAGE_MESH_DIRNAME
    legacy_names = (
        tuple(entry.name for entry in sorted(legacy.glob("*")) if entry.is_dir())
        if legacy.is_dir()
        else ()
    )
    return tuple(installed), tuple(present), tuple(skipped), legacy_names


def _product_kind(entry: Path) -> str | None:
    """Return the kind of a product directory, or None when its ``meta.json`` is unreadable."""
    try:
        meta = json.loads((entry / META_FILENAME).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None
    kind = meta.get("kind")
    return str(kind) if isinstance(kind, str) else None


def _copy_product_files(entry: Path):
    """Return the writer that copies the files of one product into a store directory."""
    import shutil

    def write(tmp: Path) -> None:
        for child in entry.iterdir():
            if child.name == META_FILENAME:
                continue
            if child.is_dir():
                shutil.copytree(child, tmp / child.name)
            else:
                shutil.copy2(child, tmp / child.name)

    return write


def _move_members(copy: Path, built: Path) -> None:
    """Move the runs and sessions of a package into the project *built*."""
    import shutil

    from hydromodpy.core.state.layout import runs_dir_for, sessions_dir_for
    from hydromodpy.results.export.project_package import (
        PACKAGE_RUNS_DIRNAME,
        PACKAGE_SESSIONS_DIRNAME,
    )
    from hydromodpy.results.storage.contract import ALLOWED_RUN_ENTRIES

    for run in sorted((copy / PACKAGE_RUNS_DIRNAME).glob("*")):
        for entry in sorted(run.iterdir()):
            if entry.name in ALLOWED_RUN_ENTRIES:
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        runs_dir_for(built).mkdir(parents=True, exist_ok=True)
        run.rename(runs_dir_for(built) / run.name)
    for session in sorted((copy / PACKAGE_SESSIONS_DIRNAME).glob("*")):
        sessions_dir_for(built).mkdir(parents=True, exist_ok=True)
        session.rename(sessions_dir_for(built) / session.name)


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
