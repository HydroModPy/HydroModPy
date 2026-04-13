# Simple Hillslope Surface-Interaction Investigation

This report keeps the same sloping 1D strip for MODFLOW-NWT, MODFLOW 6, and Boussinesq.
The only scenario change is the prescribed head overshoot above the local land surface.

Surface-lock tolerance: `0.020 m`.

## Head offset 25 cm

- head offset above topography: `0.250 m`
- drainage conductance: `1e-05 m2/s`

| Solver | RMSE vs analytical [m] | Max abs error [m] | Min clearance [m] | Surface-lock fraction | Locked length from toe [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0131 | 0.0264 | 0.1163 | 0.000 | 0.00 | `C:\codes\HydroModPy-GH\out\sih_20260412\validation\investigate_surfa_413bd6031c\offset_25cm_modflownwt` |
| MODFLOW 6 | 0.0126 | 0.0264 | 0.1141 | 0.000 | 0.00 | `C:\codes\HydroModPy-GH\out\sih_20260412\validation\investigate_surfa_413bd6031c\offset_25cm_modflow6` |
| Boussinesq | 0.1925 | 0.2444 | -0.0572 | 0.525 | 45.00 | `C:\codes\HydroModPy-GH\out\sih_20260412\validation\investigate_surfa_413bd6031c\offset_25cm_boussinesq` |

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

Figure: `C:\codes\HydroModPy-GH\out\sih_20260412\figures\offset_25cm__profiles.png`
Boussinesq diagnostics: `C:\codes\HydroModPy-GH\out\sih_20260412\figures\offset_25cm__boussinesq_surface.png`

## Head offset 5 cm

- head offset above topography: `0.050 m`
- drainage conductance: `1e-05 m2/s`

| Solver | RMSE vs analytical [m] | Max abs error [m] | Min clearance [m] | Surface-lock fraction | Locked length from toe [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0117 | 0.0213 | 0.0178 | 0.280 | 0.00 | `C:\codes\HydroModPy-GH\out\sih_20260412\validation\investigate_surfa_413bd6031c\offset_05cm_modflownwt` |
| MODFLOW 6 | 0.0118 | 0.0213 | 0.0188 | 0.200 | 0.00 | `C:\codes\HydroModPy-GH\out\sih_20260412\validation\investigate_surfa_413bd6031c\offset_05cm_modflow6` |
| Boussinesq | 0.0720 | 0.1020 | -0.0748 | 0.400 | 32.50 | `C:\codes\HydroModPy-GH\out\sih_20260412\validation\investigate_surfa_413bd6031c\offset_05cm_boussinesq` |

| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |
| --- | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0011 | 0.0016 | 0.0010 |
| MODFLOW-NWT vs Boussinesq | 0.0729 | 0.1043 | 0.0660 |
| MODFLOW 6 vs Boussinesq | 0.0739 | 0.1059 | 0.0670 |

| Boussinesq surface diagnostic | Value |
| --- | ---: |
| Peak surface threshold total [m3/day] | 295.0519 |
| Final surface threshold total [m3/day] | 295.0519 |
| Peak active fraction | 0.5375 |
| Peak head above top [m] | 0.0000 |

Figure: `C:\codes\HydroModPy-GH\out\sih_20260412\figures\offset_05cm__profiles.png`
Boussinesq diagnostics: `C:\codes\HydroModPy-GH\out\sih_20260412\figures\offset_05cm__boussinesq_surface.png`

## Head offset 2 cm

- head offset above topography: `0.020 m`
- drainage conductance: `1e-05 m2/s`

| Solver | RMSE vs analytical [m] | Max abs error [m] | Min clearance [m] | Surface-lock fraction | Locked length from toe [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0118 | 0.0205 | -0.0008 | 0.740 | 74.00 | `C:\codes\HydroModPy-GH\out\sih_20260412\validation\investigate_surfa_413bd6031c\offset_02cm_modflownwt` |
| MODFLOW 6 | 0.0118 | 0.0205 | -0.0004 | 0.720 | 72.00 | `C:\codes\HydroModPy-GH\out\sih_20260412\validation\investigate_surfa_413bd6031c\offset_02cm_modflow6` |
| Boussinesq | 0.0747 | 0.1192 | -0.1077 | 0.300 | 25.00 | `C:\codes\HydroModPy-GH\out\sih_20260412\validation\investigate_surfa_413bd6031c\offset_02cm_boussinesq` |

| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |
| --- | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0011 | 0.0016 | 0.0010 |
| MODFLOW-NWT vs Boussinesq | 0.0775 | 0.1253 | 0.0643 |
| MODFLOW 6 vs Boussinesq | 0.0784 | 0.1265 | 0.0652 |

| Boussinesq surface diagnostic | Value |
| --- | ---: |
| Peak surface threshold total [m3/day] | 120.7266 |
| Final surface threshold total [m3/day] | 120.7266 |
| Peak active fraction | 0.4800 |
| Peak head above top [m] | 0.0000 |

Figure: `C:\codes\HydroModPy-GH\out\sih_20260412\figures\offset_02cm__profiles.png`
Boussinesq diagnostics: `C:\codes\HydroModPy-GH\out\sih_20260412\figures\offset_02cm__boussinesq_surface.png`

Overview: `C:\codes\HydroModPy-GH\out\sih_20260412\figures\surface_onset_overview.png`
