"""A directory that already holds the same job is re-reported, never re-run.

``job_id`` is a content address: the digest of the process identity and of the
resolved inputs, every file link replaced by the digest of its bytes. Two
byte-identical submissions therefore carry one id, which is what lets a caller
deduplicate and retry with no job store and no database.

This module is what turns that id into a decision, and it holds the decision
for every capability rather than for the one that exists today:

* not sealed -- there is nothing to reuse, the job runs;
* sealed under the **same** id -- nothing is written, the stored outcome comes
  back with ``reused`` set, and the process exits 0;
* sealed under a **different** id -- refused, because running would overwrite a
  seal, a job id and a set of artifacts somebody else may already have read.

What a reuse does **not** do is re-hash the artifacts. The seal is trusted, and
the verification that does not trust the seal (``verify_job``) re-reads every
output and reports. Folding that into the reuse path would give an unbounded cost
to the one path whose whole purpose is to be instant, and would leave the
caller with no answer anyway -- a corrupt sealed directory cannot be re-run
into, since that is exactly what the refusal above protects.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import check_job_document, read_document
from hydromodpy.schema.job.outcome import OUTCOME_VERSIONS, JobOutcome
from hydromodpy.schema.seal import render_document

REUSED_MEMBER = "reused"
"""The one member of the outcome document that a reuse changes."""


def reuse_sealed_outcome(job: JobDirectory, *, job_id: str) -> JobOutcome:
    """Re-report the finished job of *job*, refusing a seal that names another.

    Called only on a sealed directory: the caller checks that first, because a
    request that cannot be resolved into an id must not reach a branch that
    writes.
    """
    # Imported here because the seal module reads this package: a top-level
    # import would close the cycle whenever the seal module is the one entered.
    from hydromodpy.core.exceptions import SchemaVersionMismatchError
    from hydromodpy.schema.job.seal import read_job_seal

    try:
        seal = read_job_seal(job.manifest_path)
    except SchemaVersionMismatchError:
        # A seal of another version keeps its own refusal, which names the
        # version that wrote it and what to do; wrapping it would hide both.
        raise
    except (OSError, ValueError) as exc:
        raise JobUsageError(
            f"job directory {job.root} is sealed and its {job.manifest_path.name} "
            f"cannot be read as a seal: {exc}"
        ) from exc
    if seal.request_id != job_id:
        raise JobUsageError(
            f"job directory {job.root} is sealed under {seal.request_id!r} and this request "
            f"addresses {job_id!r}; a job directory holds one job"
        )
    document = _document(job, job.outcome_path, OUTCOME_VERSIONS)
    try:
        stored = JobOutcome.from_document(document)
    except (KeyError, TypeError, ValueError) as exc:
        raise JobUsageError(
            f"job directory {job.root} is sealed and its {job.outcome_path.name} "
            f"cannot be read as an outcome: {exc}"
        ) from exc
    return replace(stored, reused=True)


def reused_outcome_text(job: JobDirectory) -> str:
    """The stored outcome document, with ``reused`` set and nothing else changed.

    Rendered from the bytes on disk rather than from the typed outcome: what a
    caller is promised is the document the directory carries, and re-rendering
    a parsed object would make stdout the output of this repository's writer
    instead of the file itself. Substituting one member of a mapping that
    already carries it leaves every other member, and their order, alone.

    "That already carries it" is the whole reason for the refusal below.
    Merging into a mapping that does **not** carry the member appends it at the
    end instead of changing it in place, so a document written by anything but
    this contract would turn "exactly one member differs" into two documents
    with different lengths -- silently, since nothing downstream re-reads them
    together.
    """
    document = _document(job, job.outcome_path, OUTCOME_VERSIONS)
    if REUSED_MEMBER not in document:
        raise JobUsageError(
            f"job directory {job.root} is sealed and its {job.outcome_path.name} carries "
            f"no {REUSED_MEMBER!r} member; it was not written by this contract"
        )
    return render_document({**document, REUSED_MEMBER: True})


def _document(job: JobDirectory, path: Path, window: VersionWindow) -> Mapping[str, Any]:
    """Read one document of a sealed directory, or say why it cannot be read.

    Every failure here is a usage error and not a job failure: the directory
    was handed over already finished, so nothing this process could do would
    make it readable, and the caller pointed at the wrong thing. A version this
    code does not read keeps its own refusal, which says what to do.
    """
    try:
        document = read_document(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise JobUsageError(
            f"job directory {job.root} is sealed and its {path.name} cannot be read: {exc}"
        ) from exc
    if not isinstance(document, Mapping):
        raise JobUsageError(
            f"job directory {job.root} is sealed and its {path.name} is not a JSON object"
        )
    return check_job_document(document, window, path=path)


__all__ = ["REUSED_MEMBER", "reuse_sealed_outcome", "reused_outcome_text"]
