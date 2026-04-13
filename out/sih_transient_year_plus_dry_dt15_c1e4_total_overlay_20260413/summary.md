# Transient Hillslope Surface-Interaction Investigation

West no-flow, east fixed head, annual recharge ramp followed by one dry year, and top drainage.

- hydraulic conductivity scale: `0.200x`
- drainage conductance: `0.0001 m2/s`
- time step: `15.0 day`
- recharge series [mm/day]: `[0.6, 0.6, 1.8, 1.8, 3.0, 3.0, 4.2, 4.2, 5.4, 5.4, 7.2, 7.2, 6.0, 6.0, 4.8, 4.8, 3.6, 3.6, 2.4, 2.4, 1.2, 1.2, 0.6, 0.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]`
- forcing shape: increase during first half-year, decrease during second half-year, then one additional year with zero recharge.

| Solver | Onset day [d] | Peak drainage flux [m3/day] | Peak drainage day [d] | Max clearance [m] | Wall time [s] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 15.0 | 67.5639 | 180.0 | 0.1073 | 15.76 | `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_dt15_c1e4_total_overlay_20260413\validation\investigate_surfa_062b168c50\transient_modflownwt` |
| MODFLOW 6 | 15.0 | 67.5738 | 180.0 | 0.1073 | 19.24 | `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_dt15_c1e4_total_overlay_20260413\validation\investigate_surfa_062b168c50\transient_modflow6` |
| Boussinesq | 15.0 | 0.0201 | 15.0 | -0.0000 | 60.40 | `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_dt15_c1e4_total_overlay_20260413\validation\investigate_surfa_062b168c50\hillslope_surface_baba065f89` |

Head snapshots: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_dt15_c1e4_total_overlay_20260413\figures\head_snapshots.png`
Head point time series: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_dt15_c1e4_total_overlay_20260413\figures\head_point_timeseries.png`
Flux chronicle: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_dt15_c1e4_total_overlay_20260413\figures\flux_timeseries.png`
Total outflow overlay: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_dt15_c1e4_total_overlay_20260413\figures\total_outflow_overlay.png`
Outflow components: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_dt15_c1e4_total_overlay_20260413\figures\outflow_components.png`
Complete flux budget: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_dt15_c1e4_total_overlay_20260413\figures\flux_budget_comparison.png`
Execution times: `C:\codes\HydroModPy-GH\out\sih_transient_year_plus_dry_dt15_c1e4_total_overlay_20260413\figures\execution_times.png`
