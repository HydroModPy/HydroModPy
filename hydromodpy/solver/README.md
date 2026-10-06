# `hydromodpy/solver`

The numerical backends. A `[solver]` table picks the flow backend, and a
`[[simulation.process]]` entry names the solvers each process runs. This
package holds the adapters that turn a built `Flow` or `Transport` into a
backend run, the extractors that read the backend's files into the results
store, and the registry that pairs a `(process_type, solver_name)` key with
each. Three flow backends ship: MODFLOW 6, MODFLOW-NWT and Boussinesq, plus
the transport tools that go with them.
This file is the map of the package: what each part answers, the import
rules, how a run reaches a backend, and where to add what.

## Parts

| part | answers |
|---|---|
| `base/` | what every backend shares: the `SolverAdapter` Protocol (`adapter_protocol.py`), the registry of adapters and extractors with its entry-point groups (`registry.py`), `SolverConfig` (`solver_config.py`, the `[solver]` table), the observable contracts (`observables.py`, `observable_support.py`), cell lookup by coordinates, the child-process switch (`api_isolation.py`), scratch cleanup |
| `contracts.py` | the public import path of `SolverAdapter`, `RunResult`, `SolverConfig` and `registry` |
| `field_property_mapping.py`, `initial_conditions.py`, `steady_initial_conditions.py` | helpers all backends use: field-based property mapping, head initial conditions, same-solver steady-state initial conditions |
| `modflow_grid/` | the grid description the MODFLOW family reads: `SolverMesh` for structured and unstructured meshes, `SolverGridContext`, spatial and temporal discretization builders |
| `modflow_common/` | what MODFLOW 6 and MODFLOW-NWT do the same way: binary resolution and download, boundary-package descriptors, budget names, calibration readers, property mapping, discharge routing, descent of the mesh, the flow-adapter lifecycle (`flow_adapter_helpers.py`) |
| `modflow6/` | MODFLOW 6 through FloPy: `build.py` (package wiring), `builders/` (one module per package: CHD and DRN, recharge and EVT, wells, LAK, SFR, MVR, HFB, solver options), `run.py`, `api/` (libmf6, in process or in a subprocess), `adapters/` (flow, GWT transport, PRT), `extractors/`, `postprocess/`, `support/`, `modflow6_config.py` |
| `modflow_nwt/` | MODFLOW-NWT through FloPy: `nwt/` (solver, pre and post processing, payload builders, `nwt_config.py`), `adapters/` (flow, MODPATH, MT3DMS), `modpath/`, `mt3dms/`, `extractors/` |
| `boussinesq/` | the in-house unstructured-mesh Boussinesq solver; its own map is `boussinesq/README.md` |

Extractors sit beside the adapters of each backend, in `extractors/`. An
extractor carries `solver_name`, a `category` (`distributed` or `lumped`), an
`extract(sim_id, solver_output_dir, store, ...)` method and a
`derive(sim_id, store, flags)` method.

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives solver `core`, `schema`,
`physics`, `spatial`, `simulation` and itself. Today it imports `core`,
`physics`, `simulation` and `spatial`. No `solver_layout.yaml` orders the
parts. The shape is:

1. Backends do not import each other. `modflow6`, `modflow_nwt` and `boussinesq`
   each import `base`, the shared helpers at the root, and, for the first two,
   `modflow_common` and `modflow_grid`. No gate checks the independence; the
   import scanner of `tools/audit/build_graph.py` shows it holds.
2. `modflow_common` and `modflow_grid` import `base` and each other, never a
   backend.
3. `base/registry.py` names every built-in adapter and extractor by a dotted
   path in `_BUILTIN_PATHS` and `_BUILTIN_EXTRACTOR_PATHS` and imports it on
   first lookup. Loading `hydromodpy.simulation` therefore loads no backend.
4. A private name read inside a backend package is declared in that package:
   `tests/unit/architecture/test_solver_private_attributes.py` checks it.
