# Method Comparison Report: ex12_mf6_nwt_moderate_same_s60

- Reference variant: `mf6_mod_s60`
- Completed variants: 2 / 2
- Observable rows: 21696
- Comparable metric groups: 7
- Unmatched row groups: 2

## Variants
- `mf6_mod_s60`: completed, solver=`modflow6`, mesh=`structured`, rows=10848, wall_time=51.44, run_folder=`C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\results_reused_real_meshes\ex12_demo_mod_mf6_s60\results_simulations\ex12_demo_mod_mf6_s60`
- `nwt_mod_s60`: completed, solver=`modflownwt`, mesh=`structured`, rows=10848, wall_time=37.08, run_folder=`C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\results_reused_real_meshes\ex12_demo_mod_nwt\results_simulations\ex12_demo_mod_nwt_s60`

## Observables
- `head_outlet_lowland`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_mid_basin_response`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_upstream_ridge`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `outlet_flux_series`: variable=`outlet_flux`, support=`outlet`, unit=`m3/s`
- `head_map_last`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `depth_map_last`: variable=`watertable_depth`, support=`map`, unit=`m`
- `outflow_drain_map_last`: variable=`outflow_drain`, support=`map`, unit=`m/day`

## Figures
- `map_comparison` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\head_map_last__map_comparison.png`
- `difference_map` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\head_map_last__difference__mf6_mod_s60__vs__nwt_mod_s60.png`
- `map_comparison` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\depth_map_last__map_comparison.png`
- `difference_map` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\depth_map_last__difference__mf6_mod_s60__vs__nwt_mod_s60.png`
- `map_comparison` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\outflow_drain_map_last__map_comparison.png`
- `difference_map` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\outflow_drain_map_last__difference__mf6_mod_s60__vs__nwt_mod_s60.png`
- `timeseries` / `head_mid_basin_response`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\head_mid_basin_response__timeseries.png`
- `timeseries` / `head_outlet_lowland`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\head_outlet_lowland__timeseries.png`
- `timeseries` / `head_upstream_ridge`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\head_upstream_ridge__timeseries.png`
- `timeseries` / `outlet_flux_series`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\outlet_flux_series__timeseries.png`
- `point_dashboard` / `head_points`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\head_points_dashboard.png`
- `native_flux_panel` / `accumulation_flux`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\native_accumulation_flux__hydrograph.png`
- `native_flux_panel` / `outflow_drain`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\native_outflow_drain__hydrograph.png`
- `flux_dashboard` / `flux_overview`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\flux_overview.png`
- `execution_time_bars` / `execution_time`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\comparison_figures\execution_time_comparison.png`

## Data Exports
- `timeseries_long_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\timeseries_long.csv`
- `timeseries_wide_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\timeseries_wide.csv`
- `timeseries_delta_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\timeseries_delta.csv`
- `native_timeseries_long_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\native_timeseries_long.csv`
- `native_timeseries_wide_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\native_timeseries_wide.csv`
- `native_timeseries_delta_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\native_timeseries_delta.csv`
- `execution_times_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate_same_s60\execution_times.csv`

## Metrics
| Variant | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| nwt_mod_s60 | depth_map_last | m | 2011 | -4.09445 | 4.09692 | 4.76381 | 11.5224 | nan |
| nwt_mod_s60 | head_map_last | m | 2011 | -2.87122 | 2.87122 | 3.53977 | 13.3466 | 0.0226722 |
| nwt_mod_s60 | head_mid_basin_response | m | 12 | -0.254 | 0.407697 | 0.779824 | 2.12574 | 0.00349982 |
| nwt_mod_s60 | head_outlet_lowland | m | 12 | -0.185195 | 0.245201 | 0.552042 | 1.80498 | 0.0021107 |
| nwt_mod_s60 | head_upstream_ridge | m | 12 | -0.514984 | 0.597373 | 1.07159 | 2.45521 | 0.0053787 |
| nwt_mod_s60 | outflow_drain_map_last | m/day | 3600 | -1.4685e-05 | 1.73791e-05 | 2.66759e-05 | 0.000133466 | 0.435553 |
| nwt_mod_s60 | outlet_flux_series | m3/s | 12 | -1.43143e-05 | 1.63422e-05 | 3.04706e-05 | 8.19811e-05 | 0.124127 |

## Gaps
- `nwt_mod_s60` / `depth_map_last` / `m`: 1589 rows skipped (missing aligned reference row or unit mismatch).
- `nwt_mod_s60` / `head_map_last` / `m`: 1589 rows skipped (missing aligned reference row or unit mismatch).
