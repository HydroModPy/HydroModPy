# Add a lake or a reservoir

```{hmp-task}
Task
: Add a lake or a reservoir whose stage the solver computes from its exchange with the aquifer, its outlets and its forcings.

Time
: An hour, most of it preparing the footprint and the stage-volume-area table.

Needs
: A MODFLOW 6 model with two layers or more, a polygon of the lake and its stage-volume-area table. Example 04 provides neither.

Gives
: The stage, the volume and the lake-aquifer exchange of every lake at every step.
```

A lake or a reservoir exchanges water with the aquifer, and its level moves with that
exchange. HydroModPy writes it as a MODFLOW 6 LAK package: you give a footprint and a
stage-volume-area table, and the solver computes the stage, the volume and the flow
between the lake and the aquifer at every step. The stage is a result, not an input. The
run stores one series per quantity under the station `lake:<name>`.

The lake needs MODFLOW 6. The balance that the stage-volume table closes is explained in
{doc}`../theory/exits`.

## What you need first

- A model that runs, with the MODFLOW 6 solver. The blocks below are merged onto
  `step4_transient.toml` of example 04, which has no lake. They show the keys to add;
  the file names are yours.
- A vector file with the lake footprint, in the project CRS.
- A table with three columns, `stage`, `volume` and `sarea`, that covers the levels the
  lake can reach.
- At least two layers in the mesh. A lake takes the top layer or layers of its cells, and
  the aquifer below must stay active.

The lake needs MODFLOW 6, the solver of example 04. `hmp config check` refuses a lake on
a file whose flow process names MODFLOW-NWT.

Example 04 has no lake, and the data shipped with the examples hold no lake footprint and
no stage-volume-area table: the folders `lake_geometry` and `lake_abacus` that
`hmp workspace init` creates carry only `EXAMPLE` templates, which are never loaded and do
not lie in the Nançon catchment. This page therefore shows no result figure. To run it, you
provide two files of your own:

- `lake/lac0.gpkg`, one polygon of the lake in the project CRS (EPSG:2154 for example
  04), with a `lake_id` column when the file holds several lakes;
- `lake/lac0.csv`, the table of step 3, from a bathymetry survey or from the DEM of a
  reservoir drawn down.

Both paths are read from the folder of the config file.

## 1. Declare the lake

Three things make a lake. The token `lake` goes in {toml}`flow.active_bc`. A table
`[flow.sinks_sources.lakes.<name>]` carries its leakance and its starting stage. Two data
sections give the footprint and the table. The mesh gets a second layer in the same step.

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "lake"]

[flow.sinks_sources.lakes.lac0]
bedleak = 1e-6
stageinit = "101.0 m"

[[data.lake_geometry.sources]]
source = "custom"
path = "lake/lac0.gpkg"

[[data.lake_abacus.sources]]
source = "custom"
path = "lake/lac0.csv"
lake_id = "lac0"

