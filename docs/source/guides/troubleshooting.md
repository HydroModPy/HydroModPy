# Troubleshooting by message

```{hmp-task}
Task
: Find the cause of an error message and the change that fixes it.

Time
: A few minutes per message.

Needs
: The whole message, not its last line, the command that printed it, and the file.

Gives
: The key to change, the code to look up, or the guide that explains the failure.
```

You have an error message and you want its cause and its fix. This page lists the
messages you are most likely to meet, in the order a run meets them: reading the file,
fetching data, building the model, solving, exporting. Each section is a table: the text,
the cause and the fix. A run that stops because the solver did not converge has its own
guide: {doc}`A run does not converge <non-convergence>`.

A variable part of a message is written `<like this>`. Search for the fixed words around
it. Most messages name the key to change. `hmp config check <file>.toml` reads the file the
way `hmp run` does, `base_config` included, and runs the checks of step 0. Most messages of
the first and the last sections stop there, before any download and before any solve.

If your message is not here, run again with `hmp run <file>.toml --debug`. The debug
lines also go to `.hmp/logs/hydromodpy_debug.log` in the project folder, whatever the
console shows. `hmp doctor` probes the environment: Python packages, solvers and the
workspace.

## How a message reaches you

A message comes in one of three shapes.

**A refusal of the file.** `hmp config check` prints `Config invalid:` and the reason.
When one field is at fault, there is one line per field: the file, the line of the key, the
path of the key, what is wrong and the value it read.

```text
Config invalid: 1 validation error(s) in my_project.toml:
  my_project.toml:3: flow.flow_regime: Value error, flow.flow_regime must be 'steady' or 'transient'. (input='steadi')
```

`hmp run` prints the same text without the words `Config invalid:` and exits with code 14.

**A step of the run that fails.** The run is a fixed list of steps. When one of them
raises, `hmp run` prints its name and the error:

```text
step '<step name>' failed: <ErrorType>: <message>
```

The exit code is the one of the error inside the step. A missing file gives 10, a refused
configuration 14, a solver that fails 15, a data error 16. An error that is not a HydroModPy
one, such as a `RasterioIOError`, gives 1. The codes are listed in
{doc}`../reference/cli/exit-codes`.

| Step | What it does | Section |
|---|---|---|
| `validate` | Loads the file again, checks the exports and the dates | {ref}`Reading the file <ts-reading>`, {ref}`Exporting <ts-exporting>` |
| `resolve` | Resolves the workspace paths | {ref}`Reading the file <ts-reading>` |
| `build_geographic` | Delineates the catchment on the DEM | {ref}`Building the model <ts-building>` |
| `load_data` | Reads or downloads the data of `[data]` | {ref}`Fetching data <ts-fetching>` |
| `build_mesh`, `setup_process`, `prepare_solver` | Builds the grid, the flow model and the solver files | {ref}`Building the model <ts-building>` |
| `run_solver` | Runs the solver | {ref}`Solving <ts-solving>` |
| `extract`, `derive`, `display`, `export` | Reads the results, derives fields, draws figures, writes the exports | {ref}`Exporting <ts-exporting>` |

**A message of a command.** `hmp export`, `hmp data` and `hmp install-binaries` print their
message and exit with a typed code. A path that does not exist gives code 10.

**A code in brackets.** A message that starts with `[HMPY.E401]` carries the code of its
class. Each code is a row of {doc}`../reference/python/exceptions`, with its class, its
parent, its exit code and where it is raised. The codes quoted below link there.

(ts-reading)=
## Reading the file

