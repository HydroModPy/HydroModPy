# `hydromodpy/model`

What a model is, written without any solver. A `[domain]` table says where the aquifer lies, a `[flow]`
table says which parameters, initial heads, boundaries and sinks and sources the groundwater has, and a
`[transport]` table holds the tracking settings. This package turns those tables into typed config
models, and the config models into the runtime objects (`Flow`, `Transport`) that the solver adapters
read. It also puts forcings on the cells of a mesh, maps the properties onto those cells, binds loaded
data to a `Flow` (recharge, ETP, lakes, stream reaches, barriers) and runs the daily soil reservoir that
turns precipitation and ETP into recharge. `Flow` lives in `model.py` and keeps its name until the
`Model` takes its place in that file, because every adapter receives a `Flow` today.
This file is the map of the package. Each folder has its own `README.md`, except `initial/` and `time/`.

## Parts

| module | answers |
|---|---|
| `contracts.py` | What the model reads without importing it: `LoadResultProto`, `FieldRecordProto`, `FieldParamLike` and the two hooks `_bootstrap.py` fills |
| `flow_config.py` | `FlowConfig`, the `[flow]` schema, and the reader of the raw `[flow]` table |
| `model.py` | The runtime `Flow`, built from a `FlowConfig`, that every solver adapter reads |
| `payloads.py` | The generic initial-condition, boundary-condition and sink/source models, and their normalizers |
| `process_spatial.py` | `ProcessSpatial`, the runtime parent of `Flow` and `Transport` |
| `runtime_config.py` | `[flow.runtime]`, the settings of the Boussinesq solve |
| `toml_examples.py` | The commented examples of the dynamic `[flow.*]` blocks of the TOML template |

| folder | answers |
|---|---|
| `domain/` | where the aquifer lies: the `Domain`, its depth models and layers, the supports a parameter can be zoned by, the lake bed and the `domain-build` worker |
| `properties/` | what value a parameter takes in each cell: `FieldParam`, zones, depth profile, geology, and `property_table.py` that maps K, Sy and Ss onto the cells for every solver |
| `forcing/` | how a series or a grid becomes the rate a solver reads: `resolve_forcing`, alignment to the stress periods, the steady-period rule, and grids and stations on cells |
| `boundaries/` | the boundary ids and their Dirichlet and drain payloads, and the binders that put loaded data on a built `Flow` |
| `sinks_sources/` | one payload per sink or source of `[flow.sinks_sources]` |
| `initial/` | the head a run starts from: the `[flow.ic]` payloads, the heads of the steady and cyclic spin-up, and `[spinup]` |
| `time/` | the flow regime and the time axes of transient histories |
| `soil/` | the daily soil reservoir, its config, and its run on the loaded grids |
| `transport/` | the transport process: `TransportConfig` (`[transport]`) and the runtime `Transport` |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives the model `core`, `schema`, `catchment`, `mesh` and
itself. Two more rules hold in the code.

1. The model never imports `data`, `results` or `solver`. It sees loaded data through `LoadResultProto`
   and a field parameter through `FieldParamLike`, both in `contracts.py`. The concrete constructors are
   registered at start-up by `hydromodpy/_bootstrap.py`.
2. Inside the package, `boundaries/` reads `contracts`, `forcing`, `payloads` and `sinks_sources`, and
   reads `model.py` for annotations only. `sinks_sources/` reads `forcing` and `soil`. `forcing/`, `soil/`
   and `process_spatial.py` read `contracts`. `initial/` and `process_spatial.py` read `payloads`.
   `domain/` reads `properties/`, `properties/` reads `time/`, and `transport/` reads `process_spatial.py`.
   `flow_config.py` and `model.py` read the folders. The only cycle is the annotation of `Flow` in
   `boundaries/`, which stays under `TYPE_CHECKING`.

Who imports the model: `solver` (most of it), `workflow`, `calibration`, `config`, `data`, `results`,
`project` and the package root.

## How a flow is built

1. Read. `HydroModPyConfig.from_toml` hands the `[flow]` table to `FlowConfig.from_toml_section` in
   `flow_config.py`. It canonicalizes the boundary ids, resolves the forcing paths and validates the table
   into a `FlowConfig`.
2. Build. `Flow(config=cfg.flow)` runs `set_config`. It fills `parameters` (`FieldParam` objects, through
   the hooks of `contracts.py`), `initial_conditions`, `boundary_conditions` and `sinks_sources`. Well
   fluxes and recharge are converted to SI there. `ensure_flow` in `solver/base/runner.py` builds a
   missing one.
3. Bind data. After the data step, `workflow/steps/data.py` calls the `apply_*_to_flow` functions of
   `boundaries/`. They put the sea level, recharge and ETP (`climate.py`), the lakes (`lakes.py`), the SFR
   reaches and the runoff they route (`streams.py`) and the barriers (`barriers.py`) on the `Flow`. The
   same cascade runs for a calibration trial.
4. Solve. A solver adapter reads the `Flow`. It resolves each dated forcing to one value per stress period
   with `forcing/time_forcing.resolve_period_values_from_forcing`. Boundary support per backend comes from
   `FLOW_BOUNDARY_DEFINITIONS`.

A soil reservoir (`[flow.sinks_sources.recharge.soil]`) is read by the recharge binder of every run, and
`soil/` runs it on the loaded grids. It applies to MODFLOW 6 only.

## Where to add what

| to add | where |
|---|---|
| a flow parameter | a field on `FlowConfig`, with a profile and a description, see `docs/source/contribute/architecture/how-to/add-a-config-field.rst` |
| a boundary id | an entry of `FLOW_BOUNDARY_DEFINITIONS` in `boundaries/boundary_condition_registry.py`, then the solver that builds it |
| a sink or source kind | a payload module in `sinks_sources/`, a field on `FlowSinksSourcesConfig` in `container.py`, a `Flow.sinks_sources` key in `Flow.set_sinks_sources` |
| a way to bring loaded data into a `Flow` | an `apply_*_to_flow` function in the module of `boundaries/` it belongs to, called from `workflow/steps/data.py` |
| an initial-condition type | a model in `initial/config.py`, added to `_IC_VARIANTS` and to the union |
| a new process | a subpackage that subclasses `ProcessSpatial`, with a config on `HydroModelBase`, see `docs/source/contribute/architecture/how-to/add-a-process.rst` |
| a depth model or a support kind | `domain/`, see its README |
| a soil-reservoir option | a field on `SoilReservoirConfig` (`soil/config.py`), its bound in `_RANGE_RULES`, its use in `soil/kernel.py` or `soil/recharge.py` |
