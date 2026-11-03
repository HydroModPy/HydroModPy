"""The loop every capability worker runs around its own work.

A worker keeps two functions of its own. ``resolve`` reads and checks the
request before a byte is written, and returns an object that carries the
``job_id`` it addresses. ``execute`` does the work inside the job and returns
the outcome it wrote. This module runs them in the order the whole family
keeps:

* a directory that is already sealed is reused or refused, see :mod:`.reuse`;
* otherwise the request is resolved, then executed;
* an interrupt writes a dismissed outcome and goes on;
* any other exception writes a failed outcome, with the exit code the caller's
  mapper gives it.

**The exit code is the runtime's decision, not the worker's.** ``run_job``
takes the mapper as an argument because a worker cannot import ``cli``, and
because the exception a capability raises and the status a shim reads are two
different contracts. The caller that owns the process owns the mapping.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.schema.capability import CapabilityDecl
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import write_document
from hydromodpy.schema.job.inputset import InputSet
from hydromodpy.schema.job.outcome import (
    UNIDENTIFIED_JOB,
    JobOutcome,
    OutputRecord,
    dismissed,
    error_record,
    now,
)
from hydromodpy.schema.job.provenance import build_provenance, write_provenance
from hydromodpy.schema.job.reuse import reuse_sealed_outcome
from hydromodpy.schema.job.seal import seal_job

ExitCodeMapper = Callable[[BaseException], int]
"""How the runtime turns an exception into the status a shim reads."""


class Resolved(Protocol):
    """What a worker's ``resolve`` returns: at least the job id it addresses."""

    @property
    def job_id(self) -> str: ...


R = TypeVar("R", bound=Resolved)


def run_job(
    job: JobDirectory,
    *,
    decl: CapabilityDecl,
    resolve: Callable[[JobDirectory], R],
    execute: Callable[[JobDirectory, R, str], JobOutcome],
    exit_code_for: ExitCodeMapper,
) -> JobOutcome:
    """Run one capability inside *job* and return what happened.

    Writes ``outcome.json`` in every case. ``execute`` writes ``manifest.json``
    only when the job succeeded and every declared output is on disk and
    hashed, which is the one invariant a caller outside this process relies on.
    ``execute`` receives the job, the resolved request and the start time.
    """
    if job.is_sealed:
        # Answered outside the try on purpose. Turning any of it into a failed
        # outcome would overwrite the outcome of the job that did finish, which
        # is the very document this branch exists to protect.
        return _reuse_or_refuse(job, resolve)
    started_at = now()
    job_id = UNIDENTIFIED_JOB
    try:
        resolved = resolve(job)
        job_id = resolved.job_id
        return execute(job, resolved, started_at)
    except KeyboardInterrupt as exc:
        # TerminationRequested subclasses KeyboardInterrupt, so SIGTERM and
        # Ctrl+C unwind through the same branch. Nothing is sealed: a
        # canceled directory is readable and explicitly unfinished.
        outcome = dismissed(
            job_id=job_id,
            process_id=decl.id,
            process_version=decl.version,
            started_at=started_at,
            exc=exc,
        )
        outcome.write(job)
        raise
    except Exception as exc:
        outcome = JobOutcome(
            job_id=job_id,
            process_id=decl.id,
            process_version=decl.version,
            status="failed",
            exit_code=exit_code_for(exc),
            started_at=started_at,
            finished_at=now(),
            errors=(error_record(exc),),
        )
        outcome.write(job)
        return outcome


def _reuse_or_refuse(job: JobDirectory, resolve: Callable[[JobDirectory], Resolved]) -> JobOutcome:
    """Answer a directory that is already sealed, without writing into it.

    The request is resolved first, because the job id is what a reuse compares.
    A request that no longer resolves cannot be addressed at all, so it cannot
    match a seal, and it is refused the way a different job is: as a usage
    error, because the caller pointed a finished directory at a request that is
    not the one that finished it.
    """
    try:
        resolved = resolve(job)
    except Exception as exc:
        raise JobUsageError(
            f"job directory {job.root} is already sealed, and this request does not "
            f"resolve into a job id to compare against it: {exc}"
        ) from exc
    return reuse_sealed_outcome(job, job_id=resolved.job_id)


def seal_successful(
    job: JobDirectory,
    *,
    decl: CapabilityDecl,
    job_id: str,
    inputset: InputSet,
    backend: dict[str, Any] | None,
    outputs: Callable[[], tuple[OutputRecord, ...]],
    warnings: tuple[str, ...],
    started_at: str,
) -> JobOutcome:
    """Write the input set, the provenance and the outcome of a success, then seal.

    *outputs* hashes the artifacts once the input set and the provenance are on
    disk, since both are declared outputs.
    """
    write_document(job.inputset_path, inputset.to_document())
    write_provenance(
        job,
        build_provenance(
            job_id=job_id,
            process_id=decl.id,
            process_version=decl.version,
            backend=backend,
        ),
    )
    records = outputs()
    outcome = JobOutcome(
        job_id=job_id,
        process_id=decl.id,
        process_version=decl.version,
        status="successful",
        # Not asked of the mapper: a success exits 0 by POSIX, and JobOutcome
        # refuses any other code beside this status, so the literal cannot drift.
        exit_code=0,
        started_at=started_at,
        finished_at=now(),
        outputs=records,
        warnings=warnings,
    )
    outcome.write(job)
    seal_job(job, job_id=job_id, inputset=inputset, outputs=records)
    return outcome


__all__ = [
    "ExitCodeMapper",
    "Resolved",
    "run_job",
    "seal_successful",
]