| Message | Cause | Fix |
|---|---|---|
| `Invalid TOML syntax: <parser text>` | The file is not valid TOML. The parser text gives the line and the column. | Fix the line. `hmp run` shows the same text with the prefix `Invalid override:`, which is misleading: the file is at fault, not an override. |
| `File not found: <path>` (exit 10) | The file you named does not exist. The path is absolute, so you see which folder was searched. | Fix the path. When the missing file is a `base_config`, `hmp run` prints `Missing file:` and Python's `[Errno 2] No such file or directory`. |
| `Unknown top-level TOML section(s): <names>` | A table of the file is not a section of the configuration, usually a typo such as `[flwo]`. | `hmp config schema --list-sections` prints the sections. They are the pages of the {doc}`parameter reference <../reference/parameters/index>`. |
| `Unknown TOML key(s) in [flow]: <names>` | A key of `[flow]` has no field behind it. | Check the spelling against the {doc}`flow reference <../reference/parameters/flow/index>`. The other sections refuse an unknown key with `Extra inputs are not permitted`, then the key path and the line. |
| `<key path>: Input should be ...`, `Field required` | The validation of a field. `Input should be` lists what the field takes, and `(input=<value>)` repeats what you wrote. `Field required` means a key is missing from a table that needs it. | The card of the key lists what it accepts. Write a length or a rate with its unit inside the string, as in {toml}`domain.depth_model.thickness`. |
| `Invalid base_config chain: Detected circular base_config chain: <a.toml> -> <b.toml> -> <a.toml>` | A file reaches itself through its bases. `base_config must be a TOML string path when provided` says the value is not a string. | Remove one of the links. {doc}`inheritance` gives the rules of the chain. |
| `TOML [workspace].project_root is required` | The file has no project folder, and neither has a base it inherits from. | Write `[workspace]` with {toml}`workspace.project_root`, see below. |
| `<file> must declare a [workflow] section with 'mode = "..."'.` | `hmp run` needs to know which workflow the file describes. The message ends with the valid values. | Write `[workflow]` with {toml}`workflow.mode`, see below. |
| `flow.param_list declares ids without payload in flow.param` | An id of {toml}`flow.param_list` has no `[flow.param.<id>.field]` table. | Add the table, or remove the id. |
| `flow.param contains ids not declared in flow.param_list` | A table names a parameter that the list does not. | Add the id. In a child file write `param_list__append = ["Ss"]`. |
| `flow.active_bc: '<name>' is not a valid boundary-condition id for Flow` | A name of {toml}`flow.active_bc` does not exist. The message ends with `Allowed values:` and the list. | Use a listed name. {toml}`flow.active_sinks_sources` says `is not a valid sink/source for Flow`. |
| `solver.backend='<name>' does not support the '<id>' boundary` | The solver cannot represent a boundary of {toml}`flow.active_bc`, so the run would have dropped it without a word. The message names the solvers that support it, after `supported by:`. | Choose one of them, or remove the boundary. See {doc}`choose-a-solver`. `hmp config check` prints it with the prefix `Config check failed:`. |
| `solver.backend names '<a>' and the flow process '<id>' of [[simulation.process]] names '<b>' in solvers. ...` | The two keys name two solvers. | Remove `solver.backend`: it follows the solver of the flow process. Or write the same name in both. |
| `flow.ic.type='steady_state' is only supported when flow.flow_regime='transient'` | A steady run has no initial condition to compute: its solution is the state. | Make the run transient, or choose another initial condition ({doc}`time-and-initial-state`). |
| `[analysis] must be a mapping` | `analysis` is written as a value, such as `analysis = 3`. | It is a table: write `[analysis]` or `[analysis.batch]` and the keys under it. |
| `constraints_mode is required.` | `[mesh_catchment]` has no {toml}`mesh_catchment.constraints_mode`. | Write one of its values. |
| `geology section is required when constraints_mode includes geology.` | A mode that uses the geology was chosen and `[mesh_catchment.geology]` is missing. | Add the table, or choose a mode that does not use the geology. |
| `a time names no stress period of this run ([simulation.time] resolves to 36 periods):` then `export[6].time: 2035-01-01 is outside the record: ...` | Step 0 reads every date of `[[export]]` and `[display]` against the stress periods. A date outside the record, or a step index past the end, is refused before any solve. | Ask for a date inside the record, see below. |
| `data.types lists '<type>' but the file has no [data.<type>] section. Add the section with its sources, or remove '<type>' from data.types.` (exit 14) | A type is in {toml}`data.types` and its table is missing. | Add the table and its source, or take the type out of the list. {doc}`get-the-data` and {doc}`use-your-own-files` show a table per type. |

