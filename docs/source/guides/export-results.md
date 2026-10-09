# Export results as files

```{hmp-task}
Task
: Write the data of a run as GeoTIFF, NetCDF, CSV, GeoPackage or a portable package, at the end of a run or after it.

Time
: Seconds per file. A NetCDF of the whole record of a monthly run takes a few seconds.

Needs
: A project that has run at least once. For the TOML blocks, a file that inherits one of example 04 with `base_config`. The blocks below are checked on top of `step4_transient.toml`.

Gives
: Files in `share/<run name>/` that a colleague can open without HydroModPy, and a check that the request is valid before the solver starts.
```

An export is a request with three words: what, when and where. The same words work in the
file, on the command line and in Python. To read a run into pandas or xarray instead, see
{doc}`read-the-results`. To hand a run to a colleague who uses a GIS, see
{doc}`hand-off-to-gis`.

## 1. Ask for files at the end of the run

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

Step 1 of example 04 writes three blocks: the catchment outline, the water table and the
seepage cells at the last period, and the budget. This block adds the water table at one date
and the whole record of the water table to the six blocks of step 4:

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
| Package | `.hmp` | The portable archive of the run (step 5). |

A simulated value is dated at the end of its period. A CSV of the monthly discharge of
January 2001 carries the date 2001-02-01. The convention is written once in
{doc}`/theory/time-alignment`.

To open a NetCDF in QGIS, add the `.nc` as a **mesh** layer, not as a raster or a vector
layer. {doc}`hand-off-to-gis` shows the whole route, with a GeoPackage and a styled project.

## 2. Change the exports in a derived file

A file that inherits another one inherits its `[[export]]` list too. Three forms manage it.
{doc}`inheritance` explains them in full.

- A plain `[[export]]` list **replaces** the inherited one, whatever the lengths.
- `[[export__append]]` keeps the inherited blocks and adds its own, as steps 2 to 4 of
  example 04 do.
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

To change one key of one inherited block, `[[export__merge]]` pairs the blocks of the child
with the inherited ones in order and refuses another length. Use it when you want to keep
the other keys of each block.

## 3. Check it before you solve

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
grouped by kind: fields, series, vector layers, raster layers and tables. Two runs rarely
hold the same names, because `[simulation.results]` decides what each one stores.

## 4. Export a finished run

The same words work after the run. Both forms take the keys of a block and return the files
they wrote.

::::{tab-set}
:::{tab-item} Command line
```bash
hmp export nancon_step4_transient --list
hmp export nancon_step4_transient all
hmp export nancon_step4_transient head watertable_depth --time 2002-10-15
hmp export nancon_step4_transient discharge discharge_obs --period 2001-01-01 2002-12-31
hmp export nancon_step4_transient watershed hydrographic_network_reference
hmp export nancon_step4_transient watertable_depth --time last --file depth_wgs84.tif --crs EPSG:4326
hmp export nancon_step4_transient all --format package
```

`hmp export` prints the path of each file it writes, one per line, and the count on the error
stream. `-w` names the project when it is not the current directory. The options are
`--time`, `--period`, `--format`, `--folder`, `--file`, `--crs`, `--resolution` and
`--layer`. `all` exports everything the run holds, each data in its natural format. With
`--format`, it exports every data that format can hold.
:::
:::{tab-item} Python
```python
import hydromodpy as hmp

run = hmp.open(".")["nancon_step4_transient"]

run.export("all")
run.export(["head", "watertable_depth"], time="2002-10-15")
run.export(["discharge", "discharge_obs"], period=("2001-01-01", "2002-12-31"))
run.export("watertable_depth", time="last", file="depth_wgs84.tif", crs="EPSG:4326")
hmp.export(run, "all", format="package")
```

`run.export` and `hmp.export` return the list of the paths they wrote.
:::
::::

The control figure for the vector layers is the reference network. The exported
`hydrographic_network_reference.gpkg` holds the same 227 segments and 45.63 km:

