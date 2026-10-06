# Get the data of a catchment

A model needs a DEM, a river network, gauge records and forcing. You list them in the
`[data]` tables of the project file. HydroModPy reads each one from a public service or
from your files, cuts it to your catchment, and keeps what it downloaded in a cache, so
the next run makes no request.

The worked case is example 04, the Nançon. Step 2 reads the river network and the gauge
from local files. Step 3 asks BD Topage and Hub'Eau for the same two. This guide takes you
from the first to the second, then adds SIM2 rain and ETP.

## What you need first

- A project file that runs. The blocks below are merged onto a file of example 04 and
  validated: `step2_local_data.toml` for most of them, `step3_api_data.toml` for the rest.
- A catchment under {toml}`geographic.catchment`. Every request is cut to the delineated
  catchment, so the catchment is built before any data is loaded.
- Network access for the first run of a downloading source. BD Topage, Hub'Eau and SIM2
  need no key.

## 1. List the variables

A variable is one kind of input: a DEM, a river network, a discharge record, a rain grid.
Each has its own table, `[data.<variable>]`. You list the ones to load in
{toml}`data.types`. Step 2 loads two of them:

```{hmp-resolved} data.types
:config: step3_api_data.toml
```

The answer is the line of step 2, because step 3 inherits it.

Twenty-seven variables exist. Their tables are generated from the code, one page per
variable, in {doc}`the data reference <../reference/parameters/data/index>`:

| Group | Variables |
|---|---|
| Terrain, subsurface and soil | {toml}`data.dem`, {toml}`data.geology`, {toml}`data.substratum`, {toml}`data.soil_capacity` |
| River network and structures | {toml}`data.hydrography`, {toml}`data.crossings` |
| Observations at stations | {toml}`data.hydrometry`, {toml}`data.piezometry`, {toml}`data.intermittency`, {toml}`data.water_quality`, {toml}`data.oceanic` |
| Forcing | {toml}`data.recharge`, {toml}`data.runoff`, {toml}`data.precipitation`, {toml}`data.etp`, {toml}`data.temperature`, {toml}`data.wind`, {toml}`data.humidity`, {toml}`data.radiation`, {toml}`data.soil_moisture` |
| Lakes and reservoirs | {toml}`data.lake_geometry`, {toml}`data.lake_bathymetry`, {toml}`data.lake_abacus`, {toml}`data.lake_levels`, {toml}`data.lake_inflow`, {toml}`data.lake_outflow`, {toml}`data.lake_withdrawal` |

A listed variable needs its table. A variable you do not list can still be loaded: the
planner adds it when another part of the file needs it. It reads these clues:

| In the file | Variable added |
|---|---|
| A parameter names, in {toml}`field_spatial_id\|flow.param.<id>.field.field_spatial_id`, a support of {toml}`domain.supports` that has `kind = "geology"` | `geology` |
| {toml}`flow.active_bc` holds `"stream"` | `hydrography` |
| {toml}`flow.active_bc` holds `"ocean"` | `oceanic` |
| {toml}`flow.active_bc` holds `"lake"` or `"reservoir"` | `lake_geometry`, `lake_abacus`, `lake_inflow`, `lake_withdrawal` |
| A soil reservoir is declared under {toml}`flow.sinks_sources.recharge.soil` | `precipitation`, `etp` |
| {toml}`data.soil_capacity` is declared | `soil_capacity` |

`substratum` is never added for you: list it. The run logs the added variables when you
raise the verbosity with `-v`. {toml}`data.inference_mode` says what happens when an added
variable has no table.

```{hmp-params}
data.types
data.inference_mode
```

With `warn`, the run goes on and logs a warning. With `strict`, it stops when the plan is
built, before any download, and names the variables:

```text
data.inference_mode='strict' requires explicit data sections for inferred types: hydrography.
```

`geology` is the exception: in `strict` mode it can still take its default table.

## 2. Choose a source for each variable

A variable has one or more sources, written as repeated `[[data.<variable>.sources]]`
tables. {toml}`source|data.hydrography.sources.source` names the provider. `"custom"` reads
your own files and is the subject of {doc}`use-your-own-files`. Any other value downloads.

