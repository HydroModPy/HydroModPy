# `hydromodpy/core`

The kernel leaf. Every other layer may import `core`, and `core` imports no
sibling layer, not even under `TYPE_CHECKING`. It holds what several layers
need and none should own: the base of every config model, units, workspace and
path rules, runtime state, I/O primitives, the typed exceptions, and a few
numerical kernels (efficiency metrics, descent on a mesh) that two layers must
compute the same way. This file is the map of the package: what each part
answers, the import rule, and where to add what.

## Parts

### Configuration kit

| part | answers |
|---|---|
| `config_kit/` | what do all config models share? `HydroModelBase` (`extra="forbid"`, `validate_assignment=True`), the `Profile` enum (`USER`, `DEV`, `EXPERT`) and its introspection, the `[[export]]` request (`export_spec.py`), the persistence switch (`persistence.py`), the `[mesh_input]` contract, the calibrable-field marker, shared validators and constrained types, the registry of root sections derived from the root model, and the protocol that lets `core` reach the root config without importing it |
| `units/` | `Annotated` unit aliases backed by pydantic-pint: `Length`, `Area`, `Volume`, `Time`, `FlowRate`, `Velocity`, `HydraulicConductivity`, `SpecificStorage`, `SpecificYield`, `Dimensionless`, and fixed-unit variants. A bare number is read in canonical SI; a string such as `"0.36 m/h"` converts |
| `toml_io/` | reading and writing TOML for every config layer: the `base_config` loader (`loader.py`), merges, path resolution, the commented template generator, the round-trip writer, and the map from a Pydantic error back to a TOML line |
| `tracking/` | which files does a config read? The `InputFile` annotation, `TrackedFileEntry` and the `collect_input_files` walker, which feed the reproducibility manifest |

### Workspace, state and paths

| part | answers |
|---|---|
| `workspace/` | where does a project live? `WorkspaceConfig` and its four-branch resolution (explicit `[workspace]` keys, `HMP_WORKSPACE`, the scaffold `<workspace>/projects/<name>/`, then the project folder itself, in that order), the `Workspace` runtime object, the path registry, and a best-effort lookup of the workspace root (`resolve.py`) |
| `state/` | runtime registries shared by the launcher and the execution: `ExecutionRegistry`, `WorkflowContext`, `LoadedDataContext`, `SetupContext`; the path helpers of a project (`paths.py`: `.hmp/index.duckdb`, `runs/`, per-run scratch, the cache folder `HMP_CACHE_HOME`); the global index of the machine (`global_index.py`) |
| `contracts/` | the neutral runtime contracts several layers implement: workflow steps, solver registry and model protocols, observables, the data cache backend, ids |
| `time/` | the simulation time window, period aggregation, steady-state initialisation, and `selection.py`, the one date-to-period resolver that figures and exports share. `time/README.md` is its map |
| `migrations/` | the schema migration runner shared by every DuckDB component (catalog, global index, workspace cache): `ensure_schema`, backups before a migration |

### I/O, logging and process

| part | answers |
|---|---|
| `io/` | low-level I/O: deterministic JSON (`json_dumps`, `json_loads`), one `HTTPClient` for the data sources, raster, vector and GeoParquet writers, the canonical Parquet options, CRS helpers, the PROJ bootstrap, atomic file replacement, and the single open point of every DuckDB file with its lock retry (`db_retry.py`) |
| `logging.py`, `progress.py`, `progress_ndjson.py` | the console and file logging policy (`LogManager`, `get_logger`, verbosity), the live progress display, and the NDJSON progress sink |
| `interrupts.py` | `terminate_as_interrupt`: SIGTERM raises like SIGINT, so a run closes its session |
| `bootstrap_hook.py` | `ensure_bootstrapped`: lazy trigger of the root bootstrap, so a layer never imports the root module |
| `exceptions.py` | the typed exception hierarchy the CLI maps to exit codes |
| `auth/` | who acts? `AuthBackend` protocol and `LocalAuthBackend` (reads `HMP_USER`, then `USER` or `USERNAME`, then the system user; allows every read and write). `get_auth_backend` reads `HMP_AUTH_BACKEND` and refuses an unknown name with a `ValueError`. The audit trail (`results/catalog/audit.py`) and the privacy purge (`cli/_workers/privacy.py`) resolve the actor through it |
| `version.py`, `licensing.py`, `rng.py` | the version string, the SPDX token written when nobody declared a licence, and the seed manager |

