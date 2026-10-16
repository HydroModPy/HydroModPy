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
Always: ``README.md``, ``config.toml``, ``provenance.json`` (redacted),
``inputs.json``, ``manifest.json``, ``figures/``, ``exports/``, ``report/``,
a generated ``ro-crate-metadata.json`` and ``PUBLICATION.json``
(:mod:`hydromodpy.results.publication`). ``with_ = ("results",)`` adds
``fields.zarr/``, ``tables.parquet/`` and ``mesh/``; ``with_ = ("inputs",)``
adds the bytes of every loaded input and every file the configuration
declared under ``inputs/<sha256><suffix>``,
addressed by content. Never: ``.hmp/``, ``logs/``, ``attempts/``,
``outcome.json``, ``published.jsonl``.

Every JSON and TOML document of the copy goes through
:func:`hydromodpy.results.publication.redact`: no host, no user, no absolute
path. Text pages (``.md``, ``.html``, ``.txt``) have the absolute path of the
project, of the workspace and of the home directory replaced. A copy that
still names one of them is refused before it is moved into place.

The source gets one line in its ``published.jsonl``.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import socket
import tarfile
import tomllib
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import tomlkit

from hydromodpy.core.exceptions import ConfigMissingError, ExportError
from hydromodpy.core.state.paths import (
    INTERNAL_DIRNAME,
    SUMMARY_DIRNAME,
    is_workspace_root,
    run_dir_rel,
)
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.export.context import AssetEntry
from hydromodpy.results.export.directory import context_from_directory, publication_of
from hydromodpy.results.export.rocrate import write_ro_crate_view
from hydromodpy.results.export.run_identity import label_of, read_sealed_manifest
from hydromodpy.results.ledger import sha256_of
from hydromodpy.results.publication import (
    REDACTED_PATH,
    Publication,
    PublicationExtra,
    PublicationFormat,
    PublicationSource,
    PublishedLine,
    append_published,
    read_publication,
    redact,
    write_publication,
)
from hydromodpy.results.record import InputsDocument
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PUBLICATION_FILENAME,
    README_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_EXPORTS_DIRNAME,
    RUN_FIGURES_DIRNAME,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_MESH_DIRNAME,
    RUN_PROVENANCE_FILENAME,
    RUN_REPORT_DIRNAME,
    TABLES_DIRNAME,
)
from hydromodpy.schema.generated_views import RO_CRATE_VIEW_FILENAME
from hydromodpy.schema.media_types import JSON_MEDIA_TYPE, OCTET_STREAM_MEDIA_TYPE

INPUTS_DIRNAME: Final[str] = "inputs"
"""Directory of a copy holding the input bytes, each named by its sha256."""

RUN_COPY_ENTRIES: Final[tuple[str, ...]] = (
    README_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_PROVENANCE_FILENAME,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_EXPORTS_DIRNAME,
    RUN_REPORT_DIRNAME,
)
"""What every copy of a run holds, when the run has it."""

RESULTS_ENTRIES: Final[tuple[str, ...]] = (FIELDS_STORE_NAME, TABLES_DIRNAME, RUN_MESH_DIRNAME)
"""What ``with results`` adds to the copy of a run."""

_STRUCTURED_SUFFIXES: Final[frozenset[str]] = frozenset({".json", ".jsonld", ".toml"})
_TEXT_SUFFIXES: Final[frozenset[str]] = frozenset({".md", ".html", ".htm", ".txt"})


