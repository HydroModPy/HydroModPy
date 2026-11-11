# Boundary table

The boundary conditions of a flow, and the binders that put the loaded data on a built `Flow`. The boundary ids form a closed table, `FLOW_BOUNDARY_DEFINITIONS` of `boundary_condition_registry.py`, where a new condition is a row added in the code and never a plugin. The table names no backend: a backend lists the ids it poses in its `supports`, and `config/cross_checks.py` refuses a file that asks for one it does not list.

## What a row holds

A `FlowBoundaryDefinition` row holds the id and its kind (`default_type`, which types the payload). The other names below are for the reader, and no code reads them. The four sides share a row, because each side is the same condition on another edge of the domain.

| id | kind | MODFLOW 6 package | NWT record | Boussinesq name | budget term |
|---|---|---|---|---|---|
| `west_side`, `east_side`, `north_side`, `south_side` | `dirichlet` | `CHD` | `BAS/CHD` | `prescribed_head` | `constant_head` |
| `stream` | `dirichlet` | `CHD` | not posed | `prescribed_head` | `constant_head`, and `constant_head_stream` for the cells of the stream role in MODFLOW 6 |
| `ocean` | `dirichlet` | `CHD` | `BAS/CHD` | `prescribed_head` | `constant_head` |
| `drainage` | `drain` | `DRN` | `DRN` | `top_drainage` | `drain` |
| `lake` | `lake` | `LAK` | not posed | not posed | `lake` |
| `sfr` | `sfr` | `SFR` | not posed | not posed | `stream` |

## What the binders receive and return

The binders are called in turn by `workflow/steps/data.py` after the data are loaded, and the same cascade runs for a calibration trial. Each `apply_*_to_flow` function receives a `Flow` and loaded objects, leaves the `Flow` ready for the solver, and refuses a value it cannot place. They read no file from disk: lake polygons, abacus tables, bathymetry rasters and barrier lines are loaded in `data` and reach the binders as objects, through `model/contracts.LoadResultProto`.

## What is refused and what tests it

`lake` and `sfr` are advanced packages declared under `[flow.sinks_sources.lakes]` and `[flow.sinks_sources.sfr]`, so `[flow.bc]` accepts the other seven ids and refuses any other key with the list of the seven. A new row joins the `supports` vocabulary of `model/supports.py` by itself, because that vocabulary reads the table, and `tests/ports/test_solver.py` checks that every trait a backend declares is a known one.
