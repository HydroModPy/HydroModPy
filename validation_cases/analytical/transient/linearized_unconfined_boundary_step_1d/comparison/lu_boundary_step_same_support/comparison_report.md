# Method Comparison Report: lu_boundary_step_same_support

- Reference variant: `modflow6`
- Completed variants: 2 / 2
- Observable rows: 1240
- Comparable metric groups: 5
- Unmatched row groups: 0

## Variants
- `modflownwt`: completed, solver=`modflownwt`, mesh=`structured`, rows=620, wall_time=6.58, run_folder=`C:\codes\HydroModPy\tmp\lu_boundary_step_same_support_workspace\.solver_scratch\modflownwt`
- `modflow6`: completed, solver=`modflow6`, mesh=`structured`, rows=620, wall_time=9, run_folder=`C:\codes\HydroModPy\tmp\lu_boundary_step_same_support_workspace\.solver_scratch\modflow6`

## Observables
- `head_west_response`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_mid_response`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_east_response`: variable=`watertable_elevation`, support=`point`, unit=`m`
- `head_map_last`: variable=`watertable_elevation`, support=`map`, unit=`m`
- `depth_map_last`: variable=`watertable_depth`, support=`map`, unit=`m`

## Figures
- `timeseries` / `head_east_response`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_east_response__timeseries.png`
- `timeseries` / `head_mid_response`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_mid_response__timeseries.png`
- `timeseries` / `head_west_response`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_west_response__timeseries.png`
- `point_dashboard` / `head_points`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\head_points_dashboard.png`
- `execution_time_bars` / `execution_time`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\comparison_figures\execution_time_comparison.png`

## Data Exports
- `timeseries_long_csv`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\timeseries_long.csv`
- `timeseries_wide_csv`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\timeseries_wide.csv`
- `timeseries_delta_csv`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\timeseries_delta.csv`
- `execution_times_csv`: `C:\codes\HydroModPy\validation_cases\analytical\transient\linearized_unconfined_boundary_step_1d\comparison\lu_boundary_step_same_support\execution_times.csv`

## Metrics
| Variant | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| modflownwt | depth_map_last | m | 250 | 2.84361e-05 | 2.84513e-05 | 3.19321e-05 | 4.59859e-05 | 2.85941e-06 |
| modflownwt | head_east_response | m | 40 | -0.000255658 | 0.000255658 | 0.000332749 | 0.000664659 | 2.5548e-05 |
| modflownwt | head_map_last | m | 250 | -2.84361e-05 | 2.84513e-05 | 3.19321e-05 | 4.59859e-05 | 2.83102e-06 |
| modflownwt | head_mid_response | m | 40 | -0.00099867 | 0.00099867 | 0.00129415 | 0.00253179 | 9.94326e-05 |
| modflownwt | head_west_response | m | 40 | -0.000305343 | 0.000305343 | 0.000396132 | 0.000758921 | 3.02689e-05 |

## Gaps
- No unmatched rows.
