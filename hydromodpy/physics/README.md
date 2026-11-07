# `hydromodpy/physics`

The physical processes of a model, written without any solver. A `[flow]`
table says which parameters, initial heads, boundaries and sinks and sources
the groundwater has. A `[transport]` table holds the tracking and transport
settings. This package turns those tables into typed config models, and
the config models into runtime objects (`Flow`, `Transport`) that the solver
adapters read. It also holds the rules that bring loaded data into a `Flow`
(recharge, ETP, lakes, stream reaches, barriers), and the daily soil reservoir
that turns precipitation and ETP into recharge.
This file is the map of the package: what each part answers, the import
rules, how a `Flow` is built, and where to add what. Each folder has its own
`README.md`.

## Parts

| part | answers |
|---|---|
| `contracts.py` | how physics reads what it must not import: `LoadResultProto`, `FieldRecordProto` and `FieldParamLike`, and the two hooks `_bootstrap.py` fills (`register_field_param_factory`, `register_field_aggregator`) |
| `base/` | what every spatial process shares: the `ProcessSpatial` runtime base, the dated forcings (`TimeSeriesForcing` and its three readings) and the generic initial-condition, boundary-condition and sink/source models in `payloads.py` |
| `forcing/` | how a loaded series becomes a solver-ready one: `resolve_forcing`, alignment to the simulation window, the steady-period rule shared by every solver (`steady_periods.py`) |
| `hydrology/soil_reservoir/` | the daily soil reservoir: `config.py` is what `[flow.sinks_sources.recharge.soil]` can say, `kernel.py` is the arithmetic |
| `hydrology/synthetic/` | synthetic precipitation, inflow and recharge series for demonstrators and tests |
| `flow/` | the groundwater-flow process: `FlowConfig` (`[flow]`), the runtime `Flow`, initial and boundary conditions, the sink/source payloads, and the binders that put loaded data on a `Flow` |
| `transport/` | the transport process: `TransportConfig` (`[transport]`) with one parameter block per engine and the runtime `Transport` |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives physics `core` and itself,
with no tolerance. Two more rules hold in the code:

1. Physics never imports `data`, `spatial`, `simulation` or `solver`. It sees
   loaded data through `LoadResultProto` and a field parameter through
   `FieldParamLike`, both in `contracts.py`. The concrete constructors are
   registered at start-up by `hydromodpy/_bootstrap.py`. The schema of a
   field parameter that `FlowParam` embeds lives in `core/config_kit/field_param/`.
2. Inside the package, `flow/` imports `base`, `contracts`, `forcing` and
   `hydrology`. `forcing/` imports `contracts`. `transport/` imports `base`.
   `base/` reaches `contracts` only inside a function.

Who imports physics: `solver` (most of it), `simulation`, `workflow`,
`calibration`, `config`, `project` and the package root.

## Tree

```
hydromodpy/physics/
  __init__.py      lazy names: Flow, FlowConfig, Transport, ProcessSpatial, ...
  contracts.py
  base/            process_spatial.py  forcing.py  payloads.py
  forcing/         forcing_bridge.py  time_alignment.py  steady_periods.py  validation.py  types.py
  hydrology/       soil_reservoir/  synthetic/
  flow/            flow.py  flow_config.py  flow_toml_loader.py  runtime_config.py
                   initial_conditions.py  boundary_conditions.py  boundary_condition_registry.py
                   time_forcing.py  history_contract.py  cutoff_wall_shore.py
                   property_ids.py  physical_properties.py  regime.py  toml_examples.py
                   sinks_sources/  binders/
  transport/       transport.py  transport_config.py
```

## How a flow is built

1. **Read.** `HydroModPyConfig.from_toml` hands the `[flow]` table to
   `FlowConfig.from_toml_section` (`flow_toml_loader.py`). It canonicalizes
   boundary ids, resolves the forcing paths, and validates the table into a
   `FlowConfig`.
2. **Build.** `Flow(config=cfg.flow)` runs `set_config`. It fills `parameters`
   (`FieldParam` objects, through the hooks of `contracts.py`),
   `initial_conditions`, `boundary_conditions` and `sinks_sources`. Well fluxes
   and recharge are converted to SI there. `ensure_flow`
   (`simulation/execution/runner.py`) builds a missing one.
3. **Bind data.** After the data step, `workflow/steps/data.py` calls the
   `apply_*_to_flow` functions of `flow/binders/`: sea level, recharge and ETP
   (`climate.py`), lake geometry, abacus, bathymetry, cutoff wall, fluxes and
   meteo (`lakes.py`), SFR reaches and the runoff they route (`streams.py`),
   barriers (`barriers.py`). The same cascade runs for a calibration trial.
4. **Solve.** A solver adapter reads the `Flow`. It resolves each dated
   forcing to one value per stress period with
   `flow/time_forcing.resolve_period_values_from_forcing`. Boundary support per
   backend comes from `FLOW_BOUNDARY_DEFINITIONS`.

A soil reservoir (`[flow.sinks_sources.recharge.soil]`) is read by the
recharge binder of every run, and `simulation/soil/` runs it on the loaded
grids. It applies to MODFLOW 6 only.

## Where to add what

| to add | where |
|---|---|
| a flow parameter | a field on `FlowConfig`, with a profile and a description; see `docs/source/contribute/architecture/how-to/add-a-config-field.rst` |
| a boundary id | an entry of `FLOW_BOUNDARY_DEFINITIONS` in `flow/boundary_condition_registry.py`, then the solver that builds it |
| a sink or source kind | a payload module in `flow/sinks_sources/`, a field on `FlowSinksSourcesConfig` in `container.py`, a `Flow.sinks_sources` key in `Flow.set_sinks_sources` |
| a way to bring loaded data into a `Flow` | an `apply_*_to_flow` function in the module of `flow/binders/` it belongs to, called from `workflow/steps/data.py` |
| an initial-condition type | a model in `flow/initial_conditions.py`, added to `_IC_VARIANTS` and to the union |
| a new process | a subpackage that subclasses `ProcessSpatial`, with a config on `HydroModelBase`; see `docs/source/contribute/architecture/how-to/add-a-process.rst` |
| a soil-reservoir option | a field on `SoilReservoirConfig` (`config.py`), its bound in `_RANGE_RULES`, its use in `kernel.py` or `simulation/soil/` |
