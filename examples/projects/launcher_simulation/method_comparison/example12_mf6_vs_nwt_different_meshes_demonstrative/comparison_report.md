# Method Comparison Report: example12_mf6_vs_nwt_different_meshes_demonstrative

- Reference variant: `mf6_demo_triangular`
- Completed variants: 2 / 2
- Observable rows: 12903
- Comparable metric groups: 7
- Unmatched row groups: 3

## Variants
- `mf6_demo_triangular`: completed, solver=`modflow6`, mesh=`mesh_input`, rows=2055, wall_time=44.77, run_folder=`C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\results_reused_real_meshes\example12_demonstrative_mf6\results_simulations\example12_demonstrative_annual_mf6_precomputed_mesh`
- `nwt_demo_structured`: completed, solver=`modflownwt`, mesh=`structured`, rows=10848, wall_time=30.09, run_folder=`C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\results_reused_real_meshes\example12_demonstrative_nwt\results_simulations\example12_demonstrative_annual_nwt`

## Observables
- `head_outlet_lowland`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_mid_basin_response`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_upstream_ridge`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `outlet_flux_series`: variable=`outlet_flux`, support=`outlet`, unit=`m3/s`
- `head_map_last`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `depth_map_last`: variable=`watertable_depth`, support=`map`, unit=`m`
- `outflow_drain_map_last`: variable=`outflow_drain`, support=`map`, unit=`m/day`

## Figures
- `map_comparison` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\head_map_last__map_comparison.png`
- `fine_raster_geotiff` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\head_map_last__fine_raster__mf6_demo_triangular.tif`
- `fine_raster_geotiff` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\head_map_last__fine_raster__nwt_demo_structured.tif`
- `fine_raster_map_comparison` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\head_map_last__fine_raster_map_comparison.png`
- `fine_raster_difference_map` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\head_map_last__fine_raster_difference__mf6_demo_triangular__vs__nwt_demo_structured.png`
- `fine_raster_difference_geotiff` / `head_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\head_map_last__fine_raster_difference__mf6_demo_triangular__vs__nwt_demo_structured.tif`
- `map_comparison` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\depth_map_last__map_comparison.png`
- `fine_raster_geotiff` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\depth_map_last__fine_raster__mf6_demo_triangular.tif`
- `fine_raster_geotiff` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\depth_map_last__fine_raster__nwt_demo_structured.tif`
- `fine_raster_map_comparison` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\depth_map_last__fine_raster_map_comparison.png`
- `fine_raster_difference_map` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\depth_map_last__fine_raster_difference__mf6_demo_triangular__vs__nwt_demo_structured.png`
- `fine_raster_difference_geotiff` / `depth_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\depth_map_last__fine_raster_difference__mf6_demo_triangular__vs__nwt_demo_structured.tif`
- `map_comparison` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\outflow_drain_map_last__map_comparison.png`
- `fine_raster_geotiff` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\outflow_drain_map_last__fine_raster__mf6_demo_triangular.tif`
- `fine_raster_geotiff` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\outflow_drain_map_last__fine_raster__nwt_demo_structured.tif`
- `fine_raster_map_comparison` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\outflow_drain_map_last__fine_raster_map_comparison.png`
- `fine_raster_difference_map` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\outflow_drain_map_last__fine_raster_difference__mf6_demo_triangular__vs__nwt_demo_structured.png`
- `fine_raster_difference_geotiff` / `outflow_drain_map_last`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\outflow_drain_map_last__fine_raster_difference__mf6_demo_triangular__vs__nwt_demo_structured.tif`
- `timeseries` / `head_mid_basin_response`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\head_mid_basin_response__timeseries.png`
- `timeseries` / `head_outlet_lowland`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\head_outlet_lowland__timeseries.png`
- `timeseries` / `head_upstream_ridge`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\head_upstream_ridge__timeseries.png`
- `timeseries` / `outlet_flux_series`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\outlet_flux_series__timeseries.png`
- `native_flux_panel` / `accumulation_flux`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\native_accumulation_flux__hydrograph.png`
- `native_flux_panel` / `outflow_drain`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\native_outflow_drain__hydrograph.png`
- `execution_time_bars` / `execution_time`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\comparison_figures\execution_time_comparison.png`

## Data Exports
- `timeseries_long_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\timeseries_long.csv`
- `timeseries_wide_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\timeseries_wide.csv`
- `timeseries_delta_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\timeseries_delta.csv`
- `native_timeseries_long_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\native_timeseries_long.csv`
- `native_timeseries_wide_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\native_timeseries_wide.csv`
- `native_timeseries_delta_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\native_timeseries_delta.csv`
- `execution_times_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_mf6_vs_nwt_different_meshes_demonstrative\execution_times.csv`

## Metrics
| Variant | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| nwt_demo_structured | depth_map_last | m | 337 | -2.24031 | 2.24031 | 2.658 | 7.26776 | nan |
| nwt_demo_structured | head_map_last | m | 337 | -16.8932 | 19.5222 | 25.5961 | 76.877 | 0.124702 |
| nwt_demo_structured | head_mid_basin_response | m | 12 | -7.26465 | 7.26465 | 8.65752 | 17.9511 | 0.0591602 |
| nwt_demo_structured | head_outlet_lowland | m | 12 | -19.0646 | 19.0646 | 21.5225 | 38.1274 | 0.140233 |
| nwt_demo_structured | head_upstream_ridge | m | 12 | -8.52873 | 8.52873 | 9.88318 | 18.3257 | 0.0723041 |
| nwt_demo_structured | outflow_drain_map_last | m/day | 562 | -0.000324006 | 0.000362505 | 0.000475336 | 0.00159583 | 0.921274 |
| nwt_demo_structured | outlet_flux_series | m3/s | 12 | -0.00235885 | 0.00235885 | 0.00295863 | 0.00542737 | 0.947406 |

## Gaps
- `nwt_demo_structured` / `depth_map_last` / `m`: 3263 rows skipped (missing aligned reference row or unit mismatch).
- `nwt_demo_structured` / `head_map_last` / `m`: 3263 rows skipped (missing aligned reference row or unit mismatch).
- `nwt_demo_structured` / `outflow_drain_map_last` / `m/day`: 3038 rows skipped (missing aligned reference row or unit mismatch).
