# Read the results of a run and write them out as files

A run keeps its results as plain files, in a folder named after the run. This guide shows
where they are, how to read them with pandas and xarray-friendly tools, and how to ask for
GeoTIFF, NetCDF, CSV, GeoPackage and other files, either at the end of the run or after it.

## What you need first

- A project that has run at least once. The worked case is example 04,
  `examples/projects/04_streamflow_intermittence_in_transient`.
- The run name. `hmp catalog ls` lists the runs of the project.
- For the TOML blocks: a file that inherits one of example 04 with `base_config`. The
  blocks below are checked on top of `step4_transient.toml`.

## Where a run keeps its results

A run writes one folder, `runs/<name>/`, named after the run. The arrays are Zarr, the
tables are Parquet, the frozen configuration is TOML, the seal and the provenance are
JSON. Nothing is packed in an archive.

```text
<project>/
├── project.toml                shared settings, and the marker of the project root
├── runs/
│   └── nancon_step4_transient/
│       ├── config.toml         the resolved configuration of this run
│       ├── fields.zarr/        arrays: head, mesh, forcings
│       ├── tables.parquet/     one Parquet file per table
│       ├── figures/            figures rendered for this run
│       ├── provenance.json    versions, git commit, solver binary
│       ├── manifest.json       the seal, written last
│       └── annotations.json    tags and notes, written after the seal
├── sessions/                   one folder per calibration session
├── share/                      files written by exports, reports and packages
└── .hmp/                       the index, logs and scratch
```

Three rules follow from this layout.

- **A run folder without `manifest.json` did not finish.** The seal is written after every
  file it lists.
- **A run keeps its name.** When a name is reused, the folder gets a `.vN` suffix, as in
  `nancon_step4_transient.v2`. `hmp catalog rename` moves the folder, then updates the index.
- **The index is not the truth.** `.hmp/index.duckdb` makes listing and ranking fast. The
  run folders hold everything needed to read a run. `hmp catalog reindex` rebuilds the
  index from them, and {ref}`Rebuild the index <catalog-reindex>` says what a rebuild
  cannot bring back.

Other files appear in a run folder on request: `ro-crate-metadata.json`, `stac-item.json` and
`prov.jsonld`, written after the seal ({ref}`step-package`). A run in the trash carries a
`trash.json`.

## 1. Read the tables

The files of `tables.parquet/` are plain Parquet. pandas reads them, and no HydroModPy
import is needed.

```python
import pandas as pd

tables = "runs/nancon_step4_transient/tables.parquet"
metrics = pd.read_parquet(f"{tables}/metrics.parquet")
budgets = pd.read_parquet(f"{tables}/budgets.parquet")
series = pd.read_parquet(f"{tables}/timeseries.parquet")
```

A run writes the files it has data for. A run with no SFR network has no
`sfr_reaches.parquet`.

| File | Columns |
|---|---|
| `simulation.parquet` | One row: the identity of the run. A rebuild of the index reads it back. |
| `parameters.parquet` | `sim_id`, `param_name`, `zone_id`, `value`, `unit`, `parameterization`, `valid_from` |
| `metrics.parquet` | `sim_id`, `station_id`, `variable`, `metric`, `value`, `n_samples`, `valid_from`, `period_start`, `period_end` |
| `timeseries.parquet` | `sim_id`, `station_id`, `variable`, `component`, `timestep`, `time`, `value`, `unit`, `qflag` |
| `budgets.parquet` | `sim_id`, `timestep`, `zone_id`, `component`, `flux_in`, `flux_out`, `unit` |
| `mass_balance.parquet` | `sim_id`, `timestep`, `quantity`, `total_in`, `total_out`, `storage_in`, `storage_out`, `percent_error`, `unit` |
| `provenance.parquet` | One row per input the run used: `variable`, `source_type`, `source_ref`, `source_sha256`, `loader_name`, `fetched_at`, `n_records` and others |
| `observation_points.parquet` | The points declared in the observation section: `station_id`, `x`, `y`, `cell_id`, `layer`, the CRS |
| `sfr_reaches.parquet` | One row per SFR reach: geometry, bed and Manning values, Strahler order |
| `soil_budget.parquet` | The soil reservoir balance, in mm, per column and per year |
| `geographic_<name>.parquet` | GeoParquet features: watershed, contour, buffered box, networks. Read them with `geopandas.read_parquet`. |

