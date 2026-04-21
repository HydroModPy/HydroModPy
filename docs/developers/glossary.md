# Glossary

Canonical HydroModPy vocabulary. Extracted from
`architecture_cible/13_coherence_globale.md` §3.1. Every other doc, module,
and commit message must use the names on the left — the aliases on the
right are forbidden in new code.

> This glossary is the tiebreaker. If a source file contradicts it, the
> glossary wins and the file is queued for rename.

## Objects

### Project (code label, not a concept)

A free-form string label attached to simulations (`simulations.project`
column in the catalog DuckDB). It **does not** correspond to a folder, a
configuration object, or a facade. The legacy `Project` facade class is
scheduled for removal and replaced by `Simulation` (see below).

### Workspace

Root directory containing one `hydromodpy.duckdb`, one `data/` input cache,
one `simulations/` tree of Zarr stores, and optional `configs/` and
`exports/` subdirectories. A workspace is mutable, locked at the process
level via `WorkspaceLock` (a `filelock` on `hydromodpy.duckdb.lock`), and
represented in code by `hydromodpy.core.workspace.Workspace`.

### Simulation (mutable facade)

- **Canonical name:** `Simulation`
- **Module:** `hydromodpy.simulation.api.Simulation`
- **Role:** programmatic execution facade. Constructed from a config,
  executes via `.run()`, writes into the catalog.
- **Forbidden aliases:** `Project`, `SimulationRunner`, `Launcher`,
  `Pipeline`.

### SimulationView (immutable view)

- **Canonical name:** `SimulationView`
- **Module:** `hydromodpy.results.simulation.SimulationView`
- **Role:** read-only handle returned by `catalog.get(sim_id)`. Exposes
  fields, timeseries, metadata, and `.plot(...)`.
- **Forbidden aliases:** `Simulation` (ambiguous), `SimulationResult`,
  `RunOutput`.

### Run

A single concrete execution instance. Identified by `run_id` (ULID,
lexicographically sortable, generated at submission). A simulation may
accumulate multiple `run_id`s; the `sim_id` is stable across them (see
*identifiers* below).

### Catalog

Top-level term with two distinct roles — always disambiguate.

- `SimulationCatalog` — **output** catalog, backed by
  `workspace/hydromodpy.duckdb`. Module
  `hydromodpy.results.catalog.SimulationCatalog`. Forbidden aliases:
  `ResultsCatalog`, `Catalog`, `SimulationStore`.
- `InputCatalog` — **input** cache, backed by
  `workspace/data/cache.duckdb`. Module
  `hydromodpy.data.cache.InputCatalog`. Forbidden aliases: `DataCatalog`,
  `CacheCatalog`.

### Plan (immutable)

- `SimulationPlan` — resolved, frozen plan for one simulation. Module
  `hydromodpy.simulation.planning.SimulationPlan`. Forbidden aliases:
  `RunPlan`, `ExecutionPlan`.
- `DataLoadPlan` — resolved, frozen plan describing which data managers to
  call. Module `hydromodpy.data.planner.DataLoadPlan`. Forbidden aliases:
  `DataPlan`, `LoadPlan`.
- `ProcessRun` — one entry inside a `SimulationPlan`. Forbidden aliases:
  `RunSpec`, `TaskSpec`.

### Pipeline

- **Canonical name:** `Pipeline`
- **Module:** `hydromodpy.simulation.pipeline.Pipeline`
- **Role:** ordered sequence of `PipelineStep` instances, orchestrating
  a simulation end to end. The word *workflow* is reserved for CLI
  auto-dispatch (`SimulationWorkflow`, `OverviewWorkflow`, ...), not the
  executor.
- **Forbidden aliases:** `Workflow`, `Runner`, `Driver`.

### Step

- **Canonical name:** `PipelineStep`
- **Module:** `hydromodpy.simulation.pipeline.step.PipelineStep`
- **Shape:** Protocol `PipelineStep[TIn, TOut]`. Pure, frozen-dataclass
  inputs and outputs.
- A step is **not** a process (`Flow`, `Transport`): it is one executable
  unit inside the pipeline (`MeshBuildStep`, `SolveStep`, `ExtractStep`).

### Adapter (legacy)

Old name for what is now called `SolverRunner`. In new code **do not use**
`Adapter` for solver integration. The term is retained only in
`simulation/adapters/` paths pending the P06 rename.

### Backend

Implementation-specific engine chosen at runtime. Used in two
orthogonal senses — always qualify:

- *Solver backend* — concrete engine behind a `SolverRunner` (`flopy`,
  `scipy`, `petsc`). Avoid using `Backend` on its own; prefer
  `SolverPlugin` for the registered entry point and `SolverRunner` for the
  Protocol.
- *Display backend* — matplotlib/pyvista renderer selected by
  `BackendManager.configure(backend=...)`.