:::{dropdown} Five sections of older files are refused by name
Each message is `Section [<name>] is no longer supported` and says what replaces it.

| Section | What the message tells you |
|---|---|
| `[initializing]` | Use `[workspace]` instead. |
| `[modflow]` | Use `[solver]`, `[modflownwt]` and `[modflow6]` sections instead. |
| `[capability_gallery]` | Use `[analysis.capability_gallery]` instead. |
| `[batch]` | Use `workflow='testbed'` with `[testbed].profile = 'regional_lab'` and `[analysis.batch]` instead. |
| `[regional_lab]` | The message says it is not a section of the configuration, and sends you to `[analysis.batch]`. |
:::

A project folder and a workflow mode, the two tables every file needs:

```toml
base_config = "step1_minimal.toml"

[workspace]
project_root = "."

[workflow]
mode = "simulation"
```

```{hmp-params}
workspace.project_root
workflow.mode
flow.flow_regime
```

An export date inside the record. Example 04 ends here:

```{hmp-resolved} simulation.time.end_datetime
:config: step4_transient.toml
```

```toml
base_config = "step4_transient.toml"

[[export__append]]
variables = "watertable_depth"
time = "2002-06-15"
```

(ts-fetching)=
## Fetching data

A variable that you declared and that cannot be loaded stops the run: `step 'load_data'
failed: <ErrorClass>: Failed to load data manager '<type>': <reason>`. The exit code says
what went wrong: 10 for a missing file, 14 for a refused configuration, 16 for a data
error. Only a type that HydroModPy added by inference, under {toml}`data.inference_mode`
`"warn"`, is dropped with a warning that ends `The run goes on without '<type>'.` With the
`strict` mode the file must declare what it needs: `data.inference_mode='strict' requires at
least one explicit data type in data.types`, or `... requires explicit data sections for
inferred types:` and the list.

```{hmp-params}
data.inference_mode
```

