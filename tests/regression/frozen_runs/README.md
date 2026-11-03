# Frozen runs

Every later 2.x reads every 2.0.0 document, and 2.0.0 reads what a later 2.x adds without
raising its version. `docs/source/about/versions.md` and the storage layout page promise
it, and this folder holds the promise. A golden compares what the code writes today with a
reference, so it moves with the code. These files do not move, and each commit reads them
with the code of today.

## What is here

`v2.0.0/current/` is a workspace as 2.0.0 stored it. The project `example` holds the
scaffolded demo in `runs/demo/`, one calibration of its K in `sessions/calage/`, and the
run that calibration promoted in `runs/calage/`. The demo keeps one small figure and one
small export, and no log.

`v2.0.0/future/` is the same as a later 2.x could have written it. Each JSON document gets
an extra key at its root and in its nested blocks, each Parquet table an extra column, and
each Zarr store an extra array at its root, an extra term in `budget/` and an extra root
attribute. No version moves. The TOML files stay as they are, because a TOML keeps
`extra="forbid"`.

`v2.0.0/expected.json` holds what the raw files say, read by `zarr`, `pyarrow` and `json`
without the readers of HydroModPy, and one digest per copy.

`test_frozen_runs.py` reads both copies through `hmp.open`, `Run`, `Session`, `hmp.read`,
`hmp.index`, `hmp catalog reindex` and `Catalog`, and compares the values with
`expected.json`. Each test works on a copy outside the repository, and the digest fails if
anything writes here. On `future/` it also rewrites what a later run or tool rewrites (an
annotation, the ledger of the exports, a session, a phase, an outcome, a table, a field, a
published copy) and checks that the extra content is still there.

## When to regenerate

```bash
python -m tools.regenerate_frozen_runs
```

It solves with MODFLOW-NWT in a throwaway workspace and takes under a minute. No test runs
it. Run it until the tag, when a stored format moves on purpose, and read the diff of
`expected.json`. After the tag this folder never moves: a later version gets a new folder
beside it, and `v2.0.0/` keeps being read.

Two runs of the command give the same heads, budgets and costs. The ids, the timestamps, the
durations and the package list change, so the bytes change with them. The host, the user and
the local paths are taken out.

The folder stays out of the wheel and the sdist (`pyproject.toml`, `MANIFEST.in`), out of
the whitespace hooks of pre-commit, and is checked in as is (`.gitattributes`,
`.gitignore`).
