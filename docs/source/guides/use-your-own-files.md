# Use your own files

You have a DEM, a geology map, a stream network, a gauge record or a recharge grid of your
own, and you want the model to read them instead of a download. A source written with
{toml}`source = "custom"|data.dem.sources.source` does that: the file you name replaces the
provider. This guide takes each kind of file in turn, says what the loader accepts, and shows
how to check what was read before a long run.

```{hmp-task}
Task
: Make the model read a DEM, a geology map, a river network, station series or a grid from your disk.

Time
: Seconds to a minute to check a file with `hmp run --until load_data`. Preparing your files is the long part.

Needs
: Your files, the coordinate system (CRS) of each one, and for a series its unit. A project file that runs (example 04).

Gives
: A catchment and its inputs read from your files, and a `loaded_data.json` that lists what was read.
```

## What you need first

- A project file that runs. The blocks below are merged onto a file of example 04
  (`step1_minimal.toml`, `step2_local_data.toml` or `step4_transient.toml`) and validated
  there. Replace the names of the files by yours.
- Your files, and for each one its coordinate system (CRS). A file with no CRS is refused:
  HydroModPy does not guess one. For a series, its unit.
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

Whichever place you use, a raster with no CRS is refused before the catchment is cut, with the
command that writes the CRS into the file (see the table of the loaders below).

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
- A vector file must be in the CRS of the project. The loader cuts it with a box written in
  that CRS and does not convert the file.

The map gives zone codes, not values. The values of K and Sy per zone are written in the
flow section, or read from a CSV with
{toml}`values_source|flow.param.K.field.values_source` and
{toml}`values_csv_file|flow.param.K.field.values_csv_file`. {doc}`k-per-zone` shows the
whole chain.

```{hmp-params}
data.geology.sources.path
data.geology.sources.code_field
```

## 4. Give your stream network

A network is a vector file of lines. Example 04 compares it with the simulated seepage.

```toml
base_config = "step2_local_data.toml"

[[data.hydrography.sources]]
source = "custom"
path = "network/my_rivers.gpkg"
```

A list of tables in a child file replaces the inherited one, so the network of step 2 is gone
and no key of it comes back. {doc}`inheritance` gives the rule.

For a single file, a `.tif` or `.tiff` is read as a raster, and any other file goes to
geopandas as a vector, so a Shapefile, a GeoPackage and a GeoJSON all work. If `path` is a
folder, a raster found there wins over a vector, then the extensions
`*.shp`, `*.gpkg`, `*.geojson` are tried in that order.

Three details.

- The CRS conversion and the clip are done for you. A vector is converted to the CRS of the
  delineated catchment, then clipped to it. A raster is clipped by the catchment, converted to
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
already in the internal unit and nothing is converted. A warning says so for each station:
`Station <id> has no unit in its LOC file; its values are taken as <unit> and not converted.`
{toml}`source_unit|data.hydrometry.sources.source_unit` does not apply to a folder of CSV
files, only to a NetCDF or a GeoTIFF.

The stations are also filtered by position. A station on the boundary of the delineated
catchment stays. A station outside it is kept for discharge and piezometry when you name it in
{toml}`station_ids|data.hydrometry.sources.station_ids`, and dropped in every other case. For
recharge, runoff and the other climate variables, it is dropped even when named. A dropped
station is named in a warning, so a gauge that vanished from the run is easy to find:

```text
[WARNING] hydrometry: 1 station(s) of source 'custom' outside the mask watershed.shp dropped: ['FAR'].
```

If every station of the source is outside, nothing is left to load and the run stops. A
station whose chronicle file is missing is skipped, with a warning
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
  `crs_wkt`, `spatial_ref` or `proj4`, or from the grid mapping. The coordinates are `x` and
  `y`, or `lon` and `lat`, or `LAMBX` and `LAMBY`.
- **NetCDF, the nodata value.** It is the `nodata` attribute of the variable, or its finite
  `_FillValue` or `missing_value`. A NaN fill value does not count: writers add one by default,
  and it declares nothing.
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

## What each loader accepts

One table for the five kinds of file. A file that declares no CRS is refused, with the file
named and the command that writes the CRS into it: `gdal_edit.py -a_srs EPSG:<code> <file>`
for a raster, `ogr2ogr -a_srs EPSG:<code> <new file> <file>` for a vector, or a `.prj` file
beside a Shapefile.