### Numerical kernels and shared constants

| part | answers |
|---|---|
| `metrics.py` | the goodness-of-fit metrics every layer uses, in pure NumPy: `align`, `nse`, `log_nse`, `kge`, `rmse`, `mae`, `bias`, `pbias`, `correlation`, and the delta and seasonal variants (`nse_delta`, `kge_delta`, `nse_seasonal`) |
| `descent.py`, `depression_filling.py`, `topographic_distance.py` | the descent D, the surface on which every cell of the model top drains (computed on a copy; the solver keeps reading the top), the priority-flood filling, and the downslope distance measured on a receiver graph. The network criterion does not read D: `stream_geometry.py` fills its own copy of the top and builds its own graph |
| `bed_regularization.py` | least-change regularisation of a channel bed on its drainage tree (isotonic regression) |
| `stream_network.py`, `stream_extent.py`, `stream_geometry.py`, `stream_heads.py`, `stream_recharge.py`, `stream_criterion_defaults.py` | the stream-network criterion, written once because calibration scores it per trial and `results` redraws it from a finished run: what counts as a simulated stream, when a cell flows, the static geometry of the comparison, the mapped network drawn from its heads, the recharge the criterion divides by, and its numeric defaults |
| `field_routing.py`, `field_precision.py`, `grid_reference.py`, `nodata.py`, `solver_diagnostics.py`, `administrative_france.py` | pure helpers for drain budgets and mesh routing, the storage precision of field arrays (float32 with a rounded mantissa), the plain geometric description of a solver grid, the nodata sentinels, the names of persisted solver diagnostic files, and the registry of French administrative region names |

`hydromodpy.core` itself exposes lazily `Workspace`, `WorkspaceConfig`,
`WorkspacePathRegistry`, `ExecutionRegistry`, `WorkflowContext`,
`LoadedDataContext`, `SetupContext` and `ResolvedSimulationTimeWindow`.

## Import rules

`core` imports only `core`. The layer matrix
(`tests/unit/architecture/layer_matrix.yaml`) gives it one allowed target, itself,
and the layer test counts every import: module level, inside a function, under
`TYPE_CHECKING`. Every other layer lists `core` among its targets.

A kernel module that needs something from a higher layer takes it through a
protocol defined in `core` and wired at bootstrap: the root config
(`config_kit/root_config_protocol.py`), the dynamic flow examples
(`toml_io/dynamic_examples_protocol.py`), the data cache backend
(`contracts/data_cache_backend.py`). Any new sibling edge is a regression unless
the YAML is updated with its rationale.

Keep `core` light: importing `hydromodpy.core` does not load the configuration
or the data stack.

## Where to add what

1. **A helper used by one layer only.** In that layer, not in `core`. A helper
   moves to `core` when a second layer needs it and the layer matrix forbids one
   importing the other.
2. **A unit alias.** In `units/`, with its canonical unit; configs then annotate
   a field with it.
3. **A field visibility rule.** `config_kit/profile.py` and `introspect.py`.
4. **An exception the CLI should map to an exit code.** A class in
   `exceptions.py`, then an entry in `exit_code_for` of `cli/helpers.py`.
5. **An auth backend.** A class that satisfies `AuthBackend` and its name in the
   table of `auth/selection.py`.
6. **A DuckDB schema change.** A new numbered `.sql` file in the `migrations/`
   folder of the component (for the global index: `state/migrations/`).
7. **A metric.** `metrics.py`, pure NumPy, JSON-friendly floats.

## Reading path

1. `units/types.py` for the unit aliases used in every model.
2. `config_kit/profile.py`, `introspect.py` for the visibility model.
3. `workspace/config.py`, then `state/paths.py` for where things live.
4. `state/__init__.py` for the cross-layer contexts.
5. `metrics.py` for the metric contract.
