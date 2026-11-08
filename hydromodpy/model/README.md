# `hydromodpy/model`

What a model is, written without any solver. A `[domain]` table says where the aquifer lies, a `[flow]`
table says which parameters, initial heads, boundaries and sinks and sources the groundwater has, and a
`[transport]` table holds the tracking settings. This package turns those tables into typed config
models, and the config models into the runtime objects. `Flow` (`flow.py`) is the object the setup binds
loaded data to. `Model` (`model.py`) is the frozen object a flow solver reads, and `prepare_solver` builds
it from the `Flow`. The package also puts forcings on the cells of a mesh, maps the properties onto those
cells, binds loaded data to a `Flow` (recharge, ETP, lakes, stream reaches, barriers) and holds the
arithmetic of the daily soil reservoir that turns precipitation and ETP into recharge.
This file is the map of the package. Each folder has its own `README.md`, except `initial/` and `time/`.

## Parts

| module | answers |
|---|---|
| `contracts.py` | What the model reads without importing it: `LoadResultProto`, `FieldRecordProto`, `FieldParamLike` and the two hooks `_bootstrap.py` fills |
| `flow_config.py` | `FlowConfig`, the `[flow]` schema, and the reader of the raw `[flow]` table |
| `flow.py` | The runtime `Flow`, built from a `FlowConfig`, that the setup binds loaded data to |
| `model.py` | The frozen `Model` a solver adapter reads, its factories (`with_properties`, `with_initial`, `steady_variant`, `cycle_variant`) and `model_from_flow` |
| `supports.py` | The closed set of names a solver backend lists in `supports`: the boundaries, the fields of `ModelOptions`, the initial states a TOML can choose, the sinks and sources, the soil reservoir, the K tensor and the layering. Each name is read from the module that owns it |
| `initial_config.py` | `[flow.ic]` and `[spinup]`: the payloads of the starting head and the readers of its strategies |
| `payloads.py` | The generic initial-condition, boundary-condition and sink/source models, and their normalizers |
| `process_spatial.py` | `ProcessSpatial`, the runtime parent of `Flow` and `Transport` |
| `runtime_config.py` | `FlowRuntimeConfig`, the settings of the Boussinesq solve. A file writes them under `[solver.boussinesq]` |
| `toml_examples.py` | The commented examples of the dynamic `[flow.*]` blocks of the TOML template |

| folder | answers |
|---|---|
| `domain/` | where the aquifer lies: the `Domain`, its depth models and layers, the supports a parameter can be zoned by, the lake bed and the `domain-build` worker |
| `properties/` | what value a parameter takes in each cell: `FieldParam`, zones, depth profile, geology, and `property_table.py` that maps K, Sy and Ss onto the cells for every solver |
| `forcing/` | how a series or a grid becomes the rate a solver reads: `resolve_forcing`, alignment to the stress periods, the steady-period rule, and grids and stations on cells, and the run of the soil reservoir on the loaded grids (`soil_*.py`) |
| `boundaries/` | the boundary ids and their Dirichlet and drain payloads, and the binders that put loaded data on a built `Flow` |
| `sinks_sources/` | one payload per sink or source of `[flow.sinks_sources]` |
| `initial/` | the head a run starts from: the five initial states of `state.py` and the head arrays of `heads.py`, in numpy |
| `time/` | the flow regime and the time axes of transient histories |
| `soil/` | the arithmetic of the daily soil reservoir, `kernel.py`, in numpy |
| `transport/` | the transport process: `TransportConfig` (`[transport]`) and the runtime `Transport` |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives the model `core`, `schema`, `catchment`, `mesh` and
itself. Two more rules hold in the code.

1. The model never imports `data`, `results` or `solver`. It sees loaded data through `LoadResultProto`
   and a field parameter through `FieldParamLike`, both in `contracts.py`. The concrete constructors are
   registered at start-up by `hydromodpy/_bootstrap.py`.
