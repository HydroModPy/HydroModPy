# Method Comparison Report: review_cycling_heterogeneous_backends

- Reference variant: `boussinesq_scipy_sparse`
- Completed variants: 3 / 3
- Observable rows: 25338
- Comparable metric groups: 8
- Unmatched row groups: 0

## Variants
- `boussinesq_scipy_sparse`: reused, solver=`boussinesq`, mesh=`mesh_input`, rows=8446, wall_time=, run_folder=`C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\cycling_heterogeneous_scipy_sparse\results_simulations\flow_main__boussinesq`
- `boussinesq_petsc_partition`: reused, solver=`boussinesq`, mesh=`mesh_input`, rows=8446, wall_time=, run_folder=`C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\cycling_heterogeneous_petsc_partition\results_simulations\flow_main__boussinesq`
- `boussinesq_petsc_mixed`: reused, solver=`boussinesq`, mesh=`mesh_input`, rows=8446, wall_time=, run_folder=`C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\cycling_heterogeneous_petsc_mixed\results_simulations\flow_main__boussinesq`

## Observables
- `head_outlet_point`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `outlet_flux_series`: variable=`outlet_flux`, support=`outlet`, unit=`m3/s`
- `watertable_elevation_map`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `watertable_depth_map`: variable=`watertable_depth`, support=`map`, unit=`m`

## Figures
- `map_comparison` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_heterogeneous_backends\comparison_figures\watertable_elevation_map__map_comparison.png`
- `difference_map` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_heterogeneous_backends\comparison_figures\watertable_elevation_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_partition.png`
- `difference_map` / `watertable_elevation_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_heterogeneous_backends\comparison_figures\watertable_elevation_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_mixed.png`
- `map_comparison` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_heterogeneous_backends\comparison_figures\watertable_depth_map__map_comparison.png`
- `difference_map` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_heterogeneous_backends\comparison_figures\watertable_depth_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_partition.png`
- `difference_map` / `watertable_depth_map`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_heterogeneous_backends\comparison_figures\watertable_depth_map__difference__boussinesq_scipy_sparse__vs__boussinesq_petsc_mixed.png`
- `timeseries` / `outlet_flux_series`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_heterogeneous_backends\comparison_figures\outlet_flux_series__timeseries.png`

## Data Exports
- `timeseries_long_csv`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_heterogeneous_backends\timeseries_long.csv`
- `timeseries_wide_csv`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_heterogeneous_backends\timeseries_wide.csv`
- `timeseries_delta_csv`: `C:\codes\HydroModPy-GH\reporting\boussinesq_figures_2026-04-12\comparison_cycling_heterogeneous_backends\timeseries_delta.csv`

## Metrics
| Variant | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| boussinesq_petsc_mixed | head_outlet_point | m | 1 | 1.26331e-07 | 1.26331e-07 | 1.26331e-07 | 1.26331e-07 | 1.3976e-09 |
| boussinesq_petsc_mixed | outlet_flux_series | m3/s | 13 | 0 | 0 | 0 | 0 | nan |
| boussinesq_petsc_mixed | watertable_depth_map | m | 4216 | -0.290653 | 0.290653 | 0.839952 | 3.94977 | 0.0248687 |
| boussinesq_petsc_mixed | watertable_elevation_map | m | 4216 | 0.290653 | 0.290653 | 0.839952 | 3.94977 | 0.00375519 |
| boussinesq_petsc_partition | head_outlet_point | m | 1 | -8.52651e-14 | 8.52651e-14 | 8.52651e-14 | 8.52651e-14 | 9.43285e-16 |
| boussinesq_petsc_partition | outlet_flux_series | m3/s | 13 | 0 | 0 | 0 | 0 | nan |
| boussinesq_petsc_partition | watertable_depth_map | m | 4216 | 2.84662e-05 | 2.87537e-05 | 0.00137476 | 0.0871557 | 1.96232e-07 |
| boussinesq_petsc_partition | watertable_elevation_map | m | 4216 | -2.84662e-05 | 2.87537e-05 | 0.00137476 | 0.0871557 | 3.18431e-07 |

## Gaps
- No unmatched rows.
