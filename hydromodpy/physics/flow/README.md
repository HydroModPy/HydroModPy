# physics/flow

The groundwater-flow process: what `[flow]` can say, and the `Flow` object the solvers read.

## Modules, in the order a run uses them

1. `flow_toml_loader.py` reads the raw `[flow]` table: it canonicalizes the boundary ids and resolves the CSV paths of the forcings (`resolve_forcing_paths`).
2. `flow_config.py` is `FlowConfig`, the `[flow]` schema, with `FlowParam` for each `[flow.param.<id>]` (its sections come from `core/config_kit/field_param/`) and `RestartReference`.
3. `runtime_config.py` is `[flow.runtime]`, the settings of the Boussinesq solve.
4. `initial_conditions.py` holds the six head initial conditions and `normalize_flow_initial_conditions`, which reads the flat `[flow.ic]` table.
5. `boundary_condition_registry.py` is the table of boundary ids, their domain, family and backend packages (`FLOW_BOUNDARY_DEFINITIONS`), and `BoundaryConditionBundle`, the view the solvers read. `boundary_conditions.py` holds the Dirichlet and drain payloads and reads the registry.
6. `sinks_sources/` holds one payload per sink or source (see its README).
7. `flow.py` is the runtime `Flow`, built from a `FlowConfig`.
8. `binders/` puts the loaded data on a built `Flow` (see its README). `cutoff_wall_shore.py` lays a dam wall on the lake shore and derives an automatic dam axis, in pure shapely.
9. `time_forcing.py` resolves a dated forcing to one value per stress period; the solvers call it. `history_contract.py` gives the time axes of transient histories.
10. `property_ids.py`, `regime.py` and `physical_properties.py` are small vocabularies: the hydraulic property ids, `steady` or `transient`, and `FlowPhysicalProperties`.
11. `toml_examples.py` renders the commented examples of the dynamic `[flow.*]` blocks for the TOML template; `_bootstrap.py` wires it into `core/toml_io/`.

## Where to start

| To change | Open first |
|---|---|
| a key of `[flow]` | `flow_config.py` |
| a boundary id or the package a backend uses | `boundary_condition_registry.py` |
| how loaded data reaches the `Flow` | `binders/` |
| how a forcing becomes one value per period | `time_forcing.py` |
