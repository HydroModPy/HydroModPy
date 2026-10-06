# Use your own files

You have a DEM, a geology map, a river network, a gauge record or a recharge grid of your
own, and you want the model to read them instead of a download. A source written with
{toml}`source = "custom"|data.dem.sources.source` does that: the file you name replaces the
provider. This guide takes each kind of file in turn, says what the loader accepts, and shows
how to check what was read before a long run.

## What you need first

- A project file that runs. The blocks below are merged onto a file of example 04
  (`step1_minimal.toml`, `step2_local_data.toml` or `step4_transient.toml`) and validated
  there. Replace the names of the files by yours.
- Your files, and for each one its coordinate system (CRS). For a series, its unit.
- The place where they live. Any folder works. A workspace folder gives you short paths,
  as `step1_minimal.toml` shows.

## 1. Write the path

Every data section holds a list of sources. A source with `source = "custom"` carries a
`path`. Three rules decide where HydroModPy looks for it.

- An absolute path, or one that starts with `~`, is used as written.
- A path with a folder part, such as `dem/mine.tif` or `../data/mine.tif`, is read from the
  folder of the file you pass to `hmp`. With a chain of files linked by `base_config`, that
  is the last file of the chain, not the file that wrote the line.
- A bare name, such as `mine.tif`, is looked for next to that file first. If it is not
  there, HydroModPy looks in `<workspace>/data/<section>/`, then in `<workspace>/data/`.
  `<section>` is the name of the data section: `dem`, `geology`, `hydrography`,
  `hydrometry`, `recharge`, and so on.

The workspace is found by the rules of {ref}`Where the files go <workspace-folder>`.
Example 04 sits in `examples/projects/`, so its workspace is `examples/`, and a bare name
is found in `examples/data/`. That is why `step1_minimal.toml` writes a bare name:

```{hmp-resolved} geographic.catchment.dem_init_path
:config: step1_minimal.toml
```

```{hmp-params}
workspace.root
workspace.data_dir
data.types
```

A section is read only if its name is in {toml}`data.types`, or if the model asks for it:
a stream boundary condition brings `hydrography`, a zoned parameter brings `geology`. Name
every section you declare, as the files of example 04 do.

## 2. Give your DEM

The DEM is the one file the catchment is cut from, so it is read first, before any data
section. You name it in one of two places. Pick one.

The first is {toml}`geographic.catchment.dem_init_path`. Example 04 uses it. The DEM is a
regional one, large enough to hold the catchment upslope of the outlet. Write the outlet
{toml}`x_outlet|geographic.catchment.x_outlet` and
{toml}`y_outlet|geographic.catchment.y_outlet` in the CRS of the project.

```toml
base_config = "step1_minimal.toml"

[geographic.catchment]
dem_init_path = "dem/regional_dem.tif"
```

The second is a data source. Leave {toml}`dem_init_path|geographic.catchment.dem_init_path`
out, and HydroModPy takes the DEM from the first custom source of the section. The card of
`dem_init_path` says the same.

```toml
base_config = "step1_minimal.toml"

[geographic.catchment]
dem_init_path__delete = true

[[data.dem.sources]]
source = "custom"
path = "dem/regional_dem.tif"
```

If neither is written, the check refuses the file:

```text
catch_def='from_outlet_coord' requires 'dem_init_path' (path to the DEM raster or XYZ text file).
```

A GeoTIFF is the safe format for either place. The DEM source also reads `.tiff`, `.asc` and `.nc`. If
`path` is a folder, the first file found is used, trying the extensions in that order. The
format templates created by `hmp workspace init`, whose name holds `EXAMPLE`, are skipped. A
NetCDF file needs a variable called `elevation`, `dem`, `z`, `altitude`, `height` or `Band1`, or
only one variable.

```{hmp-params}
geographic.catchment.dem_init_path
data.dem.sources.path
geographic.crs_project
```

## 3. Give your geology map