[modflow6.sgrid.vertical]
nlay = 2
```

The numbers and paths are placeholders. `lac0` is a name of your choice. A list in an
overlay replaces the one of its parent, so `active_bc` repeats `"drainage"` from the base
file. `"reservoir"` is a synonym of `"lake"`: both build the same package.

```{hmp-params}
flow.active_bc
flow.sinks_sources.lakes.<name>.bedleak
flow.sinks_sources.lakes.<name>.bedleak_unit
flow.sinks_sources.lakes.<name>.stageinit
flow.sinks_sources.lakes.<name>.occupied_layers
modflow6.sgrid.vertical.nlay
```

Once `lake` is in {toml}`flow.active_bc`, the data planner adds `lake_geometry`,
`lake_abacus`, `lake_inflow` and `lake_withdrawal` to the families it loads, so you do not
list them in {toml}`data.types`. You write the sections of the first two. The other two
are optional, and the run warns that their section is missing when you leave them out.

### Three names must agree

- The lake name, here `lac0`, is the table name of the lake.
- The abacus carries a lake name in its `lake_id` column. When the file has no such column,
  the name comes from {toml}`lake_id|data.lake_abacus.sources.lake_id`, and when that is
  missing too, from the file name without its extension. A table named `bathymetry.csv`
  that you never name is stored as the lake `bathymetry`, and no lake `lac0` receives it.
- With one lake, any footprint file feeds it. With several lakes, the footprint file needs a
  `lake_id` column whose values are the lake names.

## 2. Give the footprint

The footprint is a polygon in a Shapefile, a GeoPackage or a GeoJSON file.

```{hmp-params}
data.lake_geometry.sources.path
data.lake_geometry.sources.default_crs
```

HydroModPy intersects the polygon with the mesh as it is. It does not reproject it, so the
file must be in the project CRS. The CRS given by {toml}`default_crs|data.lake_geometry.sources.default_crs`
is used only when the file has none.

Every cell the polygon touches belongs to the lake. In these cells, the top
{toml}`occupied_layers|flow.sinks_sources.lakes.<name>.occupied_layers` layers become
inactive, and the layer below receives the lake-bed connection. A deep reservoir sets a
higher count, and the model must keep at least one active layer under it. In this mode
recharge is set to zero on the lake cells, because the lake gets its own rain through the
package.

Islands inside the polygon stay aquifer. To make the lake one block of cells, set
{toml}`flow.sinks_sources.lakes.<name>.fill_enclosed_cells`.

```{hmp-params}
flow.sinks_sources.lakes.<name>.fill_enclosed_cells
```

## 3. Give the stage-volume-area table

The table says how much water the lake holds, and how wide its surface is, at each stage.
MODFLOW 6 reads it as a lookup table. The file is a CSV or a Parquet file with the
columns below. Lines that start with `#` are comments in a CSV.

```text
stage,volume,sarea
98.0,0.0,0.0
101.0,40000.0,20000.0
104.0,100000.0,25000.0
108.0,200000.0,30000.0
```

The stage is an elevation in meters, the volume is in cubic meters and the surface area
in square meters. The values above are placeholders. The rules:

- `stage` increases strictly from one row to the next.
- `volume` and `sarea` are not negative. The import accepts a volume that stays equal
  between two rows. The solver build does not: the volume must increase strictly with the
  stage, so drop the rows of dead storage below the bed.
- `sarea` does not decrease when the stage rises.
- The table has at least two rows, and it covers the whole range of stages the lake can
  reach. MODFLOW 6 extrapolates poorly outside it.

```{hmp-params}
data.lake_abacus.sources.path
data.lake_abacus.sources.lake_id
```

### Starting stage

The lake starts at {toml}`stageinit|flow.sinks_sources.lakes.<name>.stageinit`. Two
settings change that start.

- A hotstart from an earlier run replaces it. {toml}`flow.restart_from` seeds the heads
  and each lake stage from the last step of the earlier run.
- The first period of a transient run is solved steady by default. In that period the stage
  settles to its equilibrium with the aquifer. For a managed reservoir whose observed
  level is far from that equilibrium, hold the stage with
  {toml}`flow.sinks_sources.lakes.<name>.steady_stage_hold`.

```{hmp-params}
flow.restart_from
flow.sinks_sources.lakes.<name>.steady_stage_hold
```

## 4. Add a spillway

Without an outlet, the lake leaves only through the aquifer. Outlets are the spillways and
the controlled releases. They are an array of tables, and `couttype` picks the shape of
each one.

| `couttype` | What it is | Keys it needs |
|---|---|---|
| `WEIR` | A fixed crest. The discharge is zero while the stage is at or below `invert`. | `invert`, `width` |
| `MANNING` | A channel with a roughness and a bed slope. | `invert`, `width`, `rough`, `slope` |
| `SPECIFIED` | A release you impose, such as a gate. | `rate`, or a `forcing` |