def publish(
    source: str | Path,
    to: str | Path,
    *,
    project_root: str | Path,
    format: PublicationFormat = "dir",
    with_: Sequence[PublicationExtra] = (),
    public: bool = False,
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
        ``"inputs"`` adds the bytes of every loaded input.
    public
        Refuse to publish without a ``[publication] license``.

    Raises
    ------
    ExportError
        An unsealed run, a destination that holds something, a copy that
        would name the machine.
    ConfigMissingError
        ``public`` without a licence.
    """
    source_dir = Path(source).resolve()
    root = Path(project_root).resolve()
    extras = tuple(dict.fromkeys(with_))
    is_summary = source_dir == (root / SUMMARY_DIRNAME)
    manifest = None if is_summary else read_sealed_manifest(source_dir)
    if not is_summary and manifest is None:
        raise ExportError(
            f"{source_dir} carries no {RUN_MANIFEST_FILENAME}: only a completed, sealed run is "
            "published. Its outcome.json and logs/ say why it did not finish."
        )
    if public:
        _require_licence(source_dir if not is_summary else root, is_summary=is_summary)
    target = _target_path(Path(to).expanduser().resolve(), format, source_dir.name)
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
            if "inputs" in extras:
                _copy_inputs(source_dir, staging, project_root=root)
            _write_crate(staging)
        _refuse_leaks(staging, prefixes)
        publication = Publication(
            source=PublicationSource(
                project=root.name,
                rel_dir=SUMMARY_DIRNAME if is_summary else run_dir_rel(source_dir.name),
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
    append_published(
        source_dir,
        PublishedLine(
            to=str(target),
            format=format,
            published_at=publication.published_at,
            publication_sha256=publication_sha256,
        ),
    )
    return target


def verify(copy: str | Path) -> list[str]:
    """Compare a published copy with its ``PUBLICATION.json``; return every difference.

    An empty list means every file listed is present with its digest and no
    file is present that the publication does not list. A tar is read in
    place.
    """
    target = Path(copy).expanduser().resolve()
    if target.is_file() and tarfile.is_tarfile(target):
        found, recorded = _tar_digests(target)
    else:
        recorded = read_publication(target).files
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
    from hydromodpy.config.publication_config import PublicationConfig
    from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME

    marker = project_root / PROJECT_MARKER_FILENAME
    if not marker.is_file():
        return PublicationConfig()
    with marker.open("rb") as handle:
        return PublicationConfig.model_validate(tomllib.load(handle).get("publication") or {})


def _target_path(to: Path, format: PublicationFormat, name: str) -> Path:
    """Return where the copy lands, refusing a destination that already holds something."""
    if format == "tar":
        target = to if to.suffix else to.with_name(f"{to.name}.tar")
        if target.exists():
            raise ExportError(f"{target} exists: name another archive, or delete it first.")
        return target
    if to.exists() and (not to.is_dir() or any(to.iterdir())):
        raise ExportError(
            f"{to} exists and is not an empty directory: publish {name} to a new directory."
        )
    if to.is_dir():
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
        if INTERNAL_DIRNAME in relative.parts or not path.is_file():
            continue
        _copy_file(path, dest / relative, prefixes=prefixes, project_root=project_root)


def _copy_file(source: Path, dest: Path, *, prefixes: tuple[str, ...], project_root: Path) -> None:
    """Copy one file; a JSON or TOML document is redacted, a text page has its paths replaced."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    if suffix in _STRUCTURED_SUFFIXES:
        dest.write_text(_redacted_document(source, project_root), encoding="utf-8")
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


def _redacted_text(text: str, prefixes: tuple[str, ...]) -> str:
    """Return a text page with every private absolute path replaced."""
    for prefix in prefixes:
        text = text.replace(prefix, REDACTED_PATH)
    return text


def _copy_inputs(source: Path, staging: Path, *, project_root: Path) -> None:
    """Copy every loaded input and every file the configuration declared under ``inputs/``.

    Each file is named by its sha256, so a file both loaded and declared is
    one copy. A published copy replays from these bytes (``hmp run
    <copy>/config.toml --frozen``).
    """
    document = InputsDocument.model_validate(
        json.loads((source / RUN_INPUTS_FILENAME).read_text(encoding="utf-8"))
    )
    roots = (source, project_root, *(p for p in project_root.parents if is_workspace_root(p)))
    for entry in document.inputs:
        if entry.sha256 is None:
            raise ExportError(
                f"input {entry.variable} ({entry.path}) has no sha256 in {RUN_INPUTS_FILENAME}: "
                "its bytes cannot be addressed by content."
            )
        located = _locate(entry.path, roots)
        if located is None:
            raise ExportError(
                f"input {entry.variable}: {entry.path} is not on disk any more, so it cannot be "
                "copied. Publish without --with inputs, or fetch it again."
            )
        if sha256_of(located) != entry.sha256:
            raise ExportError(
                f"input {entry.variable}: {located.name} no longer has the digest the run sealed."
            )
        dest = staging / INPUTS_DIRNAME / f"{entry.sha256}{located.suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(located, dest)
    seal = read_sealed_manifest(source)
    for tracked in seal.inputs if seal is not None else ():
        located = _locate(tracked.path, roots)
        if located is None:
            raise ExportError(
                f"input {tracked.role}: {tracked.path} is not on disk any more, so it cannot be "
                "copied. Publish without --with inputs."
            )
        if sha256_of(located) != tracked.sha256:
            raise ExportError(
                f"input {tracked.role}: {located.name} no longer has the digest the run sealed."
            )
        dest = staging / INPUTS_DIRNAME / f"{tracked.sha256}{located.suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(located, dest)


def _locate(path: str, roots: Sequence[Path]) -> Path | None:
    """Return the file an inputs entry names, relative to the run, the project or the workspace."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    return next((root / candidate for root in roots if (root / candidate).is_file()), None)


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
    """Refuse a copy whose text still names the machine: a private path or the host name."""
    host = socket.gethostname()
    for path in _files(staging):
        if path.suffix.lower() not in _STRUCTURED_SUFFIXES | _TEXT_SUFFIXES | {".csv"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        named = [prefix for prefix in prefixes if prefix in text]
        if len(host) >= 4 and f'"{host}"' in text:
            named.append(f"host {host}")
        if named:
            raise ExportError(
                f"{path.relative_to(staging).as_posix()} names {', '.join(named)}: "
                "a published copy never names the machine. Nothing was published."
            )


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
                recorded = Publication.model_validate(json.loads(data)).files
                continue
            found[name] = hashlib.sha256(data).hexdigest()
    return found, recorded


__all__ = [
    "INPUTS_DIRNAME",
    "RESULTS_ENTRIES",
    "RUN_COPY_ENTRIES",
    "publish",
    "verify",
]
