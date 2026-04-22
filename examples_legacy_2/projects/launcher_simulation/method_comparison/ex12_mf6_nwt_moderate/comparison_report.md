# Method Comparison Report: ex12_mf6_nwt_moderate

- Reference variant: `mf6_mod_tri`
- Completed variants: 2 / 2
- Observable rows: 12903
- Comparable metric groups: 7
- Unmatched row groups: 3

## Variants
- `mf6_mod_tri`: completed, solver=`modflow6`, mesh=`mesh_input`, rows=2055, wall_time=95.19, run_folder=`C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\results_reused_real_meshes\ex12_demo_mod_mf6\results_simulations\ex12_demo_mod_mf6_tri`
- `nwt_mod_s60`: completed, solver=`modflownwt`, mesh=`structured`, rows=10848, wall_time=44.12, run_folder=`C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\results_reused_real_meshes\ex12_demo_mod_nwt\results_simulations\ex12_demo_mod_nwt_s60`

## Observables
- `head_outlet_lowland`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_mid_basin_response`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_upstream_ridge`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `outlet_flux_series`: variable=`outlet_flux`, support=`outlet`, unit=`m3/s`
- `head_map_last`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `depth_map_last`: variable=`watertable_depth`, support=`map`, unit=`m`
- `outflow_drain_map_last`: variable=`outflow_drain`, support=`map`, unit=`m/day`

## Figures
- `map_comparison` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\head_map_last__map_comparison.png`
- `fine_raster_geotiff` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\head_map_last__fine_raster__mf6_mod_tri.tif`
- `fine_raster_geotiff` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\head_map_last__fine_raster__nwt_mod_s60.tif`
- `fine_raster_map_comparison` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\head_map_last__fine_raster_map_comparison.png`
- `fine_raster_difference_map` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\head_map_last__fine_raster_difference__mf6_mod_tri__vs__nwt_mod_s60.png`
- `fine_raster_difference_geotiff` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\head_map_last__fine_raster_difference__mf6_mod_tri__vs__nwt_mod_s60.tif`
- `map_comparison` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\depth_map_last__map_comparison.png`
- `fine_raster_geotiff` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\depth_map_last__fine_raster__mf6_mod_tri.tif`
- `fine_raster_geotiff` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\depth_map_last__fine_raster__nwt_mod_s60.tif`
- `fine_raster_map_comparison` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\depth_map_last__fine_raster_map_comparison.png`
- `fine_raster_difference_map` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\depth_map_last__fine_raster_difference__mf6_mod_tri__vs__nwt_mod_s60.png`
- `fine_raster_difference_geotiff` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\depth_map_last__fine_raster_difference__mf6_mod_tri__vs__nwt_mod_s60.tif`
- `map_comparison` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\outflow_drain_map_last__map_comparison.png`
- `fine_raster_geotiff` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\outflow_drain_map_last__fine_raster__mf6_mod_tri.tif`
- `fine_raster_geotiff` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\outflow_drain_map_last__fine_raster__nwt_mod_s60.tif`
- `fine_raster_map_comparison` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\outflow_drain_map_last__fine_raster_map_comparison.png`
- `fine_raster_difference_map` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\outflow_drain_map_last__fine_raster_difference__mf6_mod_tri__vs__nwt_mod_s60.png`
- `fine_raster_difference_geotiff` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\outflow_drain_map_last__fine_raster_difference__mf6_mod_tri__vs__nwt_mod_s60.tif`
- `timeseries` / `head_mid_basin_response`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\head_mid_basin_response__timeseries.png`
- `timeseries` / `head_outlet_lowland`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\head_outlet_lowland__timeseries.png`
- `timeseries` / `head_upstream_ridge`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\head_upstream_ridge__timeseries.png`
- `timeseries` / `outlet_flux_series`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\outlet_flux_series__timeseries.png`
- `point_dashboard` / `head_points`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\head_points_dashboard.png`
- `native_flux_panel` / `accumulation_flux`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\native_accumulation_flux__hydrograph.png`
- `native_flux_panel` / `outflow_drain`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\native_outflow_drain__hydrograph.png`
- `flux_dashboard` / `flux_overview`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\flux_overview.png`
- `execution_time_bars` / `execution_time`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\comparison_figures\execution_time_comparison.png`

## Data Exports
- `timeseries_long_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\timeseries_long.csv`
- `timeseries_wide_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\timeseries_wide.csv`
- `timeseries_delta_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\timeseries_delta.csv`
- `native_timeseries_long_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\native_timeseries_long.csv`
- `native_timeseries_wide_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\native_timeseries_wide.csv`
- `native_timeseries_delta_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\native_timeseries_delta.csv`
- `execution_times_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\ex12_mf6_nwt_moderate\execution_times.csv`

## Metrics
| Variant | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| nwt_mod_s60 | depth_map_last | m | 487 | -2.1477 | 2.48671 | 3.6954 | 11.318 | nan |
| nwt_mod_s60 | head_map_last | m | 487 | -15.353 | 16.9643 | 20.1068 | 44.3214 | 0.114143 |
| nwt_mod_s60 | head_mid_basin_response | m | 12 | -9.95985 | 9.95985 | 11.2426 | 18.6764 | 0.0774274 |
| nwt_mod_s60 | head_outlet_lowland | m | 12 | -19.905 | 19.905 | 21.8392 | 36.2355 | 0.142829 |
| nwt_mod_s60 | head_upstream_ridge | m | 12 | -11.0689 | 11.0689 | 11.9542 | 17.5115 | 0.0906789 |
| nwt_mod_s60 | outflow_drain_map_last | m/day | 562 | -0.000196813 | 0.000204609 | 0.0002224 | 0.000436334 | 0.907075 |
| nwt_mod_s60 | outlet_flux_series | m3/s | 12 | -0.00149093 | 0.00149093 | 0.00179228 | 0.00332272 | 0.922118 |

## Gaps
- `nwt_mod_s60` / `depth_map_last` / `m`: 3113 rows skipped (missing aligned reference row or unit mismatch).
- `nwt_mod_s60` / `head_map_last` / `m`: 3113 rows skipped (missing aligned reference row or unit mismatch).
- `nwt_mod_s60` / `outflow_drain_map_last` / `m/day`: 3038 rows skipped (missing aligned reference row or unit mismatch).
