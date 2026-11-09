# Frozen documents

`v2.0.0/current/` keeps the documents of 2.0.0 that `tests/regression/frozen_runs/` does not hold. They are the `published.jsonl` of a run, a published copy with its `PUBLICATION.json` and `INSTALL.toml`, an install index with a station row, the plan of a `[sites]` project, a lockfile, three sidecars, the data cache database of the island and the one of a launched case, the trial series of a session, a sealed job with its chain report, and a site catalog.
`python -m tools.freeze_documents` writes them with their real writers on a synthetic island, with no network, in about 40 seconds.
The job comes from a capability `demo` that the generator declares, because no real capability writes a job without a local path in its request.
The tree weighs about 990 kB, and the two DuckDB files take 893 kB of it.
`v2.0.0/expected.json` holds what the raw files say, read without the readers of HydroModPy, with the DuckDB and pyarrow versions that wrote them and one digest of the tree.
`test_frozen_documents.py` reads each document with the readers of today, on a copy outside the repository, so the digest fails if anything writes here.
A second generation changes the bytes of the DuckDB files, the plan date, the lockfile and the published copy, but not the values of `expected.json`.
The folder is written again only if 2.0.0 is tagged on another commit than the one `expected.json` names.
HydroModPy 2.1 refuses the lockfile (schema v1, with a sentence that names `hmp data lock`) and the data cache database (the scan names `hmp workspace clean --data-cache`). The test checks both refusals on a copy and sorts the island sidecars into rows, user files and sidecars without a variable. The database of a launched case has no reader and no test any more. `tools.freeze_documents` writes no database and refuses to write this folder from a version other than 2.0.
The folder is checked in as it is, through `.gitignore` and `.gitattributes`, and the whitespace hooks of pre-commit skip it.
