"""The seal: written last, atomically, and never on a job that did not finish.

    ``manifest.json`` exists **if and only if** the job succeeded and every
    declared output is present and hashed. Its absence is never ambiguous.

That sentence is the whole point of this module, and it is the one invariant a
caller outside this process is allowed to rely on. A crash, a ``SIGTERM`` or a
missing output leaves the directory unsealed and readable, never sealed and
wrong.

The document is the job profile of the one seal of :mod:`hydromodpy.schema.seal`.
It carries no status, no exit code, no timing and no error: those live in
``outcome.json`` and appear here only as its digest, which is what makes
tampering with the outcome break the seal instead of producing two documents
that disagree. The digests of the outputs are computed once, by the runner, and
rendered into both documents from the same records.

The 2.0.0 wrote ``schema = "hmp-manifest/v2"``, ``job_id`` and ``mediaType``.
:func:`read_job_seal` converts that document in memory, under the one name each
key now carries, and never rewrites the file.

The seal carries ``request_id``, the content address of the request, and
``outcome.json`` keeps that value under its field ``job_id``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import read_stored
from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.canonical_json import sha256_value
from hydromodpy.core.io.document_version import VersionWindow, check_version
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.schema.changes import Rule, apply_rows
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import check_job_document, read_document
from hydromodpy.schema.job.extent import SpatialExtent
from hydromodpy.schema.job.inputset import INPUTSET_VERSIONS, InputSet
from hydromodpy.schema.job.layout import INPUTSET_FILENAME, SEALED_DOCUMENTS
from hydromodpy.schema.job.outcome import OUTCOME_VERSIONS, OutputRecord, now
from hydromodpy.schema.media_types import JSON_MEDIA_TYPE
from hydromodpy.schema.seal import (
    SEAL_VERSION,
    ArtifactRecord,
    Seal,
    verify_artifacts,
    write_seal,
)

JOB_SEAL_V2_SCHEMA: Final[str] = "hmp-manifest/v2"
"""The ``schema`` a job seal of the 2.0.0 wrote; read in memory, never rewritten."""

JOB_SEAL_VERSIONS: Final[VersionWindow] = VersionWindow(oldest=SEAL_VERSION, current=SEAL_VERSION)
"""The integer ``manifest_version`` of a job seal this code reads; ``JOB_SEAL_V2_SCHEMA`` aside."""


class InputSetRef(HydroModelBase):
    """The input set a job consumed, named by its path and its digest."""

    path: str = Field(default="inputset.json", description="File inside the job directory")
    id: str = Field(description="Content address the input set carries")
    sha256: str = Field(description="Digest of the inputset.json bytes")


class JobSeal(Seal):
    """The seal of a finished job directory, version 4.

    ``request_id`` is the content address of the request the job answered. The
    2.0.0 wrote it as ``job_id``; the migration of the reading brings it under
    the one name, and ``outcome.json`` keeps ``job_id`` with the same value for
    the callers that read it.
    """

    profile: Literal["job"] = "job"
    request_id: str = Field(description="Content address of the request the job answered")
    process_id: str | None = Field(default=None, description="Process that answered")
    process_version: str | None = Field(default=None, description="Version of that process")
    inputset: InputSetRef | None = None
    geometry: SpatialExtent | None = None


def seal_job(
    job: JobDirectory,
    *,
    job_id: str,
    inputset: InputSet,
    outputs: Sequence[OutputRecord] = (),
    geometry: SpatialExtent | None = None,
    process_id: str | None = None,
    process_version: str | None = None,
) -> Path:
    """Write the seal of *job*, refusing to seal what is not complete.

    ``job_id`` is the content address of the request the job answered, and the
    seal writes it as ``request_id``. Refuses rather than seals when a document
    of the write order is missing or when an output the outcome claims is not
    on disk. A seal is a promise another program acts on without opening the
    files, so it is written only once every one of them has been opened here.
    """
    missing_documents = [name for name in SEALED_DOCUMENTS if not (job.root / name).is_file()]
    if missing_documents:
        raise ValueError(
            f"job {job.root} cannot be sealed: {', '.join(missing_documents)} not written yet"
        )
    paths = [output.path for output in outputs]
    repeated = sorted({path for path in paths if paths.count(path) > 1})
    if repeated:
        raise ValueError(
            f"job {job.root} cannot be sealed: two outputs claim {', '.join(repeated)}, "
            "and a seal that inventories one file twice describes neither"
        )
    absent_outputs = [
        output.path for output in outputs if not job.resolve_output(output.path).is_file()
    ]
    if absent_outputs:
        raise ValueError(
            f"job {job.root} cannot be sealed: declared output(s) {', '.join(absent_outputs)} "
            "are not on disk"
        )

    artifacts: dict[str, ArtifactRecord] = {
        output.path: ArtifactRecord(
            path=output.path,
            role="output",
            format=_format_of(output.path),
            bytes=output.bytes,
            sha256=output.sha256,
            media_type=output.media_type,
        )
        for output in outputs
    }
    # The control documents are re-hashed here and overwrite whatever an output
    # record said about them. A capability may declare ``outcome.json`` as one
    # of its outputs -- the process description does -- but the record for it
    # was built before that file existed, so only the bytes on disk at seal time
    # can be the ones the seal names.
    for name in SEALED_DOCUMENTS:
        digest, size = sha256_and_size(job.root / name)
        artifacts[name] = ArtifactRecord(
            path=name,
            role="document",
            format="json",
            bytes=size,
            sha256=digest,
            media_type=JSON_MEDIA_TYPE,
        )

    seal = JobSeal(
        sealed_at=now(),
        request_id=job_id,
        process_id=process_id,
        process_version=process_version,
        inputset=InputSetRef(
            path=INPUTSET_FILENAME,
            id=inputset.id,
            sha256=artifacts[INPUTSET_FILENAME].sha256 or "",
        ),
        artifacts=list(artifacts.values()),
        geometry=geometry,
    )
    return write_seal(job.manifest_path, seal)


def read_job_seal(path: str | Path) -> JobSeal:
    """Read the seal of a job directory, version 4 or the ``hmp-manifest/v2`` of 2.0.0.

    The 2.0.0 document is converted in memory only: ``job_id`` becomes
    ``request_id``, ``mediaType`` becomes ``media_type``, and each entry takes
    its role from the name of its file. The file keeps what it was written.
    """
    target = Path(path)
    payload = _read_seal_object(target)
    if "manifest_version" in payload:
        check_version(
            payload.get("manifest_version"),
            JOB_SEAL_VERSIONS,
            document=target,
            key="manifest_version",
        )
        profile = payload.get("profile")
        if profile != "job":
            raise SchemaVersionMismatchError(
                f"{target} profiles {profile!r}; this reader reads the seal of a job."
            )
        return read_stored(JobSeal, payload)
    if payload.get("schema") != JOB_SEAL_V2_SCHEMA:
        found = payload.get("schema")
        raise SchemaVersionMismatchError(
            f"{target} carries no manifest_version and has schema = {found!r}; a job seal "
            f"this code reads carries manifest_version = {SEAL_VERSION} or "
            f"schema = {JOB_SEAL_V2_SCHEMA!r}."
        )
    document = apply_rows("job.manifest", payload, rules=JOB_SEAL_RULES)
    document["manifest_version"] = SEAL_VERSION
    document["profile"] = "job"
    return read_stored(JobSeal, document)


def _read_seal_object(path: Path) -> dict[str, Any]:
    """Read one JSON object, refusing anything else as another kind of document."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaVersionMismatchError(f"{path} does not read as JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SchemaVersionMismatchError(f"{path} is not a JSON object, so it is no seal.")
    return payload


