# Transient Hillslope Surface-Interaction Investigation

West no-flow, east fixed head, annual recharge ramp followed by one dry year, and top drainage.

- hydraulic conductivity scale: `0.200x`
- drainage conductance: `1e-05 m2/s`
- time step: `30.0 day`
- recharge series [mm/day]: `[0.6, 1.8, 3.0, 4.2, 5.4, 7.2, 6.0, 4.8, 3.6, 2.4, 1.2, 0.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]`
- forcing shape: increase during first half-year, decrease during second half-year, then one additional year with zero recharge.

| Solver | Onset day [d] | Peak drainage flux [m3/day] | Peak drainage day [d] | Max clearance [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 30.0 | 0.0074 | 660.0 | 0.1295 | `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_20260413\validation\investigate_surfa_062b168c50\transient_modflownwt` |
| MODFLOW 6 | 30.0 | 0.0101 | 30.0 | 0.1611 | `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_20260413\validation\investigate_surfa_062b168c50\transient_modflow6` |
| Boussinesq | 30.0 | 0.0087 | 30.0 | -0.0000 | `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_20260413\validation\investigate_surfa_062b168c50\hillslope_surface_baba065f89` |

Head snapshots: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_20260413\figures\head_snapshots.png`
Head point time series: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_20260413\figures\head_point_timeseries.png`
Flux chronicle: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_20260413\figures\flux_timeseries.png`
Outflow components: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_20260413\figures\outflow_components.png`