Step 3 replaces the two local sources of step 2. `sources__delete = true` drops the
inherited list first, so no key of the local source leaks into the new one
({doc}`inheritance` gives the rule). The network comes from BD Topage:

```toml
base_config = "step2_local_data.toml"

[data.hydrography]
sources__delete = true

[[data.hydrography.sources]]
source = "bdtopage"
```

The discharge record comes from Hub'Eau. Here the gauge is named, and the period is written
in step 3 below:

```toml
base_config = "step2_local_data.toml"

[data.hydrometry]
sources__delete = true
date_start = "2000-01-01"
date_end = "2002-12-31"

[[data.hydrometry.sources]]
source = "hubeau"
product = "QmnJ"
station_ids = ["J001401001"]
```

```{hmp-params}
data.hydrography.sources.source
data.hydrometry.sources.source
data.hydrometry.sources.product
data.hydrometry.sources.station_ids
```

The accepted values of `source` differ by variable. Each card lists them. For the DEM and
the geology, open the cards of {toml}`data.dem.sources.source` and
{toml}`data.geology.sources.source`. A DEM source also takes a product and a pixel size:
{toml}`dataset|data.dem.sources.dataset` and
{toml}`resolution_m|data.dem.sources.resolution_m`.

### What the three sources of example 04 download

| Source | Asks for | Writes in the cache |
|---|---|---|
| `bdtopage` | Every reach of the 2026 edition of the BD Topage layer that touches the request box, each with its permanence (permanent, intermittent, and so on), in Lambert-93 | `hydrography_bdtopage_<hash>.gpkg` with every reach, and `hydrography_bdtopage_permanent_<hash>.gpkg` with the permanent reaches only |
| `hubeau` on hydrometry | One chronicle per station, for the period. The product `QmnJ` is the daily mean discharge | `hydrometry_hubeau_<station>_<start>_<end>_D.csv`, and `hydrometry_hubeau_LOC.csv` for the station locations |
| `sim2` on a grid variable | The SIM2 grid over the request box and the period | `<variable>_sim2_<hash>_<start>_<end>.nc`, for example `etp_sim2_<hash>_20000101_20021231.nc`. Precipitation adds its component: `precipitation_total_sim2_<hash>_<start>_<end>.nc` |

`<hash>` is a short hash of the request box. Next to each downloaded file sits a JSON
file with the same name and the suffix `.json`. It records the source, the download time,
the SHA-256 digest, the CRS and the box.

BD Topage loads every reach, not only the permanent ones. The permanent reaches are cut
out as a second file, so the run holds two reference networks: all reaches, and the
permanent ones. The cache also records which layer it asked for. An entry downloaded under
another layer is not reused.

## 3. Give the period

A source that downloads a time series needs the dates to fetch. A table that declares no
window inherits {toml}`simulation.time.start_datetime` and {toml}`simulation.time.end_datetime`.
Step 3 has no `[simulation.time]`, which is why it writes the window under
{toml}`data.hydrometry`:

```{hmp-resolved} data.hydrometry.date_start
:config: step3_api_data.toml
```

When the file has a simulation window, write it once and let every table inherit it. This
block deletes the two dates of step 3 and adds the window:

```toml
base_config = "step3_api_data.toml"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"

[data.hydrometry]
date_start__delete = true
date_end__delete = true
```

Write {toml}`date_start|data.hydrometry.date_start` and
{toml}`date_end|data.hydrometry.date_end` on a table only to fetch a window wider than the
simulation, for instance to fill a cache that several runs share. Write both or neither.

```{hmp-params}
data.hydrometry.date_start
data.hydrometry.date_end
```

A grid variable follows the same rule. This block adds SIM2 rain and ETP to step 3, over
the window above:

```toml
base_config = "step3_api_data.toml"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"

[data]
types = ["hydrography", "hydrometry", "precipitation", "etp"]

[[data.precipitation.sources]]
source = "sim2"

[[data.etp.sources]]
source = "sim2"
```

The list in `types` replaces the inherited one, so the two old variables are written out
again.

