# Simulation Comparison Report: mf6_ref

- Audit status: `pass`
- Audit issues: 0
# Simulation Comparison Report: site_03_natural_n1_10km2_mf6_bouss

- Reference simulation: `mf6_ref`
- Completed simulations: 2 / 2
- Observable rows: 16272
- Comparable metric groups: 4
- Unmatched row groups: 1

## Simulations
- `mf6_ref`: completed, solver=`modflow6`, mesh=`mesh_catchment`, rows=8136, flow_solve_time=73.9032, wall_time=295.6, run_folder=`/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/workspaces/mf6_ref`
- `bouss_candidate`: completed, solver=`boussinesq`, mesh=`mesh_catchment`, rows=8136, flow_solve_time=10.4719, wall_time=231.17, run_folder=`/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/workspaces/bouss_candidate`

## Observables
- `head_map_first_computed`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `head_map_wet_year1`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `head_map_dry_late`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `head_map_last`: variable=`watertable_elevation`, support=`map`, unit=`m`

## Figures
- `case_configuration` / `case_configuration`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/comparison_figures/case_configuration.png`
- `fine_raster_map_comparison` / `head_map_wet_year1`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/comparison_figures/head_map_wet_year1__fine_raster_map_comparison.png`
- `storage_comparison_dashboard` / `storage_change_total_m3_s`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/comparison_figures/storage_comparison_dashboard.png`
- `total_inputs_outputs_dashboard` / `total_inputs_outputs_m3_s`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/comparison_figures/total_inputs_outputs_dashboard.png`
- `simulated_active_network_figure` / ``: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/run_figures/mf6_ref/simulated_active_network.png`
- `simulated_active_network_figure` / ``: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/run_figures/mf6_ref/simulated_active_network_reference_overlay.png`
- `simulated_active_network_figures_skipped_json` / ``: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/simulated_active_network_figures_skipped.json`

## Data Exports
- `comparison_audit_json`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/comparison_audit.json`
- `comparison_audit_md`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/comparison_audit.md`
- `hydrographic_network_metrics_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/hydrographic_network_metrics.csv`
- `simulated_active_network_metrics_skipped_json`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/simulated_active_network_metrics_skipped.json` (1 simulation(s) skipped for simulated-active network metrics export.)
- `simulated_active_network_metrics_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/simulated_active_network_metrics.csv`
- `simulated_active_network_overlap_metrics_skipped_json`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/simulated_active_network_overlap_metrics_skipped.json` (1 simulation(s) skipped for simulated-active network overlap metrics export.)
- `simulated_active_network_overlap_metrics_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/simulated_active_network_overlap_metrics.csv`
- `simulated_active_network_distance_metrics_skipped_json`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/simulated_active_network_distance_metrics_skipped.json` (1 simulation(s) skipped for simulated-active network distance metrics export.)
- `simulated_active_network_distance_metrics_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/simulated_active_network_distance_metrics.csv`
- `release_flux_network_overlap_metrics_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/release_flux_network_overlap_metrics.csv`
- `release_flux_network_distance_metrics_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/release_flux_network_distance_metrics.csv`
- `budget_timeseries_long_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/budget_timeseries_long.csv`
- `budget_timeseries_wide_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/budget_timeseries_wide.csv`
- `numerical_closure_by_period_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/numerical_closure_by_period.csv`
- `numerical_closure_summary_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/numerical_closure_summary.csv`
- `numerical_closure_summary_json`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/numerical_closure_summary.json`
- `boussinesq_obstacle_diagnostics_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/boussinesq_obstacle_diagnostics.csv`
- `ts_vi_obstacle_runtime_summary`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/bouss_candidate__ts_vi_obstacle_runtime_summary.json`
- `ts_vi_obstacle_period_diagnostics`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/bouss_candidate__ts_vi_obstacle_period_diagnostics.csv`
- `ts_vi_obstacle_step_diagnostics`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/bouss_candidate__ts_vi_obstacle_step_diagnostics.csv`
- `execution_times_csv`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/execution_times.csv`

## Boussinesq PETSc TS VI obstacle diagnostics
- `bouss_candidate`: ts_steps_per_period=4, total_ts_steps=96, adapt=no, all_periods_converged=yes, max_active_top=1399, max_active_bottom=0, max_upper_violation=0, max_lower_violation=0
- `ts_vi_obstacle_runtime_summary` for `bouss_candidate`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/bouss_candidate__ts_vi_obstacle_runtime_summary.json`
- `ts_vi_obstacle_period_diagnostics` for `bouss_candidate`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/bouss_candidate__ts_vi_obstacle_period_diagnostics.csv`
- `ts_vi_obstacle_step_diagnostics` for `bouss_candidate`: `/mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/comparisons/site_03_natural_n1_10km2_mf6_bouss/bouss_candidate__ts_vi_obstacle_step_diagnostics.csv`

## Metrics
| Simulation | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bouss_candidate | head_map_dry_late | m | 2034 | 4.53685 | 4.58603 | 7.64246 | 29.8485 | 0.0985245 |
| bouss_candidate | head_map_first_computed | m | 2034 | 0.630913 | 0.753459 | 1.5492 | 11.4128 | 0.0225715 |
| bouss_candidate | head_map_last | m | 2033 | 4.73366 | 4.78058 | 7.88606 | 29.3134 | 0.10288 |
| bouss_candidate | head_map_wet_year1 | m | 2034 | 1.754 | 1.86058 | 3.75878 | 22.8473 | 0.0423488 |

## Gaps
- `bouss_candidate` / `head_map_last` / `m`: 1 rows skipped (missing aligned reference row or unit mismatch).
