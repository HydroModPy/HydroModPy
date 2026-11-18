# Example 03: the stream network a water table feeds

The Canut catchment (Ille-et-Vilaine), 25 km² cut out of a regional 75 m DEM. Steady state under
1.17 mm/day of recharge, a 50 m aquifer in five layers of 10 m, seepage at the ground surface.
Where the water table reaches the ground the aquifer seeps, and the seepage cells draw a network
beside the mapped one. Its size depends on K. MODFLOW 6 solves the flow. A run takes about 35 s.

## The files

- `project.toml`: the model with K = 1e-5 m/s, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` in a `hmp.Lab`, draws the mesh on the relief
  before the solve, then gives K ten values from 1e-8 to 1e-3 m/s. Each one is solved in memory
  in a few seconds, and the script keeps the share of the catchment that seeps, the mean
  water-table depth and the discharge. It draws the share against K, then keeps three values
  as runs, 4.6e-7, 1e-5 and 2.8e-4 m/s, and draws the seepage cells under the mapped streams
  and a section of the water table for each.

The DEM and the mapped streams are read from the shared `data/` folder of the workspace. The
model reads only the DEM.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp export canut_example_03 --list
```

The script takes about two minutes and keeps three runs, `canut_k_low`, `canut_example_03` and
`canut_k_high`. Played again, it writes the next version of each, `_v2`.

## What a run writes

- `runs/canut_example_03/figures/`: the catchment card, the mesh on the topography, the
  water-table depth with the seepage cells, a section from north to south, the seepage cells
  under the mapped streams, the flow they carry downstream, and where the seepage network and
  the mapped one agree, cell by cell.
- `runs/canut_example_03/exports/`: the catchment and the mapped streams as GeoPackage, and the
  water table, its depth and the seepage cells as GeoTIFF.
- `summary/`: the figures the script draws, outside the sealed runs.

Under 1e-7 m/s the aquifer cannot carry the recharge, and the whole catchment seeps. At
1e-3 m/s it carries it all under the ground, and no cell seeps.
