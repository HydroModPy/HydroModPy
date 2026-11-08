# model/boundaries

The boundary conditions of a flow, and what the data step puts on a built `Flow`. The registry lists the
boundary ids, their domain and their family. It names no backend: a backend says which ids it poses in its
`supports`, and `config/cross_checks.py` refuses a file that asks for one it does not list. The binders are called by
`workflow/steps/data.py` in turn, after the data are loaded, and the same cascade runs for a calibration
trial. Each `apply_*_to_flow` function leaves the `Flow` ready for the solver, and refuses a value it
cannot place.

## Modules

| module | answers |
|---|---|
| `barriers.py` | Reads a barrier trace, inline or from a file, and puts the flow barriers on the flow |
| `binder_payloads.py` | The lake and SFR payloads of a Flow as plain dicts the binders can enrich |
| `boundary_condition_registry.py` | The table of boundary ids (`FLOW_BOUNDARY_DEFINITIONS`) and `BoundaryConditionBundle`, the view the solvers read |
| `boundary_conditions.py` | The Dirichlet and drain payloads of `[flow.bc]` |
| `climate.py` | Sea level, recharge and ETP put on a Flow, from loaded forcings |
| `cutoff_wall_shore.py` | Lay a declared cutoff-wall trace on the lake shore it faces |
| `lakes.py` | Geometry, abacus, bathymetry, cutoff wall and forcings put on the lakes of a Flow |
| `streams.py` | SFR reach networks put on a Flow, and the catchment runoff they route |

`boundary_conditions.py` reads the registry. Of the binders, `climate.py` puts the sea level on the ocean
boundary and the recharge and ETP on the flow (`apply_oceanic_to_flow`,
`apply_recharge_load_result_to_flow`, `apply_etp_load_result_to_flow`), and `watershed_mean_rates` gives
the catchment mean of a loaded series, which the lakes and streams also read. `lakes.py` puts on each lake
its geometry, abacus, bathymetry, cutoff wall, inflow and withdrawal, and its meteo forcings. `streams.py`
puts the SFR reach networks on the flow and routes the catchment runoff to them. `barriers.py` reads a
barrier trace and puts the flow barriers on the flow.

Lakes read streams (a runoff routed by an active SFR is not given to a lake twice), barriers (the wall
trace) and climate. Nothing here imports `data`, because a loaded record is read through
`model/contracts.LoadResultProto`. The package reads `model/model.py` for the annotation of `Flow` only.

## The names of one condition

A condition has one id in the TOML, and every backend and the budget give it another name. The table
reads from the id to the six names. The table of `FLOW_BOUNDARY_DEFINITIONS` holds the id and the kind
(`default_type`, which types the payload). The other columns are for the reader, no code reads them.
The four sides share a row. Each side is the same condition on another edge of the domain.

| id | kind | MODFLOW 6 package | NWT record | Boussinesq name | budget term |
|---|---|---|---|---|---|
| `west_side`, `east_side`, `north_side`, `south_side` | `dirichlet` | `CHD` | `BAS/CHD` | `prescribed_head` | `constant_head` |
| `stream` | `dirichlet` | `CHD` | not posed | `prescribed_head` | `constant_head`, and `constant_head_stream` for the cells of the stream role in MODFLOW 6 |
| `ocean` | `dirichlet` | `CHD` | `BAS/CHD` | `prescribed_head` | `constant_head` |
| `drainage` | `drain` | `DRN` | `DRN` | `top_drainage` | `drain` |
| `lake` | `lake` | `LAK` | not posed | not posed | `lake` |
| `sfr` | `sfr` | `SFR` | not posed | not posed | `stream` |

`lake` and `sfr` are advanced packages. They are not keys of `[flow.bc]`: a lake is declared under
`[flow.sinks_sources.lakes]` and a stream network under `[flow.sinks_sources.sfr]`. `[flow.bc]` accepts
the other seven ids and refuses any other key with the list of the seven.

## Where to start

| To change | Open first |
|---|---|
| a boundary id, its kind or its family | `boundary_condition_registry.py` |
| a Dirichlet or drain payload | `boundary_conditions.py` |
| how loaded data reaches the `Flow` | the `apply_*_to_flow` function of the matching binder |
| the lake payload a binder enriches | `binder_payloads.py` |
