# Audit: simulation recording, listing, navigation, export, deletion (2026-06-11)

Multi-agent audit (40 agents: 6 subsystem mappers + live CLI walkthrough on
`examples/projects/19_cheze_reservoir`, 4 expert personas, adversarial verification of
every finding against the code, completeness pass). 28/28 findings confirmed, 0 refuted.

## Verdict

The user impression ("hard to navigate, meaningless hash ids") is justified, but the
data architecture underneath is sound. Three compounding defaults destroy the UX:

1. **Identity**: `sim_id` is a fresh `uuid4` per run (`workflow/steps/prepare_solver/dispatch.py:209`);
   the visible `hash8` is just its first 8 hex chars (`results/catalog/storage_paths.py:57-59`).
   The default run name is the config TOML stem (`workflow/steps/setup.py:398-405`), so every
   re-run collides, and the default `on_collision="replace"` NULLs the previous run's name
   (`results/catalog/registration.py:226-230`). A 20-round calibration campaign ends with
   19 `(no name)` rows addressable only by UUID. The `version` mode (`.v2` suffix) already
   exists (`registration.py:85-99,239-246`) and is simply not the default.
2. **Navigation primitives missing**: no `@latest` token, no date column in `catalog ls`,
   three divergent reference resolvers (discovery vs viz gallery vs dead `helpers.resolve_sim_id`),
   `-w/--workspace` has three incompatible semantics across sibling verbs under identical help text.
3. **Read paths mutate**: `SimulationCatalog.__init__` opens DuckDB read-write, runs migrations,
   and rewrites 10 views on every open (`results/catalog/facade.py:99-139`); `ls`/`show` go
   through it. Inspecting an archived project modifies it (mtime + WAL observed).

## What is solid (keep)

- Full provenance: config snapshot + sha256 `config_hash`, `runs_environment` (git commit,
  solver binary sha256, rng seed), per-input array fingerprints (`provenance.parquet`),
  hash-chained audit log.
- Atomic registration with staged Zarr promotion.
- Git-style resolver: full UUID, hex prefix >= 4 chars, exact name
  (`results/catalog/discovery.py:57-128`), `AmbiguousReferenceError` on multi-match.
- Python facade ergonomics: `cat["2b7a"] -> Run`, `SimulationGroup` pivots.
- Portable `.hmp` archive (tar.zst: manifest SHA-256, DuckDB snapshot, zarr.zip, parquet,
  RO-Crate) with checksum-verified import (`results/.../hmp_package.py:528-617,741-873`).
- Recovery machinery already present: pre-migration backups under `<project>/.hmp/backups/`
  (MAX_BACKUPS=5, restore-on-failure, `core/migrations/auto_boot.py:210-260`),
  `HMP_AUTO_MIGRATE=0` opt-out, `hmp doctor --restore-backup <ts>`.

## What is broken (confirmed, evidence)

- `hmp catalog ls --format json` crashes: raw UUID column fed to `DataFrame.to_json`
  (UnicodeDecodeError, `cli/commands/catalog/ls.py:79-80`, reproduced on the real catalog,
  exit 1). CSV dumps ~50 columns incl. 13 KB config blobs (31 KB for one row). Table view
  has no `created_at`. Empty-filter vs empty-catalog indistinguishable (`ls.py:75-77`).
- Concurrency: a run holds the rw DuckDB connection for the whole solve (opened
  `dispatch.py:205`, closed `workflow/steps/export.py:103`; 557 s in the example), heartbeat
  every 30 s. DuckDB rw lock excludes even read-only readers cross-process (empirically
  verified, duckdb 1.5.3): concurrent `ls`/`show` retry ~44-54 s (`core/io/db_retry.py:26-89`)
  then exit 1 with the raw lock message; `catalog query` fails immediately.
- `hmp catalog gc` applies destructive cleanup by default, `--dry-run` is opt-in
  (`gc.py:14-26`), inverse of `workspace clean` and `audit prune`. Flips `running` sims to
  `failed` after a hard-coded 10 min cutoff without confirmation (`cli/_workers/catalog.py:414,548-565`).
- `delete` confirms on the raw unresolved reference (`delete.py:50`) before resolution
  (`cli/_workers/catalog.py:299`), then cascades 12 tables in one transaction, commits, then
  `rmtree` (`results/catalog/lifecycle.py:287-319`): a failed rmtree leaves a permanent orphan
  store; no trash, no undo; `--keep-storage` is one-way (no adopt/reindex path).
- Metadata is write-only: tags inserted only at registration (`registration.py:361-366`),
  `remove_tag` exists but no `add_tag`; internal `write_tags` calls no-op silently
  (`calibration/.../trial.py:598`); no CLI tag/note verb, no `--tag/--status` filters,
  no pin/protect against delete/cleanup.
- `config_hash` is dead weight: computed, stored, indexed (`0001_initial.sql:240`) but never
  queried (no dedup, no reuse, excluded from `find()` vocabulary and all CLI flags).
- Error UX: `SimulationNotFoundError` suggests `hmp list <project>` which does not exist
  (`discovery.py:126-128`), renders with doubled quotes (KeyError subclass), prefix < 4 chars
  reported as plain not-found, ambiguous/absent share exit code 10.
