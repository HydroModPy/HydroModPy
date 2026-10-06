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
rules, how a `Flow` is built, and where to add what.

## Parts

| part | answers |
|---|---|
| `contracts.py` | how physics reads what it must not import: `LoadResultProto` and `FieldParamLike`, and the hooks `_bootstrap.py` fills with the spatial constructors (`register_field_param_factory` and its three siblings) |
| `base/` | what every spatial process shares: the `ProcessSpatial` runtime base, `ProcessSpatialConfig`, the generic initial-condition, boundary-condition and sink/source models and their normalizers, the `ConstantForcing`, `CsvForcing` and `SyntheticForcing` payloads |
| `forcing/` | how a loaded series becomes a solver-ready one: `resolve_forcing` (homogeneous or heterogeneous), unit conversion, alignment to the simulation window |
| `hydrology/soil_reservoir/` | the daily soil reservoir: `config.py` is what `[flow.sinks_sources.recharge.soil]` can say, `kernel.py` is the arithmetic (curve-number runoff, root-zone storage, transit store, spin-up, balance) |
| `hydrology/synthetic/` | synthetic precipitation, inflow and recharge series for demonstrators and tests |
| `hydrology/pyhelp/` | the PyHELP recharge model: `core/` is the model code, `preprocessing/` stages ERA5 and grid inputs, runs it and writes NetCDF. No module outside `physics/hydrology` imports it |
| `flow/` | the groundwater-flow process: `FlowConfig` (`[flow]`), the runtime `Flow`, initial conditions, boundary conditions with their registry, the sink/source payloads, the binders that apply loaded data to a `Flow` |
| `transport/` | the transport process: `TransportConfig` (`[transport]`) with one parameter block per tool (`modpath`, `mt3dms`, `modflow6gwt`, `modflow6prt`) and the runtime `Transport` |

`flow/` in short:

| module | answers |
|---|---|
| `flow_config.py`, `flow_param_config.py` | the `[flow]` schema; `FlowParam` wraps the field sections of `[flow.param.<id>]` |
| `flow_toml_loader.py` | how a raw `[flow]` section is read: id canonicalization, forcing paths resolved against the project folders |
| `flow_runtime_fields.py`, `flow_runtime_validators.py`, `flow_runtime_config.py` | the Boussinesq runtime knobs on `FlowConfig`, their validators, and the grouped view `FlowConfig.runtime` |
| `flow.py` | the runtime `Flow` and `set_config` |
| `initial_conditions.py`, `initial_conditions_config.py` | the head initial conditions: `top`, `top_offset`, `bottom`, `custom`, `steady_state`, `spinup_cyclic`, and their normalizer |
| `boundary_conditions.py`, `boundary_condition_registry.py` | the Dirichlet, Cauchy and Robin payloads; the table of canonical boundary ids with the package each backend uses (`FLOW_BOUNDARY_DEFINITIONS`) and `BoundaryConditionBundle`, which solvers read |
| `sinks_sources/` | one module per payload: `wells`, `recharge`, `etp`, `lake`, `sfr`, `flow_barrier`; `container.py` groups them under `[flow.sinks_sources]` |
| `structure_binders.py` | the `apply_*_to_flow` functions that put loaded data into a built `Flow` |
| `time_forcing.py`, `history_contract.py` | how a forcing is resolved against the simulation window; the shared time axes of transient histories |
| `physical_properties.py`, `regime.py` | `FlowPhysicalProperties` and the `FlowRegime` vocabulary (`steady`, `transient`) |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives physics `core`, `schema` and
itself. No `physics_layout.yaml` orders the parts inside the package, so the
layer matrix is the only gate. Three more rules hold in the code:

1. One tolerated edge to `spatial`: `FlowParam.field` is a `FieldSection`
   of `spatial.field.core.field_param_config`. Today only
   `flow/flow_param_config.py` uses it. Do not extend it.
2. Physics never imports `data`, `simulation` or `solver`. It sees loaded
   data through `LoadResultProto` and a field parameter through
   `FieldParamLike`, both in `contracts.py`. The concrete constructors are
   registered at start-up by `hydromodpy/_bootstrap.py`.
