# solver/base

What every backend shares, and nothing that is MODFLOW only. It also holds the plan of a simulation and the
runner that walks it, because both sit between the `[simulation]` table and the adapter of a solver.

## Modules

1. `adapter_protocol.py` is the contract a backend meets: the `SolverAdapter` Protocol, with its twelve class attributes and the five members the runner calls (`validate`, `build`, `run`, `cleanup`, `extract`). The optional members `rerun`, `observables` and `declared_observables` are listed in `RERUN_MEMBERS` and `OPTIONAL_MEMBERS`, and `CellLocator` is the Protocol of a backend that finds the cell under a point. `OutputAdapter` is the Protocol of an extractor: `process_type`, `solver_name` and `extract(solver_run, store, retention)`, which `extractors` checks on every class it registers. `face_flow` is a name of the field registry, and a flow that declares it writes the flux between connected cells into its store.
2. `registry.py` holds the two registries of the port, `solvers` and `extractors`. Both are instances of the one engine of `core/plugin_registry.py`. A backend is keyed on its `process_type` and `name` joined by `_`, for example `flow_modflow6`, and an extractor on its `process_type` and `solver_name`. The built-in ones are dotted paths imported on first lookup. Out-of-tree backends come from the `hydromodpy.solver` and `hydromodpy.solver.extractor` entry-point groups, under the same `<process_type>_<name>` names. An unknown key raises `SolverInputError`.
3. `solver_config.py` is the `[solver]` table. `solver.backend` is a string, the name of a registered flow solver, checked against the registry while the file is read. The refusal lists the names this installation serves. A key of `[solver]` that is not one of its own switches is the name of a flow solver and holds its settings, `[solver.modflow6]` for instance, checked by the `options` class of that solver. `options_of(name)` returns the table, or its defaults.
4. `simulation_config.py` is what the modeller wrote under `[simulation]`: `SimulationConfig`, `SimulationTimeConfig` (`[simulation.time]`), and one model per process, `FlowProcessConfig` and `TransportProcessConfig`, which share their checks of `solvers` and of the registry, and `MeshProcessConfig`. `results_config.py` is `[simulation.results]`, what a run persists and keeps, and `observation_config.py` is `[observation]`, the points a run samples while it still holds its outputs.
5. `plan.py` holds the frozen objects the planner, the runner and the adapters share: `ProcessRun`, `SimulationPlan`, `RunSlot`, `SolverRun` and `RunContext`. `planner.py` is `SimulationPlanner.build`: one `ProcessRun` per process and solver, in the order declared, each bound to the earlier run it depends on. A run id is `<process_id>::<solver>`, for example `flow_main::modflow_nwt`. The planner binds a dependency only to a run declared earlier in the file, so a file that lists `transport` before a flow it needs is refused and never reordered.
6. `runner.py` is `SimulationRunner.execute`. It walks the plan, opens and closes each block of one process type (`before_process`, then each run through the adapter of its solver, then `after_process`), and keeps the `SolverRun` of each run for the runs that depend on it. `slot_for` fills the `RunSlot` of a run, and `solve_one` calls `validate`, then `rerun` or `build`, then `run`. A flow run needs `setup.model`, which `prepare_solver` builds, and the runner refuses it with a `ConfigError` that names that step when it is missing. A transport run receives exactly one upstream run, the `SolverRun` of the flow its `requires` names, and the runner refuses anything else with a typed error. The adapter comes from `solvers.create`, which imports the class on first lookup, so the runner imports no backend.
7. `drain_conductance.py` is the drain arithmetic every backend uses: the conductance of a free seepage face from K, and the discharge band.
8. `observables.py` turns a solver series or field into an `ObservableResult`, and says in three states whether a backend can serve an observable (`ObservableSupport`).
9. `cell_lookup.py` finds the cell under a point on a solver mesh or a cell mesh.
10. `cleanup.py` removes the scratch files of a run.
11. `rerun.py` holds `changed_properties`, which names the properties that differ between two `Model` objects, and `chooses_rerun`, the rule by which the runner calls `rerun` instead of `build`.

## What a run receives and returns

