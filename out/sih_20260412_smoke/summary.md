# Simple Hillslope Surface-Interaction Investigation

This report keeps the same sloping 1D strip for MODFLOW-NWT, MODFLOW 6, and Boussinesq.
The only scenario change is the prescribed head overshoot above the local land surface.

Surface-lock tolerance: `0.020 m`.

## Head offset 25 cm

- head offset above topography: `0.250 m`
- drainage conductance: `1e-05 m2/s`

| Solver | RMSE vs analytical [m] | Max abs error [m] | Min clearance [m] | Surface-lock fraction | Locked length from toe [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0131 | 0.0264 | 0.1163 | 0.000 | 0.00 | `C:\codes\HydroModPy-GH\out\sih_20260412_smoke\validation\investigate_surfa_413bd6031c\offset_25cm_modflownwt_cf96c058` |
| MODFLOW 6 | 0.0126 | 0.0264 | 0.1141 | 0.000 | 0.00 | `C:\codes\HydroModPy-GH\out\sih_20260412_smoke\validation\investigate_surfa_413bd6031c\offset_25cm_modflow6_32a56ddb` |
| Boussinesq | 0.1925 | 0.2444 | -0.0572 | 0.525 | 45.00 | `C:\codes\HydroModPy-GH\out\sih_20260412_smoke\validation\investigate_surfa_413bd6031c\offset_25cm_boussinesq` |

| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |
| --- | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0016 | 0.0023 | 0.0014 |
| MODFLOW-NWT vs Boussinesq | 0.1883 | 0.2684 | 0.1834 |
| MODFLOW 6 vs Boussinesq | 0.1870 | 0.2684 | 0.1820 |

| Boussinesq surface diagnostic | Value |
| --- | ---: |
| Peak surface threshold total [m3/day] | 1449.3339 |
| Final surface threshold total [m3/day] | 1449.3339 |
| Peak active fraction | 0.4425 |
| Peak head above top [m] | 0.0000 |

Figure: `C:\codes\HydroModPy-GH\out\sih_20260412_smoke\figures\offset_25cm__profiles.png`
Boussinesq diagnostics: `C:\codes\HydroModPy-GH\out\sih_20260412_smoke\figures\offset_25cm__boussinesq_surface.png`

Overview: `C:\codes\HydroModPy-GH\out\sih_20260412_smoke\figures\surface_onset_overview.png`
