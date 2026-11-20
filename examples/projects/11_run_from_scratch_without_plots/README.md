# Example 11: run from scratch, without a single figure

The Canut catchment (Ille-et-Vilaine), 24.9 km², cut out of a regional 75 m DEM from its outlet. Steady state under 350 mm/year of recharge, a 50 m aquifer in three layers of the same thickness, a K of 1e-5 m/s and a Sy of 0.01 everywhere, seepage at the ground surface, and particles. MODFLOW 6 solves the flow and its particle tracking PRT follows the water. A run takes about 25 s.

Nothing is drawn. The run exists for the files it leaves behind, which is what a batch job or a machine with no screen needs. `project.toml` switches the display off and asks for no figure, and the script reads numbers and files and draws nothing either.

## The files

- `project.toml`: the model and its exports. `[display] enabled = false` is the only line about figures.
- `py1_run.py`: plays `project.toml` step by step in a `hmp.Lab`. It prints the catchment, the DEM and the mesh as they are built, then the thickness and the K of each layer that MODFLOW 6 will read. It solves, prints the water table, the seepage share and the discharge at the outlet, keeps the model as a run, and opens the files of the run again: the rasters, the NetCDF file, the CSV tables and the particle tracks. Its name has no `plot` in it because it draws no figure.

The DEM is read from the shared `data/` folder of the workspace, by a `workspace:` name. The recharge is written in `project.toml`.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run.py
hmp show canut_example_11
hmp export canut_example_11 --list
```

Run the file twice and nothing is computed the second time. The script keeps a run of its own each time it is played, so it writes the next version, `canut_example_11_v2`.

## The model

The outlet lies off the flow network, so it moves 89 m onto it. The domain is the box around the catchment widened by 10 % of the square root of its area, 73 rows by 128 columns of 75 m. The three layers are 16.7 m thick on average. Every cell drains at the ground surface with a conductance that follows K.

With these values the mean water table is 6.3 m under the ground over the catchment, 9.4 % of its cells seep, and the outlet gives 0.277 m³/s, which matches the recharge over the catchment.

## The particles

PRT tracks forward only. One particle starts at the top of each cell of the box and travels with the flow until it leaves the aquifer, most of them in a seepage cell. Its travel time is the time its water needs to go from the cell where it entered to the stream. The porosity is 1 %, so the times are short: half of the particles leave within 2 years and nine in ten within 9 years.

## What a run writes

- `runs/canut_example_11/exports/`: the catchment and its box as GeoPackage, the DEM, the water table, its depth, the seepage cells and the drain flow as GeoTIFF, the same fields in one NetCDF file, the water budget and the discharge as CSV, and the particle tracks as GeoPackage, one line per particle with its travel time in years. Every file opens in QGIS or a spreadsheet.
- No `figures/` folder, because no figure is asked for.
- `fields.zarr` and `tables.parquet` in the same folder hold the whole run, so any variable can be read again later, with `hmp export`, with `run.read` or from the catalog, without solving.