An adapter receives the frozen `Model`, its options (the validated table `[solver.<name>]`, or `None`) and a `RunSlot`. `validate` and `build` take them in that order, and `build` also takes `upstream`, the `SolverRun` objects the plan ran before this one. The runner fills the slot. `folder` and `name` give the run folder `slot.directory`, `bin_dir` is the folder of the solver binaries, `stop_before_solve` asks for a build and no solve, and `shared_forcing_dir` is where a calibration trial keeps the forcing files that do not change between trials, a recharge series included: the file a `rerun` copies keeps its absolute reference to that folder, so a long series is written once for the whole search. `hand_off` is the closed set of names the later runs of the plan read off this run; the runner fills it from the `reads` of those runs. `stop_flag` is the stop flag of the run folder, `.hmp/stop.json`, and `None` for a calibration trial, which has no folder. A trial asks for the name, the early stop and that folder through `SlotRequest` on the setup. The folder and the binaries are facts of the machine, so they stay out of the `Model` and out of the options, and two runs of one model can solve in two places.

Who reads `stop_flag`, and when, depends on what can be stopped without harm. The runner reads it between two runs of the plan. MODFLOW 6 through libmf6 reads it at the end of each time step, and Boussinesq between two periods, and both raise `StopRequested` through the loop. A backend that solves through an executable reads nothing, because killing the child would leave half-written files. The runner and the pipeline read the flag after its solve.

A transport receives the same three objects for its upstream flow instead of a `Model` of its own. Its `model` is `upstream[0].model`, the frozen `Model` the flow was built from. Its options are an instance of its own `options` class, read from its `[transport.<name>]` table. Its `upstream` holds exactly one `SolverRun`, the flow its `requires` names, and the runner refuses anything else with a typed error. The transport works in `upstream[0].output_dir`, the folder of its flow: a solver of the same family extends the flow simulation or reads the files it wrote, and one of another family has nothing to read.

`face_flow`, the name of `reads` for a transport, is a name of the field registry: the flux across each connection of two cells, in m3/s, positive from the smaller flat index to the larger, at every stored time step. A flow that declares it writes it into its store as `face_flow` beside `connection_cells`, the two cells of each connection, when `[simulation.results] keep_face_flows` is true; the diagonal of MODFLOW 6 `FLOW-JA-FACE` is never kept. A file whose flow does not write what a transport reads is refused when the file is read, in `config/cross_checks.py`, with the flow solvers that write it.

Each call returns a `SolverRun`, a frozen record of `model`, `options`, `slot`, `solver_model`, `output_dir`, `input_files`, `written`, `solved`, `metrics`, `solve_s` and `initial_state_converged`. `solve_s` is the wall time of the solve alone, measured by the backend around the call that solves. It is not in `metrics`, because the time of a solve is no result of the run. The `run_solver` step writes it to `profile.json`. `build` makes the solver model in memory with `written` and `solved` false. `run` writes the input files unless `written` is set, lists them in `input_files`, solves, and sets `solved`. `extract(solver_run, store, retention)` writes what the backend lists in `writes`. `retention` is a `Retention` of `results/storage/kept.py`, which says which per-cell budget terms the run keeps, whether the raw solver files stay and whether the flow between connected cells stays. `cleanup(solver_run)` removes the scratch files once the results are stored.

`rerun(previous, model, slot)` exists on a backend if and only if its `mutable` is not empty. It solves a model that differs from `previous.model` only by properties named in `mutable`, and rewrites only the input files those properties touch. It returns `None` when the change needs a build, and the runner then builds. It returns `None` too when the simulation of `previous` already carries a model of another process, so a rerun never replays a transport that a solve before it extended, and the runner builds a flow only model instead. It consumes `previous`: the solver model of `previous` describes the new run afterwards, so only the returned `SolverRun` serves as a parent. The calibration is the only caller of `rerun`: its trials that change `K` or `Sy` alone go through it, one lane per trial in flight, and the cost is the same to the bit as a build. This `rerun` is a shortcut between two solves of a calibration. `hmp catalog rerun` replays a sealed run from its configuration, and the two share only the word.

## What a backend declares

A backend is a class that carries twelve attributes, written once in the `SolverAdapter` Protocol and given no default. `solvers.register` refuses a class that leaves one out and names it, and it refuses a value outside its vocabulary.