## 2. Read the fields

`fields.zarr/` holds the arrays. Read it through `hmp.read`, which finds the variable by its
name and hands back a lazy `xarray.DataArray`.

```python
import hydromodpy as hmp

catalog = hmp.open("path/to/project")
run = catalog.latest()

head = hmp.read(run, "head")                       # lazy DataArray
last = hmp.read(run, "head", time=-1, layer=0)     # eager numpy array
```

An integer `time` returns the numpy array of that one period, counting from the end when it
is negative. Without `time`, every stored period is loaded lazily. `layer`, `sel` and `bbox`
narrow the read. A series or a vector layer goes through the same door:

```python
q = hmp.read(run, "discharge")           # pandas Series
watershed = hmp.read(run, "watershed")   # GeoDataFrame
```

The `Run` object also hands back the tables as data frames: `run.parameters`, `run.metrics`,
`run.mass_balance`, `run.budget()` and `run.timeseries("discharge")`. For raw access to the
arrays, open the folder with `zarr.open_group(path, mode="r")`.

### Some fields are rebuilt when you read them

The store keeps the primary variables. Four fields are not stored by default. They are
recomputed on every read, from the head, the per-cell budget and the mesh.

| Field | Rebuilt from |
|---|---|
| `watertable_elevation` | The head of the uppermost layer that holds a value. |
| `watertable_depth` | `topography - watertable_elevation`, clipped at zero. |
| `seepage_mask` | The surface excess budget field when the solver wrote one. Otherwise a geometric test on the water table. |
| `outflow_drain` | The per-cell drain budget field, summed over layers, as a positive outflow. It needs the per-cell budget to be stored. |

`release_flux` and `fluxes_from_budget` are rebuilt from the per-cell budget too. Three
cards decide what the run stores:

```{hmp-params}
simulation.results.budget.spatial_fields
simulation.results.derived.release_flux
simulation.results.derived.watertable_depth
```

A rebuilt field loads eagerly and ignores laziness. A run with no stored per-cell budget
still gives `watertable_elevation`, `watertable_depth` and `seepage_mask`, and gives neither
`outflow_drain` nor `fluxes_from_budget`. `hmp export <run> --list` shows what a given run
can hand out.

To keep the per-cell budget of a run, add the two switches to its file:

```toml
base_config = "step4_transient.toml"

[simulation.results.budget]
spatial_fields = true

[simulation.results.derived]
release_flux = true
```

The per-cell budget is the heaviest array a run can hold. Leave it off unless you map or
export a per-cell flux.

### What the compact precision means

A field that varies in time (head, per-cell budget terms, stored derived fields,
concentrations) is stored as float32 with its mantissa rounded to 16 bits. This is the
default.

```{hmp-params}
simulation.results.persistence.field_precision
```

In practice, each stored value moves by at most 2 to the power of -17 of itself, which is
7.6e-6 relative. On a 130 m head that is 1 mm. A daily run takes about a third of the disk it
would take in float64. The mesh geometry, the topography, the thicknesses, the indices, the
coordinates and the timestamps are never rounded.

`hmp.read` and every reader of the library hand back float64, so your code sees no change in
dtype. Raw `zarr` access sees the stored float32. A rounded array carries the attributes
`quantization = "quantization_info"` and `quantization_nsb = 16`, which follow the CF 1.11
convention for bit rounding.

Choose `"exact"` when you compare two runs to a tolerance below 1e-5 relative, or when you
want the values as the solver wrote them.

```toml
base_config = "step4_transient.toml"

[simulation.results.persistence]
field_precision = "exact"
```

This key governs a simulation. A calibration has its own switch, {toml}`calibration.persistence.field_precision`.

### The other JSON files

- `manifest.json`: `manifest_version`, `sealed_at`, `run` (id, name, version, status,
  project), `geometry` (cells, layers, mesh hash, CRS, bounding box), `period`, `config`
  (file and hash), `inputs`, `artifacts` (every file the run declares, with size),
  `parameters` and `metrics`.
- `provenance.json`: `tool`, `git` (commit and dirty flag), `python`, `platform`, `packages`,
  `environment`, `solver` (name, version, binary path and hash) and `timing`.
- `annotations.json`: the tags and notes. They are written after the seal, so tagging a run
  never invalidates its manifest.

`config.toml` is the resolved configuration of the run, after `base_config`, overlays and
`--set` overrides. `hmp catalog rerun` replays it.