The lines below give the lake of step 1 a weir and a gate. Here and in the next steps a
block shows only what to add to the file of step 1; the whole file, with every addition,
is at the end of the page and loads as written.

```toml
# not checked: add these lines to the file of step 1; the full file is validated at the end
[[flow.sinks_sources.lakes.lac0.outlets]]
couttype = "WEIR"
invert = "104.0 m"
width = "5.0 m"

[[flow.sinks_sources.lakes.lac0.outlets]]
couttype = "SPECIFIED"
rate = "-0.02 m^3/s"
```

A `SPECIFIED` rate is signed: a negative rate takes water out of the lake. A release that
follows a schedule uses `forcing` instead of `rate`, and an outlet takes one of the two,
never both.

```{hmp-params}
flow.sinks_sources.lakes.<name>.outlets.couttype
flow.sinks_sources.lakes.<name>.outlets.invert
flow.sinks_sources.lakes.<name>.outlets.width
flow.sinks_sources.lakes.<name>.outlets.rough
flow.sinks_sources.lakes.<name>.outlets.slope
flow.sinks_sources.lakes.<name>.outlets.rate
```

### Where the spillway water goes

{toml}`flow.sinks_sources.lakes.<name>.outlets.lakeout` set to 0 sends the discharge out of
the model. A positive integer sends it directly to that lake, counted from 1 in the order
the lake tables appear in the file.

For a controlled transfer, keep `lakeout` at 0 and add a `mover` to the outlet. The outlet
then feeds a MODFLOW 6 water mover (MVR) record. The receiver is a lake, an SFR reach or
the reach at the foot of the dam, and exactly one of the three is set. `mvrtype` says how
much moves. An outlet sets `lakeout` or a `mover`, never both.

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "lake"]

[flow.sinks_sources.lakes.lac_upper]
bedleak = 1e-6
stageinit = "120.0 m"

[[flow.sinks_sources.lakes.lac_upper.outlets]]
couttype = "WEIR"
invert = "121.0 m"
width = "8.0 m"

[flow.sinks_sources.lakes.lac_upper.outlets.mover]
lake = 2
mvrtype = "FACTOR"
value = 1.0

[flow.sinks_sources.lakes.lac0]
bedleak = 1e-6
stageinit = "101.0 m"

[[data.lake_geometry.sources]]
source = "custom"
path = "lake/lakes.gpkg"

[[data.lake_abacus.sources]]
source = "custom"
path = "lake/lac_upper.csv"
lake_id = "lac_upper"

[[data.lake_abacus.sources]]
source = "custom"
path = "lake/lac0.csv"
lake_id = "lac0"
```

Here `lake = 2` is the second lake of the file, `lac0`. With two lakes, the footprint file
`lakes.gpkg` holds one polygon per lake, and its `lake_id` column carries `lac_upper` and
`lac0`.

```{hmp-params}
flow.sinks_sources.lakes.<name>.outlets.lakeout
flow.sinks_sources.lakes.<name>.outlets.mover.lake
flow.sinks_sources.lakes.<name>.outlets.mover.reach
flow.sinks_sources.lakes.<name>.outlets.mover.to_downstream_reach
flow.sinks_sources.lakes.<name>.outlets.mover.mvrtype
flow.sinks_sources.lakes.<name>.outlets.mover.value
```

The spillway of a dam that feeds a stream uses {toml}`to_downstream_reach|flow.sinks_sources.lakes.<name>.outlets.mover.to_downstream_reach`
and needs an SFR network: see {doc}`route-streams-with-sfr`. The other direction, a
stream that ends in a lake, is {toml}`flow.sinks_sources.sfr.<name>.outflow_to_lake`.

## 5. Choose what falls on and enters the lake

The lake receives rain, loses open-water evaporation, and can take runoff, an inflow and a
withdrawal. Three of them have a source without any key from you.

- If {toml}`data.precipitation` and {toml}`data.etp` are loaded, their watershed mean sets
  the rainfall and the evaporation of every lake.
- If {toml}`data.runoff` is loaded, the catchment runoff rate times the catchment area
  enters each lake as a volume. Example 04 loads runoff, so a lake added to it receives
  this water. When an SFR network routes the runoff, the lake does not take it directly:
  the water reaches the lake through the reaches.
- A forcing you declare for the lake wins over these.

To declare a forcing, write it under the lake. Rainfall and evaporation are rates per unit
of lake surface. Runoff, inflow and withdrawal are volumes per time.

```toml
# not checked: add these lines to the file of step 1; the full file is validated at the end
[flow.sinks_sources.lakes.lac0.rainfall]
kind = "constant"
value = 2.0e-8
units = "m/s"

