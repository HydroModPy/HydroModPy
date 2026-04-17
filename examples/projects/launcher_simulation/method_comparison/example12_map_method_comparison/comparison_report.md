# Method Comparison Report: example12_map_method_comparison

- Reference variant: `mf6_gmsh_existing`
- Completed variants: 2 / 2
- Observable rows: 2715
- Comparable metric groups: 5
- Unmatched row groups: 0

## Variants
- `mf6_gmsh_existing`: reused, solver=`modflow6`, mesh=`mesh_catchment`, rows=1365, wall_time=, run_folder=`C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\results_simulations\example12_fast_mf6_mesh_catchment`
- `boussinesq_reused_gmsh`: reused, solver=`boussinesq`, mesh=`mesh_input`, rows=1350, wall_time=, run_folder=`C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\results_reused_real_meshes\example12_fast\results_simulations\flow_main__boussinesq`

## Observables
- `head_outlet_lowland`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_mid_basin_response`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_upstream_ridge`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `watertable_elevation_map`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `watertable_depth_map`: variable=`watertable_depth`, support=`map`, unit=`m`

## Figures
- `map_comparison` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\comparison_figures\watertable_elevation_map__map_comparison.png`
- `difference_map` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\comparison_figures\watertable_elevation_map__difference__mf6_gmsh_existing__vs__boussinesq_reused_gmsh.png`
- `map_comparison` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\comparison_figures\watertable_depth_map__map_comparison.png`
- `difference_map` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\comparison_figures\watertable_depth_map__difference__mf6_gmsh_existing__vs__boussinesq_reused_gmsh.png`
- `timeseries` / `head_mid_basin_response`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\comparison_figures\head_mid_basin_response__timeseries.png`
- `timeseries` / `head_outlet_lowland`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\comparison_figures\head_outlet_lowland__timeseries.png`
- `timeseries` / `head_upstream_ridge`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\comparison_figures\head_upstream_ridge__timeseries.png`
- `point_dashboard` / `head_points`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\comparison_figures\head_points_dashboard.png`
- `budget_diagnostics` / `budget`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\comparison_figures\boussinesq_reused_gmsh__budget_diagnostics.png`

## Data Exports
- `timeseries_long_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\timeseries_long.csv`
- `timeseries_wide_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\timeseries_wide.csv`
- `timeseries_delta_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\timeseries_delta.csv`
- `budget_timeseries_long_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\budget_timeseries_long.csv`
- `budget_timeseries_wide_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\budget_timeseries_wide.csv`
- `execution_times_csv`: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\method_comparison\example12_map_method_comparison\execution_times.csv`

## Metrics
| Variant | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| boussinesq_reused_gmsh | head_mid_basin_response | m | 4 | -0.0240264 | 0.0240264 | 0.0247326 | 0.0331762 | 0.000222445 |
| boussinesq_reused_gmsh | head_outlet_lowland | m | 4 | -0.039819 | 0.039819 | 0.0402973 | 0.0492686 | 0.000373827 |
| boussinesq_reused_gmsh | head_upstream_ridge | m | 4 | -0.0116313 | 0.0116313 | 0.0129424 | 0.020557 | 0.000111922 |
| boussinesq_reused_gmsh | watertable_depth_map | m | 669 | 0.456136 | 0.456136 | 0.750675 | 2.34842 | 5.45326 |
| boussinesq_reused_gmsh | watertable_elevation_map | m | 669 | -0.46504 | 0.46504 | 0.751233 | 2.34842 | 0.00388249 |

## Gaps
- No unmatched rows.