## 3. Find a run from the command line

`hmp catalog ls` lists the runs of the project, `hmp catalog show <run>` prints one, and
`hmp catalog query` runs SQL on the index. {doc}`find-compare-and-clean-runs` covers these
commands and every way to name a run.

## 4. Ask for files at the end of the run

Each `[[export]]` block of the file is one request, written at the end of the run, in the
order of the file. A block says what, when and where. Only {toml}`export.variables` is
required.

```{hmp-params}
export.variables
export.time
export.period
export.folder
export.file
```

Step 1 of example 04 writes three blocks: the catchment outline, the water table and the seepage
cells at the last period, and the budget. This block adds the water table at one date and the
whole record of the water table to the six blocks of step 4:

```toml
base_config = "step4_transient.toml"

# The water table in the driest month: one GeoTIFF per variable.
[[export__append]]
variables = ["head", "watertable_depth"]
time = "2002-10-15"

# The record of the water table: one NetCDF.
[[export__append]]
variables = ["head", "watertable_depth"]
file = "watertable_2000_2002.nc"
```

`variables` takes a name, a list of names, or `"all"` for everything the run holds. One
namespace covers the mesh fields (`head`, `watertable_depth`, `seepage_mask`), the series
(`discharge`, `discharge_obs`), the vector layers (`watershed`,
`hydrographic_network_reference`), the raster layers (`watershed_dem`, `watershed_fill`) and
the table `budget`. `simulated_active_network` is a field like the others: 1 on the cells the
network criterion counts as flowing at that date, 0 elsewhere. It needs the `release_flux` of
the run and a stored hydrographic network.

`time` takes a date, `"first"`, `"last"`, an integer, or a list of them. A date takes the
stress period that holds it, so one date names the same month on a monthly run and on a daily
run. An integer is a period index, from the end when negative. `period` takes two dates and
writes every period it overlaps. A block takes `time` or `period`, not both.

### What each kind of data becomes

The format follows the data, unless you name one with {toml}`export.format` or with the
extension of {toml}`export.file`.

```{hmp-params}
export.format
```

| Data | One date | Several dates, a period, or the whole run |
|---|---|---|
| Mesh field (`head`, `watertable_depth`, `seepage_mask`) | GeoTIFF, one file per variable | NetCDF, one file for every field of the block |
| Series (`discharge`, `discharge_obs`) and the table `budget` | CSV | CSV |
| Vector layer (`watershed`, `hydrographic_network_reference`) | GeoPackage | GeoPackage |
| Raster layer (`watershed_dem`, `watershed_fill`) | GeoTIFF | GeoTIFF |

A field can also be written as GeoPackage, Shapefile or VTU, a vector layer as Shapefile.
GeoTIFF, Shapefile, GeoPackage and VTU hold one instant, so several dates write one file
per date.

### Where the files land

```{hmp-params}
export.crs
export.resolution
export.layer
```

Files land in `share/<run name>/`. A relative {toml}`export.folder` is read from `share/`.
A relative {toml}`export.file` is read from the folder, and its extension gives the format.
`file` names one exact file, so it fits a request that writes one file. Several files need
`folder` and the automatic names.

A file of one instant is named by the date you asked for: `head_2002-10-15.tif`. When the
request names no date, it is named by the period: `head_2002-10.tif` on a monthly run. A
NetCDF holding several fields is `<run>_fields.nc`, and several series go to
`<run>_series.csv`.

`crs` reprojects a raster or a vector layer. NetCDF, VTU and CSV are written in the model
CRS and refuse it. `resolution` sizes the pixels of a GeoTIFF of a field.

A field of several layers in a format of one layer (GeoTIFF, GeoPackage, Shapefile) needs
`layer`: the top layer of a multi-layer model can be dry. `watertable_elevation`,
`watertable_depth` and `seepage_mask` hold one value per cell and never need it. NetCDF and
VTU keep every layer.

### What each file holds

