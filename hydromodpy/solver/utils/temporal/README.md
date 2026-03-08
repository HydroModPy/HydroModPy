# Temporal

`hydromodpy/solver/utils/temporal/` contains the time-discretization layer used
to build solver stress periods.

- `tmesh_generation.py`: temporal mesh/grid generation class (`TMesh_Generation`)
  with typed runtime config (`TMeshConfig`) and backward-compatible alias
  (`TGrid_Generation`).
- `tmesh_config.py`: Pydantic model (`TMeshConfigModel`) + TOML helpers.
- `tmesh_config.toml`: minimal template with all `TMesh_Generation` entries.
- `cases/`: runnable demo cases (`run_tmesh_case.py`) and sample TOML.

## Launcher Time-Scale Diagnostic

In launcher-driven runs, several temporal definitions coexist. They are not all
at the same level.

1. Canonical window: `[simulation.time]`
- Used by launcher-level orchestration and forcing coverage checks.
- If `simulation.time.mode="explicit"`, the launcher copies
  `simulation.time.start_datetime/end_datetime` into both solver tgrids.
- If `simulation.time.mode="from_modflow"`, the canonical window is read from
  flow-solver tgrid bounds (`start_datetime/end_datetime`).

2. Process regime: `[flow].flow_regime`
- Authoritative for steady/transient behavior in launcher flows.
- Injected at runtime into temporal mesh generation for both MODFLOW-NWT and
  MODFLOW 6 flow adapters.
- Practical consequence: `modflow6.tgrid.flow_regime` is overwritten during
  launcher execution.

3. Solver temporal mesh: `[modflownwt.tgrid]` / `[modflow6.tgrid]`
- Defines stress-period structure (`nper`, `perlen`, `nstp`, `steady_state`).
- Generation method:
  - `genmtd="synthetic_regular"`: regular periods from `nper` + `lenper`.
  - `genmtd="from_chron"`: variable periods from chronicle timestamp deltas.

## Window Semantics

`start_datetime` and `end_datetime` represent bounds used to define durations.

- For `synthetic_regular`, enforced constraint is:
  `end_datetime - start_datetime == nper * lenper`.
- For `from_chron`, if bounds are provided they must match chronicle timestamps
  exactly.

This is duration-based semantics (upper bound), not "count every calendar day
between two inclusive dates".

## TGrid Format Consumed By MODFLOW

Input schema is `TMeshConfigModel` with key fields:

- `itmuni`, `genmtd`, `nper`, `lenper`, `chron_*`, `start_datetime`,
  `end_datetime`, `firstpersteady`, `ntsp`, `tsmult`.

Generated runtime object (`flopy.discretization.modeltime.ModelTime`) exposes:

- `time_units`: textual time-unit label,
- `start_datetime`: origin timestamp,
- `perlen`: stress-period lengths,
- `nstp`: time steps per stress period,
- `tsmult`: per-period time-step multiplier,
- `steady_state`: steady/transient flags per stress period.

### Mapping To MODFLOW-NWT

Current `ModflowDis` payload uses:

- `itmuni`, `nper`, `perlen`, `nstp`, `steady`, `start_datetime`.

`tsmult` is currently not forwarded by the NWT wrapper.

### Mapping To MODFLOW 6

Current `ModflowTdis` payload uses:

- `nper`,
- `perioddata[(perlen[k], nstp[k], tsmult_k)]`,
- `time_units`.

The current wrapper sets `tsmult_k = 1.0` for all periods, even if `tgrid`
defines another `tsmult`.

## Important Unit Note

The current temporal builder computes `perlen` from timedeltas and normalizes
to day-equivalent floats. In practice, keep `itmuni="days"` to avoid ambiguity.

