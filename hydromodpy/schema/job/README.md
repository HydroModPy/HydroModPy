# `hydromodpy/schema/job`

The job directory: what a capability is handed, and what it leaves behind. One directory is the
whole interface between a caller and a capability, and nothing here opens a database, a socket
or a workspace. `manifest.json` is the seal of a finished job, at `manifest_version` 4 and
`profile = "job"`, the common model of `hydromodpy/schema/seal.py`. It carries `request_id`, the
content address of the request, and `outcome.json` keeps that value under its field `job_id`. A
job seal of the 2.0.0 wrote `schema = "hmp-manifest/v2"`, with `job_id` and `mediaType` on each
artifact, and `read_job_seal` reads both families in memory without rewriting the file. The
caller creates the directory and writes `request.json`; the process writes `outputs/`,
`inputset.json`, `provenance.json`, `outcome.json` and `manifest.json`, in that order, so the
seal exists if and only if the job succeeded. `ArtifactRecord`, `MANIFEST_SCHEMA` and
`MANIFEST_VERSIONS` left the public list of this package for the common model. The folder reads
`core` and the rest of `schema`, and the answers column below is the first line of each module
docstring.

| module | answers |
|---|---|
| `directory.py` | The one directory a capability process is allowed to touch. |
| `documents.py` | How a job writes one of its documents: whole, or not at all. |
| `extent.py` | The spatial extent a job records: one box, in the CRS it was measured in. |
| `inputset.py` | What a job consumed, as one object: resolved, hashed, licence-annotated. |
| `layout.py` | The names inside a job directory, and the order they are written in. |
| `outcome.py` | The typed outcome of one job: status, exit code, timing, errors. |
| `provenance.py` | How one job ran: tool, commit, interpreter, platform, backend, packages. |
| `refusal.py` | How this boundary refuses one member of a request document. |
| `request.py` | The input document, read and refused in one typed shape. |
| `reuse.py` | A directory that already holds the same job is re-reported, never re-run. |
| `seal.py` | The seal: written last, atomically, and never on a job that did not finish. |
| `worker.py` | The loop every capability worker runs around its own work. |