| attribute | holds |
|---|---|
| `name`, `process_type` | the solver name a TOML writes and what it computes (`flow` or `transport`). Together they make the key |
| `accepted_meshes` | the mesh engine ids whose cells it reads. A transport declares none, it reads the mesh of its flow |
| `geometry` | `cells` or `raster`, the member of `Model.geometry` its grid is built on |
| `writes`, `reads` | the fields, tables and series its extractor writes, and the products of an earlier run it needs (`face_flow` for a transport, a name of the field registry) |
| `supports` | the traits of the `Model` it honours, from the closed set of `model/supports.py` |
| `options` | the Pydantic class of its own TOML table, or `None` |
| `category` | `distributed`, `integrated` or `lumped`. The seal writes it to the manifest |
| `native_step` | a pandas frequency alias, or `None` when it advances at the step of `Model.time` |
| `mutable` | the calibration parameters it can change between two solves of one model |
| `requires` | the `(process_type, name)` keys an earlier run must have run |

`supports` is a closed set so that a name written in a backend and a name asked by a model cannot drift. It is the union of the seven sources of `SUPPORT_SOURCES` in `model/supports.py`: the boundary kinds of `FLOW_BOUNDARY_DEFINITIONS`, the fields of `ModelOptions`, the initial states a TOML can choose, the sinks and sources (`recharge`, `etp`, `wells`, `flow_barriers`, `cutoff_wall`), the soil reservoir (`soil`), the K tensor (`k_tensor`) and the layering (`layers`, `pass_through`). A default document already uses `head_rule`, and a document with recharge or wells uses those traits too, so a backend lists every trait it honours. A trait a backend leaves out is refused when the file is read, by `config/cross_checks.py`. The refusal gives the key the file wrote and the solvers that honour it, so `config/` never names a solver.

A global backend meshes the catchment as one cell of the `catchment` engine and declares `category` `lumped`; the in-tree one is `linear_reservoir`. It may declare `native_step`, a pandas frequency alias of the step it advances at; a native step finer than a transient period of the time grid is refused when the file is read, with the period grid `core/time` computes. `Model.native_recharge` carries the series of a spatialized source at the step of the source, read by area on the one-cell mesh. The options table of a backend may carry optional properties a worker reads: `wall_clock_limit_s` bounds one trial, and `runner` names the way the backend solves.

## What an adapter reads

An adapter of a flow solver reads one object, the frozen `Model` of `model/model.py`. The step `prepare_solver` builds it once from the `Flow` and the setup, puts it on `setup.model`, and the runner hands it to the adapter. Recharge, ETP and wells are in SI units. The lake, stream reach and barrier payloads keep the units the user declared, and MODFLOW 6 converts them when it builds the package. Its members are these.

| member | what it holds |
|---|---|
| `geometry` | the cell mesh, the `Domain`, the raster facts (`RasterGeometry`, with the channel rasters), the catchment facts (`CatchmentGeometry`) and the river network A read on the cells (`ChannelExits`, `None` for a run without A) |
| `properties` | one `FieldParam` per parameter id, and the per-cell values set by `with_properties` |
| `boundaries` | the boundary conditions and the ids that are active |
| `recharge`, `etp`, `wells` | the sinks and sources, in m/s and m3/s |
| `lakes`, `sfr`, `flow_barriers` | the loaded lake, stream reach and barrier payloads, in their declared units |
| `initial` | one of `HeadRule`, `SteadyStart`, `CyclicStart`, `PriorState`, `SolvedState` |
| `time`, `options` | the time grid, the flow regime and the solver options every backend shares |

A flow adapter reads nothing of the setup, the configuration or the store, and it never opens a Zarr store. Its options and its folders arrive as arguments. A transport adapter reads nothing of them either. It receives the `Model` of its flow, its own options, the slot of its flow and the `SolverRun` of that flow, everything through the arguments of `build`. A prior run reaches a flow adapter as a `PriorState`, which `prepare_solver` reads through `results/storage/prior_state.py`. The `Model` does not change during a solve. A change is a new object, from `with_properties`, `with_initial`, `steady_variant` or `cycle_variant`, and the adapter keeps the original. `tests/unit/architecture/test_run_path.py` holds these rules.

The mapping of the hydraulic properties on the cells is in `model/properties/property_table.py`, and the head a run starts from is built by `model/initial/heads.py` from `model/initial/state.py`.

`base` imports `core`, `model`, `catchment` and `results`, never a backend.