def _job_artifact_role(document: dict[str, Any]) -> None:
    """Name the role of a 2.0.0 job entry: a control document, or an output."""
    entries = document.get("artifacts")
    if not isinstance(entries, list):
        return
    for entry in entries:
        if isinstance(entry, Mapping) and isinstance(entry.get("path"), str):
            entry.setdefault("role", "document" if entry["path"] in SEALED_DOCUMENTS else "output")


JOB_SEAL_RULES: dict[str, Rule] = {"job_artifact_role": _job_artifact_role}
"""The rules of the job seal rows whose paths cannot say the whole change."""


@dataclass(frozen=True, slots=True)
class SealVerification:
    """What re-reading a finished job directory found."""

    sealed: bool
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.sealed and not self.problems


def verify_job(job: JobDirectory) -> SealVerification:
    """Re-check a job directory against its own seal, reading only the disk.

    Every artifact still hashes to what the seal recorded, the input set still
    digests to the id it carries, and the outcome names the same request.
    Nothing is repaired and nothing is rewritten. This is the verification that
    does not trust the seal: it re-reads every output.
    """
    if not job.is_sealed:
        return SealVerification(sealed=False, problems=("manifest.json is absent",))
    try:
        seal = read_job_seal(job.manifest_path)
    except (OSError, ValueError, SchemaVersionMismatchError) as exc:
        return SealVerification(sealed=True, problems=(str(exc),))
    problems: list[str] = list(verify_artifacts(job.root, seal))
    problems.extend(_inputset_problems(job, seal))
    problems.extend(_outcome_problems(job, seal))
    return SealVerification(sealed=True, problems=tuple(problems))