2. Inside the package, `boundaries/` reads `contracts`, `forcing`, `payloads` and `sinks_sources`, and
   reads `flow.py` for annotations only. `sinks_sources/` reads `forcing`. `forcing/` and
   `process_spatial.py` read `contracts`, and `forcing/soil_*.py` read `soil/kernel.py`. `process_spatial.py`
   reads `payloads`. `domain/` reads `properties/`, `properties/` reads `time/`, and `transport/` reads
   `process_spatial.py`. `flow_config.py`, `flow.py`, `initial_config.py` and `model.py` read the folders.
   The only cycle is the annotation of `Flow` in `boundaries/`, which stays under `TYPE_CHECKING`.
3. `soil/` and `initial/` follow rule 6. A module there imports the standard library, numpy and at most one
   neighbour of its folder, and `tests/unit/architecture/test_science_module_imports.py` holds it.

Who imports the model: `solver` (most of it), `workflow`, `calibration`, `config`, `data`, `results`,
`project` and the package root.

## How a flow is built

1. Read. `HydroModPyConfig.from_toml` hands the `[flow]` table to `FlowConfig.from_toml_section` in
   `flow_config.py`. It canonicalizes the boundary ids, resolves the forcing paths and validates the table
   into a `FlowConfig`.
2. Build. `Flow(config=cfg.flow)` runs `set_config`. It fills `parameters` (`FieldParam` objects, through
   the hooks of `contracts.py`), `initial_conditions`, `boundary_conditions` and `sinks_sources`. Well
   fluxes and recharge are converted to SI there. `ensure_flow` in `workflow/steps/data.py` builds it at
   setup.
3. Bind data. After the data step, `workflow/steps/data.py` calls the `apply_*_to_flow` functions of
   `boundaries/`. They put the sea level, recharge and ETP (`climate.py`), the lakes (`lakes.py`), the SFR
   reaches and the runoff they route (`streams.py`) and the barriers (`barriers.py`) on the `Flow`. The
   same cascade runs for a calibration trial.
4. Freeze. `prepare_solver` calls `model_from_flow` and gets a `Model`. It holds the same objects as the
   `Flow`, in SI, with the geometry, the time grid and the shared solver options beside them. A prior run is
   read into a `PriorState` there, so no adapter opens a Zarr.
5. Solve. A solver adapter reads the `Model` and never the `Flow`. It resolves each dated forcing to one
   value per stress period with `forcing/time_forcing.resolve_period_values_from_forcing`. Boundary support
   per backend comes from `FLOW_BOUNDARY_DEFINITIONS`. A change to the model is a new object, made by
   `with_properties`, `with_initial`, `steady_variant` or `cycle_variant`, and the `Model` of the run stays
   as it was.

A soil reservoir (`[flow.sinks_sources.recharge.soil]`) is read by the recharge binder of every run, and
`forcing/soil_forcing.py` runs the kernel of `soil/` on the loaded grids. It applies to MODFLOW 6 only.

## Where to add what

| to add | where |
|---|---|
| a flow parameter | a field on `FlowConfig`, with a profile and a description, see `docs/source/contribute/architecture/how-to/add-a-config-field.rst` |
| a boundary id | an entry of `FLOW_BOUNDARY_DEFINITIONS` in `boundaries/boundary_condition_registry.py`, then the solver that builds it |
| a sink or source kind | a payload module in `sinks_sources/`, a field on `FlowSinksSourcesConfig` in `container.py`, a `Flow.sinks_sources` key in `Flow.set_sinks_sources` |
| a way to bring loaded data into a `Flow` | an `apply_*_to_flow` function in the module of `boundaries/` it belongs to, called from `workflow/steps/data.py` |
| an initial-condition type | a model in `initial_config.py`, added to `_IC_VARIANTS` and to the union, and a state in `initial/state.py` |
| a field the solvers read | a member of `Model` in `model.py`, filled by `model_from_flow` |
| a new process | a subpackage that subclasses `ProcessSpatial`, with a config on `HydroModelBase`, see `docs/source/contribute/architecture/how-to/add-a-process.rst` |
| a depth model or a support kind | `domain/`, see its README |
| a soil-reservoir option | a field on `SoilReservoirConfig` (`forcing/soil_config.py`), its bound in `_RANGE_RULES`, its use in `soil/kernel.py` or `forcing/soil_forcing.py` |
