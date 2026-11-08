# `hydromodpy/solver`

The numerical backends. A `[solver]` table picks the flow backend, and a
`[[simulation.process]]` entry names the solvers each process runs. This
package holds the adapters that turn a built `Flow` or `Transport` into a
backend run, the extractors that read the backend's files into the results
store, and the registry that pairs a `<process_type>_<name>` key with
each. Three flow backends ship: MODFLOW 6, MODFLOW-NWT and Boussinesq, plus
the transport tools that go with them.
This file is the map of the package: what each part answers, the import
rules, how a run reaches a backend, and where to add what.

## Parts

| part | answers |
|---|---|
| `base/` | what every backend shares: the `SolverAdapter` Protocol (`adapter_protocol.py`), the registries of adapters and extractors with their entry-point groups (`registry.py`), the twelve attributes a backend declares, `SolverConfig` (`solver_config.py`, the `[solver]` table), the `[simulation]`, `[simulation.results]` and `[observation]` tables, the plan, the planner and the runner (`plan.py`, `planner.py`, `runner.py`), the drain conductance, the observable contracts (`observables.py`), cell lookup by coordinates, scratch cleanup |
| `modflow_grid/` | the grid description the MODFLOW family reads: `SolverMesh` for structured and unstructured meshes and its DISV arguments, `SolverGridContext`, spatial and temporal discretization builders, the `sgrid` table of the top sampling (`sgrid_config.py`) |
| `modflow_common/` | what MODFLOW 6 and MODFLOW-NWT do the same way: binary resolution and download, budget names, calibration readers, property mapping on the solver mesh, discharge routing, descent of the mesh, the flow-adapter lifecycle (`flow_adapter_helpers.py`) |
| `modflow6/` | MODFLOW 6 through FloPy: `build.py` (package wiring), `builders/` (one module per package: CHD and DRN, recharge and EVT, wells, LAK, SFR, MVR, HFB, solver options), `run.py`, `api/` (libmf6, in process), `adapters/` (flow, GWT transport, PRT), `extractors/`, `support/`, `modflow6_config.py` |
| `modflow_nwt/` | MODFLOW-NWT through FloPy: `nwt/` (solver, pre-processing, payload builders, `nwt_config.py`), `adapters/` (flow, MODPATH, MT3DMS), `modpath/`, `mt3dms/`, `extractors/` |
| `boussinesq/` | the in-house unstructured-mesh Boussinesq solver; its own map is `boussinesq/README.md` |

Each folder has its own README. Extractors sit beside the adapters of each backend, in `extractors/`. An
extractor carries `process_type`, `solver_name` and an
`extract(sim_id, solver_output_dir, store, ...)` method. Its category is read on the adapter.

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives solver `core`, `schema`,
`catchment`, `mesh`, `model`, `results` and itself. No `solver_layout.yaml` orders the parts. The shape is:

1. Backends do not import each other. `modflow6`, `modflow_nwt` and `boussinesq`
   each import `base`, and, for the first two, `modflow_common` and
   `modflow_grid`. No gate checks the independence; the
   import scanner of `tools/audit/build_graph.py` shows it holds.
2. `modflow_common` and `modflow_grid` import `base` and each other, never a
   backend.
3. `base/registry.py` names every built-in adapter and extractor by a dotted
   path in `_BUILTIN_PATHS` and `_BUILTIN_EXTRACTOR_PATHS` and imports it on
   first lookup, through the engine of `core/plugin_registry.py`. Loading `hydromodpy.solver.base.plan` therefore loads no backend.
4. A private name read inside a backend package is declared in that package:
   `tests/unit/architecture/test_solver_private_attributes.py` checks it.
5. A layer above `solver` imports the registry from `solver/base/registry.py`
   and calls `solvers.get`, `solvers.create` and `solvers.names`. The runner in
   `base/runner.py` imports no backend, and `calibration` reaches the solvers
   through `solver.base` only (see `calibration/README.md`).

Who imports solver: `workflow`, `config`, `calibration`, `cli`, `project` and
the package root.

