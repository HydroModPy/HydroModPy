# Refactor: Parquet lakehouse for timeseries / budgets / mass_balance

> **Audience** — a fresh Claude Opus 4.7 (max) session with NO memory of the design conversation that produced this spec. Everything needed is in this file.

> **Safety** — work on the **current branch** (`dev-database`). **DO NOT create a new branch. DO NOT push. DO NOT open a PR.** Only local commits on `dev-database`.

---

## 1. Context & motivation

HydroModPy is a Python toolbox for catchment-scale shallow groundwater modeling. Read `CLAUDE.md` at the repo root first — the "Simulation Catalog" section is directly load-bearing.

**Problem to solve.** Today, per-simulation timeseries/budgets/mass_balance rows live inside `hydromodpy.duckdb` (the single workspace-level catalog). Two issues:

1. **DuckDB is single-writer at the file level.** Concurrent writers (e.g. parallel calibration workers, parallel batch runs) will collide — DuckDB raises `IOException: Could not set lock on file` with no built-in retry. Today the calibration loop is strictly serial (`hydromodpy/calibration/engine.py`), so this is a latent problem, not yet an observed one. It becomes a hard block the day we parallelize.
2. **Volume.** 70 years daily × N stations × M variables × thousands of simulations → easily 10⁸–10⁹ rows inside `timeseries`. DuckDB can technically hold that, but inserts slow down (composite PK B-tree maintenance), file swells past a sensible single-file size, and cross-sim queries have to traverse one giant index.

**Chosen solution.** Move the large, append-only tables (`timeseries`, `budgets`, `mass_balance`) out of DuckDB and into **Parquet files, hive-partitioned by `sim_id`**, stored under `simulations/<uuid>/`. Expose them in DuckDB via `CREATE VIEW … AS SELECT * FROM read_parquet(..., hive_partitioning=true)` so all existing SQL access keeps working unchanged. Each simulation writes its own Parquet directory → **zero write contention between workers**.

Tables that stay in DuckDB (small, mutable, relational): `simulations`, `parameters`, `metrics`, `observation_points`, `provenance`, `geographic_features`, `geographic_metadata`, `runs_environment`, `tags`, `stations`, `observations`, `tracked_files`, `calibration_sessions`, `calibration_iterations`.

**Complementary fix.** Port the retry pattern that already exists in `hydromodpy/data/registry/catalog_duckdb.py` (`_retry_on_lock`, ~lines 280–349) to `SimulationCatalog` in `hydromodpy/results/catalog.py`. Today `SimulationCatalog` has **no** retry, so any cross-process lock contention — even with 1 writer + 1 reader (e.g. `hmp list` during `hmp run`) — can surface as an `IOException`. This is a pre-existing bug the refactor should fix.

---

## 2. Hard invariants (DO NOT BREAK)

These are non-negotiable. Any regression here = task failed.

1. **Public Python API unchanged.** `hmp.Project(config).run(...)`, `hmp.open(workspace)`, `run.timeseries(station=…)`, `run.budget(…)`, `run.field(…)`, `run.plot(…)`, `catalog.simulations`, `catalog.find(…)`, `catalog.best(…)`, `catalog.export_package(…)` — same signatures, same return types, same ordering, same dtypes.
2. **SQL access unchanged.** Any `catalog.connection.execute("SELECT … FROM timeseries WHERE …")` continues to work. The VIEW must preserve column names, types, and row semantics of the former table.
3. **Figures unchanged.** All plotting code under `hydromodpy/display/` goes through the `Run` façade. Do not touch `display/` except to update docstrings if needed. Figures produced before and after must be visually identical and numerically identical within 1e-12 relative tolerance.
4. **CLI unchanged.** `hmp run`, `hmp list`, `hmp export`, `hmp display`, `hmp doctor`, `hmp new`, `hmp init`, `hmp config`, `hmp test` — behaviour, exit codes, stdout format preserved.
5. **Zarr unchanged.** Spatial fields (head, watertable, etc.) stay in `simulations/<uuid>.zarr/`. This refactor is about DuckDB tables only.
6. **Calibration & batch workflows unchanged at the API level.** They may need internal plumbing changes but user-facing behaviour must be identical.
7. **Workspace portability preserved.** A workspace is still one self-contained directory that can be `rsync`ed, zipped, shared. No cloud, no external service.
8. **Migration path for existing workspaces.** Anyone with an existing `hydromodpy.duckdb` containing timeseries must be able to run a single command to migrate in-place without data loss.

