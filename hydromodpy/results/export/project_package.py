"""Export a whole project with its data: ``hmp publish --package``.

Why
---
A project travels the way a run does: on the install index of
:mod:`hydromodpy.core.payload`, so ``hmp project import`` places it in another
workspace with the rules of ``hmp catalog import``.

What the package holds
----------------------
Always, in ``INSTALL.toml`` and under ``inputs/`` by content: the files the
author wrote (the TOML files, scripts and README at the project root,
``sites.csv``, ``site_overrides/``), project-relative, and every data file the
TOML files reference, resolved the way a run resolves them
(:func:`hydromodpy.core.payload.resolve.project_data`), with the station rows
their registries hold. On demand:

- ``runs``: every sealed run, published with its results under ``runs/<name>/``
  (:mod:`hydromodpy.results.export.publish`), and every user file a run read;
- ``sessions``: every session directory under ``sessions/<name>/``, redacted;
- ``mesh``: the ``.hmp/mesh_cache/<key>/`` entries the runs consumed, since gmsh
  does not draw the same mesh twice;
- ``fetched``: every file a provider delivered to a run, with the row of the
  data cache that serves it, so the import does not fetch it again.

``PUBLICATION.json`` is of kind ``project`` and lists the digest of every file
of the package, so :func:`hydromodpy.results.export.publish.verify` checks it.
Nothing in the package names the machine: a copy that would is refused.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from hydromodpy.core.config_kit.root import RootConfig
from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.payload import (
    InstallIndex,
    PayloadBundle,
    PayloadFile,
    PayloadStation,
    payload_file_of,
    sidecar_name,
    stored_name,
)
from hydromodpy.core.payload.install import sha256_of
from hydromodpy.core.payload.resolve import authored_files, project_data
from hydromodpy.core.site import SiteRow
from hydromodpy.core.state.layout import INTERNAL_DIRNAME, runs_dir_for, sessions_dir_for
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.results.export.publish import (
    InputsOf,
    _copy_bundle,
    _copy_tree,
    _digests,
    _move_into_place,
    _private_prefixes,
    _publish_one,
    _refuse_leaks,
    _target_path,
)
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.publication import (
    PROJECT_REL_DIR,
    Publication,
    PublicationFormat,
    PublicationSource,
    PublishedLine,
    append_published,
    write_publication,
)
from hydromodpy.results.run_identity import read_sealed_manifest

ProjectExtra = Literal["runs", "sessions", "mesh", "fetched"]
"""What ``hmp publish --package --with`` adds to the files of the author and their data."""

PACKAGE_RUNS_DIRNAME: Final[str] = "runs"
PACKAGE_SESSIONS_DIRNAME: Final[str] = "sessions"
PACKAGE_MESH_DIRNAME: Final[str] = "mesh_cache"
"""Folders of a project package beside ``INSTALL.toml`` and ``inputs/``."""

AUTHORED_EXTRAS: Final[tuple[str, ...]] = ("sites.csv", "site_overrides")
"""Files and folders of the project root the author wrote beside the TOML files."""

_USER_PROVIDERS: Final[frozenset[str]] = frozenset({"custom", "constant", "synthetic"})
_MESH_DESCRIPTION: Final[str] = "mesh.json"
_LOC_SUFFIX: Final[str] = "_LOC.csv"


def export_project(
    project_root: str | Path,
    to: str | Path,
    *,
    root_config: RootConfig,
    format: PublicationFormat = "tar",
    with_: Sequence[ProjectExtra] = (),
    bundle_of: InputsOf | None = None,
    dry_run: bool = False,
) -> Path:
    """Write the package of a whole project to *to* and return it.

    *bundle_of* builds the install index of one run
    (:func:`hydromodpy.project.exchange.share.run_bundle`); it is required with
    ``runs`` or ``fetched``. With *dry_run* the checks run, the path the package would
    take is returned and nothing is written.

    Raises
    ------
    ExportError
        A destination that holds something, a data file that cannot be
        resolved, two files under one destination, a package that would name
        the machine.
    """
    root = Path(project_root).resolve()
    extras = tuple(dict.fromkeys(with_))
    if {"runs", "fetched"} & set(extras) and bundle_of is None:
        raise ExportError("with runs or fetched needs the install index of each run (bundle_of).")
    target = _target_path(Path(to).expanduser().resolve(), format, root.name)
    runs = sorted(path for path in runs_dir_for(root).glob("*") if is_sealed(path))
    bundle = _project_bundle(root, runs, extras, bundle_of, root_config=root_config)
    if dry_run:
        return target
    staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True)
    lines: list[tuple[Path, PublishedLine]] = []
    try:
        _copy_bundle(bundle, staging)
        prefixes = _private_prefixes(root)
        if "runs" in extras:
            for run in runs:
                line = _publish_one(
                    run,
                    staging / PACKAGE_RUNS_DIRNAME / run.name,
                    root=root,
                    manifest=read_sealed_manifest(run),
                    format="dir",
                    extras=("results",),
                    recorded_as=target,
                )
                lines.append((run, line))
        if "sessions" in extras:
            for session in sorted(p for p in sessions_dir_for(root).glob("*") if p.is_dir()):
                _copy_tree(
                    session,
                    staging / PACKAGE_SESSIONS_DIRNAME / session.name,
                    prefixes=prefixes,
                    project_root=root,
                )
        if "mesh" in extras:
            for entry in consumed_mesh_entries(root, runs):
                shutil.copytree(entry, staging / PACKAGE_MESH_DIRNAME / entry.name)
        _refuse_leaks(staging, prefixes)
        write_publication(
            staging,
            Publication(
                kind="project",
                source=PublicationSource(project=root.name, rel_dir=PROJECT_REL_DIR),
                files=_digests(staging),
                hydromodpy_version=HYDROMODPY_VERSION,
                published_at=datetime.now(UTC),
                format=format,
                with_=["inputs", *(["results"] if "runs" in extras else [])],
            ),
        )
        _move_into_place(staging, target, format=format, top=root.name)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    for run, line in lines:
        append_published(run, line)
    return target


def _project_bundle(
    root: Path,
    runs: Sequence[Path],
    extras: tuple[ProjectExtra, ...],
    bundle_of: InputsOf | None,
    *,
    root_config: RootConfig,
) -> PayloadBundle:
    """Return the install index of the project: authored files, their data, the runs' inputs."""
    from hydromodpy.schema.sources import input_licence, sidecar_source

    workspace = locate_workspace_root(root) or root
    files: dict[tuple[str, str], PayloadFile] = {}
    blobs: dict[str, Path] = {}
    stations: dict[tuple[str, str], PayloadStation] = {}
    sites: dict[str, SiteRow] = {}

    def add(item: PayloadFile, located: Path) -> None:
        held = files.get((item.root, item.dest))
        if held is not None and held.sha256 != item.sha256:
            raise ExportError(
                f"{item.dest}: two files under one destination (sha256 {held.sha256} and "
                f"{item.sha256}); a package installs one. Rerun the stale run, or trash it."
            )
        files.setdefault((item.root, item.dest), item)
        blobs[stored_name(item.sha256, item.dest)] = located
        if item.sidecar_sha256 is not None:
            blobs[sidecar_name(item.sidecar_sha256)] = located.with_name(f"{located.name}.json")

    for path in _authored(root):
        add(_entry(path, workspace, root, provider=None, license=None), path)
    try:
        data, rows = project_data(root, workspace / "data", root=root_config)
    except Exception as exc:  # noqa: BLE001 - a reference that does not resolve refuses the export
        raise ExportError(f"{root.name}: {exc}") from exc
    for path in data:
        add(
            _entry(
                path,
                workspace,
                root,
                provider=sidecar_source(path) or "custom",
                license=input_licence(path).spdx,
            ),
            path,
        )
    for row in rows:
        stations[(row.dest, row.id)] = row
    if bundle_of is not None and {"runs", "fetched"} & set(extras):
        for run in runs:
            bundle = bundle_of(run)
            kept = [
                item
                for item in bundle.index.files
                if ("runs" in extras and item.provider in _USER_PROVIDERS)
                or ("fetched" in extras and item.provider not in _USER_PROVIDERS)
            ]
            for item in kept:
                located = bundle.blobs[stored_name(item.sha256, item.dest)]
                add(item, located)
                if item.sidecar_sha256 is not None:
                    blobs[sidecar_name(item.sidecar_sha256)] = bundle.blobs[
                        sidecar_name(item.sidecar_sha256)
                    ]
            served = {_registry_key(item.dest, item.provider) for item in kept}
            for station in bundle.index.stations:
                if _registry_of(station.dest) in served:
                    stations[(station.dest, station.id)] = station
            for site in bundle.index.sites:
                sites.setdefault(site.site, site)
    return PayloadBundle(
        index=InstallIndex(
            files=tuple(files[key] for key in sorted(files)),
            stations=tuple(stations[key] for key in sorted(stations)),
            sites=tuple(sites[key] for key in sorted(sites)),
        ),
        blobs=blobs,
    )


