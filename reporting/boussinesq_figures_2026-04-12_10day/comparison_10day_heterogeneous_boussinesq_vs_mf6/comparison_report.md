# Method Comparison Report: review_10day_heterogeneous_boussinesq_vs_mf6

- Reference variant: `boussinesq_scipy_sparse`
- Completed variants: 4 / 4
- Observable rows: 34030
- Comparable metric groups: 12
- Unmatched row groups: 0

## Variants
- `boussinesq_scipy_sparse`: reused, solver=`boussinesq`, mesh=`mesh_input`, rows=8508, wall_time=, run_folder=`C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\bq10_scipy\results_simulations\flow_main__boussinesq`
- `boussinesq_petsc_partition`: reused, solver=`boussinesq`, mesh=`mesh_input`, rows=8508, wall_time=, run_folder=`C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\bq10_petsc_partition\results_simulations\flow_main__boussinesq`
- `boussinesq_petsc_mixed`: reused, solver=`boussinesq`, mesh=`mesh_input`, rows=8508, wall_time=, run_folder=`C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\bq10_petsc_mixed\results_simulations\flow_main__boussinesq`
- `mf6_heterogeneous_10day`: reused, solver=`modflow6`, mesh=`mesh_input`, rows=8506, wall_time=, run_folder=`C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\mf6_10d\results_simulations\mf6_h100_10d`

## Observables
- `head_reference_cell`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `outlet_flux_series`: variable=`outlet_flux`, support=`outlet`, unit=`m3/s`
- `watertable_elevation_map`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `watertable_depth_map`: variable=`watertable_depth`, support=`map`, unit=`m`

## Figures
- `map_comparison` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\comparison_figures\watertable_elevation_map__map_comparison.png`
- `difference_map` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\comparison_figures\watertable_elevation_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_partition.png`
- `difference_map` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\comparison_figures\watertable_elevation_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_mixed.png`
- `difference_map` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\comparison_figures\watertable_elevation_map__difference__boussinesq_scipy_sparse__vs__mf6_heterogeneous_10day.png`
- `map_comparison` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\comparison_figures\watertable_depth_map__map_comparison.png`
- `difference_map` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\comparison_figures\watertable_depth_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_partition.png`
- `difference_map` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\comparison_figures\watertable_depth_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_mixed.png`
- `difference_map` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\comparison_figures\watertable_depth_map__difference__boussinesq_scipy_sparse__vs__mf6_heterogeneous_10day.png`
- `timeseries` / `head_reference_cell`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\comparison_figures\head_reference_cell__timeseries.png`
- `timeseries` / `outlet_flux_series`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\comparison_figures\outlet_flux_series__timeseries.png`

## Data Exports
- `timeseries_long_csv`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\timeseries_long.csv`
- `timeseries_wide_csv`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\timeseries_wide.csv`
- `timeseries_delta_csv`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\timeseries_delta.csv`
- `execution_times_csv`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12_10day\comparison_10day_heterogeneous_boussinesq_vs_mf6\execution_times.csv`

## Metrics
| Variant | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| boussinesq_petsc_mixed | head_reference_cell | m | 38 | 1.42374 | 1.42374 | 1.60892 | 3.16836 | 0.019793 |
| boussinesq_petsc_mixed | outlet_flux_series | m3/s | 38 | 0 | 0 | 0 | 0 | nan |
| boussinesq_petsc_mixed | watertable_depth_map | m | 4216 | -0.140125 | 0.140125 | 0.461466 | 2.71221 | 0.0130436 |
| boussinesq_petsc_mixed | watertable_elevation_map | m | 4216 | 0.140125 | 0.140125 | 0.461466 | 2.71221 | 0.00187596 |
| boussinesq_petsc_partition | head_reference_cell | m | 38 | 5.77759e-07 | 2.61513e-06 | 4.0996e-06 | 9.66737e-06 | 3.67784e-08 |
| boussinesq_petsc_partition | outlet_flux_series | m3/s | 38 | 0 | 0 | 0 | 0 | nan |
| boussinesq_petsc_partition | watertable_depth_map | m | 4216 | 8.94152e-06 | 1.03899e-05 | 0.000277236 | 0.0170807 | 1.43315e-07 |
| boussinesq_petsc_partition | watertable_elevation_map | m | 4216 | -8.94152e-06 | 1.03899e-05 | 0.000277236 | 0.0170807 | 1.2564e-07 |
| mf6_heterogeneous_10day | head_reference_cell | m | 37 | 686.889 | 686.889 | 825.384 | 1458.26 | 9.5215 |
| mf6_heterogeneous_10day | outlet_flux_series | m3/s | 37 | 0 | 0 | 0 | 0 | nan |
| mf6_heterogeneous_10day | watertable_depth_map | m | 75 | -8.81326 | 8.81326 | 8.85395 | 10.7047 | 1 |
| mf6_heterogeneous_10day | watertable_elevation_map | m | 75 | 692.269 | 692.269 | 1103.84 | 4206.21 | 10.8465 |

## Gaps
- No unmatched rows.