3. Inside the package, `flow/` imports `base`, `contracts`, `forcing` and
   `hydrology`. `forcing/` imports `contracts`. `transport/` imports `base`.
   `base/` reaches `contracts` only inside a function.

Who imports physics: `solver` (most of it), `simulation`, `workflow`,
`calibration`, `config`, `analysis`, `project` and the package root.

## Tree

```
hydromodpy/physics/
  __init__.py                  lazy names: Flow, FlowConfig, Transport, ProcessSpatial, ...
  contracts.py
  base/         process_spatial.py (ProcessSpatial)  process_spatial_config.py
                initial_conditions.py  boundary_conditions.py  sinks_sources.py   (generic models)
                *_config.py (normalizers)  forcing.py
  forcing/      forcing_bridge.py  time_alignment.py  validation.py  types.py
  hydrology/    soil_reservoir/  synthetic/  pyhelp/
  flow/         flow.py  flow_config.py  flow_param_config.py  flow_toml_loader.py
                flow_runtime_*.py  initial_conditions*.py  boundary_condition*.py
                sinks_sources/  structure_binders.py  time_forcing.py  history_contract.py
                physical_properties.py  regime.py
  transport/    transport.py  transport_config.py
```

`base/README.md` and `flow/README.md` are older notes of their folder; read
the code of `flow_config.py` before trusting a key written there.

## How a flow is built

1. **Read.** `HydroModPyConfig.from_toml` hands the `[flow]` table to
   `FlowConfig.from_toml_section` (`flow_toml_loader.py`). It canonicalizes
   boundary ids, resolves well and boundary forcing paths, and validates the
   table into a `FlowConfig`.
2. **Build.** `Flow(config=cfg.flow)` runs `set_config`. It fills `parameters`
   (`FieldParam` objects, through the hooks of `contracts.py`),
   `initial_conditions`, `boundary_conditions` and `sinks_sources`. Well fluxes
   and recharge are converted to SI there. `ensure_flow` (`simulation/execution/runner.py`) builds a
   missing one; `workflow/steps/setup.py` and `workflow/steps/data.py` call it,
   and `workflow/steps/planning.py` builds a fresh one for a run with overrides.
3. **Bind data.** After the data step, `workflow/steps/data.py` calls the
   `apply_*_to_flow` functions of `flow/structure_binders.py`: oceanic levels,
   recharge and ETP (through `forcing.resolve_forcing`), lake geometry,
   abacus and bathymetry, lake fluxes and meteo, barriers, SFR reaches, runoff
   routed to SFR. The same cascade runs for a calibration trial.
4. **Resolve time.** `apply_simulation_time_to_flow_wells` and
   `apply_simulation_time_to_flow_boundary_conditions` turn forcings into
   one value per stress period against `[simulation.time]`.
5. **Solve.** A solver adapter reads the `Flow`. Boundary support per backend
   comes from `FLOW_BOUNDARY_DEFINITIONS`; the adapter never parses a TOML
   dictionary.

A soil reservoir (`[flow.sinks_sources.recharge.soil]`) is read by the
recharge binder of every run, and `simulation/soil_recharge.py` turns the
config into the kernel parameters. It applies to MODFLOW 6 only.

## Where to add what

| to add | where |
|---|---|
| a flow parameter | a field on `FlowConfig`, with a profile and a description; see `docs/source/contribute/architecture/how-to/add-a-config-field.rst` |
| a boundary id | an entry of `FLOW_BOUNDARY_DEFINITIONS` in `flow/boundary_condition_registry.py`, then the solver that builds it |
| a sink or source kind | a payload module in `flow/sinks_sources/`, a field on `FlowSinksSourcesConfig` in `container.py`, a `Flow.sinks_sources` key in `Flow.set_sinks_sources` |
| a way to bring loaded data into a `Flow` | an `apply_*_to_flow` function in `flow/structure_binders.py`, called from `workflow/steps/data.py` |
| an initial-condition type | a model in `flow/initial_conditions.py` and its entry in `FlowInitialConditions` |
| a new process | a subpackage that subclasses `ProcessSpatial`, with a config on `ProcessSpatialConfig`; see `docs/source/contribute/architecture/how-to/add-a-process.rst` |
| a soil-reservoir option | a field on `SoilReservoirConfig` (`config.py`), its use in `kernel.py` or `simulation/soil_recharge.py` |