{toml}`data.lake_geometry`, {toml}`data.lake_bathymetry`, {toml}`data.lake_abacus`,
{toml}`data.substratum`, {toml}`data.soil_capacity` and {toml}`data.crossings` carry no
window: they are static.

## 4. Leave the extent to the catchment

You write no box. The loader fills the mask of each table from the delineated catchment,
and the sources are asked over that shape. Three details:

- Geology is asked over the buffered box of the domain, a little larger than the catchment.
  A cell of the domain that no polygon covers would get no value.
- The hydrography table clips all its sources once, so its mask sits on the table:
  {toml}`data.hydrography.mask_path`. A project run fills it.
- {toml}`extent|data.hydrometry.sources.extent` is a developer key. A project run clips on
  the catchment either way, so you can leave it out.

To ask for known stations instead of every station inside the catchment, write
{toml}`station_ids|data.hydrometry.sources.station_ids`, as step 3 does. Only named stations
are served from the cache. A search over the catchment goes to the service on every run.

## 5. Run the load alone

`hmp run` has a flag that stops after a step. The data step is called `load_data`:

```bash
hmp run step3_api_data.toml --until load_data
```

It builds the catchment, loads the variables of `data.types`, and stops before any mesh
or solver. On the first run a downloading source prints one line at the default verbosity:

```text
load_data
[WFS] BD Topage sa:TronconHydrographique_FXX_Topage2026: fetched 1188 reaches
Hub'Eau: 1 station records loaded
```

Run it again. The same two lines do not come back: the cache holds the answers, and no
request leaves. A request whose box lies inside a cached box reuses the cached file. The
chronicle of a named station is asked again only for the periods the cache lacks.

To bypass the cache for one source, set {toml}`force_refresh|data.hydrography.sources.force_refresh`
on that source:

```toml
base_config = "step3_api_data.toml"

[data.hydrography]
sources__delete = true

[[data.hydrography.sources]]
source = "bdtopage"
force_refresh = true
```

```{hmp-params}
data.hydrography.sources.force_refresh
```

(workspace-folder)=
## Where the files go

Downloads go to the `data/` folder of the workspace, one sub-folder per variable, with
an index next to them, `data/cache.duckdb`. The workspace is the first of these that
applies:

1. The folder named by {toml}`workspace.root`, or the parent of {toml}`workspace.data_dir`.
2. The folder named by the environment variable `HMP_WORKSPACE`.
3. The folder two levels above the project, when the project sits in
   `<workspace>/projects/<name>/` and `<workspace>/data/` exists. Example 04 is in this
   case: its workspace is `examples/`.
4. The project folder itself.

Results stay in the project (`runs/`, `.hmp/`). Only the input data is shared.

## Check it worked

1. `hmp config check step3_api_data.toml` reads the file against the schema and prints
   `OK: <path>`. It does not contact any service and does not test the links between
   tables, so it passes a variable that is listed without a table.
2. `hmp run step3_api_data.toml --until load_data` runs the real load. Read the lines
   after `load_data`: a line that starts with `[ERROR]` is a variable that did not load.
3. `hmp data ls --workspace <folder>` lists what the cache holds. Pass the folder of the
   rule above, the one that contains `data/cache.duckdb`. Without `--workspace`, the
   command reads `~/hydromodpy`. The columns are the variable, the source, the station and
   the file:

   ```text
      variable   source station_id                                           file_path
   hydrography bdtopage       None data/hydrography/hydrography_bdtopage_5347fa22.gpkg
    hydrometry   hubeau J001401001 data/hydrometry/hydrometry_hubeau_J001401001_20000101_20021231_D.csv
   ```

   `--variable` and `--provider` filter the list.
4. Open the file. A GeoPackage opens in QGIS, a NetCDF file in any xarray session. The
   sidecar `.json` next to it says where it came from.
5. A run stopped with `--until load_data` leaves
   `<project>/.hmp/checkpoints/<simulation name>/loaded_data.json`. It lists each loaded
   record with its variable, station, source, period and, when it came from a file, the
   path and the SHA-256 digest of that file. A Hub'Eau record has the station, the source
   and the period only. For hydrography the file is the rasterised network, not the
   GeoPackage.
