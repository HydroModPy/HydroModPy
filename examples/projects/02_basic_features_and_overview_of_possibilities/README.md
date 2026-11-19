# Example 02: a conceptual relief, and the main features of HydroModPy

A conceptual relief of 5 km by 5 km at 75 m, taken whole as the domain, with no download. Steady
state, a recharge that changes from cell to cell, an aquifer whose base mirrors the relief under
sea level, ten layers that thicken with depth, K in three bands of depth, seepage at the ground
surface, and particles. MODFLOW 6 solves the flow and its particle tracking PRT follows the
water. A run takes about 25 s.

## The files

- `project.toml`: the model, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` step by step in a `hmp.Lab`. After `load_data` it
  prints the range of the recharge map. After `prepare_solver` it draws the mesh and prints, for
  each of the ten layers, its thickness and the share of its cells in each band of K. It then
  solves, and tries two other inputs from Python without a new file: the mean of the recharge
  map in every cell, then one K over the whole depth. It prints the mean water table and the
  discharge of each trial, comes back to the file, keeps the run and draws one more section.

The DEM, the base of the aquifer and the recharge map are read from the shared `data/` folder of
the workspace: `conceptual_dem.tif`, `conceptual_base.tif` (-top in each cell) and
`recharge_conceptual.tif` (one value per cell, drawn at random between 0 and 100 mm per month).

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp export conceptual_example_02 --list
```

Run the file twice and nothing is computed the second time. The run that the script keeps is
the run of `project.toml`, so after `hmp run` the script writes the next version,
`conceptual_example_02_v2`.

## What a run writes

- `runs/conceptual_example_02/figures/`: the mesh on the topography, the recharge, K from west
  to east, the water table, its depth with the seepage cells, a section from west to east, the
  drain flow and the flow it accumulates downstream, the particle tracks alone and over the
  travel time to the exit, and the distribution of the travel times.
- `runs/conceptual_example_02/exports/`: the domain as GeoPackage, the water table, its depth,
  the seepage cells and the drain flow as GeoTIFF, the water budget as CSV, and the particle
  tracks as GeoPackage, one line per particle with its travel time.
- `summary/`: the figures the script draws, outside the sealed run.

Each layer takes the band of K of its base, so a layer that ends below 30 m holds 1e-7 m/s
where another of the same rank, thinner, still holds 1e-5 m/s.
