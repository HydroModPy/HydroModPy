# core/payload

This folder answers: what does a package install into a workspace, and where? An example, a published
run and an exported project all carry the same index file, `INSTALL.toml`, and one installer places
their files.

## Modules, in the order a caller uses them

1. `resolve.py` finds the data a project's TOML files reference, the way a run resolves them (`authored_configs`, `authored_files`, `project_data`).
2. `index.py` reads and writes `INSTALL.toml`: `InstallIndex`, `PayloadFile` and `PayloadStation`, schema `hydromodpy.install.v1` (`read_index`, `render_index`).
3. `install.py` plans every placement before it writes one (`plan_files`, `plan_stations`, `refuse_conflicts`, `write_file`). Identical bytes cost nothing, an absent file is copied with its sidecar, other bytes at the same path are a conflict named with both digests (`PayloadConflictError`).

## What other layers import from it

`examples`, `project`, `results` and `cli`.

## Where to add what

- A new kind of package: it writes the same index, no new format.
- A new placement rule: `install.py`, planned first, written after.
- A change of the index fields: `index.py`, with a new schema version.

The layer rules are checked by `tests/unit/architecture/`.