## Tree

```
hydromodpy/solver/
  __init__.py
  base/          adapter_protocol.py  registry.py  solver_config.py  plan.py  planner.py  runner.py ...
  modflow_grid/  solver_mesh.py  discretization_spatial.py  top_sampling.py  discretization_temporal.py  sgrid_config.py
  modflow_common/  flow_adapter_helpers.py  binaries.py   property_mapping.py ...
  modflow6/      build.py  run.py  builders/  api/  adapters/  extractors/  support/
  modflow_nwt/   nwt/  adapters/  extractors/  modpath/  mt3dms/
  boussinesq/    boussinesq.py  catalog.py  mesh.py  assembly/  runtimes/  ... (see its README)
```

## How a run reaches a backend

1. **Choose.** `[solver] backend` selects the flow backend (`modflow6`,
   `modflow_nwt`, `boussinesq`, or `custom` with a registered name).
   `SolverConfig.validate_registry` refuses a name the registry does not know.
2. **Plan.** The planner (`base/planner.py`) reads the `requires` attribute of the
   backend class, `solvers.get(process_type, solver).requires`, to bind a transport run
   to an earlier flow run.
3. **Look up.** The runner calls `solvers.create(process_type, solver)`:
   the registry imports the built-in class, or a plugin, and returns an instance.
4. **Run.** `adapter.validate(ctx)`, then `adapter.execute(ctx)`, which builds
   the backend model from the `Flow` (or `Transport`) of the context, writes
   its files in the scratch folder and returns a `RunExecutionResult`. After
   extraction, `adapter.cleanup(ctx)`.
5. **Extract.** `extractors.create(process_type, solver)` returns the
   extractor that reads the scratch files into the results store.
6. **Observe.** `adapter.extract_observables(ctx, store, requests)` serves a
   calibration trial from the scratch folder. An adapter that cannot produce a
   requested observable raises `ObservableNotAvailableError`.

What a backend can do is declared on its adapter class, in the twelve attributes of
`base/README.md`. `writes` lists what it stores, `supports` the traits of the `Model`
it honours and `category` how it resolves space. Two copies remain and a contract test holds
each equal to the adapters: the `supported_backends` column of the boundary table, and the
category table of `results/catalog/constants.py` that the index reads when a manifest has none.

## Where to add what

| to add | where |
|---|---|
| a solver, in tree | a package with its adapter and extractor, its adapter class with the twelve attributes, one entry in each of `_BUILTIN_PATHS` and `_BUILTIN_EXTRACTOR_PATHS`, a member of the `[solver]` backend union in `base/solver_config.py`; see `docs/source/contribute/architecture/how-to/add-a-solver.rst` |
| a solver, out of tree | an adapter class on the `hydromodpy.solver` entry-point group and an extractor on `hydromodpy.solver.extractor`; the entry-point name is `<process_type>_<name>`, and the registry compares it with the joined attributes of the loaded class, so a name that holds an underscore stays whole |
| a MODFLOW 6 package | a module in `modflow6/builders/`, called from `modflow6/build.py`; builders stay independent of each other and couple through `builders/mvr.py` records |
| a process type | a process model in `base/simulation_config.py` joined to `SimulationProcessConfig`, its requirements in the `requires` attribute of the backends, an `ensure_*` function and an entry in the two tables of `base/runner.py` (`_REQUIRED_COMPONENTS_BY_PROCESS`, `_COMPONENT_ENSURERS`) |
| a callback around a run | a field of `ProcessCallbacks` and its call in `SimulationRunner` |
| something both MODFLOW backends do | `modflow_common/`, or `modflow_grid/` for a grid |
| a boundary kind | `boundaries/boundary_condition_registry.py` in `model`, then its package in each backend |
| a backend option | the field on `modflow6_config.py`, `nwt/nwt_config.py` or the Boussinesq runtime knobs of `FlowConfig`, with a profile and a description |
| an observable a backend can serve | its reader in the backend's extractor or `modflow_common/observable_extraction.py`, and its state in `base/observables.py` |