| Format | Suffix | Notes |
|---|---|---|
| CSV | `.csv` | Series: `datetime`, `station_id`, `variable`, `value`, `unit`. Times are the clock of the run, without a time zone: `2002-10-01 00:00:00`. The simulated catchment series is the station `catchment`. The budget has one row per period, zone and component, with `period_start` and `period_end`. |
| NetCDF | `.nc` | NetCDF-4 with a UGRID-1.0 mesh, every field of the request, the dates asked for. It carries the ACDD metadata of the run. |
| GeoTIFF | `.tif` | Cloud-optimised raster. The pixel size follows the mesh unless `resolution` is given. Tags name the run, the variable, its units and the period (`HMP_PERIOD`). |
| GeoPackage | `.gpkg` | A vector layer as stored, or one polygon per cell carrying a field. |
| Shapefile | `.shp` | The same, for software that reads nothing else. |
| VTU | `.vtu` | Mesh and field, every layer, for ParaView. |
| Package | `.hmp` | The portable archive of the run ({ref}`step-package`). |

A simulated value is dated at the end of its period. A CSV of the monthly discharge of
January 2001 carries the date 2001-02-01.

### Opening a NetCDF in QGIS

Add the `.nc` as a **mesh** layer, not as a raster or a vector layer. QGIS reads it through
MDAL, which understands the UGRID mesh of the file. Each field becomes one dataset group with
its own time steps, and the layer is georeferenced.

MDAL binds a dataset to the faces of the mesh, so a field stored per layer is written as one
variable per layer: `head` on a single-layer model, `head_layer1`, `head_layer2` and so on
above it. If you export over a file that a QGIS layer holds open, QGIS keeps showing the
version it opened. Reload the layer to see the new one.

## 5. Change the exports in a derived file

A file that inherits another one inherits its `[[export]]` list too. Three directives manage
it. {doc}`inheritance` explains them in full.

- A plain `[[export]]` list **replaces** the inherited one, unless it has the same number of
  blocks.
- `[[export__append]]` keeps the inherited blocks and adds its own, as steps 2 to 4 of example 04
  do.
- `export__delete = true` drops the inherited blocks first, then the file writes its own, as
  step 5 does.

```toml
base_config = "step4_transient.toml"

# Drop the six inherited blocks, then write this list.
export__delete = true

[[export]]
variables = ["watershed", "hydrographic_network_reference"]

[[export]]
variables = ["discharge", "discharge_obs"]
period = ["2001-01-01", "2002-12-31"]

[[export]]
variables = "budget"
```

Two lists of the same length do not replace each other: they merge block by block, by
position. Step 1 writes three blocks. A file that inherits step 1 and writes three blocks of
its own gets, for each position, the keys of the new block over the keys of the old one:

```toml
base_config = "step1_minimal.toml"

[[export]]
variables = "head"

[[export]]
variables = "budget"
format = "csv"

[[export]]
variables = ["discharge"]
```

The second block of step 1 has `time = "last"`. The merge keeps it, so this file writes the
budget with `time = "last"` and not the whole record. Write `export__delete = true` at the
top of such a file, and the lengths no longer matter.

## 6. Check it before you solve

```bash
hmp config check my_exports.toml
```

The check reads every `[[export]]` block before any solve. It refuses a name no run can
export, a date outside `[simulation.time]`, `time` together with `period`, a `file` on a
request that writes several files, a format that cannot hold the data, and two blocks that
write the same file. Each message names its block by position, `export[6]` for the seventh
block.

Run the file, then list what the run can export:

```bash
hmp run my_exports.toml
hmp export nancon_step4_transient --list
```

The files are in `share/nancon_step4_transient/`. The command prints what the run holds,
grouped by kind:

```text
nancon_step4_transient can export:
fields:
  head
  seepage_mask
  simulated_active_network
  watertable_depth
  ...
series:
  discharge
  discharge_obs
vector layers:
  hydrographic_network_reference
  watershed
  ...
raster layers:
  watershed_dem
  watershed_fill
tables:
  budget
```

Two runs rarely hold the same names, because `[simulation.results]` decides what each one
stores. The list above is an excerpt.

Example 04 ships `py3_read_exports.py`. It draws a figure from the exported files of step 5
alone, with pandas, geopandas, rasterio and xarray, and no HydroModPy import. It is what a
colleague can do with a copy of `share/<run>/`.

## 7. Export a finished run

The same words work after the run, from the command line and from Python. Both take the keys
of a block and return the files they wrote.

```bash
hmp export nancon_step4_transient --list
hmp export nancon_step4_transient all
hmp export nancon_step4_transient head watertable_depth --time 2002-10-15
hmp export nancon_step4_transient discharge discharge_obs --period 2001-01-01 2002-12-31
hmp export nancon_step4_transient watershed hydrographic_network_reference
hmp export nancon_step4_transient watertable_depth --time last --file depth_wgs84.tif --crs EPSG:4326
hmp export nancon_step4_transient all --format package
```

