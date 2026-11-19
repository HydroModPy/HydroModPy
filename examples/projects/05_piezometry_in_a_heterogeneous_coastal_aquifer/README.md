# Example 05: piezometry in a heterogeneous coastal aquifer

The coastal aquifer of Gouville-sur-Mer (Manche), a strip of 3.2 km² along the shore cut on a
25 m DEM, 39 by 134 cells. One year 2016 in daily stress periods, one layer down to a flat base at
20 m below sea level. The aquifer has two zones: a western strip along the shore with K = 18.5
m/day and Sy = 0.08, and an eastern one inland with K = 95 m/day and Sy = 0.45. The recharge
changes every day and the sea level follows the tide. The 549 cells whose ground is at or below
the highest sea level of the year are held at the sea level of the day, and every other cell
drains at the ground. 1 January is solved in steady state under the mean recharge and the mean
sea level. The simulated head is put next to the daily record of the piezometer BSS
01423X0044/F4, in the western strip. MODFLOW 6 solves the flow. A run takes about 40 s.

## The files

- `project.toml`: the model, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` step by step in a `hmp.Lab`. It draws the recharge,
  the sea level and the piezometer record, then the mesh on the relief. It prints the sea cells,
  the drains and the two zones the solver will read, solves, and keeps the model as a run. It
  then draws the simulated head at the piezometer against the measured one, in elevation and in
  depth, asks the run for two more figures and prints the water budget.

The DEM, the model area, the two zones, the recharge and the piezometer record are read from the
shared `data/` folder of the workspace, by a `workspace:` name. The sea level is read by its path
from this folder, `../../data/oceanic/`.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp export gouville_example_05 --list
```

The head at the piezometer is kept by `[observation]` under the station `obs:GOUVILLE_F4`. In
Python, `run.timeseries("head", station="obs:GOUVILLE_F4")` gives it as a daily series.

## What a run writes

- `runs/gouville_example_05/figures/`: the mesh on the topography, K and Sy, the water-table depth
  on 1 January, in mid March and in mid October, the head from west to east through the
  piezometer in March and in October, and the daily water budget of the strip.
- `runs/gouville_example_05/exports/`: the DEM, the head, the water-table depth and the seepage
  cells of mid March and mid October as GeoTIFF, the 366 days of the same three fields in
  `watertable_2016.nc`, and the budget as CSV. Every file opens in QGIS or a spreadsheet.
- `summary/`: the figures the script draws or asks for, outside the sealed run.

Over the year the recharge brings 0.71 mm/day on average and the sea takes back 0.74 mm/day. The
drains take almost nothing, because only the cells near the shore seep.
