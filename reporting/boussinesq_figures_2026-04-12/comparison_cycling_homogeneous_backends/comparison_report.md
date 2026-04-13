# Method Comparison Report: review_cycling_homogeneous_backends

- Reference variant: `boussinesq_scipy_sparse`
- Completed variants: 3 / 3
- Observable rows: 25338
- Comparable metric groups: 8
- Unmatched row groups: 0

## Variants
- `boussinesq_scipy_sparse`: reused, solver=`boussinesq`, mesh=`mesh_input`, rows=8446, wall_time=, run_folder=`C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\cycling_homogeneous_scipy_sparse\results_simulations\flow_main__boussinesq`
- `boussinesq_petsc_partition`: reused, solver=`boussinesq`, mesh=`mesh_input`, rows=8446, wall_time=, run_folder=`C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\cycling_homogeneous_petsc_partition\results_simulations\flow_main__boussinesq`
- `boussinesq_petsc_mixed`: reused, solver=`boussinesq`, mesh=`mesh_input`, rows=8446, wall_time=, run_folder=`C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\cycling_homogeneous_petsc_mixed\results_simulations\flow_main__boussinesq`

## Observables
- `head_outlet_point`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `outlet_flux_series`: variable=`outlet_flux`, support=`outlet`, unit=`m3/s`
- `watertable_elevation_map`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `watertable_depth_map`: variable=`watertable_depth`, support=`map`, unit=`m`

## Figures
- `map_comparison` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_homogeneous_backends\comparison_figures\watertable_elevation_map__map_comparison.png`
- `difference_map` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_homogeneous_backends\comparison_figures\watertable_elevation_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_partition.png`
- `difference_map` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_homogeneous_backends\comparison_figures\watertable_elevation_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_mixed.png`
- `map_comparison` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_homogeneous_backends\comparison_figures\watertable_depth_map__map_comparison.png`
- `difference_map` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_homogeneous_backends\comparison_figures\watertable_depth_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_partition.png`
- `difference_map` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_homogeneous_backends\comparison_figures\watertable_depth_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_mixed.png`
- `timeseries` / `outlet_flux_series`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_homogeneous_backends\comparison_figures\outlet_flux_series__timeseries.png`

## Data Exports
- `timeseries_long_csv`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_homogeneous_backends\timeseries_long.csv`
- `timeseries_wide_csv`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_homogeneous_backends\timeseries_wide.csv`
- `timeseries_delta_csv`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_homogeneous_backends\timeseries_delta.csv`

## Metrics
| Variant | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| boussinesq_petsc_mixed | head_outlet_point | m | 1 | 5.05327e-08 | 5.05327e-08 | 5.05327e-08 | 5.05327e-08 | 6.22656e-10 |
| boussinesq_petsc_mixed | outlet_flux_series | m3/s | 13 | 0 | 0 | 0 | 0 | nan |
| boussinesq_petsc_mixed | watertable_depth_map | m | 4216 | -0.110061 | 0.110176 | 0.410999 | 3.18281 | 0.0179003 |
| boussinesq_petsc_mixed | watertable_elevation_map | m | 4216 | 0.110061 | 0.110176 | 0.410999 | 3.18281 | 0.00146743 |
| boussinesq_petsc_partition | head_outlet_point | m | 1 | -2.41585e-13 | 2.41585e-13 | 2.41585e-13 | 2.41585e-13 | 2.97677e-15 |
| boussinesq_petsc_partition | outlet_flux_series | m3/s | 13 | 0 | 0 | 0 | 0 | nan |
| boussinesq_petsc_partition | watertable_depth_map | m | 4216 | 1.13147e-05 | 1.13582e-05 | 0.000436506 | 0.0273785 | 8.78306e-08 |
| boussinesq_petsc_partition | watertable_elevation_map | m | 4216 | -1.13147e-05 | 1.13582e-05 | 0.000436506 | 0.0273785 | 1.40035e-07 |

## Gaps
- No unmatched rows.