A geology source is a polygon file whose attribute table holds a zone code. Add the section
to {toml}`data.types` and name the column.

```toml
base_config = "step1_minimal.toml"

[data]
types = ["geology"]

[[data.geology.sources]]
source = "custom"
path = "geology/my_zones.gpkg"
code_field = "zone"
```

{toml}`code_field|data.geology.sources.code_field` is required for a vector file. Its values
become the zone codes. The loader accepts three kinds of file.

- A vector file: `.shp`, `.gpkg`, `.geojson` or `.json`.
- A GeoTIFF with one numeric class per cell: `.tif` or `.tiff`.
- A CSV of points, with the columns named by
  {toml}`col_x|data.geology.sources.col_x`,
  {toml}`col_y|data.geology.sources.col_y` and
  {toml}`col_code|data.geology.sources.col_code`. Each point owns the area closest to it.

Two properties of the map matter for the model.

- It must cover the model domain, not only the catchment. The domain is wider than the
  catchment by the margin {toml}`buff_area|geographic.catchment.buff_area`. A cell that no
  zone covers gets no value.
- A vector file must be in the CRS of the project. See the CRS rules below.

The map gives zone codes, not values. The values of K and Sy per zone are written in the
flow section, or read from a CSV with
{toml}`values_source|flow.param.K.field.values_source` and
{toml}`values_csv_file|flow.param.K.field.values_csv_file`. {doc}`k-per-zone` shows the
whole chain.

```{hmp-params}
data.geology.sources.path
data.geology.sources.code_field
```

## 4. Give your river network

A network is a vector file of lines. Example 04 compares it with the simulated seepage.

```toml
base_config = "step2_local_data.toml"

[data.hydrography]
sources__delete = true

[[data.hydrography.sources]]
source = "custom"
path = "network/my_rivers.gpkg"
```

`sources__delete = true` removes the source that step 2 declares. Without it, the two lists
of tables are merged element by element and a key you did not write can come back from
step 2. {doc}`inheritance` explains the trap.

For a single file, a `.tif` or `.tiff` is read as a raster, and any other file goes to
geopandas as a vector, so a Shapefile, a GeoPackage and a GeoJSON all work. If `path` is a
folder, a raster found there wins over a vector, then the extensions
`*.shp`, `*.gpkg`, `*.geojson` are tried in that order.

Three details.

- The CRS conversion and the clip are done for you. A vector is converted to the CRS of the
  delineated watershed, then clipped to it. A raster is clipped by the watershed, converted to
  the CRS of the raster.
- {toml}`rasterize_field|data.hydrography.sources.rasterize_field` names the column burnt
  into the raster of the network. If the file has no such column, a sequential number is
  used and the run goes on.
- A column called `permanence`, with the value `permanent` on the reaches that flow all
  year, makes HydroModPy write a second layer with only those reaches. The file of
  example 04 has no such column, so it gives no second layer.

```{hmp-params}
data.hydrography.sources.path
data.hydrography.sources.rasterize_field
data.hydrography.mask_path
```

## 5. Give your time series

A series is a folder, not a file. It holds one file of locations and one file per station.
The names matter, because the loader finds the files by them. The folder below is the one
that example 04 reads for its recharge, `examples/data/recharge/`.

```text
recharge/
|-- recharge_custom_LOC.csv
`-- recharge_custom_NANCON_20000101_20021231_M.csv
```

- The location file is `<section>_custom_LOC.csv`. A `.shp`, `.gpkg` or `.geojson` file with
  the same stem also works. The section `water_quality` is written `waterquality` in file
  names.
- A chronicle is `<section>_custom_<id>_<start>_<end>_<freq>.csv`. The loader takes the first
  file that matches `<section>_custom_<id>_*.csv`. The frequency letter comes from the name,
  and it is `D` when the name has none.

The location file has one row per station:

```text
id,x,y,crs,unit
NANCON,389285.91,6816518.749,EPSG:2154,mm/day
```

A chronicle has a date column and a value column:

```text
datetime,value
2000-01-31,2.088043
```

Dates are ISO dates, or Unix times in seconds or milliseconds. A value that is not a number
becomes a gap. A chronicle with a single row is a constant. When the run has a period, it is
repeated on every day of it.

Select the station and name your own columns in the TOML. You do not need to rename columns in
the files.

```toml
base_config = "step4_transient.toml"

