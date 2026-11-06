"""Publish a run or a summary out of the project: one function, a directory or a tar.

Why
---
A run is read where it was computed; it leaves the project as a copy. The
copy must stand alone: a reader with pandas, pyarrow and zarr learns from it
which basin, which period, which version and which label, and never sees the
machine it was computed on. The source must remember where the copy went, so
a delete warns. The portable archive of a run is the same copy in a tar:
there is no second packer.

What a copy holds
-----------------
Always: ``README.md``, ``config.toml``, ``config.resolved.toml``, ``provenance.json`` (redacted),
``inputs.json``, ``manifest.json``, ``figures/``, ``exports/``, ``report/``,
a generated ``ro-crate-metadata.json`` and ``PUBLICATION.json``
(:mod:`hydromodpy.results.publication`). ``with_ = ("results",)`` adds
``fields.zarr/`` and ``tables.parquet/``; ``with_ = ("inputs",)``
adds the install index ``INSTALL.toml`` and the bytes of every file it lists
under ``inputs/<sha256><suffix>``, with their sidecars under
``inputs/<sha256>.json``, addressed by content
(:mod:`hydromodpy.core.payload`). The caller builds that index, from the
workspace the run read
(:func:`hydromodpy.project.exchange.share.run_bundle`): this module never reads the
data layer. Never: ``.hmp/``, ``logs/``, ``attempts/``, ``outcome.json``,
``published.jsonl``.

A public copy (``public = True``) needs a ``[publication] license``, and,
with its inputs, a licence that allows redistribution for each of them: an
input without one is refused by name.

Every JSON, JSON Lines and TOML document and every cell of a CSV or TSV
table goes through :func:`hydromodpy.results.publication.redact`: no host,
no user, no absolute path. Text pages (``.md``, ``.html``, ``.txt``) have the
absolute path of the project, of the workspace and of the home directory
replaced. A Parquet file is copied as it is, so a text column holding an
absolute path refuses the copy, by file and column. A copy whose text still
names the machine is refused before it is moved into place.

The source gets one line in its ``published.jsonl``, and that journal never
enters a copy. ``publish_project`` stages every sealed run and the summary
side by side and renames the whole at once: a refused member leaves nothing
in the destination and no line in any journal. The project copy carries its
own ``PUBLICATION.json`` (kind ``project``) that lists each member by name
and by the digest of the member's ``PUBLICATION.json``, so :func:`verify`
checks the whole copy and names a member that is missing or was added.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import os
import shutil
import socket
import tarfile
import tomllib
import uuid
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import tomlkit

from hydromodpy.core.config_kit.stored import read_stored
from hydromodpy.core.exceptions import ConfigMissingError, ExportError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.payload import PayloadBundle, sidecar_name, stored_name, write_index
from hydromodpy.core.payload.install import sha256_of as file_sha256
from hydromodpy.core.state.layout import (
    INTERNAL_DIRNAME,
    SUMMARY_DIRNAME,
    is_workspace_root,
    runs_dir_for,
)
from hydromodpy.core.state.result_dirs import run_dir_rel
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.export.context import AssetEntry
from hydromodpy.results.export.directory import context_from_directory, publication_of
from hydromodpy.results.export.rocrate import write_ro_crate_view
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.publication import (
    PROJECT_REL_DIR,
    PUBLICATION_VERSIONS,
    REDACTED_PATH,
    Publication,
    PublicationExtra,
    PublicationFormat,
    PublicationMember,
    PublicationSource,
    PublishedLine,
    append_published,
    read_publication,
    redact,
    write_publication,
)
from hydromodpy.results.run_identity import label_of, read_sealed_manifest
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PUBLICATION_FILENAME,
    README_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_EXPORTS_DIRNAME,
    RUN_FIGURES_DIRNAME,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_PROVENANCE_FILENAME,
    RUN_PUBLISHED_FILENAME,
    RUN_REPORT_DIRNAME,
    RUN_RESOLVED_CONFIG_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.json_io import check_sealed
from hydromodpy.schema.generated_views import RO_CRATE_VIEW_FILENAME
from hydromodpy.schema.media_types import JSON_MEDIA_TYPE, OCTET_STREAM_MEDIA_TYPE

INPUTS_DIRNAME: Final[str] = "inputs"
"""Directory of a copy holding the input bytes, each named by its sha256."""

InputsOf = Callable[[Path], PayloadBundle]
"""Return the install index of one run directory, with the files holding its bytes."""

RUN_COPY_ENTRIES: Final[tuple[str, ...]] = (
    README_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_RESOLVED_CONFIG_FILENAME,
    RUN_PROVENANCE_FILENAME,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_EXPORTS_DIRNAME,
    RUN_REPORT_DIRNAME,
)
"""What every copy of a run holds, when the run has it."""

RESULTS_ENTRIES: Final[tuple[str, ...]] = (FIELDS_STORE_NAME, TABLES_DIRNAME)
"""What ``with results`` adds to the copy of a run."""

_STRUCTURED_SUFFIXES: Final[frozenset[str]] = frozenset({".json", ".jsonld", ".toml"})
_LINES_SUFFIX: Final[str] = ".jsonl"
_TABLE_DELIMITERS: Final[dict[str, str]] = {".csv": ",", ".tsv": "\t"}
_TEXT_SUFFIXES: Final[frozenset[str]] = frozenset({".md", ".html", ".htm", ".txt"})
_SCANNED_SUFFIXES: Final[frozenset[str]] = (
    _STRUCTURED_SUFFIXES | _TEXT_SUFFIXES | set(_TABLE_DELIMITERS) | {_LINES_SUFFIX}
)
_PARQUET_SUFFIX: Final[str] = ".parquet"


def publish(
    source: str | Path,
    to: str | Path,
    *,
    project_root: str | Path,
    format: PublicationFormat = "dir",
    with_: Sequence[PublicationExtra] = (),
    public: bool = False,
    inputs: InputsOf | None = None,
    dry_run: bool = False,
) -> Path:
    """Copy a sealed run or the summary of a project out of the tree; return the copy.

    Parameters
    ----------
    source
        A sealed run directory (``runs/<run>``) or the ``summary/`` of the
        project.
    to
        Where the copy goes. With ``format = "dir"`` it is the directory of
        the copy, absent or empty. With ``format = "tar"`` it is the archive
        file; ``.tar`` is appended when it carries no suffix.
    project_root
        The project the source belongs to.
    format
        ``"dir"`` or ``"tar"``.
    with_
        ``"results"`` adds the field store, the tables and the mesh;
        ``"inputs"`` adds the install index and the bytes of every input.
    public
        Refuse to publish without a ``[publication] license``, and an input
        whose licence does not allow redistribution.
    inputs
        How to build the install index of the run; required with ``"inputs"``.
    dry_run
        Run every check, return where the copy would land and write nothing.

    Raises
    ------
    ExportError
        An unsealed run, a destination that holds something, a copy that
        would name the machine, an input that cannot be carried.
    ConfigMissingError
        ``public`` without a licence, or with an input that has none.
    """
    source_dir = Path(source).resolve()
    root = Path(project_root).resolve()
    manifest = _checked_source(source_dir, root, public=public)
    bundle = _bundle_of(source_dir, manifest, with_, inputs, public=public)
    target = _target_path(Path(to).expanduser().resolve(), format, source_dir.name, dry_run=dry_run)
    if dry_run:
        return target
    line = _publish_one(
        source_dir,
        target,
        root=root,
        manifest=manifest,
        format=format,
        extras=tuple(with_),
        bundle=bundle,
    )
    append_published(source_dir, line)
    return target


def publish_project(
    project_root: str | Path,
    to: str | Path,
    *,
    format: PublicationFormat = "dir",
    with_: Sequence[PublicationExtra] = (),
    public: bool = False,
    inputs: InputsOf | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """Copy every sealed run and the summary of a project, each in its own folder under *to*.

    The members are staged together beside *to* and renamed into place at
    once. A member that is refused leaves nothing in *to* and no line in any
    ``published.jsonl``. With ``format = "tar"`` each member is an archive
    ``<member>.tar`` under *to*. *to* gets its own ``PUBLICATION.json``, of
    kind ``project``, that lists every member. With *dry_run* every check runs, the
    copies it would write are returned, and nothing is written.

    Raises
    ------
    ExportError
        A project with nothing to publish, a destination that holds
        something, a member that would name the machine.
    ConfigMissingError
        ``public`` without a licence.
    """
    root = Path(project_root).resolve()
    sources = project_members(root)
    if not sources:
        raise ExportError(
            f"{root} holds no sealed run and no {SUMMARY_DIRNAME}/: nothing to publish."
        )
    checked = [(source, _checked_source(source, root, public=public)) for source in sources]
    bundles = {
        source: _bundle_of(source, manifest, with_, inputs, public=public)
        for source, manifest in checked
    }
    destination = _target_path(Path(to).expanduser().resolve(), "dir", root.name, dry_run=dry_run)
    if dry_run:
        return [
            destination / (f"{source.name}.tar" if format == "tar" else source.name)
            for source in sources
        ]
    staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True)
    extras = list(dict.fromkeys(with_))
    lines: list[tuple[Path, PublishedLine]] = []
    members: list[PublicationMember] = []
    try:
        for source, manifest in checked:
            name = f"{source.name}.tar" if format == "tar" else source.name
            line = _publish_one(
                source,
                staging / name,
                root=root,
                manifest=manifest,
                format=format,
                extras=tuple(extras),
                recorded_as=destination / name,
                bundle=bundles[source],
            )
            lines.append((source, line))
            members.append(
                PublicationMember(
                    name=name,
                    rel_dir=_source_rel_dir(source, manifest),
                    manifest_sha256=None
                    if manifest is None
                    else sha256_of(source / RUN_MANIFEST_FILENAME),
                    publication_sha256=line.publication_sha256,
                )
            )
        write_publication(
            staging,
            Publication(
                kind="project",
                source=PublicationSource(project=root.name, rel_dir=PROJECT_REL_DIR),
                hydromodpy_version=HYDROMODPY_VERSION,
                published_at=datetime.now(UTC),
                format=format,
                with_=extras,
                members=members,
            ),
        )
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    for source, line in lines:
        append_published(source, line)
    return [Path(line.to) for _, line in lines]


def project_members(project_root: str | Path) -> list[Path]:
    """Return what ``publish_project`` copies: every sealed run, then ``summary/``."""
    root = Path(project_root)
    runs = sorted(path for path in runs_dir_for(root).glob("*") if is_sealed(path))
    summary = root / SUMMARY_DIRNAME
    return [*runs, *([summary] if summary.is_dir() else [])]


def _checked_source(source_dir: Path, root: Path, *, public: bool) -> Any:
    """Return the seal of a run source, ``None`` for the summary; refuse what cannot leave."""
    is_summary = source_dir == (root / SUMMARY_DIRNAME)
    manifest = None if is_summary else read_sealed_manifest(source_dir)
    if not is_summary and manifest is None:
        raise ExportError(
            f"{source_dir} carries no {RUN_MANIFEST_FILENAME}: only a completed, sealed run is "
            "published. Its outcome.json and logs/ say why it did not finish."
        )
    if public:
        _require_licence(source_dir if not is_summary else root, is_summary=is_summary)
    return manifest


def _publish_one(
    source_dir: Path,
    target: Path,
    *,
    root: Path,
    manifest: Any,
    format: PublicationFormat,
    extras: tuple[PublicationExtra, ...],
    recorded_as: Path | None = None,
    bundle: PayloadBundle | None = None,
) -> PublishedLine:
    """Stage one copy beside *target*, check it, move it into place; return its journal line."""
    extras = tuple(dict.fromkeys(extras))
    is_summary = manifest is None
    staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True)
    try:
        prefixes = _private_prefixes(root)
        if is_summary:
            _copy_tree(source_dir, staging, prefixes=prefixes, project_root=root)
        else:
            for name in RUN_COPY_ENTRIES:
                _copy_entry(source_dir / name, staging / name, prefixes=prefixes, project_root=root)
            if "results" in extras:
                for name in RESULTS_ENTRIES:
                    _copy_entry(
                        source_dir / name, staging / name, prefixes=prefixes, project_root=root
                    )
            if bundle is not None:
                _copy_bundle(bundle, staging)
            _write_crate(staging)
        _refuse_leaks(staging, prefixes)
        publication = Publication(
            kind="summary" if is_summary else "run",
            source=PublicationSource(
                project=root.name,
                rel_dir=_source_rel_dir(source_dir, manifest),
                sim_id=None if manifest is None else manifest.run.sim_id,
            ),
            manifest_sha256=None if is_summary else sha256_of(source_dir / RUN_MANIFEST_FILENAME),
            files=_digests(staging),
            label=None if manifest is None else label_of(manifest).label,
            label_date=None if manifest is None else datetime.now(UTC).date(),
            hydromodpy_version=HYDROMODPY_VERSION,
            published_at=datetime.now(UTC),
            format=format,
            with_=list(extras),
        )
        written = write_publication(staging, publication)
        publication_sha256 = sha256_of(written)
        _move_into_place(staging, target, format=format, top=source_dir.name)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return PublishedLine(
        to=str(recorded_as or target),
        format=format,
        published_at=publication.published_at,
        publication_sha256=publication_sha256,
    )


def _source_rel_dir(source_dir: Path, manifest: Any) -> str:
    """Return ``source.rel_dir`` of a copy: ``summary`` or ``runs/<run>``."""
    return SUMMARY_DIRNAME if manifest is None else run_dir_rel(source_dir.name)


def verify(copy: str | Path) -> list[str]:
    """Compare a published copy with its ``PUBLICATION.json``; return every difference.

    An empty list means every file listed is present with its digest and no
    file is present that the publication does not list. A tar is read in
    place. A project copy written by :func:`publish_project` is verified
    member by member: each difference of a member is prefixed with
    ``<member>/``, a member gone or whose ``PUBLICATION.json`` changed is
    named, and so is an entry the project copy does not list. A project
    package (:mod:`hydromodpy.results.export.project_package`) lists its files
    like a run copy.
    """
    target = Path(copy).expanduser().resolve()
    if target.is_file() and tarfile.is_tarfile(target):
        found, recorded = _tar_digests(target)
    else:
        publication = read_publication(target)
        if publication.kind == "project" and publication.members:
            return _verify_project(target, publication)
        recorded = publication.files
        found = _digests(target)
    problems = [f"{name}: missing" for name in sorted(recorded) if name not in found] + [
        f"{name}: digest differs"
        for name in sorted(recorded)
        if name in found and found[name] != recorded[name]
    ]
    problems += [
        f"{name}: not listed in {PUBLICATION_FILENAME}"
        for name in sorted(found)
        if name not in recorded
    ]
    return problems


def _verify_project(target: Path, publication: Publication) -> list[str]:
    """Verify every member of a project copy against the list its ``PUBLICATION.json`` holds."""
    problems: list[str] = []
    listed = {member.name for member in publication.members}
    for member in publication.members:
        entry = target / member.name
        if not entry.exists():
            problems.append(f"{member.name}: missing")
            continue
        if not entry.is_dir() and not tarfile.is_tarfile(entry):
            problems.append(f"{member.name}: not a published copy")
            continue
        if _member_publication_sha256(entry) != member.publication_sha256:
            problems.append(f"{member.name}: {PUBLICATION_FILENAME} digest differs")
        problems += [f"{member.name}/{problem}" for problem in verify(entry)]
    problems += [
        f"{entry.name}: not listed in {PUBLICATION_FILENAME}"
        for entry in sorted(target.iterdir())
        if entry.name not in listed and entry.name != PUBLICATION_FILENAME
    ]
    return problems


def _member_publication_sha256(entry: Path) -> str | None:
    """Return the digest of the ``PUBLICATION.json`` of a member folder or tar."""
    import hashlib

    if entry.is_dir():
        path = entry / PUBLICATION_FILENAME
        return sha256_of(path) if path.is_file() else None
    with tarfile.open(entry, "r") as archive:
        for item in archive.getmembers():
            if item.isfile() and item.name.partition("/")[2] == PUBLICATION_FILENAME:
                handle = archive.extractfile(item)
                return None if handle is None else hashlib.sha256(handle.read()).hexdigest()
    return None


def _require_licence(source: Path, *, is_summary: bool) -> None:
    """Refuse a public copy whose project declares no licence."""
    licence = _project_publication(source).license if is_summary else publication_of(source).license
    if not licence:
        raise ConfigMissingError(
            "hmp publish --public needs a licence: declare it in project.toml, e.g. "
            '[publication] license = "CC-BY-4.0", then run again.'
        )


def _project_publication(project_root: Path) -> Any:
    """Return the ``[publication]`` table of ``project.toml``."""
    from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
    from hydromodpy.results.publication import PublicationConfig

    marker = project_root / PROJECT_MARKER_FILENAME
    if not marker.is_file():
        return PublicationConfig()
    with marker.open("rb") as handle:
        return PublicationConfig.model_validate(tomllib.load(handle).get("publication") or {})


def _target_path(to: Path, format: PublicationFormat, name: str, *, dry_run: bool = False) -> Path:
    """Return where the copy lands, refusing a destination that already holds something."""
    if format == "tar":
        target = to if to.suffix == ".tar" else to.with_name(f"{to.name}.tar")
        if target.exists():
            raise ExportError(f"{target} exists: name another archive, or delete it first.")
        return target
    if to.exists() and (not to.is_dir() or any(to.iterdir())):
        raise ExportError(
            f"{to} exists and is not an empty directory: publish {name} to a new directory."
        )
    if to.is_dir() and not dry_run:
        to.rmdir()
    return to


def _private_prefixes(project_root: Path) -> tuple[str, ...]:
    """Return the absolute paths no copy may name, longest first."""
    workspace = next(
        (parent for parent in (project_root, *project_root.parents) if is_workspace_root(parent)),
        project_root,
    )
    prefixes = {str(project_root), str(workspace), str(Path.home())}
    return tuple(sorted(prefixes, key=len, reverse=True))


def _copy_entry(source: Path, dest: Path, *, prefixes: tuple[str, ...], project_root: Path) -> None:
    """Copy one file or directory of the source, redacting its documents."""
    if source.is_dir():
        _copy_tree(source, dest, prefixes=prefixes, project_root=project_root)
    elif source.is_file():
        _copy_file(source, dest, prefixes=prefixes, project_root=project_root)


def _copy_tree(source: Path, dest: Path, *, prefixes: tuple[str, ...], project_root: Path) -> None:
    """Copy a directory, skipping the internal state, redacting its documents."""
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if (
            INTERNAL_DIRNAME in relative.parts
            or relative.name == RUN_PUBLISHED_FILENAME
            or not path.is_file()
        ):
            continue
        _copy_file(path, dest / relative, prefixes=prefixes, project_root=project_root)


def _copy_file(source: Path, dest: Path, *, prefixes: tuple[str, ...], project_root: Path) -> None:
    """Copy one file; documents and tables are redacted, a text page has its paths replaced."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    if suffix in _STRUCTURED_SUFFIXES:
        dest.write_text(_redacted_document(source, project_root), encoding="utf-8")
    elif suffix == _LINES_SUFFIX:
        dest.write_text(_redacted_lines(source, project_root), encoding="utf-8")
    elif suffix in _TABLE_DELIMITERS:
        _copy_table(source, dest, delimiter=_TABLE_DELIMITERS[suffix], project_root=project_root)
    elif suffix in _TEXT_SUFFIXES:
        dest.write_text(
            _redacted_text(source.read_text(encoding="utf-8"), prefixes), encoding="utf-8"
        )
    else:
        shutil.copy2(source, dest)


