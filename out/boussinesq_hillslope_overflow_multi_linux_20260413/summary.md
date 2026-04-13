# Multi-Solver Boussinesq Overflow Comparison

This report compares multiple Boussinesq surface-interaction formulations on the same transient hillslope overflow case.

- solvers: `['boussinesq', 'petsc_partition', 'petsc']`
- forcing preset: `strong`
- forcing scale: `1.000`
- dt_days override: `None`
- east_head override: `None`
- initial_head override: `None`

| Solver | Backend | Surface law | Onset day [d] | Peak total overflow [m3/day] | Peak day [d] | Max h-z [m] | Wall time [s] | Results dir |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Local dense runtime | local | regularized_partition | 8.00 | 69.502 | 20.00 | -0.1622 | 58.75 | `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_20260413/validation/run_multi_solver_case/boussinesq_hillsl_07d97bd987` |
| PETSc regularized partition | petsc | regularized_partition | 8.00 | 69.503 | 20.00 | -0.1622 | 15.46 | `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_20260413/validation/run_multi_solver_case/boussinesq_hillsl_6a3172c37d` |
| PETSc complementarity | petsc | complementarity | 20.00 | 26.065 | 20.00 | 0.0000 | 2.10 | `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_20260413/validation/run_multi_solver_case/boussinesq_hillsl_9c566ea726` |

Total overflow overlay: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_20260413/figures/total_overflow_overlay.png`
Execution times: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_20260413/figures/execution_times.png`