[flow.sinks_sources.lakes.lac0.withdrawal]
kind = "seasonal"
units = "m3/s"
by_season = { DJF = -0.01, MAM = -0.03, JJA = -0.05, SON = -0.02 }
```

A forcing is `constant`, `csv`, `piecewise` or `seasonal`, picked by `kind`. A `piecewise`
forcing covers the run with dated segments, each one a constant or a CSV. A `seasonal`
forcing repeats a mapping by season or by month, and the mapping must be complete.

```{hmp-params}
flow.sinks_sources.lakes.<name>.rainfall
flow.sinks_sources.lakes.<name>.evaporation
flow.sinks_sources.lakes.<name>.runoff
flow.sinks_sources.lakes.<name>.inflow
flow.sinks_sources.lakes.<name>.withdrawal
```

An inflow or a withdrawal can also come from files. The station id of each chronicle is the
lake name, and the series is averaged over each stress period.

```toml
# not checked: add these lines to the file of step 1; the full file is validated at the end
[[data.lake_inflow.sources]]
source = "custom"
path = "lake_inflow"
station_ids = ["lac0"]
```

```{hmp-params}
data.lake_inflow.sources.path
data.lake_inflow.sources.source_unit
data.lake_withdrawal.sources.path
```

The keys of the lake data sections are in
{doc}`../reference/parameters/data/lake_abacus`, {doc}`../reference/parameters/data/lake_geometry`
and {doc}`../reference/parameters/data/lake_inflow`.

How the forcings reach MODFLOW 6 is a detail of the writer: a long chronicle goes to a
time-series file, a short one into the stress periods, and the declared forcing reaches
the solver either way. {toml}`modflow6.process_specific.lak_forcing_mode` forces one of the
two.

## 6. Carve the lake bed from a bathymetry

By default the lake is a flat reservoir: its footprint cells are inactive and the table
alone gives the storage. If you have a bathymetry raster, the real bed can be carved into
the mesh. The raster is resampled on the lake cells, and by default re-mapped so that the
area of the carved basin follows the table. The table stays the source of truth for the
storage.

```toml
# not checked: add these lines to the file of step 1; the full file is validated at the end
[flow.sinks_sources.lakes.lac0.bed_reconstruction]
dynamic_area = true

[data]
types = ["hydrography", "hydrometry", "recharge", "runoff", "lake_bathymetry"]

