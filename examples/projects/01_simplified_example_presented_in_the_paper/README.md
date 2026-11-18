# Example 01: the Canut catchment, the case of the paper

The Canut catchment (Ille-et-Vilaine), 25 km² cut out of a regional 75 m DEM. Steady state under
350 mm/year of recharge, a 50 m aquifer in five layers that thicken with depth, K and Sy that
fall as exp(-depth / 20 m), seepage at the ground surface, and particles that show where the
seepage water comes from. MODFLOW 6 solves the flow and its particle tracking PRT follows the
water. A run takes about a minute.

## The files

- `project.toml`: the model, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` step by step in a `hmp.Lab`. After `load_data` it
  draws the regime of the Canut from the gauge, 1990 to 2019. After `prepare_solver` it draws the
  mesh on the relief and prints, for each of the five layers, its thickness and the K and Sy
  that MODFLOW 6 will read. It then solves, keeps the model as a run and asks the run for two
  more figures: K from north to south, and the water-table depth under the particle tracks.

The DEM, the mapped streams and the gauge are read from the shared `data/` folder of the
workspace. The model reads only the DEM. The streams and the gauge are drawn and exported.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp export canut_example_01 --list
```

Run the file twice and nothing is computed the second time. The script keeps a run of its own
each time it is played, so it writes the next version, `canut_example_01_v2`.

## What a run writes

- `runs/canut_example_01/figures/`: the catchment card, the mesh on the topography, K from west
  to east and Sy from north to south, the water table, its depth with the seepage cells, a
  section from north to south, the drain flow and the flow it accumulates downstream, the
  particle tracks alone and over the travel time to the exit, and the distribution of the
  travel times.
- `runs/canut_example_01/exports/`: the catchment, its box and the mapped streams as
  GeoPackage, the DEM, the water table, its depth, the seepage cells and the drain flow as
  GeoTIFF, the water budget as CSV, and the particle tracks as GeoPackage, one line per
  particle with its travel time.
- `summary/`: the figures the script draws, outside the sealed run.

PRT tracks forward only. Each particle starts in a cell of the box and ends where the water
leaves the aquifer, most often in a seepage cell, so the tracks that end in the seepage cells
show where their water comes from.
