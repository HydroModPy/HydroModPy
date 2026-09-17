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
  seal, a job id and a set of artefacts somebody else may already have read.

What a reuse does **not** do is re-hash the artefacts. The seal is trusted, and
``hmp process verify`` is the verb that does not trust it: it re-reads every
byte and reports. Folding that into the reuse path would give an unbounded cost
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
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, render_document
from hydromodpy.schema.job.outcome import JobOutcome

REUSED_MEMBER = "reused"
"""The one member of the outcome document that a reuse changes."""


def reuse_sealed_outcome(job: JobDirectory, *, job_id: str) -> JobOutcome:
    """Re-report the finished job of *job*, refusing a seal that names another.

    Called only on a sealed directory: the caller checks that first, because a
    request that cannot be resolved into an id must not reach a branch that
    writes.
    """
    manifest = _document(job, job.manifest_path)
    sealed = manifest.get("job_id")
    if sealed != job_id:
        raise JobUsageError(
            f"job directory {job.root} is sealed under {sealed!r} and this request "
            f"addresses {job_id!r}; a job directory holds one job"
        )
    document = _document(job, job.outcome_path)
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
    """
    document = _document(job, job.outcome_path)
    return render_document({**document, REUSED_MEMBER: True})


def _document(job: JobDirectory, path: Path) -> Mapping[str, Any]:
    """Read one document of a sealed directory, or say why it cannot be read.

    Every failure here is a usage error and not a job failure: the directory
    was handed over already finished, so nothing this process could do would
    make it readable, and the caller pointed at the wrong thing.
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
    return document


__all__ = ["REUSED_MEMBER", "reuse_sealed_outcome", "reused_outcome_text"]