def _authored(root: Path) -> list[Path]:
    """Return the files the author of the project wrote: root files, sites, overrides."""
    found = list(authored_files(root))
    for name in AUTHORED_EXTRAS:
        path = root / name
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(item for item in path.rglob("*") if item.is_file()))
    return found


def _entry(
    path: Path, workspace: Path, root: Path, *, provider: str | None, license: str | None
) -> PayloadFile:
    try:
        return payload_file_of(
            path,
            workspace=workspace,
            project=root,
            sha256=sha256_of(path),
            provider=provider,
            license=license,
        )
    except ValueError as exc:
        raise ExportError(f"{root.name}: {exc}") from exc


def _registry_key(dest: str, provider: str | None) -> tuple[str, str]:
    """Return the folder and provider of a station file, the key of its registry."""
    folder, _, _ = dest.rpartition("/")
    return folder, str(provider)


def _registry_of(dest: str) -> tuple[str, str]:
    """Return the folder and provider a registry ``<prefix>_<provider>_LOC.csv`` serves."""
    folder, _, name = dest.rpartition("/")
    return folder, name.removesuffix(_LOC_SUFFIX).rsplit("_", 1)[-1]


def consumed_mesh_entries(project_root: Path, runs: Sequence[Path]) -> list[Path]:
    """Return the entries of ``.hmp/mesh_cache/`` the meshes of *runs* were read from.

    An entry describes the request and the engine build it meshes
    (``mesh.json``); a run records the same in the attributes of its mesh
    group (``fields.zarr/mesh``).
    """
    wanted = {identity for run in runs if (identity := _run_mesh_identity(run)) is not None}
    cache = Path(project_root) / INTERNAL_DIRNAME / "mesh_cache"
    if not wanted or not cache.is_dir():
        return []
    entries: list[Path] = []
    for entry in sorted(path for path in cache.iterdir() if path.is_dir()):
        description = entry / _MESH_DESCRIPTION
        if not description.is_file():
            continue
        identity = json.loads(description.read_text(encoding="utf-8")).get("identity") or {}
        key = (
            str(identity.get("engine_id")),
            str(identity.get("engine_version")),
            str(identity.get("request_hash")),
        )
        if key in wanted:
            entries.append(entry)
    return entries


def _run_mesh_identity(run: Path) -> tuple[str, str, str] | None:
    """Return the engine, its version and the request hash the mesh of a run records."""
    import zarr

    store = run / "fields.zarr"
    if not store.is_dir():
        return None
    try:
        root = zarr.open_group(str(store), mode="r", use_consolidated=False)
    except (FileNotFoundError, KeyError, ValueError, zarr.errors.GroupNotFoundError):
        return None
    mesh = root.get("mesh")
    if mesh is None or mesh.attrs.get("mesh_request_hash") is None:
        return None
    return (
        str(mesh.attrs.get("engine")),
        str(mesh.attrs.get("engine_version")),
        str(mesh.attrs.get("mesh_request_hash")),
    )


__all__ = [
    "AUTHORED_EXTRAS",
    "PACKAGE_MESH_DIRNAME",
    "PACKAGE_RUNS_DIRNAME",
    "PACKAGE_SESSIONS_DIRNAME",
    "ProjectExtra",
    "consumed_mesh_entries",
    "export_project",
]
