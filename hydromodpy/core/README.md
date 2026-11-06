# `hydromodpy/core`

The kernel leaf. Every other layer may import `core`, and `core` imports no sibling layer, not even
under `TYPE_CHECKING`. It holds what several layers need and none should own: the base of every config
model, units, workspace and path rules, runtime state, I/O primitives, the typed exceptions, and a few
numerical kernels (scores and the defaults of the stream criterion) that two layers must compute the
same way. The root keeps only the words every layer shares: the exceptions, the logger, the version, the
step names, the table words, the licence token. Everything else sits in a sub-package that answers one
question, and each sub-package has its own `README.md`.

## Root modules

| module | answers |
|---|---|
| `exceptions.py` | what can go wrong, by name? The typed `HydroModPyError` hierarchy the CLI maps to exit codes |
| `logging.py` | how loud is a run? The console and file logging policy (`LogManager`, `get_logger`, verbosity) |
| `version.py` | which release is this? The one source of `__version__` |
| `pipeline_steps.py` | how are the steps of a simulation called? `STEP_NAMES`, shared by every layer |
| `scope.py` | which words do the stored tables share? `catchment`, `domain`, `observed`, `simulated`, and the checks on station and zone names |
| `licensing.py` | which licence is written when nobody declared one? `UNDETERMINED_LICENSE` |
| `old_members.py` | what did this name become? The members that left before the first stable version, each refused with its new name (`refuse_old_member`) |
| `code_fingerprint.py` | which code computes? `code_fingerprint()`: one digest per layer that changes a number, the same from Python 3.11 to 3.13. The identity of a run and the calibration cache read it |
| `__init__.py` | lazily exposes `WorkspaceConfig`, `WorkspacePathRegistry`, `ExecutionRegistry`, `WorkflowContext`, `LoadedDataContext`, `SetupContext` and `ResolvedSimulationTimeWindow` |

## Sub-packages

| folder | answers |
|---|---|
| `config_kit/` | what do all config models share? The strict base, the `Profile` visibility, the calibrable marker, the persistence switch, what a config was given versus its defaults, the root sections |
| `units/` | what unit is this number in? Pint registry, annotated aliases (`Length`, `HydraulicConductivity`, ...), conversions to SI, physical bounds, axis labels |
| `toml_io/` | how is a TOML config read, merged and written? Loader with `base_config`, overrides, path resolution, commented templates, error lines |
| `tracking/` | which files does a config read? `InputFile` and the walker that feeds the manifest |
| `workspace/` | where does a workspace live, and what are its paths? `WorkspaceConfig`, `WorkspaceLayout`, the path registry, `workspace.toml` |
| `state/` | where do things live in a project, and what does a run carry between steps? Path helpers, run contexts, the seed manager |
| `site/` | what is a site? `SiteConfig`, `SiteRow`, the site fingerprint, the gauge rule |
| `payload/` | what does a package install, and where? `INSTALL.toml` and the one installer |
| `contracts/` | what do two layers agree on without importing each other? Protocols, solver and cache contracts |
| `time/` | when does a run start, stop and step? The time window, period aggregation, date-to-period selection (`time/README.md`) |
| `io/` | how do I read, write and fetch files safely? JSON, rasters, vectors, Parquet, HTTP, DuckDB open, atomic replace |
| `runtime/` | how does the process behave? `HMP_*` variables, SIGTERM as an interrupt, the lazy bootstrap trigger |
| `console/` | what does a run show while it works? Live progress and its NDJSON sink |
| `budget/` | what sign has a budget flux, and which terms does a run keep? |
| `scoring/` | how well does a simulation match observations? Efficiency metrics, the cost margin and the numeric defaults of the stream-network criterion |
| `plugin_registry.py` | how does an id resolve to a class? One registry for the evaluator, forward-model, terrain-engine and mesh-engine plugins |
| `fields/` | how is a grid or a field array described? Nodata, grid reference, vertical column, storage precision |

## What left core

`bed_regularization` is now in `spatial/geographic/core/`; `solver_diagnostics` is
`solver/boussinesq/runtimes/diagnostic_files.py`; `administrative_france` is
`spatial/administrative/regions.py`; `units/udunits` is `results/storage/udunits.py`;
`config_kit/export_spec` is `results/exporters/export_spec.py`; `migrations` is
`data/registry/migrations/`. The drainage kernels (receiver graph, depression filling, descent D,
downslope distance) are in `spatial/drainage/`, the mean recharge of the stream criterion is in
`spatial/forcing/recharge_rates.py`, and the rest of the stream criterion is in `results/derive/stream/`.

## Import rules

`core` imports only `core`. The layer matrix (`tests/unit/architecture/layer_matrix.yaml`) gives it one
allowed target, itself, and the layer test counts every import: module level, inside a function, under
`TYPE_CHECKING`. Every other layer lists `core` among its targets.

A kernel module that needs something from a higher layer takes it through a protocol defined in `core`
and wired at bootstrap: the root config (`config_kit/root_config_protocol.py`), the dynamic flow
examples (`toml_io/dynamic_examples_protocol.py`), the data cache backend
(`contracts/data_cache_backend.py`), the solver registry (`contracts/solver_registry.py`) and the
bootstrap itself (`runtime/bootstrap_hook.py`). A new sibling edge is a regression unless the YAML is
updated with its rationale.

Keep `core` light: importing `hydromodpy.core` does not load the configuration or the data stack.

## Where to add what

1. A helper used by one layer only goes in that layer. It moves to `core` when a second layer needs it and the layer matrix forbids one importing the other.
2. A word every layer shares (a step name, a table word) goes in a root module. Anything else goes in the sub-package that answers its question, never in the root.
3. A unit alias goes in `units/types.py`, with its canonical unit.
4. A field visibility rule goes in `config_kit/profile.py` and `config_kit/introspect.py`.
5. An exception the CLI should map to an exit code goes in `exceptions.py`, then in `exit_code_for` of `hydromodpy/cli/helpers.py`.
6. A DuckDB schema change is a new numbered `.sql` file in the `migrations/` folder of the component (data cache: `data/registry/migrations/`). The project index is never migrated, a schema change there is a rebuild (`results/catalog/index_schema.py`).
7. A metric goes in `scoring/metrics.py`, pure NumPy, JSON-friendly floats.

## Reading path

1. `units/types.py` for the unit aliases used in every model.
2. `config_kit/profile.py` and `config_kit/introspect.py` for the visibility model.
3. `workspace/config.py`, then `state/layout.py` for where things live.
4. `state/run_state.py` for the cross-layer contexts.
5. `scoring/metrics.py` for the metric contract.
