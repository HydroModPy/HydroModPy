"""The job directory: what a capability is given, and what it leaves behind.

One directory is the whole interface. The caller writes ``request.json`` into
it and hands over the path; the process reads that document, resolves every
input path against it, writes its artefacts inside it, and seals it with
``manifest.json`` written last and atomically. Nothing here knows it is a job
in a queue, and nothing here opens a database, a socket or a workspace.

Public surface::

    from hydromodpy.schema.job import JobDirectory, read_request

    job = JobDirectory.open(path)
    request = read_request(job)
"""

from __future__ import annotations

from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.layout import (
    ALLOWED_JOB_ENTRIES,
    JOB_WRITE_ORDER,
    SEALED_DOCUMENTS,
)
from hydromodpy.schema.job.refusal import refuse_request
from hydromodpy.schema.job.request import (
    FileLink,
    JobRequest,
    ProcessRef,
    check_process,
    read_request,
    requested_outputs,
    validate_inputs,
)

__all__ = [
    "ALLOWED_JOB_ENTRIES",
    "FileLink",
    "JOB_WRITE_ORDER",
    "JobDirectory",
    "JobRequest",
    "ProcessRef",
    "SEALED_DOCUMENTS",
    "check_process",
    "read_request",
    "refuse_request",
    "requested_outputs",
    "validate_inputs",
]
