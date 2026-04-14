# Sloping-Substratum Transient Intercomparison

Comparison on one explicit irregular triangular mesh with `z_bottom(x)` sloping by `10 deg`.

- topography slope: `12 deg`
- substratum slope: `10 deg`
- hydraulic conductivity: `2e-05 m/s`
- drainage conductance: `0.0001 m2/s`
- time step: `15.0 day`
- recharge series [mm/day]: `[0.6, 0.6, 1.8, 1.8, 3.0, 3.0, 4.2, 4.2, 5.4, 5.4, 7.2, 7.2, 6.0, 6.0, 4.8, 4.8, 3.6, 3.6, 2.4, 2.4, 1.2, 1.2, 0.6, 0.6, 0.0, 0.0, 0.0, 0.0]`
- west boundary is omitted here because the case keeps the divide/no-flow setting.
- `MODFLOW-NWT` and `MODFLOW 6 structured` are run on one sloping structured support.
- `MODFLOW 6 irregular triangles` and `Boussinesq` are run on one explicit irregular triangular bundle.

| Solver | Onset day [d] | Peak drainage flux [m3/day] | Peak total outflow [m3/day] | Max clearance [m] | Wall time [s] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | nan | 0.0000 | 0.0000 | -0.1501 | 6.40 | `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\validation\investigate_slopi_62f9eb2d8a\sloping_substratu_6a70813a83_16e64d64` |
| MODFLOW 6 structured | nan | 0.0000 | 0.0000 | -0.1501 | 9.39 | `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\validation\investigate_slopi_62f9eb2d8a\sloping_substratu_8c05ec3c51_2203c092` |
| MODFLOW 6 irregular triangles | nan | 0.0000 | 7.5906 | -0.1950 | 12.92 | `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\validation\investigate_slopi_62f9eb2d8a\sloping_substratu_de581b6b00_92e37133` |
| Boussinesq | nan | 0.0059 | 61.6073 | -0.0643 | 10.44 | `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\validation\investigate_slopi_62f9eb2d8a\sloping_substratu_db8131e9e1_e662a9a5` |

Head snapshots: `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\figures\head_snapshots.png`
Head point time series: `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\figures\head_point_timeseries.png`
Flux chronicle: `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\figures\flux_timeseries.png`
Total outflow overlay: `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\figures\total_outflow_overlay.png`
Outflow components: `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\figures\outflow_components.png`
Complete flux budget: `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\figures\flux_budget_comparison.png`
Execution times: `C:\codes\HydroModPy-GH\out\sih_sloping_substratum_10deg_20260414\figures\execution_times.png`
