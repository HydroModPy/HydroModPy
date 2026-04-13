# Simple Hillslope Surface-Interaction Investigation

This report keeps the same sloping 1D strip for MODFLOW-NWT, MODFLOW 6, and Boussinesq.
The setup uses west no-flow, east fixed head, uniform recharge, and distributed top drainage.

Surface-lock tolerance: `0.020 m`.

## Recharge 0.5 mm/day

- recharge: `0.500 mm/day`
- drainage conductance: `1e-05 m2/s`
- hydraulic conductivity scale: `0.200x`

| Solver | Row spread [m] | Min clearance [m] | Mean clearance [m] | Surface-lock fraction | Locked length from toe [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0000 | -3.6762 | -1.6610 | 0.025 | 10.00 | `C:\codes\HydroModPy-GH\out\sih_divide_20260413\validation\investigate_surfa_413bd6031c\rch_05_modflownwt_3a81e328` |
| MODFLOW 6 | 0.0000 | -3.6804 | -1.6639 | 0.025 | 10.00 | `C:\codes\HydroModPy-GH\out\sih_divide_20260413\validation\investigate_surfa_413bd6031c\rch_05_modflow6_ec40ff58` |
| Boussinesq | 0.0001 | -3.5533 | -1.5956 | 0.025 | 10.00 | `C:\codes\HydroModPy-GH\out\sih_divide_20260413\validation\investigate_surfa_413bd6031c\rch_05_boussinesq_6d11c5ad` |

| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |
| --- | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0031 | 0.0041 | 0.0028 |
| MODFLOW-NWT vs Boussinesq | 0.0774 | 0.1229 | 0.0663 |
| MODFLOW 6 vs Boussinesq | 0.0805 | 0.1270 | 0.0691 |

| Boussinesq surface diagnostic | Value |
| --- | ---: |
| Peak surface threshold total [m3/day] | 12.2540 |
| Final surface threshold total [m3/day] | 12.2540 |
| Peak active fraction | 0.0708 |
| Peak head above top [m] | 0.0000 |

Figure: `C:\codes\HydroModPy-GH\out\sih_divide_20260413\figures\rch_05__profiles.png`
Boussinesq diagnostics: `C:\codes\HydroModPy-GH\out\sih_divide_20260413\figures\rch_05__boussinesq_surface.png`

## Recharge 1.0 mm/day

- recharge: `1.000 mm/day`
- drainage conductance: `1e-05 m2/s`
- hydraulic conductivity scale: `0.200x`

| Solver | Row spread [m] | Min clearance [m] | Mean clearance [m] | Surface-lock fraction | Locked length from toe [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0000 | -2.5682 | -0.9352 | 0.050 | 20.00 | `C:\codes\HydroModPy-GH\out\sih_divide_20260413\validation\investigate_surfa_413bd6031c\rch_10_modflownwt_07b18e26` |
| MODFLOW 6 | 0.0000 | -2.5631 | -0.9317 | 0.050 | 20.00 | `C:\codes\HydroModPy-GH\out\sih_divide_20260413\validation\investigate_surfa_413bd6031c\rch_10_modflow6_e7443f98` |
| Boussinesq | 0.0001 | -2.4727 | -0.8595 | 0.100 | 40.00 | `C:\codes\HydroModPy-GH\out\sih_divide_20260413\validation\investigate_surfa_413bd6031c\rch_10_boussinesq_bee2ec71` |

| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |
| --- | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0039 | 0.0051 | 0.0035 |
| MODFLOW-NWT vs Boussinesq | 0.0797 | 0.0955 | 0.0757 |
| MODFLOW 6 vs Boussinesq | 0.0758 | 0.0904 | 0.0722 |

| Boussinesq surface diagnostic | Value |
| --- | ---: |
| Peak surface threshold total [m3/day] | 18.9056 |
| Final surface threshold total [m3/day] | 18.9056 |
| Peak active fraction | 0.0125 |
| Peak head above top [m] | 0.0000 |

Figure: `C:\codes\HydroModPy-GH\out\sih_divide_20260413\figures\rch_10__profiles.png`
Boussinesq diagnostics: `C:\codes\HydroModPy-GH\out\sih_divide_20260413\figures\rch_10__boussinesq_surface.png`

## Recharge 2.0 mm/day

- recharge: `2.000 mm/day`
- drainage conductance: `1e-05 m2/s`
- hydraulic conductivity scale: `0.200x`

| Solver | Row spread [m] | Min clearance [m] | Mean clearance [m] | Surface-lock fraction | Locked length from toe [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0000 | -1.1762 | -0.1359 | 0.050 | 10.00 | `C:\codes\HydroModPy-GH\out\sih_divide_20260413\validation\investigate_surfa_413bd6031c\rch_20_modflownwt_41e000f2` |
| MODFLOW 6 | 0.0000 | -1.1739 | -0.1347 | 0.050 | 10.00 | `C:\codes\HydroModPy-GH\out\sih_divide_20260413\validation\investigate_surfa_413bd6031c\rch_20_modflow6_838e5de1` |
| Boussinesq | 0.0000 | -1.2759 | -0.2411 | 0.525 | 210.00 | `C:\codes\HydroModPy-GH\out\sih_divide_20260413\validation\investigate_surfa_413bd6031c\rch_20_boussinesq_f27313fa` |

| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |
| --- | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0015 | 0.0023 | 0.0012 |
| MODFLOW-NWT vs Boussinesq | 0.1093 | 0.1457 | 0.1052 |
| MODFLOW 6 vs Boussinesq | 0.1104 | 0.1461 | 0.1064 |

| Boussinesq surface diagnostic | Value |
| --- | ---: |
| Peak surface threshold total [m3/day] | 29.7925 |
| Final surface threshold total [m3/day] | 29.7925 |
| Peak active fraction | 0.8708 |
| Peak head above top [m] | 0.0000 |

Figure: `C:\codes\HydroModPy-GH\out\sih_divide_20260413\figures\rch_20__profiles.png`
Boussinesq diagnostics: `C:\codes\HydroModPy-GH\out\sih_divide_20260413\figures\rch_20__boussinesq_surface.png`

Overview: `C:\codes\HydroModPy-GH\out\sih_divide_20260413\figures\surface_onset_overview.png`
