# Temporal

`hydromodpy/discretization/time/` contains the neutral time-grid layer used to
build period lengths and time-step arrays.

- `tmesh_generation.py`: temporal mesh/grid generation class (`TmeshGenerator`).
- `tmesh_config.py`: Pydantic model (`TMeshConfig`) + TOML helpers.
- `tmesh_config.toml`: minimal template with all `TmeshGenerator` entries.
- `cases/`: runnable demo cases (`run_tmesh_case.py`) and sample TOML.

## Launcher Time-Scale Diagnostic

In launcher-driven runs, several temporal definitions coexist. They are not all
at the same level.

1. Canonical window: `[simulation.time]`
- Used by launcher-level orchestration and forcing coverage checks.
- In launcher mode, this window is explicit and copied from
  `simulation.time.start_datetime/end_datetime` into both solver tgrids.
- Launcher flow solvers consume the canonical `time_grid` derived from this
  section; solver `tgrid` is no longer a fallback path.

2. Flow policy: `[flow].flow_regime` and `[flow].first_period_steady`
- Authoritative for steady/transient behavior in launcher flows.
- Consumed by solver adapters when they assemble MODFLOW `steady` arrays.
- Temporal mesh generation does not import `physics` and does not decide
  steady/transient solver policy.

3. Solver temporal mesh: `[modflownwt.tgrid]` / `[modflow6.tgrid]`
- Defines stress-period structure (`nper`, `perlen`, `nstp`, `tsmult`).
- In launcher mode, this section is mirrored from `[simulation.time]`.
- Legacy `flow_regime` and `firstpersteady` keys may still be parsed for old
  files, but they are ignored by temporal mesh generation.
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

Input schema is `TMeshConfig` with key fields:

- `itmuni`, `genmtd`, `nper`, `lenper`, `chron_*`, `start_datetime`,
  `end_datetime`, `ntsp`, `tsmult`.

Generated runtime object (`TimeGrid`, HydroModPy-native frozen dataclass) exposes:

- `time_units`: textual time-unit label,
- `start_datetime`: origin timestamp,
- `perlen`: stress-period lengths,
- `nstp`: time steps per stress period,
- `tsmult`: per-period time-step multiplier,
- `steady_state`: legacy neutral flags; solver adapters derive effective
  steady/transient flags from `[flow]`,
- `totim`: cumulative period lengths (in `time_units`),
- `datetimes`: tuple of period-end timestamps (empty when `start_datetime` is None).

Backends translate this POPO to their own structures (FloPy `ModelTime`,
MODFLOW DIS/TDIS payloads, ...). No FloPy import survives at this layer.

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
