# Example 10: coupling with a land surface model on the Urse catchment

The Urse catchment (Switzerland, EPSG:2056), 6.2 km² of Alpine grassland between 1800 and 3400 m.
The land surface model PyHELP computed the recharge, a grid of daily percolation over 2021-2023
from the rain, the air temperature and the solar radiation, and `examples/data/recharge/recharge_pyhelp_urse.nc`
holds that grid. This example models the groundwater flow it forces: steady state, MODFLOW 6, one
layer 50 m thick, K of 3.1e-6 m/s, seepage at the ground surface. A second file searches K on the
mapped stream network, with no discharge observation. A run takes about 40 s.

## The files

- `project.toml`: the model, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` step by step in a `hmp.Lab`. It draws the daily and
  monthly recharge of the PyHELP grid after `load_data`, the mesh on the relief after
  `prepare_solver`, and prints the recharge that MODFLOW 6 reads in each cell. It solves, tries K
  ten times smaller and ten times larger to show how the seepage follows K divided by the
  recharge, keeps the model as a run, and asks the run for two more figures: the depth of the
  water table under the mapped streams, and a section from south to north.
- `run_calibration_k.toml`: inherits `project.toml` and searches K.

The DEM, the catchment polygon, the mapped network and the recharge grid are read from the shared
`data/` folder of the workspace, by `workspace:` names.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp run run_calibration_k.toml
hmp export urse_example_10 --list
```

Run a file twice and nothing is computed the second time. The script keeps a run of its own each
time it is played, so it writes the next version, `urse_example_10_v2`.

## The model

The catchment is a polygon drawn on the Swiss grid. The domain is the box around it, widened by
20 % of the square root of its area, about 500 m on each side, cut on a 25 m DEM: 196 rows and 147
columns, 28 470 active cells. The last row and the last column of the box lie outside the DEM and
are not active. K is homogeneous, Sy is 0.01 and Ss is 1e-5 m⁻¹. Every cell drains at the ground
surface with a conductance C = K × cell area / 1 m, so the extent of the seepage depends on K
divided by the recharge.

## The recharge

PyHELP is a column model. It computes one water balance per cell, and its percolation under the
root zone is the recharge. Here it ran with one rain series and one soil, so the 1600 cells of the
grid hold the same series. The recharge is zero from December to April, then it follows the rain and
the melt: 685, 638 and 929 mm in 2021, 2022 and 2023. The mean
is 750.9 mm/year.

The run declares a `[simulation.time]` window even though it is steady. A gridded forcing is cut
on the window of the run before it is averaged, so a steady run has to say which three years it
averages. Without the window the cut is empty and the aquifer would be solved with no recharge.

## The water table

With K = 3.1e-6 m/s the water table lies 32 m under the ground on average over the catchment and
reaches the ground in 3.1 % of its cells. The discharge at the outlet is about 13 200 m³/day. A K
ten times smaller lets the water table reach the ground in a third of the catchment, and a K ten
times larger leaves almost no seepage. This is what the calibration uses.

## The calibration

`run_calibration_k.toml` compares the stream network that the water table sustains with the mapped
one. The criterion is the signed gap between the two, and a bisection on K drives it to zero. The
search takes 14 solves and about 50 s, and ends on K = 3.9e-6 m/s, a K divided by the recharge of
165. The gap does not reach zero. It jumps between two neighbouring values of K, because a cell
either seeps or it does not, so the search stops when the bracket of K is 1 % wide.

## What a run writes

- `runs/urse_example_10/figures/`: the catchment card, the mesh on the topography, the recharge,
  the water table, its depth and the seepage cells with the mapped streams, the mapped network, the
  simulated network alone and over the mapped one, where the two agree, and a section from west to
  east.
- `runs/urse_example_10/exports/`: the catchment and the mapped network as GeoPackage, the water
  table, its depth, the seepage cells and the recharge as one NetCDF that QGIS opens, and the
  water budget as CSV.
- `sessions/urse_example_10_k/`: the trials of the calibration and its figures, the root search,
  the parameter against the cost and the progress of the search.
- `summary/`: the figures the script draws, outside the sealed run.
