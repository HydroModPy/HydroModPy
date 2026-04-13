# Multi-Solver Boussinesq Overflow Comparison

This report compares multiple Boussinesq surface-interaction formulations on the same transient hillslope overflow case.

- solvers: `['boussinesq', 'scipy_sparse']`
- forcing preset: `strong`
- forcing scale: `1.000`
- dt_days override: `None`
- east_head override: `None`
- initial_head override: `None`

| Solver | Backend | Surface law | Onset day [d] | Peak total overflow [m3/day] | Peak day [d] | Max h-z [m] | Wall time [s] | Results dir |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Local dense runtime | local | regularized_partition | 8.00 | 69.502 | 20.00 | -0.1622 | 54.08 | `C:\codes\HydroModPy-GH\out\boussinesq_hillslope_overflow_multi_smoke_20260413\validation\run_multi_solver_case\boussinesq_hillsl_07d97bd987_8c3bb686` |
| SciPy sparse regularized partition | scipy_sparse | regularized_partition | 8.00 | 69.502 | 20.00 | -0.1622 | 2.60 | `C:\codes\HydroModPy-GH\out\boussinesq_hillslope_overflow_multi_smoke_20260413\validation\run_multi_solver_case\boussinesq_hillsl_18833a8e1f_c6d7fd55` |

Total overflow overlay: `C:\codes\HydroModPy-GH\out\boussinesq_hillslope_overflow_multi_smoke_20260413\figures\total_overflow_overlay.png`
Execution times: `C:\codes\HydroModPy-GH\out\boussinesq_hillslope_overflow_multi_smoke_20260413\figures\execution_times.png`