| Message | Cause | Fix |
|---|---|---|
| `Failed to load data manager '<type>': <reason>` | A type of {toml}`data.types` could not be read or downloaded. The text after the colon is the real cause. | Look the reason up in this section. |
| `Data manager '<type>' is active but <detail>.` | A type is listed and its table is missing. For hydrography the detail reads `missing [data.hydrography] section`. | Add the table, or take the type out of the list. |
| `Unsupported data type '<name>'. Allowed values: ...` | A name of {toml}`data.types` is not a data type. | Use one of the names the message lists. |
| `data.<type>: date_end is missing: declare date_start and date_end together ...` | The window of a data type is two keys that go together. The mirror message names `date_start`, and `date_start must be before date_end` exists too. | Declare both, or neither: with neither, the window comes from `[simulation.time]`. |
| `project_period required to fetch hydrometry stations: declare date_start and date_end in [data.hydrometry], or a window in [simulation.time].` (`MissingForcingError`, <a href="../reference/python/exceptions.html#HMPY.E206">HMPY.E206</a>, exit 16) | A station variable fetched from an API has no period. | Declare the window. |
| `Custom <variable> path not found: <path>` | A source with `source = "custom"` points to a file or a folder that does not exist. The message exists for each variable: `Custom DEM path not found:`, `Custom geology path not found:` and the others. The DEM says `[data.dem] custom source path not found:`. | The printed path is made absolute from the folder of the TOML file you run. Compare it with the file on disk. `hmp data check` validates the custom files of `data/<variable>/` without ingesting them. |
| `<variable>: station_ids declares [...], absent from <file>. Known ids: ...` | You asked for a station that the location file of the folder does not list. The message prints the first ten known ids. | Copy one with its exact case. |
| `<variable>: <n> station(s) of source '<source>' outside the mask <file> dropped: [...]` (warning) | A station lies outside the catchment mask. The mask is the catchment, so the station is dropped, and now named. | Check the coordinates of the station, or accept the drop. |
| `<variable>: every station of source '<source>' lies outside the mask <file>: [...]. No station is left to load.` (<a href="../reference/python/exceptions.html#HMPY.E204">HMPY.E204</a>, exit 16) | Every station of a declared source is outside. | Fix the coordinates or the mask. |
| `<variable>: <file> declares no CRS, and HydroModPy does not guess one. Write the CRS into the file: ...` (<a href="../reference/python/exceptions.html#HMPY.E201">HMPY.E201</a>, exit 16) | A custom DEM, geology file or river network has no CRS. The message gives the `gdal_edit.py` or `ogr2ogr` command. | Write the CRS into the file. For a shapefile, a `.prj` file beside it. |
| `Station <id> has no unit in its LOC file; its values are taken as <unit> and not converted.` (warning) | The location file gives no unit for a station. | Add a `unit` column. |
| `No <variable>_custom_LOC.* in <folder>`, `Custom data directory not found: <folder>`, `No unit for station '<id>'. Add a 'unit' column in the LOC file.` | A folder of station data needs a location file named `<variable>_custom_LOC` with the extension csv, shp, gpkg or geojson, next to one chronicle file per station. | Add the file, or fix the folder. |
| `HTTP GET <url> -> <status>`, `HTTP <method> <url> failed after <n> retries`, `Response from <url> is not valid JSON` | A provider answered with an error status, did not answer, or sent something that is not an answer, a maintenance page for example. The client retries the statuses that can be temporary, with a delay that doubles. | A 5xx or a timeout is the provider: retry later, or serve the data from files ({doc}`work-offline`). A 4xx means the request is wrong: the station id, the period or the product. |
| `--frozen: hydromodpy.lock not found at <path>; --frozen requires a prior run.` (exit 14) | `hmp run --frozen` refuses any fresh download and checks every input against `hydromodpy.lock`. It stops when the lock does not exist yet. | Run once without `--frozen`, with network access, then freeze. |
| `Data cache not found at <path>; --frozen requires a populated workspace.`, `<n> lockfile mismatch(es); first:` and the first difference (exit 14) | The data cache is not there, or an input differs from its record. | {doc}`work-offline` has the whole procedure. |
| A `FrozenDataError` raised during the load: a cache miss, an entry missing from the lock, a digest mismatch (exit 16, <a href="../reference/python/exceptions.html#HMPY.E202">HMPY.E202</a>) | A frozen run met an input it cannot take from the cache. It now stops for every variable, not only for the DEM, the geology and the river network. | Populate the cache with a run without `--frozen`. |

```toml
base_config = "step2_local_data.toml"

[data.hydrometry]
sources__delete = true

[[data.hydrometry.sources]]
source = "custom"
path = "hydrometry"
station_ids = ["NANCON"]
```

```{hmp-params}
data.hydrometry.sources.station_ids
data.hydrometry.date_start
data.hydrometry.date_end
data.hydrometry.sources.path
data.types
```

(ts-building)=
## Building the model

### `Snapping outlet 'outlet' found no data cell in a snap window of <d> m around (<x>, <y>).`

The delineation moves your outlet to the cell of highest flow accumulation inside a square
window, and the window holds only empty cells. The message continues with `Check
geographic.catchment.x_outlet / y_outlet, increase geographic.catchment.snap_dist, or verify
that the corrected DEM and flow-accumulation rasters cover the outlet.` Check that the point
is inside the DEM and in the project CRS, then widen the window.

```{hmp-params}
geographic.catchment.x_outlet
geographic.catchment.y_outlet
geographic.catchment.snap_dist
geographic.crs_project
```

```toml
base_config = "step1_minimal.toml"

[geographic.catchment]
snap_dist = "300 m"
```

The window is not a distance limit: a window of one cell snaps nowhere. After a successful
snap, the log says `Outlet moved <d> m (limit <l> m) onto the flow network`, from one point
to the other. It is a warning when the outlet moved by more than half the window. Read it: an
outlet moved onto the wrong stream gives the wrong catchment.