```{figure} /_static/figures/guides/hydrographic_network_reference.webp
:alt: The reference hydrographic network of the Nançon catchment, 227 segments over 45.63 km.
:width: 80%

`hydrographic_network_reference` of example 04. `geopandas.read_file` on the exported
GeoPackage gives 227 rows whose lengths sum to 45.63 km, in EPSG:2154.
```

(export-package)=
## 5. Package a run for exchange

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
`folder` or `file`. {doc}`share-a-run` shows how to send the package and load it in another
project, and how to publish the metadata.

## How to check it worked

- `hmp config check my_exports.toml` prints `OK:` and the path.
- `hmp export <run> --list` names every variable you asked for.
- The files are in `share/<run>/`, one per request, named by the date or the period.
- A GeoTIFF reports the CRS of the model unless you gave `crs`: `rasterio.open(path).crs`
  gives `EPSG:2154` for example 04.
- Example 04 ships `py3_read_exports.py`. It draws a figure from the exported files of
  step 5 alone, with pandas, geopandas, rasterio and xarray, and no HydroModPy import. It is
  what a colleague can do with a copy of `share/<run>/`.

## What can go wrong

| What you see | Cause | Fix |
|---|---|---|
| `no run can export export[6]: 'waterdepth'. The names a run can export:` followed by the names by kind | A name of `variables` is not something a run can write. | Fix the spelling, or read the list. |
| `run '<name>' holds no '<variable>'.` then `It can export:` (exit 1, from `hmp export`) | The run did not store it. Typically a per-cell budget term and `spatial_fields` was off, or the run has no stored network. | Pick a name from the list, or run again with the switch on ({doc}`read-the-results`). |
| `a time names no stress period of this run ([simulation.time] resolves to 36 periods):` then `export[6].time: 2015-10-15 is outside the record: the record runs from 2000-01-01 to 2003-01-01.` | A date outside the record. | Use a date inside the record. |
| `export[2] and export[6] both write nancon_step4_transient/budget.csv. Give one of them its own file or folder.` | Two blocks plan the same file. | Give one its own `file` or `folder`, or merge them. |
| `file = 'x.tif' names one file, but in geotiff 2 names write one file each. Write folder instead of file, or format = "netcdf", which holds several variables and dates in one file.` | A `file` on a request that writes several files. | Do what the message says. |
| `crs = 'EPSG:4326' on format 'netcdf', which does not reproject: it is written in the model CRS. Drop crs, or write a GeoTIFF, a GeoPackage or a Shapefile.` | A `crs` on a format that does not reproject. | Drop `crs`, or change the format. |
| `time and period are both given. Write time for instants, or period for a window, not both.` | Both keys in one block. | Keep one. |
| `format = 'package' describes the whole run, not a variable. Write variables = "all".` | A run format with a variable. | Write `variables = "all"`. |
| The message says the field holds N layers and a GeoTIFF holds one: `Write layer = 0 for the top layer (or another), or export a field of one value per cell: watertable_elevation, watertable_depth, seepage_mask. NetCDF and VTU keep every layer.` | A field of several layers in a format of one layer. | Write `layer = 0`, or choose a field of one value per cell, or NetCDF. |
| The CSV of January has the date of February | A simulated value is dated at the end of its period. | Read {doc}`/theory/time-alignment`. |
| QGIS keeps showing the old file | A QGIS layer holds the file open. | Reload the layer. |
| A file with the old `[export]` table of format switches | It still loads and is rewritten in memory as `[[export]]` blocks. | `hmp doctor --fix-config <file>` rewrites it on disk. |

## Where to go next

- {doc}`inheritance` for `__append`, `__delete` and `__merge` on any list.
- {doc}`share-a-run` to send a package or publish the metadata of a run.
- {doc}`hand-off-to-gis` to open the files in QGIS.
- {doc}`read-the-results` to read a run from Python.
- {doc}`/reference/cli/export` for every option of `hmp export`.