def _redacted_document(path: Path, project_root: Path) -> str:
    """Return a JSON or TOML document without host, user or absolute path."""
    if path.suffix.lower() == ".toml":
        with path.open("rb") as handle:
            return tomlkit.dumps(redact(tomllib.load(handle), project_root=project_root))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        cleaned: Any = redact(payload, project_root=project_root)
    else:
        cleaned = redact({"items": payload}, project_root=project_root)["items"]
    return json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n"


def _redacted_lines(path: Path, project_root: Path) -> str:
    """Return a JSON Lines document with every line redacted."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return "".join(
        json.dumps(redact({"line": json.loads(line)}, project_root=project_root)["line"]) + "\n"
        for line in lines
    )


def _copy_table(source: Path, dest: Path, *, delimiter: str, project_root: Path) -> None:
    """Copy a CSV or TSV table, every cell redacted; a table without a path is copied as is.

    An absolute path under the project becomes relative to it, any other one
    becomes :data:`REDACTED_PATH`.
    """
    text = source.read_text(encoding="utf-8", errors="surrogateescape")
    if redact({"text": text}, project_root=None)["text"] == text:
        shutil.copy2(source, dest)
        return
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    cleaned = redact({"rows": rows}, project_root=project_root)["rows"]
    with dest.open("w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        csv.writer(handle, delimiter=delimiter, lineterminator="\n").writerows(cleaned)


def _redacted_text(text: str, prefixes: tuple[str, ...]) -> str:
    """Return a text page with every private absolute path replaced."""
    for prefix in prefixes:
        text = text.replace(prefix, REDACTED_PATH)
    return text


class MissingInputError(ExportError):
    """An input of a run is not on disk any more, so a copy cannot carry its bytes.

    ``detail`` says which input and why; the message adds what to do.
    """

    def __init__(self, detail: str, *, derived: bool = False) -> None:
        self.detail = detail
        advice = "Publish without --with inputs" + ("." if derived else ", or fetch it again.")
        super().__init__(f"{detail} {advice}")


def _bundle_of(
    source: Path,
    manifest: Any,
    with_: Sequence[PublicationExtra],
    inputs: InputsOf | None,
    *,
    public: bool,
) -> PayloadBundle | None:
    """Return the install index a copy of *source* carries, or None without ``inputs``."""
    if "inputs" not in with_ or manifest is None:
        return None
    if inputs is None:
        raise ExportError(
            "with inputs needs the install index of the run: pass inputs=run_bundle "
            "(hydromodpy.project.exchange.share), as hmp publish does."
        )
    bundle = inputs(source)
    if public:
        _require_redistributable(bundle)
    return bundle


def _require_redistributable(bundle: PayloadBundle) -> None:
    """Refuse a public copy that would carry an input whose licence does not allow it."""
    from hydromodpy.schema.sources import is_determined

    refused = [item for item in bundle.index.files if not is_determined(item.license)]
    if refused:
        names = "\n".join(
            f"  {item.dest} ({item.provider or 'custom'}): {item.license or 'no licence'}"
            for item in refused
        )
        raise ConfigMissingError(
            f"hmp publish --public carries {len(refused)} input(s) whose licence does not "
            f"allow redistribution:\n{names}\nDeclare the licence of a file you supplied in "
            "its sidecar (<file>.json, key 'license'), or publish without --with inputs."
        )


def _copy_bundle(bundle: PayloadBundle, staging: Path) -> None:
    """Write ``INSTALL.toml`` and copy every file it lists under ``inputs/``, by content.

    The bytes are copied as they are, never redacted, and checked against the
    digest the index states.
    """
    folder = staging / INPUTS_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    expected: dict[str, str] = {}
    for item in bundle.index.files:
        expected[stored_name(item.sha256, item.dest)] = item.sha256
        if item.sidecar_sha256 is not None:
            expected[sidecar_name(item.sidecar_sha256)] = item.sidecar_sha256
    for name, sha256 in sorted(expected.items()):
        located = bundle.blobs.get(name)
        if located is None or not located.is_file():
            raise MissingInputError(f"{name}: the bytes of this input are not on disk any more.")
        dest = folder / name
        shutil.copyfile(located, dest)
        if file_sha256(dest) != sha256:
            raise ExportError(f"{located.name} changed while it was copied: publish again.")
    write_index(staging, bundle.index)


def _write_crate(staging: Path) -> None:
    """Write the RO-Crate of a run copy, listing every file the copy holds."""
    context = context_from_directory(staging)
    listed = {asset.relative_path for asset in context.assets}
    extra = [
        AssetEntry(
            key=name,
            relative_path=name,
            media_type=JSON_MEDIA_TYPE if name.endswith(".json") else OCTET_STREAM_MEDIA_TYPE,
            roles=("data", "derived"),
            sha256=digest,
            size_bytes=(staging / name).stat().st_size,
        )
        for name, digest in _digests(staging).items()
        if name not in listed and name != RO_CRATE_VIEW_FILENAME
    ]
    write_ro_crate_view(
        staging, context=dataclasses.replace(context, assets=(*context.assets, *extra))
    )


def _refuse_leaks(staging: Path, prefixes: tuple[str, ...]) -> None:
    """Refuse a copy that still names the machine: a private path, the host, a Parquet path."""
    host = socket.gethostname()
    for path in _files(staging):
        suffix = path.suffix.lower()
        relative = path.relative_to(staging).as_posix()
        if suffix == _PARQUET_SUFFIX:
            _refuse_parquet_leaks(path, relative, prefixes)
            continue
        if suffix not in _SCANNED_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        named = [prefix for prefix in prefixes if prefix in text]
        if len(host) >= 4 and f'"{host}"' in text:
            named.append(f"host {host}")
        if named:
            raise ExportError(
                f"{relative} names {', '.join(named)}: "
                "a published copy never names the machine. Nothing was published."
            )


def _refuse_parquet_leaks(path: Path, relative: str, prefixes: tuple[str, ...]) -> None:
    """Refuse a Parquet file whose metadata names a private path or whose text holds a path.

    A Parquet file is copied byte for byte, so it is never redacted: the
    writer of the table writes its paths relative to the project.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    schema = pq.read_schema(path)
    for key, value in (schema.metadata or {}).items():
        named = [prefix for prefix in prefixes if prefix in value.decode("utf-8", "replace")]
        if named:
            raise ExportError(
                f"{relative}: the metadata {key.decode('utf-8', 'replace')!r} names "
                f"{', '.join(named)}: a published copy never names the machine. "
                "Nothing was published."
            )
    columns = [field.name for field in schema if _holds_text(field.type)]
    if not columns:
        return
    table = pq.read_table(path, columns=columns)
    for name in columns:
        values = pc.unique(table.column(name).cast(pa.string())).to_pylist()
        leaked = next(
            (
                value
                for value in values
                if value and redact({"value": value}, project_root=None)["value"] != value
            ),
            None,
        )
        if leaked is not None:
            raise ExportError(
                f"{relative}: the column {name!r} holds an absolute path ({leaked[:80]!r}): "
                "a published copy never names the machine, and a Parquet file is not "
                "rewritten. Write the table with paths relative to the project. "
                "Nothing was published."
            )