---

## 3. Deliverables

### 3.1 Code changes

| Area | Change |
|---|---|
| `hydromodpy/results/catalog_schema.py` | Remove `_TIMESERIES_DDL`, `_BUDGETS_DDL`, `_MASS_BALANCE_DDL` from `_ALL_DDL`. Add Parquet VIEWs defined over `read_parquet('.../simulations/*/timeseries.parquet', hive_partitioning=true)` etc. Handle the empty-workspace case (no files yet) gracefully. |
| `hydromodpy/results/catalog.py` | Rewrite `write_timeseries`, `write_budgets`, `write_mass_balances` to write Parquet files with atomic `.tmp` + `os.replace` pattern. Add a `@_with_lock_retry` decorator (factored from `data/registry/catalog_duckdb.py`) and apply to all remaining DuckDB write methods. Expose `_resolve_sim_parquet_dir(sim_id)` helper. |
| `hydromodpy/results/run.py` | `Run.timeseries(…)`, `Run.budget(…)`, `Run.mass_balance(…)` read from the VIEW (no change needed if implemented via SQL today) or directly from Parquet for faster point reads. Behaviour must be byte-identical on output. |
| `hydromodpy/results/exporters/` | Update the `.hmp` package exporter/importer to include Parquet directories and reconstruct them on import. |
| `hydromodpy/simulation/extraction/extractors/modflow6.py` and siblings | If they call `write_timeseries` row-by-row, convert to batched write (accumulate in a list/DataFrame, flush once at the end of simulation). |
| `hydromodpy/_cli/commands/` | Add `hmp migrate` subcommand that detects legacy workspaces (timeseries rows inside DuckDB) and moves them to Parquet. Idempotent. |
| `hydromodpy/_cli/commands/doctor.py` | Extend `hmp doctor` output to report Parquet layout health (missing files vs. completed sims in DuckDB, orphan Parquet directories). |

### 3.2 Tests

- Update `tests/regression/golden_utils.py` if it compares DuckDB tables directly on the three moved tables — redirect to the VIEW or to Parquet.
- Regenerate goldens **only at the end**, after manually verifying that the first few sims produce correct Parquet outputs. Use `hmp test regression --update-goldens`.
- Add new tests under `tests/unit/results/`:
  - `test_parquet_write_atomic.py` — interrupt a write mid-flight, assert no partial Parquet visible in the VIEW.
  - `test_concurrent_writes.py` — spawn 8 `multiprocessing.Process` workers each registering & writing a sim; assert all 8 sims visible in catalog, no data loss, no exception surfaced to caller.
  - `test_view_semantics.py` — assert `SELECT * FROM timeseries WHERE sim_id=…` returns exactly what `Run.timeseries()` returns, column-for-column, row-for-row.
  - `test_migration.py` — create a legacy DuckDB with timeseries rows, run `hmp migrate`, assert VIEW returns the same rows, DuckDB table is dropped, Parquet files exist.

### 3.3 Documentation

Every non-trivial change must come with a companion `.md` in `docs/developers/` explaining the choice, the rationale, and the tradeoffs. At minimum:

