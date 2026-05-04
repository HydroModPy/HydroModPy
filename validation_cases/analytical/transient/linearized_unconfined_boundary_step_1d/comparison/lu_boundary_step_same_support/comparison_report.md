# Simulation Comparison Report: modflow6

- Audit status: `pass`
- Audit issues: 0
# Simulation Comparison Report: lu_boundary_step_same_support

- Reference simulation: `modflow6`
- Completed simulations: 2 / 2
- Observable rows: 1240
- Comparable metric groups: 5
- Unmatched row groups: 0

## Simulations
- `modflownwt`: reused, solver=`modflownwt`, mesh=`structured`, rows=620, wall_time=, run_folder=`C:\codes\HydroModPy\tmp\lu_boundary_step_same_support_workspace`
- `modflow6`: reused, solver=`modflow6`, mesh=`structured`, rows=620, wall_time=, run_folder=`C:\codes\HydroModPy\tmp\lu_boundary_step_same_support_workspace`

## Observables
- `head_west_response`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_mid_response`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_east_response`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_map_last`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `depth_map_last`: variable=`watertable_depth`, support=`map`, unit=`m`

## Figures
- `map_comparison` / `head_map_last`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_map_last__map_comparison.png`
- `difference_map` / `head_map_last`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_map_last__difference__modflow6__vs__modflownwt.png`
- `map_triptych` / `head_map_last`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_map_last__triptych__modflow6__vs__modflownwt.png`
- `map_comparison` / `depth_map_last`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\depth_map_last__map_comparison.png`
- `difference_map` / `depth_map_last`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\depth_map_last__difference__modflow6__vs__modflownwt.png`
- `map_triptych` / `depth_map_last`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\depth_map_last__triptych__modflow6__vs__modflownwt.png`
- `timeseries` / `head_east_response`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_east_response__timeseries.png`
- `timeseries` / `head_mid_response`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_mid_response__timeseries.png`
- `timeseries` / `head_west_response`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_west_response__timeseries.png`
- `point_dashboard` / `head_points`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_points_dashboard.png`
- `budget_diagnostics` / `budget`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\modflow6__budget_diagnostics.png`
- `budget_diagnostics` / `budget`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\modflownwt__budget_diagnostics.png`
- `simulated_active_network_figures_skipped_json` / ``: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\simulated_active_network_figures_skipped.json`

## Data Exports
- `comparison_audit_json`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_audit.json`
- `comparison_audit_md`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_audit.md`
- `timeseries_long_csv`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\timeseries_long.csv`
- `timeseries_wide_csv`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\timeseries_wide.csv`
- `timeseries_delta_csv`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\timeseries_delta.csv`
- `hydrographic_network_metrics_skipped_json`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\hydrographic_network_metrics_skipped.json` (2 simulation(s) skipped for hydrographic-network metrics export.)
- `simulated_active_network_metrics_skipped_json`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\simulated_active_network_metrics_skipped.json` (2 simulation(s) skipped for simulated-active network metrics export.)
- `simulated_active_network_overlap_metrics_skipped_json`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\simulated_active_network_overlap_metrics_skipped.json` (2 simulation(s) skipped for simulated-active network overlap metrics export.)
- `simulated_active_network_distance_metrics_skipped_json`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\simulated_active_network_distance_metrics_skipped.json` (2 simulation(s) skipped for simulated-active network distance metrics export.)
- `budget_timeseries_long_csv`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\budget_timeseries_long.csv`
- `budget_timeseries_wide_csv`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\budget_timeseries_wide.csv`

## Metrics
| Simulation | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| modflownwt | depth_map_last | m | 250 | 0 | 0 | 0 | 0 | 0 |
| modflownwt | head_east_response | m | 40 | 0 | 0 | 0 | 0 | 0 |
| modflownwt | head_map_last | m | 250 | 0 | 0 | 0 | 0 | 0 |
| modflownwt | head_mid_response | m | 40 | 0 | 0 | 0 | 0 | 0 |
| modflownwt | head_west_response | m | 40 | 0 | 0 | 0 | 0 | 0 |

## Gaps
- No unmatched rows.
