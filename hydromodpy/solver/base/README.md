# solver/base

What every backend shares, and nothing that is MODFLOW only. It also holds the plan of a simulation and the
runner that walks it, because both sit between the `[simulation]` table and the adapter of a solver.

## Modules

1. `adapter_protocol.py` is the contract a backend meets: the `SolverAdapter` Protocol, with its twelve class attributes and the methods the runner calls (`validate`, `execute`, `cleanup`, `extract_observables`), `CellLocator` and `STOP_BEFORE_THE_SOLVE`, which a calibration uses to stop a trial before the solve.
2. `registry.py` holds the two registries of the port, `solvers` and `extractors`. Both are instances of the one engine of `core/plugin_registry.py`. A backend is keyed on its `process_type` and `name` joined by `_`, for example `flow_modflow6`, and an extractor on its `process_type` and `solver_name`. The built-in ones are dotted paths imported on first lookup. Out-of-tree backends come from the `hydromodpy.solver` and `hydromodpy.solver.extractor` entry-point groups, under the same `<process_type>_<name>` names. An unknown key raises `SolverInputError`.
3. `solver_config.py` is the `[solver]` table and its backend union.
4. `simulation_config.py` is what the modeller wrote under `[simulation]`: `SimulationConfig`, `SimulationTimeConfig` (`[simulation.time]`), and one model per process, `FlowProcessConfig` and `TransportProcessConfig`, which share their checks of `solvers` and of the registry, and `MeshProcessConfig`. `results_config.py` is `[simulation.results]`, what a run persists and keeps, and `observation_config.py` is `[observation]`, the points a run samples while it still holds its outputs.
5. `plan.py` holds the frozen objects the planner, the runner and the adapters share: `ProcessRun`, `SimulationPlan`, `RunContext` and `RunExecutionResult`. `planner.py` is `SimulationPlanner.build`: one `ProcessRun` per process and solver, in the order declared, each bound to the earlier run it depends on. A run id is `<process_id>::<solver>`, for example `flow_main::modflow_nwt`. The planner binds a dependency only to a run declared earlier in the file, so a file that lists `transport` before a flow it needs is refused and never reordered.
6. `runner.py` is `SimulationRunner.execute`. It walks the plan, opens and closes each block of one process type (`ensure_process_context`, `before_process`, then each run through the adapter of its solver, then `after_process`), and keeps the primary model of each run for the runs that depend on it. A flow run needs `setup.model`, which `prepare_solver` builds, and the runner refuses it with a `ConfigError` that names that step when it is missing. `ensure_transport` and `ensure_process_context` build the other process objects a block needs. The adapter comes from `solvers.create`, which imports the class on first lookup, so the runner imports no backend.
7. `transport_runs.py` is what the transport adapters of every solver share.
8. `protocols.py` holds the structural types the backends annotate with: `DomainLike`, `FlowModelLike`, `TransportLike`.
9. `drain_conductance.py` is the drain arithmetic every backend uses: the conductance of a free seepage face from K, and the discharge band.
10. `observables.py` turns a solver series or field into an `ObservableResult`, and says in three states whether a backend can serve an observable (`ObservableSupport`).
11. `cell_lookup.py` finds the cell under a point on a solver mesh or a cell mesh.
12. `cleanup.py` removes the scratch files of a run.

## What a backend declares

A backend is a class that carries twelve attributes, written once in the `SolverAdapter` Protocol and given no default. `solvers.register` refuses a class that leaves one out and names it, and it refuses a value outside its vocabulary.

| attribute | holds |
|---|---|
| `name`, `process_type` | the solver name a TOML writes and what it computes (`flow` or `transport`). Together they make the key |
| `accepted_meshes` | the mesh engine ids whose cells it reads. A transport declares none, it reads the mesh of its flow |
| `geometry` | `cells` or `raster`, the member of `Model.geometry` its grid is built on |
| `writes`, `reads` | the fields, tables and series its extractor writes, and the products of an earlier run it needs (`face_flow` for a transport) |
| `supports` | the traits of the `Model` it honours, from the closed set of `model/supports.py` |
| `options` | the Pydantic class of its own TOML table, or `None` |
| `category` | `distributed`, `integrated` or `lumped`. The seal writes it to the manifest |
| `native_step` | a pandas frequency alias, or `None` when it advances at the step of `Model.time` |
| `mutable` | the calibration parameters it can change between two solves of one model |
| `requires` | the `(process_type, name)` keys an earlier run must have run |

`supports` is a closed set so that a name written in a backend and a name asked by a model cannot drift. It is the union of the boundary kinds of `FLOW_BOUNDARY_DEFINITIONS`, the fields of `ModelOptions` and the initial states a TOML can choose, and it lives in `model/supports.py`. A trait a backend leaves out is refused before the run when the model asks for it.

## What an adapter reads

An adapter of a flow solver reads one object, the frozen `Model` of `model/model.py`, through `ctx.state.setup.model`. The step `prepare_solver` builds it once from the `Flow` and the setup. Recharge, ETP and wells are in SI units. The lake, stream reach and barrier payloads keep the units the user declared, and MODFLOW 6 converts them when it builds the package. Its members are these.

| member | what it holds |
|---|---|
| `geometry` | the cell mesh, the `Domain`, the raster facts (`RasterGeometry`, with the channel rasters) and the catchment facts (`CatchmentGeometry`) |
| `properties` | one `FieldParam` per parameter id, and the per-cell values set by `with_properties` |
| `boundaries` | the boundary conditions and the ids that are active |
| `recharge`, `etp`, `wells` | the sinks and sources, in m/s and m3/s |
| `lakes`, `sfr`, `flow_barriers` | the loaded lake, stream reach and barrier payloads, in their declared units |
| `initial` | one of `HeadRule`, `SteadyStart`, `CyclicStart`, `PriorState`, `SolvedState` |
| `time`, `options` | the time grid, the flow regime and the solver options every backend shares |

An adapter does not read the `Flow`, the geographic object, the domain or the time grid of the setup, and it never opens a Zarr store. Two reads remain until the run gets its own slot. The MODFLOW 6 and NWT adapters read their backend table of the configuration (`[modflow6]`, `[modflownwt]`), and the Boussinesq adapter reads `[flow.runtime]`. Every adapter reads the scratch folder of the setup workspace, and the two MODFLOW adapters its binary folder too. A prior run reaches it as a `PriorState`, which `prepare_solver` reads through `results/storage/prior_state.py`. The `Model` does not change during a solve. A change is a new object, from `with_properties`, `with_initial`, `steady_variant` or `cycle_variant`, and the adapter keeps the original. `tests/unit/architecture/test_backends_read_the_model.py` holds these rules.

The mapping of the hydraulic properties on the cells is in `model/properties/property_table.py`, and the head a run starts from is built by `model/initial/heads.py` from `model/initial/state.py`.

`base` imports `core`, `model` and `catchment`, never a backend.
