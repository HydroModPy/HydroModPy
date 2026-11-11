"""The one seal of a run and of a job: what a finished directory promises.

A run directory and a job directory are two profiles of one document. Both
seal ``manifest.json`` last, atomically, and its presence is what *finished*
means for the thing it covers. The block that says who produced it, when, what
it derived from and which entries it inventories is written once, here. The
run adds its site, its period, its checks and its score in
:mod:`hydromodpy.results.record.manifest`; the job adds the request it
answered, the process that answered it and the input set it read.

Format
------
``manifest_version`` is the integer 4 for both profiles, and ``profile`` says
which one the document is. A job seal of the 2.0.0 wrote ``schema =
"hmp-manifest/v2"`` instead; ``read_job_seal`` of
:mod:`hydromodpy.schema.job.seal` reads both families in memory and never
rewrites the file. This module reads only ``core`` and ``schema.lineage``. ``artifacts`` inventories every entry the
seal certifies, with the digest of its bytes or of its directory tree. A job
entry carries the ``media_type`` its capability declared; a run entry does
not. ``values`` carries the digests of the values the seal compared, under one
rule, or is absent for a seal that compared none.

A failed or aborted attempt writes no seal. The document is the promise
another process acts on without opening the files, so it is written only once
every file it names is on disk, through a temporary file, an ``fsync`` and one
rename.

``results/record/manifest.py`` extends this seal for a run, because the blocks of a run
are types of ``results``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Final

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import Vocabulary, dump_stored
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.core.io.value_digest import VALUES_RULE
from hydromodpy.schema.lineage import Lineage

SEAL_VERSION: Final[int] = 4
"""The integer ``manifest_version`` a run seal and a job seal both write."""

SealProfile = Annotated[str, Vocabulary("run", "job")]
"""Which of the two directories the document seals."""

_TABLE_KEY: Final[str] = "tables/"


class ArtifactRecord(HydroModelBase):
    """One entry a seal certifies, by the path its directory spells."""

    path: str = Field(description="Relative path of the entry in its directory")
    role: str = Field(description="run: fields, config, table:<name>; job: document, output")
    format: str | None = Field(default=None, description="json, parquet, zarr, directory...")
    bytes: int | None = Field(default=None, ge=0, description="Size of a file, files under a tree")
    sha256: str | None = Field(
        default=None,
        description="Digest of the file or of the directory tree; null when not sealed yet",
    )
    media_type: str | None = Field(
        default=None, description="Media type a job capability declared for its output"
    )


class ValueDigests(HydroModelBase):
    """The digests of the values a seal compared, all under one rule.

    Keys name an array of ``fields.zarr`` (``fields/<path>``), an array of
    ``final_state/`` (``final_state/<path>``) or one quantity column of one
    table (``tables/<table>/<column>``).
    """

    rule: str = Field(default=VALUES_RULE, description="Rule every digest follows")
    digests: dict[str, str] = Field(
        default_factory=dict, description="Value key to its digest, in key order"
    )

    @field_validator("digests")
    @classmethod
    def _keys(cls, value: dict[str, str]) -> dict[str, str]:
        faults = [
            key
            for key in value
            if not (
                key.startswith(("fields/", "final_state/"))
                or (key.startswith(_TABLE_KEY) and key.count("/") == 2)
            )
        ]
        if faults:
            raise ValueError(f"value key(s) {', '.join(sorted(faults)[:5])} name no stored value")
        return value


class Seal(HydroModelBase):
    """What a finished run directory and a finished job directory both promise."""

    manifest_version: int = Field(default=SEAL_VERSION, ge=1)
    profile: SealProfile = Field(description="run or job: which directory the document seals")
    sealed_at: datetime = Field(description="Instant the seal was written, UTC")
    lineage: Lineage = Field(default_factory=Lineage)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    values: ValueDigests | None = Field(
        default=None, description="Value digests; none for a seal that compared no values"
    )


def render_document(payload: Any) -> str:
    """Render *payload* as the exact text a job document carries, strict JSON.

    A non-finite number raises ``ValueError``: ``Infinity`` or ``NaN`` is not
    JSON, and a reader in another language would refuse the seal.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False, allow_nan=False)
    return text + "\n"


def write_seal(path: str | Path, seal: Seal) -> Path:
    """Write *seal* to *path* through a temporary file, an ``fsync`` and one rename.

    A reader sees the old file or the whole new one. A crash before the rename
    leaves no seal, which is exactly what an unfinished directory says.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = render_document(dump_stored(seal))
    with staged_path(target) as staged:
        with staged.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    _sync_directory(target.parent)
    return target


def _sync_directory(directory: Path) -> None:
    """Flush the directory entry of a renamed file, where the system has directories."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Some filesystems refuse fsync on a directory; the rename is still atomic.
        return
    finally:
        os.close(descriptor)


def verify_artifacts(
    root: str | Path,
    seal: Seal,
    *,
    tree_digest: Callable[[Path], str] | None = None,
) -> tuple[str, ...]:
    """Re-read every entry a seal names and report what no longer matches.

    A file is compared by its size and its digest. A directory store is
    compared by *tree_digest* when the caller gives one, since the rule that
    skips a sidecar is a rule of the results package and this module reads
    only ``core`` and ``schema``. An entry that leaves the directory is
    refused by name before it is opened.
    """
    directory = Path(root)
    resolved = directory.resolve()
    problems: list[str] = []
    for record in seal.artifacts:
        target = directory / record.path
        try:
            target.resolve().relative_to(resolved)
        except ValueError:
            problems.append(f"{record.path} is sealed and lies outside {directory}")
            continue
        if target.is_dir():
            if record.sha256 is not None and tree_digest is not None:
                if tree_digest(target) != record.sha256:
                    problems.append(f"{record.path} does not hash to what the seal recorded")
            continue
        if not target.is_file():
            problems.append(f"{record.path} is sealed and absent")
            continue
        digest, size = sha256_and_size(target)
        if record.bytes is not None and size != record.bytes:
            problems.append(f"{record.path} is {size} bytes and the seal says {record.bytes}")
        if record.sha256 is not None and digest != record.sha256:
            problems.append(f"{record.path} does not hash to what the seal recorded")
    return tuple(problems)


__all__ = [
    "SEAL_VERSION",
    "ArtifactRecord",
    "Seal",
    "SealProfile",
    "ValueDigests",
    "render_document",
    "verify_artifacts",
    "write_seal",
]