### Variable

A named, typed input quantity (piezometry, hydrography, geology, climate
timeseries, DEM, ...). Each variable has:

- a Pydantic config model `*_config.py`;
- a manager `*_manager.py` subclassing `BaseVariableManager`, with a
  `load() -> LoadResult` method.

Variables live under `hydromodpy/data/variables/`.

### Manager

A `BaseVariableManager` subclass responsible for loading one variable from
its configured `DataSource`s and producing a normalized `LoadResult`. One
variable → one manager. Managers are stateless beyond their config and
their (injected) `InputCatalog`.

### Source

A `DataSource` Protocol implementation that fetches one kind of data from
one provider (`HubEauPiezometrySource`, `SIM2Source`, `CustomFileSource`,
...). Sources are registered via `@register_source(provider="...",
variable="...")` in `hydromodpy/data/sources/`. A manager may query several
sources; a source may feed several managers.

## Identifiers

### sim_id

Deterministic **UUID v5**,
`uuid5(HYDROMODPY_NAMESPACE, run_fingerprint)`, where
`run_fingerprint = sha256(canonical_config_json + inputs_fingerprints)`.
Identical config + identical inputs → identical `sim_id` (enables
deduplication). Phase 10's mention of UUID v4 is superseded.

### run_id

**ULID**, 26 characters, lexicographically sortable, generated at
submission. Multiple runs may share one `sim_id`.

## Pipeline internals

### PipelineState

- **Canonical name:** `PipelineState`
- **Module:** `hydromodpy.pipeline.state.PipelineState`
- **Shape:** `@dataclass(frozen=True, slots=True)` carrying `run_id`,
  `step_index`, `step_name`, `elapsed_ms`, and an untyped `data` mapping.
- **Role:** the single value that flows between pipeline steps. Steps
  never mutate; they produce a successor via `state.advance(...)`.

### Checkpoint

- **Canonical name:** `CheckpointStore`
- **Module:** `hydromodpy.pipeline.checkpoint.CheckpointStore`
- **Role:** persists `PipelineState` snapshots to
  `<workspace>/.hmp/checkpoints/<run_id>/<step_index>_<step_name>.pkl.zst`
  after each step, enabling resume-after-crash. Falls back to plain
  pickle when `zstandard` is unavailable.
- **Forbidden aliases:** `Snapshot`, `StateCheckpoint`.

### Ledger

- **Canonical name:** `StepsLedger`
- **Module:** `hydromodpy.pipeline.ledger.StepsLedger`
- **Role:** DuckDB-backed log of pipeline step executions, one row per
  `(run_id, step_index)` with status, timestamps, elapsed duration, and
  failure message. Stored at
  `<workspace>/.hmp/checkpoints/steps_ledger.duckdb`.
- **Forbidden aliases:** `StepLog`, `ExecutionLog`.

### DerivedRegistry

- **Canonical name:** `DerivedRegistry`
- **Module:** `hydromodpy.pipeline.derived.DerivedRegistry`
- **Role:** ordered registry of `DerivedComputation` entries evaluated
  by `step_09_derive`. Resolves dependencies via `ordered_names()` so
  downstream derived fields see their prerequisites already written.

### ParamsHashCache

- **Canonical name:** `ParamsHashCache`
- **Module:** `hydromodpy.calibration.cache.ParamsHashCache`
- **Role:** fingerprint-based memoisation used inside the calibration
  loop to deduplicate evaluations of identical parameter vectors within
  one session.

## Config visibility

### Profile (IntEnum)

- **Canonical name:** `Profile`
- **Module:** `hydromodpy.core.config.profile.Profile`
- **Role:** visibility level for a Pydantic config field — one of
  `Profile.USER` (1, physical/project fields), `Profile.DEV` (2,
  tolerances/backends/cache), `Profile.EXPERT` (3, solver internals). A
  field is included in a generated TOML when its profile is less than or
  equal to the requested profile. Declared inside ``Annotated[T, Profile.X]``.

### ParamLevel (legacy)

- **Alias for:** `Profile`
- **Module:** `hydromodpy.core.config.param_level.ParamLevel`
- **Role:** legacy dataclass tag (`ParamLevel("user" | "dev" | "expert")`)
  kept as a v0.6 shim so existing scripts keep working. New code must use
  `Profile`. Slated for removal in v0.7.

## Naming hygiene

- Do not introduce new aliases for concepts already in this glossary.
- When you need a new name, add it here first with a one-line role
  description, then use it in code.
- Renames required by the migration (e.g. `SolverAdapter → SolverRunner`,
  `Geographic → CatchmentDelineation`, `SinkSource → SourceTerm`,
  `ParamSpace → ParameterSpace`, `DataManagersPlanner → DataPlanner`) are
  tracked in `architecture_cible/13_coherence_globale.md` §3.2.
