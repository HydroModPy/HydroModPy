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

Artifacts:

- baseline: `reporting/calibration_profiling_2026-04-13`
- after runtime lean: `reporting/calibration_profiling_2026-04-13_after_runtime_lean`
- after solver-mesh cache: `reporting/calibration_profiling_2026-04-13_after_solvermesh_cache`

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

## Measured Results

### `simplex`

| metric | baseline | after_runtime_lean | after_solvermesh_cache |
| --- | ---: | ---: | ---: |
| calibration total (s) | 112.65 | 106.32 | 83.50 |
| mean candidate total (s) | 4.85 | 4.56 | 3.59 |
| mean candidate simulation (s) | 3.37 | 3.63 | 3.24 |
| mean candidate output selection (s) | 1.43 | 0.88 | 0.30 |
| mean candidate objective total (s) | 1.43 | 0.88 | 0.30 |

Net gain versus baseline:

- total calibration time: `-29.14 s` (`-25.9%`)
- output-selection time per candidate: `-1.13 s` (`-78.9%`)

### `da_mh_gp`

| metric | baseline | after_runtime_lean | after_solvermesh_cache |
| --- | ---: | ---: | ---: |
| calibration total (s) | 130.90 | 97.11 | 93.20 |
| mean candidate total (s) | 4.99 | 3.69 | 3.54 |
| mean candidate simulation (s) | 3.42 | 2.99 | 3.20 |
| mean candidate output selection (s) | 1.54 | 0.66 | 0.29 |
| mean candidate objective total (s) | 1.54 | 0.66 | 0.29 |

Net gain versus baseline:

- total calibration time: `-37.70 s` (`-28.8%`)
- output-selection time per candidate: `-1.25 s` (`-81.0%`)

## Hotspots After Optimization

### `simplex`

From `reporting/calibration_profiling_2026-04-13_after_solvermesh_cache/transient_k_sy__simplex_pstats.txt`:

- `flopy.mf6.mfsimbase.write_simulation`: `52.36 s`
- `flopy.mf6.mfsimbase.run_simulation`: `16.19 s`
- `hydromodpy.solver.modflow6.modflow6.pre_processing`: `8.08 s`
- `launchers.model_calibration.output_selection.select_candidate_outputs_from_selectors`: `6.95 s`

### `da_mh_gp`

From `reporting/calibration_profiling_2026-04-13_after_solvermesh_cache/transient_k_sy__da_mh_gp_pstats.txt`:

- `flopy.mf6.mfsimbase.write_simulation`: `58.52 s`
- `flopy.mf6.mfsimbase.run_simulation`: `18.34 s`
- `hydromodpy.solver.modflow6.modflow6.pre_processing`: `9.31 s`
- `launchers.model_calibration.output_selection.select_candidate_outputs_from_selectors`: `7.64 s`

## Interpretation

The large opaque bucket previously attributed to "simulation" was not mostly
`mf6.exe`. After the lean-runtime changes:

- heavy solver post-processing is no longer part of the candidate loop
- output selection is no longer the dominant overhead
- the main remaining cost is now clearly the repeated FloPy input writing step
  (`write_simulation`)

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

The next major optimization frontier is no longer post-processing. It is the
full FloPy rewrite path. Any further large gain will likely require reducing or
reusing:

- package rebuilds in `pre_processing`
- `write_simulation(...)` calls
- repeated raw-budget reader initialization in the selected-output path
