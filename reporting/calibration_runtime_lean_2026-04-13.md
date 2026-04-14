# Calibration Runtime Lean Profiling

Date: 2026-04-13

## Scope

Transient calibration twin case:

- case: `calibration_twin_linearized_recharge_step_modflow6`
- methods: `simplex`, `da_mh_gp`
- solver: `modflow6`

Three profiling states were compared:

1. `baseline`
2. `after_runtime_lean`
3. `after_solvermesh_cache`
4. `after_solver_reuse`

Artifacts:

- baseline: `reporting/calibration_profiling_2026-04-13`
- after runtime lean: `reporting/calibration_profiling_2026-04-13_after_runtime_lean`
- after solver-mesh cache: `reporting/calibration_profiling_2026-04-13_after_solvermesh_cache`
- after solver reuse: `reporting/calibration_profiling_2026-04-13_after_solver_reuse`

## Changes Applied

### Runtime lean

- calibration candidates now skip heavy solver post-processing via
  `flow_runtime_overrides.skip_solver_postprocess`
- calibration output selection can read selected MODFLOW 6 variables directly from
  raw solver outputs when `_postprocess` artifacts are absent
- runtime canonicalization is restricted to variables actually requested by the
  prepared selectors

### Solver-mesh cache fix

- `SolverMesh` is a frozen dataclass, so plain `setattr(...)` did not persist the
  calibration coordinate cache
- output-selection coordinate caching now falls back to `object.__setattr__(...)`
  when possible, which makes the cache effective on real solver meshes

### Solver reuse and partial MF6 write

- reusable calibration candidates now keep one stable MF6 model name/workspace
- the `flow/modflow6` adapter reuses one `Modflow6` instance across lean
  calibration candidates
- `Modflow6.pre_processing(...)` refreshes hydraulic packages in place when the
  runtime structure is unchanged
- `Modflow6.processing(...)` rewrites only dirty packages (`NPF`, `STO`, and
  `DRN` when conductivity-derived drainage is active) instead of calling
  `write_simulation(...)` every time
- raw solver-output caches are cleared before each reused candidate run
- the compatibility pickle emitted before each candidate run is skipped in lean
  calibration mode

## Measured Results

### `simplex`

| metric | baseline | after_runtime_lean | after_solvermesh_cache | after_solver_reuse |
| --- | ---: | ---: | ---: |
| calibration total (s) | 112.65 | 106.32 | 83.50 | 27.85 |
| mean candidate total (s) | 4.85 | 4.56 | 3.59 | 1.16 |
| mean candidate simulation (s) | 3.37 | 3.63 | 3.24 | 0.73 |
| mean candidate output selection (s) | 1.43 | 0.88 | 0.30 | 0.38 |
| mean candidate objective total (s) | 1.43 | 0.88 | 0.30 | 0.38 |

Net gain versus baseline:

- total calibration time: `-84.80 s` (`-75.3%`)
- output-selection time per candidate: `-1.05 s` (`-73.2%`)

### `da_mh_gp`

| metric | baseline | after_runtime_lean | after_solvermesh_cache | after_solver_reuse |
| --- | ---: | ---: | ---: |
| calibration total (s) | 130.90 | 97.11 | 93.20 | 24.53 |
| mean candidate total (s) | 4.99 | 3.69 | 3.54 | 0.90 |
| mean candidate simulation (s) | 3.42 | 2.99 | 3.20 | 0.53 |
| mean candidate output selection (s) | 1.54 | 0.66 | 0.29 | 0.32 |
| mean candidate objective total (s) | 1.54 | 0.66 | 0.29 | 0.32 |

Net gain versus baseline:

- total calibration time: `-106.37 s` (`-81.3%`)
- output-selection time per candidate: `-1.22 s` (`-79.1%`)

## Hotspots After Optimization

### `simplex`

From `reporting/calibration_profiling_2026-04-13_after_solver_reuse/transient_k_sy__simplex_pstats.txt`:

- `flopy.mf6.mfsimbase.run_simulation`: `12.62 s`
- `launchers.model_calibration.output_selection.select_candidate_outputs_from_selectors`: `8.84 s`
- `flopy.utils.binaryfile.CellBudgetFile` indexing/open path: about `7.11 s`
- `flopy.mf6.mfsimbase.write_simulation` is no longer a dominant hotspot in the
  current lean profile
- `_persist_pre_run_payload(...)` is no longer among the dominant cumulative
  costs

### `da_mh_gp`

From `reporting/calibration_profiling_2026-04-13_after_solver_reuse/transient_k_sy__da_mh_gp_pstats.txt`:

- `flopy.mf6.mfsimbase.run_simulation`: `10.72 s`
- `launchers.model_calibration.output_selection.select_candidate_outputs_from_selectors`: `8.41 s`
- `flopy.utils.binaryfile.CellBudgetFile` indexing/open path: about `6.73 s`
- `da_mh_gp` algorithm overhead remains modest relative to model execution:
  about `1.19 s` over the full run
- `_persist_pre_run_payload(...)` is no longer among the dominant cumulative
  costs

## Interpretation

The large opaque bucket previously attributed to "simulation" was not mostly
`mf6.exe`. After the lean-runtime changes and solver reuse:

- heavy solver post-processing is no longer part of the candidate loop
- output selection is no longer the dominant overhead
- repeated full `write_simulation(...)` calls are no longer the main cost
- the remaining hot spots are now:
  - actual MF6 execution
  - raw output reopening/indexing
  - lightweight selected-output extraction

In other words, the candidate loop is now much closer to the true lower-level
cost structure:

1. prepare/update model packages
2. write MF6 input files
3. run `mf6.exe`
4. read only the calibration outputs that matter

## Practical Conclusion

The optional work that should stay disabled by default for calibration is now
largely under control:

- solver post-processing: disabled
- generic full output canonicalization: reduced to requested variables only
- repeated solver-mesh centroid rebuild: fixed by effective caching

The next major optimization frontier is now the selected-output read path rather
than the full FloPy rewrite path. Any further large gain will likely require
reducing or reusing:

- repeated raw-budget / head-file index construction
- repeated binary reopening in `_modflow6_raw_output_payloads(...)`
- Python-side stream reading around `flopy.mf6.mfsimbase.run_simulation(...)`