```python
run.export("all")
run.export(["head", "watertable_depth"], time="2002-10-15")
run.export(["discharge", "discharge_obs"], period=("2001-01-01", "2002-12-31"))
run.export("watertable_depth", time="last", file="depth_wgs84.tif", crs="EPSG:4326")
hmp.export(run, "all", format="package")
```

`hmp export` prints the path of each file it writes, one per line, and the count on the error
stream. `-w` names the project when it is not the current directory. The options are
`--time`, `--period`, `--format`, `--folder`, `--file`, `--crs`, `--resolution` and
`--layer`. `all` exports everything the run holds, each data in its natural format. With
`--format`, it exports every data that format can hold.

(step-package)=
### Package a run for exchange

`package` writes the portable `.hmp` archive of the run. `stac`, `rocrate` and `prov` write
its metadata views. The four describe the whole run, so they take `variables = "all"` and
refuse `time`, `period`, `crs`, `resolution` and `layer`.

```toml
base_config = "step4_transient.toml"

[[export__append]]
variables = "all"
format = "package"
```

A package is written after the seal, so it carries the manifest and the provenance. The
metadata views are written inside the run folder, beside `manifest.json`, unless you give
`folder` or `file`. To send a run to a colleague and load it in another project:

```bash
hmp export nancon_step4_transient all --format package --file paper_run.hmp
hmp catalog import share/nancon_step4_transient/paper_run.hmp
```

```python
run.export("all", format="package", file="paper_run.hmp")

target = hmp.open("path/to/other/project", read_only=False)
target.import_package("share/nancon_step4_transient/paper_run.hmp")
```

`hmp.open` opens a catalog read-only by default, and an import writes to it, so the Python
call needs `read_only=False`.

The import verifies the checksums first. Importing a run that the project already holds
needs `--force`.

## What can go wrong

**A name no run can export.** The check stops before the solve:

```text
no run can export export[6]: 'waterdepth'. The names a run can export:
```

followed by the list of names by kind. Fix the spelling, or read the list.

**A name this run does not hold.** `hmp export` says what the run has. Typically the field is
a per-cell budget term and `spatial_fields` was off, or the run has no stored network. The
message is `run '<name>' holds no '<variable>'.` followed by `It can export:` and the list. The
exit code is 1.

**A date outside the record.**

```text
export[6].time: 2015-10-15 is outside the record: the record runs from 2000-01-01 to 2003-01-01.
```

**Two blocks write one file.**

```text
export[2] and export[6] both write nancon_step4_transient/budget.csv. Give one of them its own file or folder.
```

**A `file` on a request that writes several files.** The message ends with the way out:

```text
file = 'x.tif' names one file, but in geotiff 2 names write one file each. Write folder instead of file, or format = "netcdf", which holds several variables and dates in one file.
```

**A `crs` on a format that does not reproject.**

```text
crs = 'EPSG:4326' on format 'netcdf', which does not reproject: it is written in the model CRS. Drop crs, or write a GeoTIFF, a GeoPackage or a Shapefile.
```

**`time` and `period` together.**

```text
time and period are both given. Write time for instants, or period for a window, not both.
```

**A run format with a variable.**

```text
format = 'package' describes the whole run, not a variable. Write variables = "all".
```

**A field of several layers in a format of one layer.** The message says that the field
holds N layers and that a GeoTIFF holds one, then tells you the way out:

```text
Write layer = 0 for the top layer (or another), or export a field of one value per cell: watertable_elevation, watertable_depth, seepage_mask. NetCDF and VTU keep every layer.
```

**The old `[export]` table.** A file written for the earlier `[export]` table of format
toggles still loads, and `HydroModPyConfig.from_toml` rewrites it in memory as `[[export]]`
blocks. `hmp doctor --fix-config <file>` rewrites the file on disk.

## Where to go next

- {doc}`inheritance` for `__append` and `__delete` on any list.
- {doc}`find-compare-and-clean-runs` to rank, tag, rename and delete runs.
- {doc}`drive-from-python` to run and read from a script.
- {doc}`read-a-value-at-a-point` to read one cell of a finished run.
- {doc}`/understand/reading-results` to read the figures of example 04.
- {doc}`/reference/cli/export` for every option of `hmp export`.