6. A full run draws the figures of {toml}`display.figures` and writes the
   {toml}`[[export]]|export` blocks. Step 3 draws `hydrographic_network_reference` and
   `hydrographic_network_permanence`, and exports the two networks as GeoPackages under
   `share/<simulation name>/`.

For a look at every variable of a catchment without a model, use the overview workflow:
{doc}`describe-a-catchment`.

## Fetch one variable without a project

`hmp data get` runs the same loaders from the command line, over a box, a mask or a list
of stations, and writes one file per variable and source. A variable served by several
sources needs `--source`:

```bash
hmp data get hydrography --source bdtopage --bbox 388000,6815000,391000,6818000 --crs EPSG:2154 --out nancon-data
```

```text
[WFS] BD Topage sa:TronconHydrographique_FXX_Topage2026: fetched 110 reaches
  hydrography      bdtopage                 hydrography_bdtopage.gpkg
  Report -> nancon-data/request.json
```

```bash
hmp data get hydrometry --stations J001401001 --start 2000-01-01 --end 2002-12-31 --out nancon-data
```

```text
Hub'Eau: 1 station records loaded
  hydrometry       hubeau                   hydrometry_hubeau.parquet
  Report -> nancon-data/request.json
```

`request.json` lists each file with its box, CRS, period, size and digest, and the
sources that failed. Without `--workspace`, the cache of the command lives in memory and
nothing stays after it. With `--workspace <folder>`, the command reads and fills the data
cache of that workspace. The full list of options is in {doc}`the reference <../reference/cli/data>`.

## What can go wrong

**A table is missing for a listed variable.** `hmp config check` passes. The load does
not stop, so the line is easy to miss:

```text
[ERROR] Load of 'hydrometry' failed: Data manager 'hydrometry' is active but missing [data.hydrometry] section.
```

**A custom file is not found.** For `dem`, `geology` and `hydrography`, a failure stops the
run with exit code 1. A bare file name is looked for next to the TOML file, then
in `data/<variable>/` and `data/` of the workspace:

```text
step 'load_data' failed: ValueError: Failed to load data manager 'hydrography': <path>/nope.gpkg: No such file or directory
```

**A station variable has no period.** The file has neither a window on the table nor a
{toml}`simulation.time`. `hmp config check` passes, and the run goes on after this line:

```text
[ERROR] Load of 'hydrometry' failed: Failed to load data manager 'hydrometry': project_period required to fetch hydrometry stations.
```

Every variable other than `dem`, `geology` and `hydrography` fails this way: the error is
logged, the exit code stays 0, and the run goes on without that variable. Read the console
after `load_data`.

**Half a window.** Only one of `date_start` and `date_end` is written. `hmp config check`
stops:

```text
data.hydrometry: date_end is missing: declare date_start and date_end together, or declare neither and inherit the window from [simulation.time]
```

**A station returns nothing.** The code is wrong, or the gauge has no record in the
window. The run goes on without it:

```text
[WARNING] Hub'Eau: 1 of 1 stations returned no QmnJ observation between 2000-01-01 and 2002-12-31 and were dropped: XXXX. Their declared service period overlaps the window, which is all require_observations can check before downloading.
Hub'Eau: 0 station records loaded
```

The cache remembers that answer. `hmp data ls` shows the station with the file `empty`, and
the next run does not ask again. The marker belongs to the station, not to the window: a
later request over another period skips it too. Set `force_refresh = true` on the source
to ask again.

**The service answers late or not at all.** The client retries and warns, for example
`HTTP GET <url> -> 502, retry 2/4 in 1.18s`. If the retries run out, the variable does not
load, and the cases above say what each kind of variable does then. To run with no network
after one good run, see {doc}`work-offline`.

## Next

- Read your own files instead of a download: {doc}`use-your-own-files`.
- Run again with no network, and refuse any file that changed: {doc}`work-offline`.
- Draw the identity card of a catchment from these data, with no model: {doc}`describe-a-catchment`.
- Take recharge from SIM2 or compute it from rain and ETP: {doc}`recharge`.
- Every key of every variable, and the sources each one accepts:
  {doc}`the data reference <../reference/parameters/data/index>`.
- A message that is not here: {doc}`troubleshooting`.