- `started_at` declared (`0001_initial.sql:216`) but never written; `created_at` is the proxy.
- Export story split: the real portable archive lives in `hmp data export-package` while
  `hmp data export --format hmp` writes only a RO-Crate sidecar (`data/export.py:327-331`),
  yet the engine already routes `ExportFormat.hmp` to `export_package` (`reads.py:372-373`).
- Listing does not scale: per-project rw open + 10 view DDL per invocation, `SELECT s.*`
  incl. config blobs for every row, pandas-side filters, `--limit` applied after concat
  (`cli/_workers/catalog.py:82-103`, `reads.py:104-115`). 100 sims ~ 2.6 MB JSON moved per `ls`.

## Prioritized roadmap

Quick wins / critical:
- **P1** Fix `catalog ls`: CAST sim_id AS VARCHAR + stable column set in the worker, clean
  JSON (`json.dumps(default=str)`), `created_at` column in the table, distinct
  "no match" vs "empty catalog" messages, JSON round-trip regression test.
- **P2** Invert gc default: print plan + exit 0 by default, execute under `--apply`
  (mirror `audit prune`), add `--stale-minutes N` (default 10). Update `docs/source/cli/catalog.rst:47-53`.
- **P3** Default `on_collision="version"` (change together: `config.py:359-370`,
  `registration.py:171`, `dispatch.py:217`) + `--on-collision {version,replace,fail}` on `hmp run`.
  Seed the API `run_NNNN` counter from the catalog instead of instance state (`runner.py:184-186`).
- **P4** Resolve the reference BEFORE the delete prompt; show identity + cost
  ("Delete project_chronicle [2b7a4dd2] project=... completed 2026-06-11, 1.1 GB? [y/N]");
  shared `helpers.confirm_simulation_action`; standardize abort exit on 130.
- **P5** `read_only=True` on `SimulationCatalog.__init__` and `hmp.open` (duckdb read_only,
  skip mkdirs/migrations/views; clear error if schema behind; surface `HMP_AUTO_MIGRATE=0`);
  switch ls/show/viz workers to it. Also shorten rw lock tenure during runs (short-lived
  connections per step), since read_only alone cannot fix inspect-while-running.

Medium term:
- **P6** `@latest` (and `@latest:<project>`, `@best:<metric>`) in `DiscoveryMixin.resolve`;
  reimplement `ProjectRunsAccessor.latest()` on `store.latest()` (currently status-blind
  `iloc[-1]`, `project/accessors.py:67-71`).
- **P7** Single workspace resolver in `_conventions.py` for all catalog verbs; remove the
  silent `~/hydromodpy` fallback; failure message lists probed paths; align gc/vacuum on `-w`.
- **P8** Single reference resolver everywhere (viz gallery has its own startswith matcher,
  `viz.py:71-91`; `helpers.resolve_sim_id` is dead code); fix hint to `hmp catalog ls`;
  make `SimulationNotFoundError` an Exception; explicit "< 4 hex chars" message; distinct
  exit code for ambiguous.
- **P9** Expose the metadata model: `add_tag` (audited) + fix no-op `write_tags` calls;
  `hmp catalog tag <ref> --add/--remove`; `--tag/--status` on `catalog ls`; reserved
  `pinned` tag refused by delete/cleanup without `--force`.
- **P10** Unify export: `hmp data export <ref> -o run.hmp` invokes `catalog.export` (already
  routes to `export_package`); rename sidecar choices `--sidecar {stac,rocrate,prov}`;
  `--list` to stdout; drop the `--resolution` requirement in favor of engine fallback.
- **P11** gc category `orphan_simulation_stores` (diff `simulations/*` vs
  `simulations.storage_basename`, size per orphan, removal under `--apply` only) +
  `hmp catalog adopt` to re-register a `--keep-storage` store. Detection already exists in
  doctor (`storage_diagnostics.py:153-177`) and dev manage (`backend.py:235-297`).

Nice to have:
- **P12** Make `config_hash` useful: add to `find()` vocabulary + `hmp catalog ls --config
  <toml|hash8>`; show hash8 in `catalog show`; opt-in reuse (`hmp run --reuse`) querying
  project+config_hash+completed before minting a uuid and re-solving 557 s.
- **P13** Immutable basename `<project>__<hash8>` for new registrations (human name stays a
  catalog column shown by ls/show); kills rename/replace filesystem desync without a file
  renaming machinery.
- **P14** Paper cuts: write `started_at` in `register_simulation`; show parameter names in
  `catalog show` (K/Sy/Ss lost via `set_index` + `index=False`); handle or reject
  `--format csv` on show; fix the broken SQL example in `query` help (`query.py:26`).

## Method notes

Full raw workflow output (maps, 28 confirmed findings with verdicts, completeness pass):
was at `/tmp/.../wsd9gz9dx.output` (ephemeral). Verification was adversarial: each finding
handed to a skeptic instructed to refute it via code reading; all 28 survived, several with
precision corrections folded in above.