[data.hydrometry]
sources__delete = true

[[data.hydrometry.sources]]
source = "custom"
path = "gauge"
station_ids = ["MYGAUGE"]
col_datetime = "date"
col_value = "Q"
```

The unit is read from the `unit` column of the location file and converted to the unit the
variable has inside HydroModPy. For discharge and piezometry, a station with no unit stops the
load. For recharge, runoff and the other climate variables, a station with no unit is taken as
already in the internal unit, and nothing is converted.
{toml}`source_unit|data.hydrometry.sources.source_unit` does not apply to a folder of CSV
files, only to a NetCDF or a GeoTIFF.

The stations are also filtered by position, and nothing says so. A station on the boundary of
the delineated watershed stays. A station outside it is kept for discharge and piezometry when
you name it in {toml}`station_ids|data.hydrometry.sources.station_ids`, and dropped in every
other case. For recharge, runoff and the other climate variables, it is dropped even when
named. A station whose chronicle file is missing is skipped, with a warning
`No chronicle for station <id>`.

```{hmp-params}
data.hydrometry.sources.path
data.hydrometry.sources.station_ids
data.hydrometry.sources.col_id
data.hydrometry.sources.col_x
data.hydrometry.sources.col_y
data.hydrometry.sources.col_crs
data.hydrometry.sources.default_crs
data.hydrometry.sources.col_datetime
data.hydrometry.sources.col_value
data.hydrometry.date_start
data.hydrometry.date_end
```

## 6. Give your grid

A grid, for variables such as recharge, runoff, precipitation or ETP, is a NetCDF or a
GeoTIFF. The same `path` key takes a file here and a folder above.

```toml
base_config = "step4_transient.toml"

[data.recharge]
sources__delete = true

