"""The names inside a job directory, and the order they are written in.

A job directory is the second profile of the vocabulary a run directory
already uses (``manifest.json`` is the seal, ``provenance.json`` says how it
ran), so the two profiles share their names and their meaning. What differs is
the entry list and the presence of the caller's own document: a job carries
``request.json``, written by whoever invoked the process and by nobody else.

The write order is the contract. Everything a reader needs is on disk before
the seal names it, and a crash between any two steps leaves no seal, which is
the one unambiguous signal a caller outside this process can read.
"""

from __future__ import annotations

REQUEST_FILENAME = "request.json"
"""The input document, written by the caller before the process starts."""

INPUTSET_FILENAME = "inputset.json"
"""What the job consumed: resolved, hashed and licence-annotated."""

JOB_PROVENANCE_FILENAME = "provenance.json"
"""Tool, commit, interpreter, platform and backend of one job."""

OUTCOME_FILENAME = "outcome.json"
"""Typed status, exit code, timing and errors. Also the stdout payload."""

JOB_MANIFEST_FILENAME = "manifest.json"
"""The seal, written last and atomically. Absent means the job did not finish."""

OUTPUTS_DIRNAME = "outputs"
"""The artefacts the capability declared, and nothing else."""

LOGS_DIRNAME = "logs"
"""Diagnostics of one job. Not an artefact, not in the seal."""

JOB_LOG_FILENAME = "job.jsonl"
"""Structured log inside :data:`LOGS_DIRNAME`, still open when the seal is written."""

PROGRESS_FILENAME = "progress.ndjson"
"""Appended one JSON object per line while the job runs. Not an artefact."""

SEALED_DOCUMENTS: tuple[str, ...] = (
    INPUTSET_FILENAME,
    JOB_PROVENANCE_FILENAME,
    OUTCOME_FILENAME,
)
"""The documents the seal hashes, in the order they are written.

``request.json`` is absent on purpose: the caller owns it, the job did not
produce it, and what the job consumed is stated by ``inputset.json`` with the
digests it read the bytes with.
"""

JOB_WRITE_ORDER: tuple[str, ...] = (OUTPUTS_DIRNAME, *SEALED_DOCUMENTS, JOB_MANIFEST_FILENAME)
"""Bytes, then what was consumed, then how it ran, then status, then the seal."""

NON_ARTIFACT_ENTRIES: frozenset[str] = frozenset({LOGS_DIRNAME, PROGRESS_FILENAME})
"""Job state that is still being written when the seal is computed.

A log or a progress stream cannot carry an honest size while it is open, which
is the reason the run profile already gives for keeping its pipeline log out of
the seal.
"""

ALLOWED_JOB_ENTRIES: frozenset[str] = (
    frozenset({REQUEST_FILENAME, JOB_MANIFEST_FILENAME, OUTPUTS_DIRNAME})
    | frozenset(SEALED_DOCUMENTS)
    | NON_ARTIFACT_ENTRIES
)
"""Every name a job directory may carry at its top level.

Asserted as a subset, never as an equality: a job that failed before writing
its outputs is still a legal job directory, and a generated view added later
extends this set without invalidating a single directory already on disk.
"""


__all__ = [
    "ALLOWED_JOB_ENTRIES",
    "INPUTSET_FILENAME",
    "JOB_LOG_FILENAME",
    "JOB_MANIFEST_FILENAME",
    "JOB_PROVENANCE_FILENAME",
    "JOB_WRITE_ORDER",
    "LOGS_DIRNAME",
    "NON_ARTIFACT_ENTRIES",
    "OUTCOME_FILENAME",
    "OUTPUTS_DIRNAME",
    "PROGRESS_FILENAME",
    "REQUEST_FILENAME",
    "SEALED_DOCUMENTS",
]
