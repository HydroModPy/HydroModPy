# Example 06: particle tracking and residence times on the Lasset catchment

The Lasset catchment (Pyrenees), 3.8 km² cut out of a regional 75 m DEM. Steady state under
1.17 mm/day of recharge, an aquifer whose base is flat at 1000 m, cut in ten layers that thicken
with depth, a K that falls with depth, seepage at the ground surface, and particles that give the
travel time of the water. MODFLOW 6 solves the flow and its particle tracking PRT follows the
water. A run takes about 30 s.

## The files

- `project.toml`: the model, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` step by step in a `hmp.Lab`. It prints the
  catchment, the DEM and the mesh as they are built, draws the mesh on the relief, and prints for
  each of the ten layers its thickness and the K that MODFLOW 6 will read. It then solves, keeps
  the model as a run and asks the run for two more figures: the pathlines over the water-table
  depth, and a section from west to east through the outlet. The script ends with the travel
  times of the particles, counted in a log-log plot of their own.

The DEM is read from the shared `data/` folder of the workspace, by a `workspace:` name. The
recharge is written in `project.toml`.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp export lasset_example_06 --list
```

Run the file twice and nothing is computed the second time. The script keeps a run of its own
each time it is played, so it writes the next version, `lasset_example_06_v2`.

## The model

The base of the aquifer is an elevation, 1000 m, and not a thickness under the ground. The
aquifer is 120 m thick under the valleys and more than 1300 m thick under the crests. Each layer
is 1.5 times thicker than the one above it, so the first is 6.6 m thick on average and the last
254 m. K is 1e-6 m/s at the ground surface and falls as exp(-depth / 50 m) down to a floor four
decades lower. The first layer takes the value at the ground, and each layer below reads it at
the depth of its base. Sy is 0.01 and the porosity of the particles is 0.01.

The recharge is the mean of a monthly series of 10, 20, 30, 40, 50, 60, 60, 50, 40, 30, 20 and
10 mm per month, divided by 30 days.

## The particles

PRT tracks forward only. One particle starts at the top of each cell of the box and travels with
the flow until it leaves the aquifer, most of them in a seepage cell. Its travel time is the time
its water needs to go from the cell where it entered to the stream. The deep paths under the
crests are long and the shallow ones short, so the travel times spread over four decades. Half of
the particles leave within 3 years, nine in ten within 12 years, and a few take thousands of
years. The distribution of the travel times departs from an exponential law, which is the
distribution of a homogeneous aquifer.

## What a run writes

- `runs/lasset_example_06/figures/`: the catchment card, the mesh on the topography, the water
  table, its depth with the seepage cells, a section from north to south, the drain flow and the
  flow it accumulates downstream, the particle tracks alone and over the travel time to the
  exit, the map of the travel time of each cell, and the distribution of the travel times.
- `runs/lasset_example_06/exports/`: the catchment and its box as GeoPackage, the DEM, the water
  table, its depth, the seepage cells and the drain flow as GeoTIFF, the water budget as CSV,
  and the particle tracks as GeoPackage, one line per particle with its travel time in years.
  Every file opens in QGIS or a spreadsheet.
- `summary/`: the figures the script draws, outside the sealed run.
