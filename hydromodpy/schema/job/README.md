# `hydromodpy/schema/job`

The job directory: what a capability is handed, and what it leaves behind. One
directory is the whole interface between a caller and a capability. Nothing here
knows it is a job in a queue, and nothing here opens a database, a socket or a
workspace.

## Modules

| module | answers |
|---|---|
| `layout.py` | the names inside a job directory and the order they are written in (`JOB_WRITE_ORDER`, `ALLOWED_JOB_ENTRIES`) |
| `directory.py` | `JobDirectory`: resolves its root once, so that an input path is checked to stay inside it; a URI scheme other than `file:` is refused |
| `request.py`, `refusal.py` | the input document, read and refused in one typed shape; `content_address()` gives the `job_id`; how a member of a request is refused |
| `inputset.py`, `extent.py` | what the job consumed, hashed and annotated with a licence; the one box-and-CRS shape a job records a place in |
| `provenance.py`, `outcome.py` | how the job ran, with no instant and no host name; the typed status, which refuses to contradict its exit code |
| `seal.py`, `reuse.py` | `seal_job` and `verify_job`; what a sealed directory is answered with when the same job comes again |
| `worker.py` | the loop every capability worker runs around its own work: reuse or refuse a sealed directory, resolve, execute, write a failed or dismissed outcome; `seal_successful` writes and seals a success |
| `documents.py`, `digest.py` | atomic document writes, the two digests |

The runner that chains several capabilities, each filling its inputs from the artifacts of an earlier one, has no verb and no caller in the wheel. It sits in `hydromodpy_annex/schema/job_chain/`.

## How a job directory is written

The caller creates the directory and writes `request.json`. The process then
writes, in this order: `outputs/`, `inputset.json`, `provenance.json`,
`outcome.json` and `manifest.json`. `logs/` and `progress.ndjson` are not
artifacts and are not in the seal. The invariant that the order buys:
`manifest.json` exists if and only if the job succeeded and every declared
output is present and hashed. A caller outside the process never has to guess.

`seal_job` writes the manifest last and atomically; `verify_job` re-checks a
directory against it from the disk alone. A directory that already holds the
same `job_id` is re-reported with `reused` set and nothing is written
(`reuse.py`); a different one is refused. A generated view (RO-Crate, STAC,
PROV) may be added after the seal and is not inventoried by it.

## Import rules

`job/` imports `core` and the rest of `schema` only. `__init__.py` re-exports the
names of its modules, and that list is a public surface: a new name goes in its
module first, then in the list.