[[data.lake_bathymetry.sources]]
source = "custom"
path = "lake/lac0_bathymetry.tif"
```

The bathymetry is not inferred from `active_bc`, because it is read only by a lake that
asks for the carve: you list `lake_bathymetry` in {toml}`data.types` and write its section. A lake with `bed_reconstruction` and no
bathymetry stops the build.

With {toml}`dynamic_area|flow.sinks_sources.lakes.<name>.bed_reconstruction.dynamic_area`
the lake-bed cells stay active. A cell exchanges with the lake while it is under water and
recharges as land when the shore drops below its bed. This is the case of a lake that
rises and falls over a wide shore band. The mode is harder for the solver: see the last
section.

```{hmp-params}
flow.sinks_sources.lakes.<name>.bed_reconstruction.reconcile_to_abacus
flow.sinks_sources.lakes.<name>.bed_reconstruction.dynamic_area
flow.sinks_sources.lakes.<name>.bed_reconstruction.bank_seepage
flow.sinks_sources.lakes.<name>.bed_reconstruction.min_thickness
flow.sinks_sources.lakes.<name>.bed_reconstruction.min_pixels
data.lake_bathymetry.sources.path
```

The figure `lake_abacus_comparison` checks the carve. It overlays the table on what the
carved cells hold at each stage. It tests the geometry, not the water balance: MODFLOW 6
reads the table as it is, so the storage is right whatever the figure shows.

## 7. Check it

`hmp config check` validates the shape of the file and the links between the lake keys.

```text
$ hmp config check lake.toml
```

It does not open the footprint or the table. Those are read when the data is loaded, so a
missing file, a CRS mistake or a table that breaks a rule shows up at the run. The last
section lists the messages.

To see what the run builds without solving, `hmp run lake.toml --dry-run` prints the
resolved plan.

Then run it.

```text
$ hmp run lake.toml
```

After the run, list the lake series the store holds.

```text
$ hmp catalog query "SELECT DISTINCT station_id, variable FROM timeseries WHERE station_id LIKE 'lake:%'"
```

## 8. Read what the run reports

Each lake has one station, `lake:<name>`. These variables are stored for it, in SI units.

| Variable | What it is | Unit |
|---|---|---|
| `stage` | Solved lake stage. | m |
| `volume` | Volume, read from the table. | m3 |
| `surface_area` | Surface area, read from the table. | m2 |
| `gwf_exchange` | Lake-aquifer exchange. Positive when the lake gains water from the aquifer, negative when it loses water. | m3/s |
| `seepage_under_dam` | The part of the exchange that goes through the lake bed (the vertical connections). | m3/s |
| `ext_outflow` | Discharge that leaves the model through the outlets, not through a mover. Positive for an outflow. | m3/s |
| `outlet` | Discharge through the outlets. | m3/s |
| `inflow`, `runoff`, `rainfall`, `evaporation`, `withdrawal` | The terms of the lake water balance, as the solver applied them. | m3/s |
| `storage` | The storage term of the lake balance. | m3/s |
| `to_mvr`, `from_mvr` | Water the lake sends to, or receives from, a water mover. Only with a mover. | m3/s |

Rainfall and evaporation are volumes per time here, because the solver reports them for
the whole lake surface.

The exchange is read from the LAK binary budget, not from the per-connection observations.
The two differ on a connection with no wetted area, and summing the observations would
inflate the exchange as the lake draws down. The total matches the package budget file.
The same value is stored in the `budgets` table as the component `lak_gwf`.

The per-cell lake seepage is a field named `lake`. It is stored only when
{toml}`simulation.results.budget.spatial_fields` is on.

In Python:

```python
import hydromodpy as hmp

run = hmp.open(".").latest()
run.stations("stage")
stage = run.timeseries("stage", station="lake:lac0")
```

To write the series to a file, add an `[[export]]` block, or call `hmp export` for a run
you already have. The CSV holds the columns `datetime`, `station_id`, `variable`, `value`
and `unit`, one row per value. Give the block a `file` of its own: step 4 already writes
its discharge series to the default CSV of the run, and two exports to one file stop the
run.

```toml
# not checked: add these lines to the file of step 1; the full file is validated at the end
[[export__append]]
variables = ["stage", "volume", "gwf_exchange"]
file = "lake_series.csv"
```

```text
$ hmp export @last stage volume gwf_exchange --format csv
```

### Compare with a gauged level

A gauged level is a record of the lake stage, in a folder of station files like the other
records. The station id is the lake name. It is never loaded by itself, so list it in
{toml}`data.types`.

```toml
# not checked: add these lines to the file of step 1; the full file is validated at the end
[data]
types = ["hydrography", "hydrometry", "recharge", "runoff", "lake_levels"]