def _inputset_problems(job: JobDirectory, seal: JobSeal) -> list[str]:
    """Check the input set against its own digest and against the seal."""
    if not job.inputset_path.is_file():
        return ["inputset.json is absent"]
    inputset, fault = _read_object(job.inputset_path, INPUTSET_VERSIONS)
    if inputset is None:
        return [fault]
    problems: list[str] = []
    recomputed = f"sha256:{sha256_value(inputset.get('resources', []))}"
    if recomputed != inputset.get("id"):
        problems.append(
            f"inputset.json carries the id {inputset.get('id')} and digests to {recomputed}"
        )
    declared = None if seal.inputset is None else seal.inputset.id
    if declared != inputset.get("id"):
        problems.append("manifest.json and inputset.json disagree about the input-set id")
    return problems


def _outcome_problems(job: JobDirectory, seal: JobSeal) -> list[str]:
    """Check that the outcome names the request the seal names."""
    if not job.outcome_path.is_file():
        return ["outcome.json is absent"]
    outcome, fault = _read_object(job.outcome_path, OUTCOME_VERSIONS)
    if outcome is None:
        return [fault]
    if outcome.get("job_id") != seal.request_id:
        return ["manifest.json and outcome.json disagree about the request id"]
    return []


def _read_object(path: Path, window: VersionWindow) -> tuple[Mapping[str, Any] | None, str]:
    """Read one job document, reporting what is wrong instead of raising.

    A verification verb is pointed at directories it did not write, including
    ones a transfer truncated or a later version sealed. It reports; it never
    crashes on them.
    """
    try:
        document = read_document(path)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name} cannot be read as JSON: {exc}"
    if not isinstance(document, Mapping):
        return None, f"{path.name} is not a JSON object"
    try:
        check_job_document(document, window, path=path)
    except SchemaVersionMismatchError as exc:
        return None, str(exc)
    return document, ""


def _format_of(relative: str) -> str:
    """Return the format of an output, from its suffix."""
    return Path(relative).suffix.lstrip(".") or "unknown"


__all__ = [
    "JOB_SEAL_RULES",
    "JOB_SEAL_V2_SCHEMA",
    "JOB_SEAL_VERSIONS",
    "InputSetRef",
    "JobSeal",
    "SealVerification",
    "read_job_seal",
    "seal_job",
    "verify_job",
]