def _holds_text(kind: Any) -> bool:
    """Return True for a string column, plain or dictionary encoded."""
    import pyarrow as pa

    if pa.types.is_dictionary(kind):
        kind = kind.value_type
    return bool(pa.types.is_string(kind) or pa.types.is_large_string(kind))


def _files(root: Path) -> Iterator[Path]:
    return (path for path in sorted(root.rglob("*")) if path.is_file())


def _digests(root: Path) -> dict[str, str]:
    """Return the sha256 of every file of a copy, by path relative to it."""
    return {
        path.relative_to(root).as_posix(): sha256_of(path)
        for path in _files(root)
        if path.name != PUBLICATION_FILENAME or path.parent != root
    }


def _move_into_place(staging: Path, target: Path, *, format: PublicationFormat, top: str) -> None:
    """Rename the staged copy to its destination, or pack it in a tar."""
    if format == "dir":
        os.replace(staging, target)
        return
    partial = target.with_name(f".{target.name}.partial")
    with tarfile.open(partial, "w") as archive:
        for path in _files(staging):
            archive.add(path, arcname=f"{top}/{path.relative_to(staging).as_posix()}")
    os.replace(partial, target)


def _tar_digests(archive_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return the digests found in a tar and the ones its ``PUBLICATION.json`` lists."""
    import hashlib

    found: dict[str, str] = {}
    recorded: dict[str, str] = {}
    with tarfile.open(archive_path, "r") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            data = handle.read()
            _, _, name = member.name.partition("/")
            if name == PUBLICATION_FILENAME:
                payload = check_sealed(
                    json.loads(data), PUBLICATION_VERSIONS, path=archive_path / member.name
                )
                recorded = read_stored(Publication, payload).files
                continue
            found[name] = hashlib.sha256(data).hexdigest()
    return found, recorded


__all__ = [
    "INPUTS_DIRNAME",
    "RESULTS_ENTRIES",
    "InputsOf",
    "MissingInputError",
    "RUN_COPY_ENTRIES",
    "project_members",
    "publish",
    "publish_project",
    "verify",
]
