"""The job directory: what a capability is handed, and what it leaves behind.

One directory is the whole interface. The caller writes ``request.json`` into
it and hands over the path; the process reads that document, resolves every
input path against it, writes its artefacts inside it, and seals it with
``manifest.json`` written last and atomically. Nothing here knows it is a job
in a queue, and nothing here opens a database, a socket or a workspace.

The five documents, in the order they are written::

    outputs/*           the bytes
    inputset.json       what was consumed, hashed from the bytes that were read
    provenance.json     how it ran
    outcome.json        status, exit code, timing, errors; also the stdout payload
    manifest.json       the seal, atomically, hashing all of the above

Public surface::

    from hydromodpy.schema.job import JobDirectory, read_request, seal_job

    job = JobDirectory.open(path)
    request = read_request(job)
"""

from __future__ import annotations

from hydromodpy.schema.job.digest import sha256_file, sha256_value
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, render_document, write_document
from hydromodpy.schema.job.inputset import (
    UNDETERMINED,
    InputResource,
    InputSet,
    Licence,
    LicenceRollup,
    build_inputset,
    file_resource,
    inline_resource,
    roll_up_licences,
)
from hydromodpy.schema.job.layout import (
    ALLOWED_JOB_ENTRIES,
    JOB_WRITE_ORDER,
    SEALED_DOCUMENTS,
)
from hydromodpy.schema.job.outcome import (
    UNIDENTIFIED_JOB,
    JobOutcome,
    JobStatus,
    OutputRecord,
    dismissed,
    error_record,
    now,
)
from hydromodpy.schema.job.provenance import (
    PROVENANCE_SCHEMA,
    build_provenance,
    write_provenance,
)
from hydromodpy.schema.job.refusal import refuse_request
from hydromodpy.schema.job.request import (
    FileLink,
    JobRequest,
    ProcessRef,
    check_process,
    content_address,
    read_request,
    requested_outputs,
    validate_inputs,
)
from hydromodpy.schema.job.reuse import (
    REUSED_MEMBER,
    reuse_sealed_outcome,
    reused_outcome_text,
)
from hydromodpy.schema.job.seal import (
    ArtifactRecord,
    SealVerification,
    seal_job,
    verify_job,
)

__all__ = [
    "ALLOWED_JOB_ENTRIES",
    "ArtifactRecord",
    "FileLink",
    "InputResource",
    "InputSet",
    "JOB_WRITE_ORDER",
    "JobDirectory",
    "JobOutcome",
    "JobRequest",
    "JobStatus",
    "Licence",
    "LicenceRollup",
    "OutputRecord",
    "PROVENANCE_SCHEMA",
    "REUSED_MEMBER",
    "ProcessRef",
    "SEALED_DOCUMENTS",
    "SealVerification",
    "UNDETERMINED",
    "UNIDENTIFIED_JOB",
    "build_inputset",
    "build_provenance",
    "check_process",
    "content_address",
    "dismissed",
    "error_record",
    "file_resource",
    "inline_resource",
    "now",
    "read_document",
    "read_request",
    "refuse_request",
    "render_document",
    "requested_outputs",
    "reuse_sealed_outcome",
    "reused_outcome_text",
    "roll_up_licences",
    "seal_job",
    "sha256_file",
    "sha256_value",
    "validate_inputs",
    "verify_job",
    "write_document",
    "write_provenance",
]
