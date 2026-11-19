# Example 09: nitrate in the aquifer of an agricultural catchment

The Kervidy catchment at Naizin (Morbihan), 5.0 km² of farmland cut out of a 25 m DEM, in a box
of 134 by 165 cells. A synthetic drought year 2003 in 52 weekly stress periods: 2 mm/day of
recharge in January, February, November and December, and none from March to October. The
aquifer sits on a flat base at sea level, about 100 m under the valley, cut in ten layers that
thicken with depth. K and Sy fall with depth, and every cell drains at the ground surface. The
nitrate starts at 100 mg/L in the whole aquifer, the recharge brings 50 mg/L, and it decays with
a mean life of two years. MODFLOW 6 solves the flow, its transport model GWT carries the nitrate
and its particle tracking PRT gives the travel time of the water. A run takes about 20 minutes.

## The files

- `project.toml`: the model, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` step by step in a `hmp.Lab`. It draws the recharge,
  the runoff and the gauged discharge of 2003, then the mesh on the relief, and prints for each
  of the ten layers its thickness, K and Sy as MODFLOW 6 will read them. It then solves and keeps
  the model as a run. From the run it prints the water table, the seepage and the discharge week
  by week, draws the nitrate of the seepage cells of each week as a box beside the recharge, asks
  the run for a map of that nitrate every four weeks and stitches the maps into an animated GIF.
  It ends with the travel times of the particles.

The DEM, the mapped streams of BD Topage, the discharge gauged at the outlet (station `KERVIDY`)
and the runoff are read from the shared `data/` folder of the workspace, by a `workspace:` name.
The recharge is written in `project.toml`.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp export naizin_example_09 --list
```

Run the file twice and nothing is computed the second time. The script keeps a run of its own
each time it is played, so it writes the next version, `naizin_example_09_v2`, and takes as long
as `hmp run`.

The run is long because the box holds 221 100 cells and 52 weeks, and MODFLOW 6 solves the flow
three times: alone in about 4 minutes, then beside GWT and beside PRT in about 6 minutes each.

## The model

The first week is solved in steady state under the mean recharge of the year, 0.65 mm/day, so
the drought starts from a water table in balance. K is 5e-5 m/s at the ground and falls with
depth, faster under the hills: its decay length is 15 m where the ground stands at 93 m or lower
and 1 m where it stands at 136 m or higher, down to 1e-8 m/s. Sy is 0.02 at the ground and falls
the same way, with a decay length of 30 m in the valley and 10 m on the hills, down to 0.001.
The first layer takes both at the ground, and each layer below at its base. The runoff is a
tenth of the recharge. It does not enter the aquifer and is added to the drain flow to give the
discharge.

## The nitrate

The nitrate is written in kg/m3 in `project.toml`, 0.1 for 100 mg/L, and the figures draw it in
mg/L. GWT counts time in seconds, so the decay rate is 1.5855e-8 /s for a mean life of two years
and the diffusion is 1e-10 m²/s. The longitudinal dispersivity is 5 m, and the transverse ones
are ratios of it, 0.5 across and 0.05 down. No porosity is given, so each cell takes its Sy as
porosity, and HydroModPy warns about it. The nitrate of the seepage cells falls from 96 mg/L to
76 mg/L over the wet weeks of the winter, then by about 0.6 mg/L a week through the dry months
as the old water decays, down to 50 mg/L in December.

## The particles

PRT tracks forward only. One particle starts in each of 2000 columns spread over the box and
travels with the flow until it leaves the aquifer, most of them in a seepage cell. After the last
week the particles go on with the flow of December. The travel time of a particle is the time its
water needs to reach the stream from the cell where it entered. Half of the particles leave
within 0.8 years and nine in ten within 2 years.

## What a run writes

- `runs/naizin_example_09/figures/`: the catchment card, the mesh on the topography, the
  simulated discharge against the gauge, the weekly water budget, the water-table depth with the
  seepage cells at the end of October, the share of the year each cell seeps, the nitrate of the
  seepage cells in January and in October, a section of the nitrate from west to east in
  October, and the map of the travel time of each cell under the pathlines of the particles.
- `runs/naizin_example_09/exports/`: the catchment and the mapped streams as GeoPackage, the
  water table, its depth and the seepage cells of the end of October as GeoTIFF, the nitrate of
  the seepage cells at the end of the year as GeoTIFF, the simulated and
  gauged discharge and the budget as CSV, and the particle tracks as GeoPackage, one line per
  particle with its travel time in years. Every file opens in QGIS or a spreadsheet.
- `summary/`: the figures and the animation the script draws, outside the sealed run.
