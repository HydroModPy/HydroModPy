# MODFLOW BAS Contract (`ibound`, `strt`)

This note documents how HydroModPy prepares `ibound` and `strt` for the MODFLOW-NWT BAS package.

## Why this matters

`ibound` and `strt` are the most sensitive startup arrays in MODFLOW:

- `ibound` controls **where** head is solved vs imposed vs inactive.
- `strt` controls **which head values** are used at startup and for constant-head cells.

If these two arrays are inconsistent, simulations can silently become unstable or physically inconsistent.

## MODFLOW semantics used in HydroModPy

HydroModPy follows the standard BAS sign-based contract:

1. `ibound > 0`: active cell (head is computed by MODFLOW).
2. `ibound = 0`: inactive/no-flow cell.
3. `ibound < 0`: constant-head cell (head is imposed).

`strt` is a 3D startup head array (`nlay, nrow, ncol`).  
For constant-head cells (`ibound < 0`), `strt` provides the imposed head values used by BAS.

## Where arrays are built

Primary source of truth:

- `hydromodpy/solver/modflow_nwt/modflow/flow_to_modflow_adapter.py`
  - `FlowToModflowAdapter._build_initial_heads_and_sides`
  - `FlowToModflowAdapter._build_ocean_chd`
  - `FlowToModflowAdapter._validate_ibound_strt_contract`

Assembly point:

- `hydromodpy/solver/modflow_nwt/modflow/nwt_solver.py`
  - `flopy.modflow.ModflowBas(..., ibound=self.iboundData, strt=self.strtData, ...)`

## Mapping from process inputs to BAS arrays

`strt` initialization policy comes from `flow.initial_conditions.h.type`:

1. `top`: initialize from DEM.
2. `bottom`: initialize from bottom-layer elevation.
3. `custom`: initialize from one scalar user value.

Then side Dirichlet boundaries (`west/east/north/south`) are applied:

1. set face cells to `ibound = -1`,
2. overwrite matching `strt` faces with boundary head values.

Then no-data mask convention is applied:

1. DEM cells below sentinel threshold are set to `ibound = 0`.

Then ocean boundary can modify both arrays:

1. scalar ocean level can set submerged cells to `ibound < 0` and overwrite `strt`,
2. transient ocean forcing generates CHD stress-period payload and can disable drainage support locally.

## Contract checks enforced in code

Before package assembly continues, adapter validation checks:

1. `ibound` shape is exactly `(nlay, nrow, ncol)`.
2. `strt` shape is exactly `(nlay, nrow, ncol)`.
3. `drain_array` shape is exactly `(nrow, ncol)`.
4. all values are finite.
5. `drain_array` is binary (`0` or `1`).

The adapter intentionally validates the sign-based BAS semantics for `ibound`, not only `{-1, 0, 1}`.

## Practical debugging tips

1. Check boundary assignment order first (initial condition, then side BC, then ocean BC).
2. Inspect `ibound` sign masks (`>0`, `=0`, `<0`) before running solver.
3. Plot `strt` slices for constant-head faces and ocean-influenced zones.
4. Treat any non-finite values in `ibound/strt` as a hard error.