1. `docs/developers/parquet_lakehouse_architecture.md` — new architecture doc. Supersedes the relevant parts of `simulation_catalog_architecture.md` (link it from there, don't delete the old doc without consulting the user).
2. `docs/developers/parquet_lakehouse_migration_guide.md` — for existing users: how to run `hmp migrate`, what it does, rollback.
3. `docs/developers/parquet_lakehouse_concurrency.md` — the retry/atomic-rename patterns used, why, failure modes.
4. Update `CLAUDE.md` — the "Simulation Catalog" section and the "Storage Architecture" subsection must reflect the new layout. Add the Parquet directory to the workspace tree diagram.
5. Add a `CHANGELOG.md` entry at repo root (create file if it does not exist) under an `## [Unreleased]` heading, section `### Changed` / `### Added` / `### Fixed`.

---

## 4. Proposed workspace layout (final state)

```
workspace/
├── hydromodpy.duckdb          # metadata only now (small)
├── data/
│   ├── cache.duckdb
│   └── <variable>/
├── simulations/
│   └── <uuid>/                # NEW: per-sim directory (was a .zarr dir only)
│       ├── data.zarr/         # spatial fields (unchanged)
│       ├── timeseries.parquet
│       ├── budgets.parquet
│       └── mass_balance.parquet
└── projects/
```

Note: the existing Zarr path `simulations/<uuid>.zarr/` (a bare directory) changes to `simulations/<uuid>/data.zarr/` to group everything per sim. **If** this rename breaks too much, an acceptable fallback is to keep Zarr at `simulations/<uuid>.zarr/` and put Parquets at `simulations/<uuid>.parquet/{timeseries,budgets,mass_balance}.parquet`. Decide based on blast radius; document the choice.

---

## 5. Execution plan (phases)

You have access to sub-agents (Explore, general-purpose, test-debugger). Use them aggressively for parallel phases. User is on Claude Max x20 — budget is not the bottleneck, clock time is.

### Phase 0 — Baseline (serial, do first)

1. Confirm you are on `dev-database`: `git branch --show-current` must print `dev-database`. **Do not create a new branch.**
2. Inspect `git status` — the working tree may already have modifications. Do not discard them; commit or stash them at the user's discretion before starting. If in doubt, stop and ask.
3. Run the full fast test suite and capture baseline: `hmp test regression --fast -j auto 2>&1 | tee /tmp/baseline_fast.log` then `pytest tests/unit/ -v 2>&1 | tee /tmp/baseline_unit.log`.
4. Record current sizes of `examples/data/cache.duckdb` and any workspace fixtures used in tests.

### Phase 1 — Parallel exploration (spawn 3 Explore sub-agents simultaneously)

- **Sub-agent A**: "Find every read site of tables `timeseries`, `budgets`, `mass_balance` anywhere in `hydromodpy/`, `tests/`, `validation_cases/`, `examples/`, `launchers/`. Report each as `file:line` + surrounding 3 lines. Include SQL in strings, raw `read_parquet` calls, `catalog.connection.execute(...)`, pandas/polars queries."
- **Sub-agent B**: "Find every write site of tables `timeseries`, `budgets`, `mass_balance`. Same format. Report whether each write is row-by-row or batched. List the call stack up to the public entrypoint."
- **Sub-agent C**: "Enumerate every pytest file that interacts with the `SimulationCatalog`, directly or via fixtures. Identify which ones construct goldens for the three moved tables. Also list all `.hmp` package tests."

Consolidate into a single document `docs/developers/parquet_lakehouse_refactor_blast_radius.md` before writing any production code.

### Phase 2 — Retry decorator + schema DDL (serial, single focused context)

- Factor `_retry_on_lock` into a shared helper (e.g. `hydromodpy/results/_db_retry.py` or keep it in `core/` if natural).
- Apply to all `SimulationCatalog` `write_*` methods.
- Remove the three TABLE DDLs from `catalog_schema.py`. Add VIEW DDLs. Handle the "no parquet files yet" case (a glob pattern that matches nothing) without raising — return an empty VIEW with the correct column types.
- Add unit tests for retry: a fixture that holds a lock, assert writer retries & eventually succeeds.

### Phase 3 — Write-path refactor (serial)

- Implement Parquet write with `pyarrow.parquet.write_table` or `polars.DataFrame.write_parquet`, preference for the library already used in the project (check `pyproject.toml`).
- Atomic pattern: write to `simulations/<uuid>/.tmp_timeseries.parquet`, `fsync`, then `os.replace` to `simulations/<uuid>/timeseries.parquet`.
- Batch accumulation: writers must call `write_timeseries(all_rows_at_once)` once per sim, not once per row. Refactor `simulation/extraction/extractors/*.py` accordingly.
- Ensure the Parquet schema exactly mirrors the old SQL schema (column names, types). Use `TIMESTAMPTZ` → `pa.timestamp('us', tz='UTC')`. `UUID` → `pa.string()` (Parquet has no native UUID; VIEW casts it back with `CAST(sim_id AS UUID)`).

### Phase 4 — Migration command (serial)

- `hmp migrate [--workspace PATH] [--dry-run]`
- Opens an existing `.duckdb`, detects rows in the three tables, groups by `sim_id`, writes one Parquet file per sim, verifies row counts match, then drops the SQL tables.
- On any error, leave the SQL tables untouched (no partial drop).
- Idempotent: running twice on the same workspace is a no-op.

### Phase 5 — Parallel test & validation (spawn sub-agents)

- **Sub-agent D** (test-debugger): "Run `pytest tests/unit/ tests/regression/fast/ -n auto -v`. Compare failures against the baseline `/tmp/baseline_unit.log` and `/tmp/baseline_fast.log`. For each new failure, diagnose and fix (in-process — you can write code). For each baseline failure still present, ignore."
- **Sub-agent E** (test-debugger): "Run `pytest tests/regression/extensive/ -n auto -v` in the background. Report failures."
- **Sub-agent F** (general-purpose): "Run every case in `validation_cases/` end-to-end and confirm reports match baseline. Use `python -m validation_cases.run_cases --solver modflownwt --regime steady --no-show` and equivalents for other solvers/regimes. If outputs differ beyond numerical noise, diagnose."

Do not regenerate goldens until all three sub-agents report clean.

### Phase 6 — Golden regeneration & final tests (serial)

- Manually inspect 2–3 Parquet files produced by recent simulation tests. Confirm schemas, row counts, sample values.
- Regenerate goldens: `hmp test regression --update-goldens`.
- Re-run full suite one last time. All green required.

### Phase 7 — Documentation & commit (serial)

- Write the four `.md` deliverables listed in section 3.3.
- Update `CLAUDE.md`.
- Write `CHANGELOG.md` entry.
- Commit incrementally on `dev-database`. **Aim for atomic, meaningful commits — not one-liner spam.** A good commit = one coherent change that stands on its own and can be reverted in isolation. Rough guidance: expect roughly 8–15 commits for the whole refactor, not 50. Group small related edits (e.g. adding a helper + its first two call sites) into one commit; split unrelated changes (e.g. the retry decorator and the Parquet write path) into separate commits.
- **Commit message format, strict** — `[XXX] - YYY`
  - `XXX` = the file or folder being touched (lowercase, short). Examples: `[catalog]`, `[run]`, `[catalog_schema]`, `[tests/unit/results]`, `[docs/developers]`, `[cli/migrate]`.
  - `YYY` = a few words of simple scientific/technical English describing what was done. Examples: `move timeseries write path to parquet`, `add lock retry decorator`, `create view over hive-partitioned parquet`, `regenerate fast regression goldens`.
  - Complete examples, matching the repo's existing style: `[catalog] - move timeseries write to parquet`, `[catalog_schema] - add parquet views`, `[tests] - add concurrent write test`, `[docs] - document lakehouse migration`.
- **Never add a `Co-Authored-By:` trailer or any co-author attribution.** Single-author commits only.
- Do not use `--amend` on prior commits. Make new commits.

**Do not push. Do not open a PR. Do not create any branch.** Stop at the final local commit on `dev-database`.

---

## 6. Permitted improvements (only if cheap & safe)

You may (not must) improve:

- **Inefficient row-by-row INSERTs** elsewhere in `catalog.py` — convert to DataFrame-backed inserts.
- **Missing `busy_timeout`** or equivalent on the DuckDB connection — the retry decorator is the primary fix, but adding a sane connection-level timeout is also welcome.
- **`ensure_schema` idempotency** — harden against partial states left by a crashed migration.
- **`hmp doctor` output clarity** around the new layout.

Do not go beyond the refactor scope. No drive-by renames, no unrelated cleanups, no dependency bumps.

---

## 7. Code style and output quality

The user is a French scientific developer reading code and docs written in English. Keep the writing and the code grounded and practical. Do not produce "AI-flavored" prose or heavy decoration.

**Docstrings and comments**
- English, natural and simple. Short technical sentences that a non-native reader can parse on a first read.
- Scientific/technical vocabulary is fine and expected; marketing-flavored adjectives are not. No "elegantly", "seamlessly", "leverage", "utilize", "robust and scalable", "cutting-edge".
- State what the function does and the contract (inputs, outputs, side effects). Do not restate what the code already says line by line.
- Default to no comment. Add one only when the *why* is non-obvious: a hidden constraint, a workaround, an invariant that is not visible from the code. Never add a comment to label a section of code.

**Formatting**
- **No em-dashes** (`—`). Use a comma, a period, or parentheses. Hyphens (`-`) in compound words are fine.
- No decorative separators inside code or docstrings: no `# =====`, no `# -----`, no banner comments. The file structure and imports speak for themselves.
- No trailing ASCII art, no emoji in code or docstrings, no "TL;DR" sections inside docstrings.
- Keep module-level docstrings short: one paragraph stating the module's purpose, optionally a short list of public entry points. No tutorial-length docstrings.

**Naming and structure**
- Names describe the thing, not the history. Avoid `new_*`, `v2_*`, `final_*` in committed code.
- Do not introduce helper layers or abstractions that the refactor does not need. Three similar lines is better than a premature abstraction.
- Do not add defensive error handling for conditions that cannot occur given internal invariants. Validate at external boundaries only.

**Markdown files** (the `.md` deliverables)
- Same rules: plain English, simple sentences, no em-dashes, minimal decoration.
- Headings as structure. Short paragraphs. Bulleted lists where they help, not systematically.
- No horizontal rules every two lines, no emoji banners, no "Congratulations!" paragraphs.

**Rough self-check before each commit**: re-read what you wrote. If a paragraph sounds like a blog post, rewrite it as a lab notebook entry.

---

## 8. Success criteria (the Definition of Done)

All of the following must hold, independently verified:

1. `pytest tests/unit/ tests/regression/fast/ -n auto` green.
2. `pytest tests/regression/extensive/ -n auto` green (may be slow; parallelize).
3. Every `validation_cases/` scenario produces reports numerically identical to baseline (tolerance 1e-10 on metrics, bit-for-bit on `Run.timeseries` output).
4. Manual smoke test: start from a fresh workspace, `hmp new`, `hmp run` on `examples/projects/02_nancon_watershed/project.toml` (or equivalent), `hmp display`, confirm a figure is produced and looks reasonable.
5. Concurrent-write test: `tests/unit/results/test_concurrent_writes.py` passes with 8 parallel workers.
6. Migration test: starting from a legacy workspace (can be built on the fly by the test), `hmp migrate` completes, VIEW returns the same rows, Parquet files exist, `timeseries` table no longer in DuckDB.
7. `hmp doctor` reports no errors on a migrated workspace.
8. All four `.md` docs written, `CLAUDE.md` updated, `CHANGELOG.md` entry present.
9. `git status` shows a clean working tree after the final commit. `git log --oneline dev-database ^origin/dev-database` shows a coherent series of new local commits ahead of the remote.
10. **No push, no new branch.** Verify with `git branch --show-current` (must still be `dev-database`) and `git rev-parse --abbrev-ref HEAD@{upstream}` (must still point to the original upstream, with local commits ahead but nothing pushed).

---

## 9. Rollback plan

You are committing directly on `dev-database`, so rollback = reverting specific commits, never destroying the branch.

- Commit incrementally and **frequently** (one commit per logical step, not one commit per phase) so that `git revert <sha>` is a precise tool if a step turns out wrong.
- If a full rollback is needed: `git revert <first_refactor_sha>..HEAD` to produce inverse commits. **Never** `git reset --hard` on `dev-database` — it could destroy prior local work that was not yet pushed.
- `rm -rf simulations/*/timeseries.parquet simulations/*/budgets.parquet simulations/*/mass_balance.parquet` if any testing left orphans in a real workspace. But you should be working in `/tmp/hydromodpy_tests/` per the CLAUDE.md convention.

**Do not** touch `master`. **Do not** force-push anything, anywhere.

---

## 10. When to stop and ask the user

Stop and leave a message in the final commit + a top-level `STATUS.md` file at the repo root if:

- A baseline test is already failing before your changes and you are unsure whether to fix it.
- A validation case produces outputs that differ from baseline by more than numerical noise and you cannot identify a deterministic cause.
- The workspace layout rename (`simulations/<uuid>.zarr/` → `simulations/<uuid>/data.zarr/`) would break `examples/` or `validation_cases/` in ways that require substantive code changes beyond this refactor. In that case fall back to the alternative layout mentioned in section 4 and document the decision.
- Any hard invariant from section 2 appears impossible to preserve.

---

## 11. One-line summary to remember

> Move three big append-only tables from a shared DuckDB file into per-sim hive-partitioned Parquet directories, keep DuckDB as the index + VIEW layer so every caller sees the exact same surface, add retry on lock to the remaining DuckDB writes, and prove it with the existing test suite.

Good luck.
