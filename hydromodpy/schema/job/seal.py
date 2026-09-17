"""The seal: written last, atomically, and never on a job that did not finish.

    ``manifest.json`` exists **if and only if** the job succeeded and every
    declared output is present and hashed. Its absence is never ambiguous.

That sentence is the whole point of this module, and it is the one invariant a
caller outside this process is allowed to rely on. A crash, a ``SIGTERM`` or a
missing output leaves the directory unsealed and readable, never sealed and
wrong.

The manifest carries no status, no exit code, no timing and no error: those
live in ``outcome.json`` and appear here only as its digest, which is what
makes tampering with the outcome break the seal instead of producing two
documents that disagree. The digests of the outputs are computed once, by the
runner, and rendered into both documents from the same records.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.schema.job.digest import sha256_file, sha256_value
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, write_document
from hydromodpy.schema.job.inputset import InputSet
from hydromodpy.schema.job.layout import INPUTSET_FILENAME, SEALED_DOCUMENTS
from hydromodpy.schema.job.outcome import OutputRecord, now

MANIFEST_SCHEMA = "hmp-manifest/v2"
JOB_PROFILE = "job"
JSON_MEDIA_TYPE = "application/json"


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """One file the seal inventories, by the path the directory spells."""

    path: str
    media_type: str
    bytes: int
    sha256: str

    def to_document(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mediaType": self.media_type,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }


def artifact_record(job: JobDirectory, relative: str, *, media_type: str) -> ArtifactRecord:
    """Hash the bytes of one file of *job* and record them."""
    digest, size = sha256_file(job.resolve_output(relative))
    return ArtifactRecord(
        path=job.relative(relative), media_type=media_type, bytes=size, sha256=digest
    )


def seal_job(
    job: JobDirectory,
    *,
    job_id: str,
    inputset: InputSet,
    outputs: Sequence[OutputRecord] = (),
    geometry: Mapping[str, Any] | None = None,
) -> Path:
    """Write the seal of *job*, refusing to seal what is not complete.

    Refuses rather than seals when a document of the write order is missing or
    when an output the outcome claims is not on disk. A seal is a promise
    another program acts on without opening the files, so it is written only
    once every one of them has been opened here.
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
            media_type=output.media_type,
            bytes=output.bytes,
            sha256=output.sha256,
        )
        for output in outputs
    }
    # The control documents are re-hashed here and overwrite whatever an output
    # record said about them. A capability may declare ``outcome.json`` as one
    # of its outputs — the process description does — but the record for it was
    # built before that file existed, so only the bytes on disk at seal time can
    # be the ones the seal names.
    for name in SEALED_DOCUMENTS:
        artifacts[name] = artifact_record(job, name, media_type=JSON_MEDIA_TYPE)

    document: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "profile": JOB_PROFILE,
        "job_id": job_id,
        "sealed_at": now(),
        "inputset": {
            "path": INPUTSET_FILENAME,
            "id": inputset.id,
            "sha256": artifacts[INPUTSET_FILENAME].sha256,
        },
        "artifacts": [record.to_document() for record in artifacts.values()],
    }
    if geometry is not None:
        document["geometry"] = dict(geometry)
    return write_document(job.manifest_path, document)


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

    Every artefact still hashes to what the seal recorded, the input set still
    digests to the id it carries, and the outcome names the same job. Nothing
    is repaired and nothing is rewritten. This is what the verification verb
    of the CLI will report, the day that verb exists.
    """
    if not job.is_sealed:
        return SealVerification(sealed=False, problems=("manifest.json is absent",))
    manifest, fault = _read_object(job.manifest_path)
    if manifest is None:
        return SealVerification(sealed=True, problems=(fault,))
    problems: list[str] = []

    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        problems.append("manifest.json carries no artifact list")
    else:
        for entry in entries:
            problems.extend(_artifact_problems(job, entry))

    problems.extend(_inputset_problems(job, manifest))
    problems.extend(_outcome_problems(job, manifest))
    return SealVerification(sealed=True, problems=tuple(problems))


def _read_object(path: Path) -> tuple[Mapping[str, Any] | None, str]:
    """Read one job document, reporting what is wrong instead of raising.

    A verification verb is pointed at directories it did not write, including
    ones a transfer truncated. It reports; it never crashes on them.
    """
    try:
        document = read_document(path)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name} cannot be read as JSON: {exc}"
    if not isinstance(document, Mapping):
        return None, f"{path.name} is not a JSON object"
    return document, ""


def _inputset_problems(job: JobDirectory, manifest: Mapping[str, Any]) -> list[str]:
    """Check the input set against its own digest and against the seal."""
    if not job.inputset_path.is_file():
        return ["inputset.json is absent"]
    inputset, fault = _read_object(job.inputset_path)
    if inputset is None:
        return [fault]
    problems: list[str] = []
    recomputed = f"sha256:{sha256_value(inputset.get('resources', []))}"
    if recomputed != inputset.get("id"):
        problems.append(
            f"inputset.json carries the id {inputset.get('id')} and digests to {recomputed}"
        )
    block = manifest.get("inputset")
    declared = block.get("id") if isinstance(block, Mapping) else None
    if declared != inputset.get("id"):
        problems.append("manifest.json and inputset.json disagree about the input-set id")
    return problems


def _outcome_problems(job: JobDirectory, manifest: Mapping[str, Any]) -> list[str]:
    """Check that the outcome names the job the seal names."""
    if not job.outcome_path.is_file():
        return ["outcome.json is absent"]
    outcome, fault = _read_object(job.outcome_path)
    if outcome is None:
        return [fault]
    if outcome.get("job_id") != manifest.get("job_id"):
        return ["manifest.json and outcome.json disagree about the job id"]
    return []


def _artifact_problems(job: JobDirectory, entry: Any) -> list[str]:
    """Check one sealed artefact against the bytes on disk."""
    if not isinstance(entry, Mapping) or not entry.get("path"):
        return ["manifest.json inventories an artefact that carries no path"]
    relative = str(entry["path"])
    if not job.contains(relative):
        return [f"{relative} is sealed and lies outside the job directory"]
    path = job.root / relative
    if not path.is_file():
        return [f"{relative} is sealed and absent"]
    digest, size = sha256_file(path)
    problems: list[str] = []
    if size != entry.get("bytes"):
        problems.append(f"{relative} is {size} bytes and the seal says {entry.get('bytes')}")
    if digest != entry.get("sha256"):
        problems.append(f"{relative} does not hash to what the seal recorded")
    return problems


__all__ = [
    "JOB_PROFILE",
    "MANIFEST_SCHEMA",
    "ArtifactRecord",
    "SealVerification",
    "artifact_record",
    "seal_job",
    "verify_job",
]
