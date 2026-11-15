# Example 00: a quick tour on the Aber catchment

The Aber catchment (Finistère), 2.4 km² cut out of a regional 75 m DEM. One year 2017 in monthly
stress periods, a 50 m aquifer, seepage at the ground surface, two pumping wells and particles
that show where the seepage water comes from. MODFLOW 6 solves the flow and its particle tracking
PRT follows the water. A run takes about 5 s.

## The files

- `project.toml`: the model, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` step by step in a `hmp.Lab` (mesh, wells, head, a
  change of K) and keeps the model as a run. HydroModPy draws every figure: the mesh on the
  relief before the solve, then two more the script asks the run for. The script also prints the
  numbers of the water budget and writes the particle tracks as a GeoPackage.

The DEM and the mapped streams are read from the shared `data/` folder of the workspace, by a
`workspace:` name. The recharge and the pumping rates are written in `project.toml`.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp export aber_example_00 --list
hmp export aber_example_00 head --time 2017-07-15
```

Run the file twice and nothing is computed the second time: the command names the first run and
stops. Edit the file and the new run is `aber_example_00.v2`, beside the first one. The script
keeps a run of its own each time it is played, so it writes the next version too.

## What a run writes

- `runs/aber_example_00/figures/`: the catchment card, the mesh on the topography, the
  water-table depth and the seepage cells in January, the section through the two wells, the
  share of the year each cell seeps, the particle tracks alone, then over the travel time to the
  exit and over the water-table depth, the distribution of their travel times and the monthly
  water budget.
- `runs/aber_example_00/exports/`: the catchment, its box and the mapped streams as GeoPackage,
  the DEM, the head, the water-table depth and the seepage cells of January as GeoTIFF, the
  twelve months of the same three fields in `watertable_2017.nc`, the discharge and the budget
  as CSV. Every file opens in QGIS or a spreadsheet.
- `summary/`: the figures the script asks for and the tracks it writes, outside the sealed run.

The discharge is the drain flow routed to the outlet over the model top. Its basin is the 426
cells of the catchment polygon.