| Kind | Extensions | CRS | Also required |
|---|---|---|---|
| DEM | `.tif`, `.tiff`, `.asc`, `.nc` | The file. Refused if none, whether the DEM is named by `dem_init_path` or by `[[data.dem.sources]]`. | A NetCDF names its variable `elevation`, `dem`, `z`, `altitude`, `height` or `Band1`, or holds only one. |
| Geology, vector | `.shp`, `.gpkg`, `.geojson`, `.json` | The file, in any CRS: the domain box is reprojected into it. Refused if none. | {toml}`code_field\|data.geology.sources.code_field`, a column of the file. |
| Geology, raster | `.tif`, `.tiff` | The file. Refused if none. | One numeric class per cell. |
| Geology, points | `.csv` | {toml}`default_crs\|data.geology.sources.default_crs`: a CSV has no CRS, and this key gives it. | The columns named by `col_x`, `col_y` and `col_code`. |
| Stream network, vector | `.shp`, `.gpkg`, `.geojson`, any vector | The file. Converted to the CRS of the catchment. Refused if none. | Optional `rasterize_field` and `permanence` columns. |
| Stream network, raster | `.tif`, `.tiff` | The file. Refused if none. | Burnt as is. |
| Stations | A folder: `<section>_custom_LOC.csv` (or `.shp`, `.gpkg`, `.geojson`) and one `<section>_custom_<id>_<start>_<end>_<freq>.csv` per station | The `crs` column of the location file, one value per station, or the geometry of a vector file. {toml}`default_crs\|data.hydrometry.sources.default_crs` for a CSV with no such column. | A `unit` column for discharge and piezometry. The columns `datetime` and `value`, or the names in `col_datetime` and `col_value`. |
| NetCDF grid | `.nc` | The file, or an attribute `crs`, `crs_wkt`, `spatial_ref` or `proj4`. Only ETP can take it from the TOML. Refused if none. | A variable named after the section, a regular time axis, a nodata value (attribute or finite fill value). |
| GeoTIFF grid | `.tif`, `.tiff` | The file. Refused if none. | A nodata value. |

## What is checked, and when

| When | What |
|---|---|
| `hmp config check` | The shape of the TOML: keys, types, the keys a source requires. It does not open a file and does not test that a path exists. |
| Start of `hmp run` | Files named `<section>_custom_*` in `<workspace>/data/<section>/` are indexed. A file that cannot be read gives the warning `auto_scan could not read <file>: <reason>`, and the run goes on. |
| Step `build_geographic` | The DEM of `dem_init_path` or of the first custom DEM source: a raster with no CRS is refused here, before the catchment is cut. For a diagnostic of the network, the first custom vector of the hydrography section. |
| Step `load_data` | Every section of {toml}`data.types`: first the DEM, the geology and the hydrography, then the series and the grids. |

A listed section that fails at `load_data` stops the run, whatever its kind. The message
starts with `step 'load_data' failed: <ErrorClass>: Failed to load data manager '<section>':`,
and the exit code names the cause: 10 for a file that is not there, 16 for a file the loader
refuses ({doc}`../reference/cli/exit-codes`). The table at the end of this page gives the end
of each message.

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

4. Run the model and open the figures. Name them in {toml}`display.figures`, as the files of
   example 04 do. If the basin looks shifted, cropped or empty, the CRS of a file is wrong.
   Fix the file, not the solver settings. Three figures answer for three kinds of file.

   `watershed_id_card` draws the delineated catchment and what the run holds of it:

   ```{figure} /_static/figures/guides/watershed_id_card.webp
   :alt: Identity card of the Nançon catchment: the outline on the DEM, the outlet and a table of the run.
   :width: 90%

   `watershed_id_card`: the outline must enclose the basin you mean, and the outlet must sit on the stream.
   ```

   `hydrographic_network_reference` draws your network inside the outline:

   ```{figure} /_static/figures/guides/hydrographic_network_reference.webp
   :alt: Map of the Nançon catchment with its mapped river network drawn over the outline.
   :width: 90%

   `hydrographic_network_reference`: the reaches must fall inside the outline and meet the outlet.
   ```

   `hydrograph_sim_obs` draws your gauge against the simulation:

   ```{figure} /_static/figures/guides/hydrograph_sim_obs.webp
   :alt: Daily discharge of the Nançon, observed and simulated.
   :width: 90%

   `hydrograph_sim_obs`: the observed series is your gauge, in the unit of the model.
   ```

## What can go wrong

The message of a run that stops starts with `step 'load_data' failed: <ErrorClass>: Failed to
load data manager '<section>':`. The first column gives what follows. The folder part of a
path is written `<folder>`.

