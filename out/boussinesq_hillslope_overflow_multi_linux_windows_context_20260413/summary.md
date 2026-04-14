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
| Local dense runtime | local | regularized_partition | 3.00 | 168.126 | 20.00 | -0.5788 | 58.12 | `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/validation/run_multi_solver_case/boussinesq_hillsl_07d97bd987` |

Head snapshots: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/head_snapshots.png`
Head point time series: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/head_point_timeseries.png`
Flux chronicle: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/flux_timeseries.png`
Total overflow overlay: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/total_overflow_overlay.png`
Outflow components: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/outflow_components.png`
Complete flux budget: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/flux_budget_comparison.png`
Execution times: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/execution_times.png`

| PETSc regularized partition | petsc | regularized_partition | 3.00 | 168.124 | 20.00 | -0.5788 | 10.54 | `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/validation/run_multi_solver_case/boussinesq_hillsl_6a3172c37d` |

Head snapshots: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/head_snapshots.png`
Head point time series: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/head_point_timeseries.png`
Flux chronicle: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/flux_timeseries.png`
Total overflow overlay: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/total_overflow_overlay.png`
Outflow components: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/outflow_components.png`
Complete flux budget: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/flux_budget_comparison.png`
Execution times: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/execution_times.png`

| PETSc complementarity | petsc | complementarity | 19.00 | 100.256 | 20.00 | -0.1194 | 1.51 | `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/validation/run_multi_solver_case/boussinesq_hillsl_9c566ea726` |

Head snapshots: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/head_snapshots.png`
Head point time series: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/head_point_timeseries.png`
Flux chronicle: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/flux_timeseries.png`
Total overflow overlay: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/total_overflow_overlay.png`
Outflow components: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/outflow_components.png`
Complete flux budget: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/flux_budget_comparison.png`
Execution times: `/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260413/figures/execution_times.png`