[[data.recharge.sources]]
source = "custom"
path = "recharge/recharge_daily.nc"
source_unit = "mm/day"
```

The extension must be written in lower case: `.nc`, `.tif` or `.tiff`. Any other extension
is refused. The file must satisfy these points, and each one is checked when the file is read.

- **NetCDF, the variable.** It must hold a data variable with the name of the section:
  `recharge` for recharge, `runoff` for runoff, and so on. Other names are refused with the
  list of those present.
- **NetCDF, the CRS.** It is read from the CRS of the file, or from an attribute named `crs`,
  `crs_wkt` or `spatial_ref`, or from the grid mapping. The coordinates are `x` and `y`, or
  `lon` and `lat`, or `LAMBX` and `LAMBY`.
- **NetCDF, the nodata value.** It must be an attribute of the variable called `nodata`. A
  `_FillValue` is not enough: it is no longer an attribute once xarray has opened the file.
- **NetCDF, the time axis.** It must be regular. It is cut to the period of the run.
- **GeoTIFF.** It declares a CRS and a nodata value.
- **The unit.** Write {toml}`source_unit|data.recharge.sources.source_unit`, or a `units`
  attribute on the variable. If neither is there, the file is taken as already in the unit
  the variable has inside HydroModPy, and nothing is converted.

Only ETP has a way to give the CRS or the nodata value from the TOML, for a file that lacks
them: {toml}`crs|data.etp.sources.crs` and {toml}`nodata|data.etp.sources.nodata`. For the other
variables, write them into the file.

```{hmp-params}
data.recharge.sources.path
data.recharge.sources.source_unit
data.etp.sources.crs
data.etp.sources.nodata
```

How the recharge enters the model, once it is loaded, is in {doc}`recharge`.

## The CRS rules

Each loader does something different when a file declares no CRS. Write the CRS into your
files and the last column does not apply.

| File | Where the CRS comes from | If the file has none |
|---|---|---|
| DEM | The file. | The DEM loader labels it `EPSG:2154`. The delineated watershed can then carry no CRS, and the data loaders refuse a mask without one. |
| Geology, vector or GeoTIFF | The file. The vector must be in the CRS of the project. | Taken as `EPSG:2154`. |
| Geology, CSV points | {toml}`default_crs\|data.geology.sources.default_crs` | Not applicable: a CSV has no CRS, and this key gives it. |
| River network, vector | The file. It is converted to the CRS of the watershed. | Taken as `EPSG:4326`. |
| Stations | The `crs` column of the location file, one value per station. A vector location file gives its own. | {toml}`default_crs\|data.hydrometry.sources.default_crs` for a CSV file. |
| NetCDF grid | The file, or an attribute `crs`, `crs_wkt` or `spatial_ref`. | The file is refused. Only ETP can take the CRS from the TOML. |
| GeoTIFF grid | The file. | The file is refused. |

The geology rule is the one that bites. The vector is cut with a box that is written in the
CRS of the project. A vector in another CRS is cut with the wrong box, and the run stops
with `No geology feature intersects bbox after clipping`. Convert the file to the CRS of the
project before you use it.

## What is checked, and when

| When | What |
|---|---|
| `hmp config check` | The shape of the TOML: keys, types, the keys a source requires. It does not open a file and does not test that a path exists. |
| Start of `hmp run` | Files named `<section>_custom_*` in `<workspace>/data/<section>/` are indexed. A file that cannot be read gives the warning `auto_scan could not read <file>: <reason>`, and the run goes on. |
| Step `build_geographic` | The DEM, and for a diagnostic of the network, the first custom vector of the hydrography section. |
| Step `load_data` | Every section of {toml}`data.types`: first the DEM, the geology and the hydrography, then the series and the grids. |

A failure at `load_data` does not always stop the run. A failure on the DEM, the geology or
the hydrography does, with a message that starts with `step 'load_data' failed:`. A failure on
a series or a grid is only logged, and the run goes on without that data:

```text
[ERROR] Load of 'hydrometry' failed: Failed to load data manager 'hydrometry': <reason>
```

Read the log of `load_data` after every change of file. A run that was meant to read your
gauge may carry on without it.

## Check that it worked

1. Validate the shape of the file.

   ```text
   hmp config check my_project.toml
   ```

2. Read the files without solving anything. The run stops after the step that loads the data.

   ```text
   hmp run my_project.toml --until load_data
   ```

   Then open `<project>/.hmp/checkpoints/<name>/loaded_data.json`, where `<name>` is the
   {toml}`simulation.name` of the run. It holds one entry per series and per field that was
   loaded, with `variable`, `station_id`, `source_path`, `source_sha256`, `period_start` and
   `period_end`. A station or a grid that is not in the list was not read. For the river
   network, `source_path` names the raster HydroModPy made from your file.

3. If your series sit in `<workspace>/data/<section>/` under the names of section 5, check them
   without loading them. The command reads the workspace you pass, not the one of the project.
   It opens the CSV series and the lake tables. For a raster or a vector, it checks only that
   the file is there.

   ```text
   hmp data check --workspace <workspace> --variable hydrometry
   ```

   It requires the columns `id`, `x`, `y`, `crs` and `unit` in the location file, and
   `datetime` and `value` in a chronicle, whatever you wrote in `col_datetime` or `col_value`.

4. Run the model and open the figures. `watershed_id_card` draws the delineated catchment,
   `hydrographic_network_reference` your network, and `hydrograph_sim_obs` your gauge against
   the simulation. Name them in {toml}`display.figures`, as the files of example 04 do. If the
   basin looks shifted, cropped or empty, the CRS of a file is wrong. Fix the file, not the
   solver settings.

## What can go wrong

The messages below are the ones of the code. A message that comes from `load_data` is written
in full as `step 'load_data' failed: ValueError: Failed to load data manager '<section>': <message>`.
For a series or a grid, the run does not stop, and the same text reaches the log as
`[ERROR] Load of '<section>' failed: Failed to load data manager '<section>': <message>`. The table
gives `<message>`.

| The message | Cause and fix |
|---|---|
| `Custom source requires 'path'` | A source says `custom` and has no `path`. `hmp config check` reports it, before any run. A series adds a hint after the message. |
| `[data.dem] custom source path not found: <path>` | The same fault, found early, when `dem_init_path` is left out and the DEM comes from the data source. |
| `Custom DEM path not found: <path>` | The path does not exist. Check the path rules above. |
| `Unsupported custom DEM format: '<ext>'. Supported: .tif, .tiff, .asc, .nc` | Convert the DEM. |
| `No DEM file (TIF, ASC, NC) found in <folder>. EXAMPLE templates are ignored: add your own file or point 'path' at it.` | The folder holds no DEM, or only the templates of `hmp workspace init`. |
| `Custom geology path not found: <path>` | The path does not exist. |
| `'code_field' is required for custom vector geology source (<file>). Set it in [[data.geology.sources]] to the column containing geology codes.` | Add {toml}`code_field\|data.geology.sources.code_field`. |
| `Column '<name>' not found in <file>. Available: [...]` | `code_field`, or a CSV column name, is misspelled. The list shows the columns. |
| `No geology feature intersects bbox after clipping` | The map does not cover the domain, or it is in another CRS than the project. |
| `No vector or raster file (*.shp, *.gpkg, *.geojson, *.tif, *.tiff) found in <folder>. EXAMPLE templates are ignored: add your own file or point 'path' at it.` | The network folder holds no usable file. |
| `<path>: No such file or directory` | The `path` of a network file does not exist. A warning `[data.hydrography] custom source path not found` comes first, at `build_geographic`, and says the diagnostic of the network is skipped. |
| `Mask <file> declares no CRS, so the shape it describes means nothing on its own. Write the file with a CRS, or name the extent explicitly.` | A mask file, such as the watershed made from a DEM with no CRS, has none. |
| `Custom data directory not found: <folder>` | The `path` of a series is not a folder. |
| `No <section>_custom_LOC.* in <folder>` | The location file is missing or badly named. |
| `<section>: station_ids declares ['X'], absent from <section>_custom_LOC.csv. Known ids: ...` | The station is not in the location file. The list shows the known ones. |
| `No unit for station 'X'. Add a 'unit' column in the LOC file.` | Add the column. |
| `Unknown unit: '<unit>'` | The unit string is not one HydroModPy converts. Use a common spelling such as `m3/s` or `L/s`. |
| `Chronicle CSV <file> missing datetime column. Expected 'datetime'. Columns: [...]` | Set {toml}`col_datetime\|data.hydrometry.sources.col_datetime`, or rename the column. The same message exists for `value`. |
| `Unsupported custom format: <ext>. Use a directory (CSV), .nc, or .tif.` | A grid file has another extension, or its extension is in capitals. |
| `Custom grid dataset does not contain variable '<name>'; available variables: [...]` | Rename the variable in the NetCDF file. |
| `Custom grid dataset <file> must declare nodata metadata.` | Add a `nodata` attribute to the variable. |
| `Custom grid dataset must declare CRS metadata.` | Write a `crs` attribute, or a CRS in the file. |
| `Custom grid dataset <file> must declare a regular time axis.` | The time steps are not evenly spaced. |
| `Custom GeoTIFF <file> must declare a CRS.` | Write the CRS into the file. The same message exists for the nodata value. |

## Next

- Which value goes to which zone: {doc}`k-per-zone`.
- How a recharge series or a grid reaches the model: {doc}`recharge`.
- The same files, without a network: {doc}`work-offline`.
- Fetch the data of a catchment instead: {doc}`get-the-data`.
- How `base_config` and `__delete` merge files: {doc}`inheritance`.
