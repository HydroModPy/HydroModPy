"""The job directory: what a capability is handed, and what it leaves behind.

One directory is the whole interface. The caller writes ``request.json`` into
it and hands over the path; the process reads that document, resolves every
input path against it, writes its artifacts inside it, and seals it with
``manifest.json`` written last and atomically. Nothing here knows it is a job
in a queue, and nothing here opens a database, a socket or a workspace.

The five documents, in the order they are written::

    outputs/*           the bytes
    inputset.json       what was consumed, hashed from the bytes that were read
    provenance.json     how it ran
    outcome.json        status, exit code, timing, errors; also the stdout payload
    manifest.json       the seal, atomically, hashing all of the above

Public surface::

    from hydromodpy.schema.job.directory import JobDirectory
    from hydromodpy.schema.job.request import read_request
    from hydromodpy.schema.job.seal import seal_job

    job = JobDirectory.open(path)
    request = read_request(job)
"""