[[data.lake_levels.sources]]
source = "custom"
path = "lake_levels"
station_ids = ["lac0"]

[display]
figures = ["lake_stage_sim_obs", "lake_volume_sim_obs"]
```

`lake_stage_sim_obs` draws the simulated stage over the gauged one, with the usual scores.
`lake_volume_sim_obs` does the same in volume: the gauged stage goes through the table of
the lake, never through the carved bed. Both figures are refused when the run has no gauged
level. A calibration can target the stage of a lake with
{toml}`calibration.outputs.<name>.lake_id`: see {doc}`calibrate`.

## Put it together

This file holds the lake of step 1 and every addition of steps 4 to 8, except the second
lake of the mover. It loads as written; it runs once the two files of the first section
and the files it names exist. {download}`Download it <recipes/model/guide_lake.toml>`.

```toml
base_config = "step4_transient.toml"

[simulation]
name = "nancon_guide_lake"

[flow]
active_bc = ["drainage", "lake"]

[flow.sinks_sources.lakes.lac0]
bedleak = 1e-6
stageinit = "101.0 m"

[[flow.sinks_sources.lakes.lac0.outlets]]
couttype = "WEIR"
invert = "104.0 m"
width = "5.0 m"

[[flow.sinks_sources.lakes.lac0.outlets]]
couttype = "SPECIFIED"
rate = "-0.02 m^3/s"

[flow.sinks_sources.lakes.lac0.rainfall]
kind = "constant"
value = 2.0e-8
units = "m/s"

[flow.sinks_sources.lakes.lac0.withdrawal]
kind = "seasonal"
units = "m3/s"
by_season = { DJF = -0.01, MAM = -0.03, JJA = -0.05, SON = -0.02 }

[flow.sinks_sources.lakes.lac0.bed_reconstruction]
dynamic_area = true

[data]
types = ["hydrography", "hydrometry", "recharge", "runoff", "lake_bathymetry", "lake_levels"]

[[data.lake_geometry.sources]]
source = "custom"
path = "lake/lac0.gpkg"

[[data.lake_abacus.sources]]
source = "custom"
path = "lake/lac0.csv"
lake_id = "lac0"

[[data.lake_inflow.sources]]
source = "custom"
path = "lake_inflow"
station_ids = ["lac0"]

[[data.lake_bathymetry.sources]]
source = "custom"
path = "lake/lac0_bathymetry.tif"

[[data.lake_levels.sources]]
source = "custom"
path = "lake_levels"
station_ids = ["lac0"]

[modflow6.sgrid.vertical]
nlay = 2

[display]
figures = ["lake_stage_sim_obs", "lake_volume_sim_obs", "lake_abacus_comparison"]

