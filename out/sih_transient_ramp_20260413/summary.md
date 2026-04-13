# Transient Hillslope Surface-Interaction Investigation

West no-flow, east fixed head, progressive recharge ramp, and top drainage.

- hydraulic conductivity scale: `0.200x`
- drainage conductance: `1e-05 m2/s`
- time step: `10.0 day`
- recharge series [mm/day]: `[0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4]`

| Solver | Onset day [d] | Peak drainage flux [m3/day] | Peak drainage day [d] | Max clearance [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 10.0 | 0.0001 | 120.0 | 0.0000 | `C:\codes\HydroModPy-GH\out\sih_transient_ramp_20260413\validation\investigate_surfa_062b168c50\transient_modflownwt_b03a9504` |
| MODFLOW 6 | 10.0 | 0.0021 | 120.0 | 0.0330 | `C:\codes\HydroModPy-GH\out\sih_transient_ramp_20260413\validation\investigate_surfa_062b168c50\transient_modflow6_bcf2d9c0` |
| Boussinesq | 10.0 | 0.0198 | 10.0 | -0.0081 | `C:\codes\HydroModPy-GH\out\sih_transient_ramp_20260413\validation\investigate_surfa_062b168c50\hillslope_surface_baba065f89_a8459d41` |

Head snapshots: `C:\codes\HydroModPy-GH\out\sih_transient_ramp_20260413\figures\head_snapshots.png`
Flux chronicle: `C:\codes\HydroModPy-GH\out\sih_transient_ramp_20260413\figures\flux_timeseries.png`