| Symptom | Cause | Fix |
|---|---|---|
| `Custom source requires 'path'` (`hmp config check`, exit 14) | A source says `custom` and has no `path`. A series adds a hint after the message. | Add the path. |
| `[data.dem] custom source path not found: <path>` | The DEM comes from the data source, and the path does not exist. | Check the path rules of section 1. |
| `Custom DEM path not found: <path>` | The path of a custom DEM does not exist. | Same. |
| `Unsupported custom DEM format: '<ext>'. Supported: .tif, .tiff, .asc, .nc` | The DEM has another extension. | Convert the DEM. |
| `No DEM file (TIF, ASC, NC) found in <folder>. EXAMPLE templates are ignored: add your own file or point 'path' at it.` | The folder holds no DEM, or only the templates of `hmp workspace init`. | Add your file, or point `path` at it. |
| `step 'build_geographic' failed: DataContractViolation: dem: <file> declares no CRS, and HydroModPy does not guess one. Write the CRS into the file: for a raster, 'gdal_edit.py -a_srs EPSG:<code> <file>'; ...` (exit 16) | The DEM has no CRS. A geology map or a network with no CRS gives the same text after `geology:` or `hydrography:`, from `load_data`. | Write the CRS into the file with the command in the message. |
| `Custom geology path not found: <path>` | The path does not exist. | Check the path. |
| `'code_field' is required for custom vector geology source (<file>). Set it in [[data.geology.sources]] to the column containing geology codes.` | A vector geology map with no `code_field`. | Add {toml}`code_field\|data.geology.sources.code_field`. |
| `Column '<name>' not found in <file>. Available: [...]` | `code_field`, or a CSV column name, is misspelled. The list shows the columns. | Copy a name from the list. |
| `No geology feature of <file> intersects the requested box (...) (in <CRS>, the CRS of the file).` | The map does not cover the domain. The box is given in the CRS of the file. | Check the extent of the file against the box. |
| `No vector or raster file (*.shp, *.gpkg, *.geojson, *.tif, *.tiff) found in <folder>. EXAMPLE templates are ignored: add your own file or point 'path' at it.` | The network folder holds no usable file. | Add your file. |
| `<path>: No such file or directory` (exit 16) | The `path` of a network file does not exist. A warning `[data.hydrography] custom source path not found` comes first, at `build_geographic`, and says the diagnostic of the network is skipped. | Check the path. |
| `Mask <file> declares no CRS, so the shape it describes means nothing on its own. Write the file with a CRS, or name the extent explicitly.` | A mask file, such as a catchment made from a DEM with no CRS, has none. | Write the CRS into the mask. |
| `Custom data directory not found: <folder>` (exit 10) | The `path` of a series is not a folder. | Check the path. |
| `No <section>_custom_LOC.* in <folder>` (exit 10) | The location file is missing or badly named. | Name it `<section>_custom_LOC.csv`. |
| `<section>: station_ids declares ['X'], absent from <section>_custom_LOC.csv. Known ids: ...` | The station is not in the location file. The list shows the known ones. | Copy an id from the list. |
| `No unit for station 'X'. Add a 'unit' column in the LOC file.` | A discharge or piezometry station has no unit. | Add the column. |
| `Unknown unit: '<unit>'` | The unit string is not one HydroModPy converts. | Use a common spelling such as `m3/s`, `L/s` or `mm/day`. |
| `Chronicle CSV <file> missing datetime column. Expected 'datetime'. Columns: [...]` | The chronicle has other column names. The same message exists for `value`. | Set {toml}`col_datetime\|data.hydrometry.sources.col_datetime`, or rename the column. |
| `<section>: N station(s) of source '<source>' outside the mask <file> dropped: [...]` (warning) | A station lies outside the catchment and is dropped. | Check the coordinates and the CRS of the station. For discharge or piezometry, name the station in `station_ids` to keep it. |
| `<section>: every station of source '<source>' lies outside the mask <file>: [...]. No station is left to load.` (exit 16) | Every station of the source is outside the catchment. | Same, or the outlet is not where you think. |
| `Station <id> has no unit in its LOC file; its values are taken as <unit> and not converted.` (warning) | A climate station has no unit. | Add the `unit` column. |
| `No chronicle for station <id>` (warning) | The location file lists a station and no chronicle file matches. | Name the file `<section>_custom_<id>_<start>_<end>_<freq>.csv`. |
| `Unsupported custom format: <ext>. Use a directory (CSV), .nc, or .tif.` | A grid file has another extension, or its extension is in capitals. | Rename or convert it. |
| `Custom grid dataset does not contain variable '<name>'; available variables: [...]` | The NetCDF variable has another name. | Rename the variable in the file. |
| `Custom grid dataset <file> must declare a nodata value: an attribute 'nodata', '_FillValue' or 'missing_value' on the variable.` | No `nodata` attribute and no finite fill value. | Add a `nodata` attribute to the variable. |
| `Custom grid dataset must declare CRS metadata.` | The NetCDF has no CRS. | Write a `crs` attribute, or a grid mapping. |
| `Custom grid dataset <file> must declare a regular time axis.` | The time steps are not evenly spaced. | Resample the series. |
| `Custom GeoTIFF <file> must declare a CRS.` | The grid has no CRS. The same message exists for the nodata value. | Write it into the file. |

## Next

- Which value goes to which zone: {doc}`k-per-zone`.
- How a recharge series or a grid reaches the model: {doc}`recharge`.
- The same files, without a network: {doc}`work-offline`.
- Fetch the data of a catchment instead: {doc}`get-the-data`.
- How `base_config` and `__delete` merge files: {doc}`inheritance`.