| Message | Cause | Fix |
|---|---|---|
| `Delineation produced an empty catchment: <path>` | The delineation returned no polygon for the outlet. When the DEM is conditioned by breaching, HydroModPy tries once more with filling and logs `Catchment delineation returned an empty polygon with dem_correc_type=...; retrying geographic preprocessing with dem_correc_type='fill'.` | If the error stays, check the outlet and the snap window as above. {toml}`geographic.dem_correc_type` sets the conditioning. |
| `step 'build_geographic' failed: RasterioIOError: <path>: No such file or directory` (exit 1) | The DEM named by {toml}`geographic.catchment.dem_init_path` is read in this step. `hmp config check` does not look for the file. The path is made absolute from the folder of the TOML file you run. | Check the path and the format of the file. |
| `domain.depth_model kind = '<kind>' reads the raster declared under [data.substratum]` | The depth model reads a raster of the substratum and `[data.substratum]` has none. | Declare it with one custom source, as the message says. {toml}`domain.depth_model.kind` |
| `geographic.crossings is enabled without a path`, `geographic.crossings.path points to nothing: <path>`, `geographic.crossings.path <path> carries no CRS ...`, `geographic.enforce_lakes.lake_geometry_path not found:`, `geographic.dam_carve.line_path not found:` | The ground corrections of `[geographic]` read files and say which one is wrong. | Fix the file or the key the message names. |

(ts-solving)=
## Solving

| Message | Cause | Fix |
|---|---|---|
| `[HMPY.E401] Flow solver '<solver>' failed for run '<id>'.` (<a href="../reference/python/exceptions.html#HMPY.E401"><code>SolverDivergedError</code></a>, exit 15) | The solver did not converge. The message ends with the path of the listing to open. | {doc}`non-convergence` says where the listing lives, how long it stays and which settings exist. |
| `[HMPY.E405] mf6_newton and mf6_enable_rewet are mutually exclusive in MODFLOW 6 ...` (<a href="../reference/python/exceptions.html#HMPY.E405">HMPY.E405</a>) | Newton forbids rewetting. | Disable one of the two. |
| `[HMPY.E406] mf6_linear_acceleration='CG' is invalid with mf6_newton=True ...` (<a href="../reference/python/exceptions.html#HMPY.E406">HMPY.E406</a>) | Newton builds a non-symmetric matrix, which CG cannot solve. | Use `BICGSTAB`, or leave the key unset. |
| `step 'run_solver' failed: FileNotFoundError: Solver '<name>' not found under <folder> after download attempt. Expected file: <path>.` (exit 10) | The solver executables are downloaded to the cache folder (`~/.cache/hydromodpy/bin` on Linux) the first time a run needs them. The download ended without producing the file, usually for lack of network. | Run `hmp install-binaries` once, then work offline. It prints `Already cached` when the files are there, and `--upgrade` downloads them again. The options are in {doc}`../reference/cli/install-binaries`. |
| `Boussinesq runtime_backend='petsc' requires petsc4py to be installed in the active Linux environment.` | The Boussinesq solver was asked for the PETSc runtime and `petsc4py` is missing. `Boussinesq runtime_backend='petsc' is only supported on Linux.` on another platform. | Install `petsc4py`, or choose another {toml}`flow.runtime_backend`. |
| `MF6 API subprocess for <folder> timed out after <n>s.` | With the `api` runner, each solve runs in a subprocess under a time budget. A long chronicle can need more. | Raise {toml}`modflow6.runtime.mf6_api_timeout_s`. |
| `MF6 API subprocess for <folder> exited (code <n>) without a result; libmf6 likely crashed.` | Not a timeout. | Run the same file with the `subprocess` runner ({toml}`modflow6.runtime.mf6_runner`) to see whether the crash comes from the library. |
| `The 'cma' package is required for the cma_es method; install via 'pip install cma'.` | A calibration asked for `cma_es` and the package is missing. The Optuna TPE sampler comes with HydroModPy. | `pip install "hydromodpy[calibration]"`. |
| `Unknown optimizer: '<name>'. Available built-ins: [...]` | An unknown {toml}`calibration.method`. | Use one of the names the message lists. |

(ts-exporting)=
## Exporting