[[export__append]]
variables = ["stage", "volume", "gwf_exchange"]
file = "lake_series.csv"
```

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `flow.sinks_sources.lakes declares lakes but flow.active_bc lists neither 'lake' nor 'reservoir'; ...` from `hmp config check` | A lake table that nothing would build. | Add `"lake"` to `active_bc`. |
| `solver.backend='modflow_nwt' does not support the 'lake' boundary (supported by: modflow6); it would be silently ignored. ...` from `hmp config check` | The flow process names MODFLOW-NWT. | Use MODFLOW 6. |
| `Unsupported leakance unit 'm'. Allowed units: 1/s, 1/day, 1/h, 1/min` from `hmp config check` | `bedleak_unit` is not a leakance. | Write a unit per time. |
| `flow.sinks_sources.lakes outlet 'SPECIFIED' requires either rate or forcing` from `hmp config check` | A gate with no release. | Give the outlet a `rate` or a `forcing`, not both. |
| `flow.sinks_sources.lakes outlet sets both lakeout and mover; keep lakeout = 0 when a mover is declared` from `hmp config check` | Two routings on one outlet. | Choose one. |
| `flow.active_bc lists "lake" without "sfr": ...` from `hmp config check` | A lake in soil mode, where the water reaches a lake only through the streams. | Add the network: see {doc}`recharge` and {doc}`route-streams-with-sfr`. |
| `Data manager 'lake_geometry' is active but missing [data.lake_geometry] section.` (warning, data step) | No footprint section. The same warning appears for `lake_inflow` and `lake_withdrawal`. | Write the section. The warning is harmless for the two optional families. |
| `Abacus contract violated (lac0.csv)` (data step) | The table breaks a rule of step 3. The message lists the failed checks. | Fix the table. |
| `flow.sinks_sources.lakes.lac0 has no polygon geometry; load the lake_geometry data family before pre-processing.` (mesh step) | The footprint did not reach the lake. | With several lakes, add a `lake_id` column whose values are the lake names. |
| `flow.sinks_sources.lakes.lac0 polygon does not intersect any grid cell; check the lake geometry CRS and the model extent.` (mesh step) | The polygon is outside the domain, or not in the project CRS. | Reproject the footprint, or move the model. |
| `flow.sinks_sources.lakes.lac0 occupied_layers (1) must leave at least one active layer below the lake (nlay=1); the VERTICAL connection needs an aquifer cell to leak into.` (mesh step) | One layer under a lake. | Add a layer: `[modflow6.sgrid.vertical] nlay = 2`. |
| `flow.sinks_sources.lakes.lac0.abacus is required to build the LAK stage-volume-area table.` (build step) | The table did not reach the lake: its `lake_id` is not `lac0`. | See the three names of step 1. |
| `flow.sinks_sources.lakes.lac0.abacus volume must strictly increase with stage (MF6 rejects equal volumes); got 0.0 after 0.0. Drop dead-storage rows of equal volume below the bed.` (build step) | Rows of equal volume. | Remove the repeated rows. |
| `flow.sinks_sources.lakes.lac0 outlet lakeout=3 has no matching downstream lake (2 lakes declared).` (build step) | `lakeout` counts the lake tables from 1. | Name a lake that exists. |
| `flow.sinks_sources.lakes.lac0 sets bed_reconstruction but no lake_bathymetry raster was loaded; declare [data.lake_bathymetry].` (build step) | A carve with no bathymetry. | Add `lake_bathymetry` to `data.types` and write its section. |
| `export[<i>] and export[<j>] both write <run>/<run>_series.csv. Give one of them its own file or folder.` when the run starts | An appended export of series without a `file`, on a base file that already exports series. | Give it a `file`, as in step 8. |
| `LAK binary budget <file> is missing; the lake-aquifer exchange series (gwf_exchange, seepage_under_dam, lak_gwf) is not extracted. ...` (warning, after the run) | The solver wrote no lake budget. The run publishes no exchange series rather than a wrong one. | Run again. |
| `run holds no gauged lake level for 'lac0'; declare [data.lake_levels]` (figure) | A level figure without a gauged level. | See the last block of step 8. |

If the solver does not converge, go to {doc}`non-convergence`. One setting belongs to
lakes. {toml}`surfdep|flow.sinks_sources.lakes.<name>.surfdep` smooths the dry and wet
transition of the lake edge, and a higher value helps the active-shore mode when many
cells toggle at once, at the cost of a fuzzier shoreline.

```{hmp-params}
flow.sinks_sources.lakes.<name>.surfdep
```

## Next

- Add a cutoff wall under the dam: {doc}`add-a-flow-barrier`.
- Connect the lake to a stream network: {doc}`route-streams-with-sfr`.
- Fit the leakance to a gauged level: {doc}`calibrate`.
- Start the lake from a settled state: {doc}`time-and-initial-state`.
- Every key of the lake: {doc}`../reference/parameters/flow/sinks_sources/lakes`.
- The balance behind the stage: {doc}`../theory/exits`.