5. A lower layer reaches the registry through the provider
   `core.contracts.solver_registry`, which `hydromodpy/_bootstrap.py` fills.
   `simulation` and `analysis` do not import `solver`; `calibration` reaches
   it through `solver.base` only (see `calibration/README.md`).

Who imports solver: `workflow`, `config`, `calibration`, `cli`, `project` and
the package root.

## Tree

```
hydromodpy/solver/
  __init__.py  contracts.py  field_property_mapping.py  initial_conditions.py  steady_initial_conditions.py
  base/          adapter_protocol.py  registry.py  solver_config.py  observables.py  observable_support.py ...
  modflow_grid/  solver_mesh.py  grid_context.py  discretization_spatial.py  discretization_temporal.py
  modflow_common/  flow_adapter_helpers.py  binaries.py  boundary_packages.py  property_mapping.py ...
  modflow6/      build.py  run.py  builders/  api/  adapters/  extractors/  postprocess/  support/
  modflow_nwt/   nwt/  adapters/  extractors/  modpath/  mt3dms/
  boussinesq/    boussinesq.py  mesh.py  assembly/  adapters/  extractors/  ... (see its README)
```

GR4J is not a solver backend. It is a lumped model in `calibration/lumped/`,
run in memory and outside this registry.

## How a run reaches a backend

1. **Choose.** `[solver] backend` selects the flow backend (`modflow6`,
   `modflow_nwt`, `boussinesq`, or `custom` with a registered name).
   `SolverConfig.validate_registry` refuses a name the registry does not know.
2. **Plan.** The simulation planner reads `required_bindings(process_type,
   solver)` from the registry to bind a transport run to an earlier flow run.
3. **Look up.** The runner calls `get_solver_adapter(process_type, solver)`:
   the registry imports the built-in class, or a plugin, and returns an instance.
4. **Run.** `adapter.validate(ctx)`, then `adapter.execute(ctx)`, which builds
   the backend model from the `Flow` (or `Transport`) of the context, writes
   its files in the scratch folder and returns a `RunExecutionResult`. After
   extraction, `adapter.cleanup(ctx)`.
5. **Extract.** `get_extractor_instance(process_type, solver)` returns the
   extractor that reads the scratch files into the results store.
6. **Observe.** `adapter.extract_observables(ctx, store, requests)` serves a
   calibration trial from the scratch folder. An adapter that cannot produce a
   requested observable raises `ObservableNotAvailableError`.

Capabilities (`flow`, `flow:heads`, `flow:budget`, `flow:restart`,
`flow:spinup_cyclic`, `flow:surface_excess`, `transport:particles`,
`transport:concentration`) are declared per pair in `_BUILTIN_CAPABILITIES`
and read with `registry.capabilities`.

## Where to add what

| to add | where |
|---|---|
| a solver, in tree | a package with its adapter and extractor, one entry in each of `_BUILTIN_PATHS`, `_BUILTIN_EXTRACTOR_PATHS` and `_BUILTIN_CAPABILITIES`, a member of the `[solver]` backend union in `base/solver_config.py`; see `docs/source/contribute/architecture/how-to/add-a-solver.rst` |
| a solver, out of tree | an adapter class on the `hydromodpy.solver` entry-point group and an extractor on `hydromodpy.solver.extractor`; the entry-point name is `<process_type>_<solver_name>` and the loader splits it at the first underscore |
| a MODFLOW 6 package | a module in `modflow6/builders/`, called from `modflow6/build.py`; builders stay independent of each other and couple through `builders/mvr.py` records |
| something both MODFLOW backends do | `modflow_common/`, or `modflow_grid/` for a grid |
| a boundary kind | `flow/boundary_condition_registry.py` in `physics`, then its package in each backend; `modflow_common/flow_translator.py` holds the shared translation |
| a backend option | the field on `modflow6_config.py`, `nwt/nwt_config.py` or the Boussinesq runtime knobs of `FlowConfig`, with a profile and a description |
| an observable a backend can serve | its reader in the backend's extractor or `modflow_common/observable_extraction.py`, and its state in `base/observable_support.py` |
