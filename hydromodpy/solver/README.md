# `hydromodpy/solver`

The numerical backends. `solver.backend` names the flow backend, the table
`[solver.<name>]` holds its settings, and a
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
| `base/` | what every backend shares: the `SolverAdapter` Protocol (`adapter_protocol.py`), the registries of adapters and extractors with their entry-point groups (`registry.py`), the twelve attributes a backend declares, `SolverConfig` (`solver_config.py`, the `[solver]` table), the `[simulation]`, `[simulation.results]` and `[observation]` tables, the plan, the planner and the runner (`plan.py`, `planner.py`, `runner.py`), the rule that chooses `rerun` (`rerun.py`), the drain conductance, the observable contracts (`observables.py`), cell lookup by coordinates, scratch cleanup |
| `modflow_grid/` | the grid description the MODFLOW family reads: `SolverMesh` for structured and unstructured meshes and its DISV arguments, `SolverGridContext`, spatial and temporal discretization builders, the `sgrid` table of the top sampling (`sgrid_config.py`) |
| `modflow_common/` | what MODFLOW 6 and MODFLOW-NWT do the same way: binary resolution and download, budget names, calibration readers, property mapping on the solver mesh, discharge routing, descent of the mesh, the flow-adapter lifecycle (`flow_run.py`) |
| `modflow6/` | MODFLOW 6 through FloPy: `build.py` (package wiring), `builders/` (one module per package: CHD and DRN, recharge and EVT, wells, LAK, SFR, MVR, HFB, solver options), `run.py`, `rerun.py` (a solved model solved again for a new K or Sy), `api/` (libmf6, in process), `adapter.py` (flow), `adapters/` (GWT transport, PRT), `extractors/`, `support/`, `modflow6_config.py` |
| `modflow_nwt/` | MODFLOW-NWT through FloPy: `nwt/` (solver, pre-processing, payload builders, `nwt_config.py`), `adapter.py` (flow), `adapters/` (MODPATH, MT3DMS), `modpath/`, `mt3dms/`, `extractors/` |
| `boussinesq/` | the in-house unstructured-mesh Boussinesq solver; its own map is `boussinesq/README.md` |

Each folder has its own README. Extractors sit beside the adapters of each backend, in `extractors/`. An
extractor carries `process_type`, `solver_name` and an
`extract(solver_run, store, retention)` method, which the `extract` of the adapter calls. Its category is read on the adapter.

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
   `tests/unit/architecture/test_layers.py` checks it.
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
  modflow_common/  flow_run.py  binaries.py   property_mapping.py ...
  modflow6/      adapter.py  build.py  run.py  rerun.py  builders/  api/  adapters/  extractors/  support/
  modflow_nwt/   adapter.py  nwt/  adapters/  extractors/  modpath/  mt3dms/
  boussinesq/    adapter.py  options.py  boussinesq.py  catalog.py  mesh.py  assembly/  runtimes/  ... (see its README)
```

## How a run reaches a backend

1. Choose. `solver.backend` is the name of a registered flow backend
   (`modflow6`, `modflow_nwt`, `boussinesq` or a plugin). A name the registry
   does not serve is refused while the file is read, with the names it serves.
   The settings of a backend are the table `[solver.<name>]`, checked by the
   `options` class on its adapter. A file that uses something the backend leaves
   out of `supports` is refused as well, by `config/cross_checks.py`.
2. Plan. The planner (`base/planner.py`) reads the `requires` attribute of the
   backend class, `solvers.get(process_type, solver).requires`, to bind a transport run
   to an earlier flow run.
3. Look up. The runner calls `solvers.create(process_type, solver)`:
   the registry imports the built-in class, or a plugin, and returns an instance.
   `slot_for` fills the `RunSlot` and `options_for` reads the table of the backend.
4. Run. `solve_one` calls `adapter.validate(model, options, slot)`, then
   `adapter.build(model, options, slot, ctx)`, which makes the backend model in
   memory, then `adapter.run(solver_run)`, which writes its files in the run folder,
   solves and returns a `SolverRun`. A calibration trial that gives a solved run of
   the same model asks `adapter.rerun` first, and the adapter may decline.
5. Extract. `adapter.extract(solver_run, store, retention)` writes the fields and tables of
   the run into the results store, through the extractor registered under the same key.
   After extraction, `adapter.cleanup(solver_run)` removes the scratch files when the
   run keeps no solver files.
6. Observe. `adapter.observables(solver_run, requests)` serves a
   calibration trial from the run folder. An adapter that cannot produce a
   requested observable raises `ObservableNotAvailableError`.

What a backend can do is declared on its adapter class, in the twelve attributes of
`base/README.md`. `writes` lists what it stores, `supports` the traits of the `Model`
it honours and `category` how it resolves space. One copy remains and a contract test holds
it equal to the adapters: the category table of `results/catalog/constants.py` that the index
reads when a manifest has none.

## Where to add what

| to add | where |
|---|---|
| a solver, in tree | a package with its adapter (`adapter.py`) and extractor, its adapter class with the twelve attributes and the five members of the contract, one entry in each of `_BUILTIN_PATHS` and `_BUILTIN_EXTRACTOR_PATHS`, its `options` class on the adapter when it has settings, which a file writes under `[solver.<name>]`; see `docs/source/contribute/architecture/how-to/add-a-solver.rst` |
| a solver, out of tree | an adapter class on the `hydromodpy.solver` entry-point group and an extractor on `hydromodpy.solver.extractor`; the entry-point name is `<process_type>_<name>`, and the registry compares it with the joined attributes of the loaded class, so a name that holds an underscore stays whole |
| a MODFLOW 6 package | a module in `modflow6/builders/` with its build step, called from `modflow6/build.py` in the build order; a builder reads another one only along that order |
| a process type | a process model in `base/simulation_config.py` joined to `SimulationProcessConfig`, its requirements in the `requires` attribute of the backends, an `ensure_*` function and an entry in the two tables of `base/runner.py` (`_REQUIRED_COMPONENTS_BY_PROCESS`, `_COMPONENT_ENSURERS`) |
| a callback around a run | a field of `ProcessCallbacks` and its call in `SimulationRunner` |
| something both MODFLOW backends do | `modflow_common/`, or `modflow_grid/` for a grid |
| a boundary kind | `boundaries/boundary_condition_registry.py` in `model`, then its package in each backend that lists it in `supports` |
| a backend option | the field on `modflow6_config.py`, `nwt/nwt_config.py` or `boussinesq/options.py`, with a profile and a description. A file writes it under `[solver.<name>]` |
| an observable a backend can serve | its reader in the backend's extractor or `modflow_common/observable_extraction.py`, and its state in `base/observables.py` |