The blocks of `[[export]]` are checked twice: by `hmp config check` and by step 0 of
`hmp run`. The message names the block, counted from 0, as `export[<n>]`. The blocks of a
base file count first. {doc}`export-results` has the rules and every message in context.

| Message | Cause | Fix |
|---|---|---|
| `no run can export export[<n>]: '<name>'` | A name of {toml}`export.variables` is not something a run can write. The message continues with the names that exist, by kind. | After a run, `hmp export <run> --list` prints what that run holds. |
| `export[<a>] and export[<b>] both write <file>` | Two blocks plan the same file. | Give one of them its own {toml}`export.file` or {toml}`export.folder`, or merge them. |
| `export[<n>]: ... variables is missing: name what to export` | A block has no {toml}`export.variables`. The message gives the three forms: one name, a list, and `"all"`. Its relatives are `variables is empty` and the message that says `"all"` cannot be mixed with names. | Write the key. |
| `time = '<value>' is not a date. Write ...` | A selector of {toml}`export.time` is not a date, `"first"` or `"last"`. The same check applies to the time of `[display]`. `time = "all" is the default: leave time out to export the whole simulation.` answers the value `"all"`. | Write a date. |
| `time and period are both given` | A block uses {toml}`export.time` and {toml}`export.period` together. | Keep one. |
| `... does not reproject`, `resolution = <r> sizes the pixels of a GeoTIFF` | An {toml}`export.crs` or an {toml}`export.resolution` only means something for some formats. A CSV file is written in the model CRS. | Drop the key, or ask for a format that takes it. |
| `run '<name>' holds no '<variable>'.` then `It can export:` (exit 1) | From `hmp export`, once the run exists. The run does not hold what you asked for. For the simulated stream network, a line after the first gives the reason the run has none. | Pick a name from the list ({doc}`read-the-results`). |
| `the request selects no stress period.` | `hmp export` was given a date or a period that holds no stress period of the run. | Name a date in `--time`, a window in `--period`, or leave both out. |
| `VTU export requires meshio: pip install meshio` | The VTU format needs `meshio`. | Install it in the environment of HydroModPy. |
| `No .hmp archive at <path>`, `Simulation '<id>' already exists. Use force=True to overwrite.` | `hmp data import <archive>` was pointed at a file that does not exist, or at an archive whose run is already in the catalog. On the command line the option is `--force`. | `--dry-run` validates the archive and writes nothing. `hmp export <run> all --format package` writes an archive ({doc}`share-a-run`). |
| `Zarr store not found at <path>` | Packaging a run reads its `fields.zarr` folder, and the folder is gone. | Run the simulation again, or restore the run folder from a backup. |
| `CSV time series not found: <path>`, `NetCDF file not found: <path>` | These come from the importers `import_csv_timeseries` and `import_netcdf_fields` of the Python package. The path is tested as you wrote it: a relative path is read from the working directory of the Python process, not from the folder of a TOML file. | Write an absolute path. See {doc}`drive-from-python`. |

```{hmp-params}
export.variables
export.file
export.folder
export.time
export.period
export.crs
export.resolution
export.format
```

## After a fix

- A fix that makes the next message appear is normal: the file is read in the order of this
  page. Run `hmp config check` again after each change.
- A step fails with a Python error that is not listed here, such as `KeyError` or
  `ValueError`. The text after the error type is the cause. Run again with `--debug` and keep
  the traceback.

## How to check it worked

- `hmp config check <file>.toml` prints `OK:` and the path.
- `hmp run <file>.toml --dry-run` prints the plan and runs nothing.
- After a data fix, `hmp run <file>.toml --until load_data` stops after the data step.

## Where to go next

- {doc}`non-convergence` for a solver that stops or a budget that does not close.
- {doc}`get-the-data`, {doc}`use-your-own-files` and {doc}`work-offline` for the data steps.
- {doc}`export-results` for what a run writes and how to ask for it.
- {doc}`../reference/python/exceptions` for every code and class, and
  {doc}`../reference/cli/exit-codes` for the exit codes of `hmp`.

To report a message that is not listed, open an issue with the whole message, the TOML file
or a reduced copy of it, and the output of `hmp --version`.
