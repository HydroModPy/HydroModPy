# solver/boussinesq/runtimes

The engines that solve one Boussinesq step or steady problem. Each engine module exposes `solve_steady_problem` and `solve_transient_step`, and `catalog.py` names the module of each engine.

## Engines

1. `local.py`: dense Newton with line search, for small meshes.
2. `scipy_dense.py`: SciPy hybrid root solve, dense.
3. `scipy_sparse.py`: sparse Newton, the cross-platform reference on larger meshes.
4. `petsc_partition.py`: PETSc SNES on the head-only system with the regularized partition.
5. `petsc_mixed.py` (with `petsc_mixed_common.py`): PETSc SNES on the mixed head and surface-excess system, with a Fischer-Burmeister complementarity.
6. `petsc_vi_obstacle.py` (with `petsc_vi/`): PETSc SNESVI, the head bounded between the bottom and the top, the surface and bottom reactions rebuilt after convergence.
7. `petsc_ts_vi_obstacle.py`: the same obstacle problem integrated by PETSc TS with backward Euler steps.

## Shared helpers

`execution_common.py`, `head_only_common.py`, `newton_common.py`, `partition_utils.py`, `petsc_common.py` and `vi_bounds.py` are what several engines share. `dry_equilibrium.py` detects a dry steady equilibrium before the solve.

## Diagnostics

`vi_obstacle_diagnostics.py`, `ts_vi_obstacle_diagnostics.py` and `stationary_failure_diagnostics.py` write the CSV and JSON diagnostics of a run, under the file names of `diagnostic_files.py`. `diagnostics_io.py` holds the CSV and JSON helpers they share.

The Picard and L-scheme initializer for steady obstacle problems is not here. No `[flow.runtime] backend` selects it, so it sits in `hydromodpy_annex/solver/boussinesq_picard/`.
