# Example 04: the seepage network of the Nançon through the seasons

The Nançon catchment at Lécousse (Ille-et-Vilaine), 65 km² cut out of a regional 75 m DEM. A
monthly transient run from 2000 to 2002, a 30 m aquifer in one layer, seepage at the ground
surface, and the SIM2 recharge and runoff of the catchment. As the recharge swings between wet
winters and dry summers, the seepage cells spread out and draw back. MODFLOW 6 solves the flow.
A run takes about a minute and a half.

## The files

- `project.toml`: the model, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` one step at a time in a `hmp.Lab`. After
  `load_data` it draws the recharge and the runoff, and after `prepare_solver` the mesh on the
  relief. It then gives Sy three values, 0.001, 0.05 and 0.3, and keeps a run for each:
  `nancon_sy_small`, `nancon_intermittence_mf6` (the Sy of the file, so the run of
  `project.toml`) and `nancon_sy_large`. With Sy = 0.001 the water table moves by metres in a
  month, and MODFLOW 6 needs four time steps per month to converge. For each run the script
  prints the months when the catchment seeps the least and the most, with the NSE of the
  discharge, and draws the seepage cells and a section of the water table for these two months,
  the share of the 36 months each cell seeps, the discharge against the gauge, and the seepage
  share of the catchment over time.

The DEM, the mapped streams, the gauge and the recharge and runoff of station `NANCON` are read
from the shared `data/` folder of the workspace. The model reads the DEM and the forcing. The
streams and the gauge are drawn, exported and scored against.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp export nancon_intermittence_mf6 --list
```

Run the file twice and nothing is computed the second time. The script takes about six minutes
and writes the next version of each run, `_v2`, when it is played again.

## What a run writes

- `runs/nancon_intermittence_mf6/figures/`: the catchment card, the mesh on the topography, the
  water-table depth with the seepage cells and a section from south to north in October 2002,
  the share of the run each cell seeps, the discharge against the gauge on a log axis, the
  seepage share of the catchment beside the discharge, and the monthly water budget.
- `runs/nancon_intermittence_mf6/exports/`: the catchment and the mapped streams as GeoPackage,
  the water-table depth and the seepage cells of October 2002 as GeoTIFF, the simulated and
  gauged discharge as CSV, and the water budget as CSV.
- `summary/`: the figures the script draws, outside the sealed runs.

The discharge is the drain flow routed to the outlet, plus the runoff. It is scored against the
gauge on 2001 and 2002, and the year 2000 is spin-up.
