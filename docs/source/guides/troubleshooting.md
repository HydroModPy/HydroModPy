# Troubleshooting by message

You have an error message and you want its cause and its fix. This page lists the
messages you are most likely to meet, in the order a run meets them: reading the file,
fetching data, building the model, solving, exporting. Each entry gives the text, the
cause and what to change.

A run that stops because the solver did not converge has its own guide:
{doc}`A run does not converge <non-convergence>`.

## What you need first

- The whole message, not its last line. Most messages name the key to change.
- The command that printed it. `hmp config check <file>.toml` reads the file the way
  `hmp run` does, `base_config` included, and runs the checks of step 0. Most messages of
  the first and the last sections stop there, before any download and before any solve.
- A variable part of a message is written `<like this>` below. Search for the fixed words
  around it.

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
The exit codes are listed in {doc}`../reference/cli/exit-codes`.

**A step of the run that fails.** The run is a fixed list of steps. When one of them
raises, `hmp run` prints its name and the error, and exits with code 1.

```text
step '<step name>' failed: <ErrorType>: <message>
```

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

(ts-reading)=
## Reading the file

### `Invalid TOML syntax: ...`

The file is not valid TOML. The text after the colon comes from the TOML parser and gives
the line and the column.

```text
Invalid TOML syntax: Expected ']' at the end of a table declaration (at line 2, column 6)
```

Fix the line it names. A table header closes with `]`, a string with its quote. `hmp run`
shows the same parser text with the prefix `Invalid override:`, which is misleading: the
override is not at fault, the file is.

### `File not found: <path>`

`hmp config check` and `hmp run` print this when the file you named does not exist. Both
exit with code 10. The path is absolute, so you see which folder the command looked in.
When the missing file is a `base_config`, `hmp run` prints `Missing file:` and Python's
`[Errno 2] No such file or directory` with the path, and `hmp config check` prints the
`[Errno 2]` text alone.

### `Unknown top-level TOML section(s): <names>`

A table of the file is not a section of the configuration. The usual cause is a typo in
the table name, such as `[flwo]` for `[flow]`. The sections that exist are the pages of the
{doc}`parameter reference <../reference/parameters/index>`. `hmp config schema --list-sections`
prints them.

### `Unknown TOML key(s) in [flow]: <names>`

A key of `[flow]` has no field behind it. Check the spelling against the
{doc}`flow reference <../reference/parameters/flow/index>`. The other sections refuse an
unknown key with `Extra inputs are not permitted`, followed by the key path and the line of
the file.

### `Section [<name>] is no longer supported`

Five sections of older files are refused by name. Each message says what replaces it.

| Section | What the message tells you |
|---|---|
| `[initializing]` | Use `[workspace]` instead. |
| `[modflow]` | Use `[solver]`, `[modflownwt]` and `[modflow6]` sections instead. |
| `[capability_gallery]` | Use `[analysis.capability_gallery]` instead. |
| `[batch]` | Use `workflow='testbed'` with `[testbed].profile = 'regional_lab'` and `[analysis.batch]` instead. |
| `[regional_lab]` | The message says it is not a section of the configuration, and sends you to `[analysis.batch]`. |

### `<key path>: Input should be ...` and `Field required`

These two come from the validation of a field. `Input should be` is followed by the values
the field takes, and `(input=<value>)` repeats what you wrote. `Field required` means a key
is missing from a table that needs it. The card of the key lists what it accepts:

```{hmp-params}
flow.flow_regime
```

A length or a rate written without its unit is refused with the path of the key and a unit
conversion error. Write the unit inside the string, as in {toml}`domain.depth_model.thickness`.

### `Invalid base_config chain: ...`

A file can name another file in `base_config` and inherit from it. When the chain loops,
`hmp config check` prints:

```text
Invalid base_config chain: Detected circular base_config chain: <a.toml> -> <b.toml> -> <a.toml>
```

`hmp run` prints the same text with the prefix `Invalid override:`. A file reaches itself
through its bases: remove one of the links. The message `base_config must be a TOML string
path when provided` says the value is not a string. See {doc}`inheritance` for the rules of
the chain.

### `TOML [workspace].project_root is required`

The file has no project folder, and neither has a base it inherits from. Name it:

```toml
base_config = "step1_minimal.toml"

[workspace]
project_root = "."
```

```{hmp-params}
workspace.project_root
```

### `<file> must declare a [workflow] section with 'mode = "..."'.`

`hmp run` needs to know which workflow the file describes. The message ends with the
valid values. Add the table:

```toml
base_config = "step1_minimal.toml"

[workflow]
mode = "simulation"
```

```{hmp-params}
workflow.mode
```

### `flow.param_list declares ids without payload in flow.param`

Two lists must agree: the parameters named in {toml}`flow.param_list` and the tables
`[flow.param.<id>.field]`. This message names an id of the list that has no table. Its
mirror, `flow.param contains ids not declared in flow.param_list`, names a table that the
list does not mention. Add the missing table, or the missing id.

```toml
base_config = "step1_minimal.toml"

[flow]
param_list = ["K", "Sy"]
```

### `flow.active_bc: '<name>' is not a valid boundary-condition id for Flow`

A name of {toml}`flow.active_bc` does not exist. The message ends with `Allowed values:` and
the list. The same form exists for {toml}`flow.active_sinks_sources`, which says
`is not a valid sink/source for Flow`.

```toml
base_config = "step1_minimal.toml"

[flow]
active_bc = ["drainage"]
```

### `solver.backend='<name>' does not support the '<id>' boundary`

The solver you chose cannot represent a boundary of {toml}`flow.active_bc`, so the run
would have dropped it without a word. The message names the solvers that support it, after
`supported by:`. Choose one of them, or remove the boundary from the list. `hmp config
check` prints this message with the prefix `Config check failed:`.

```toml
base_config = "step1_minimal.toml"

[solver.backend]
backend = "modflow6"
```

See {doc}`choose-a-solver` for what each solver supports.

### `flow.ic.type='steady_state' is only supported when flow.flow_regime='transient'`

A steady run has no initial condition to compute: its solution is the state. The message
names the key as `flow.ic.type`. The key you write is {toml}`flow.ic.h.type`. Either make the
run transient, or choose another initial condition. {doc}`time-and-initial-state` shows the
pairs that go together.

### `[analysis] must be a mapping`

`analysis` is written as a value, such as `analysis = 3`. It is a table. Write `[analysis]`
and the keys under it, or `[analysis.batch]` and its keys.

### `constraints_mode is required.` and `geology section is required ...`

Both come from `[mesh_catchment]`. The first says the table has no
{toml}`mesh_catchment.constraints_mode`. The second,
`geology section is required when constraints_mode includes geology.`, says a mode that uses
the geology was chosen and `[mesh_catchment.geology]` is missing. Add the table, or choose a
mode that does not use the geology.

```{hmp-params}
mesh_catchment.constraints_mode
```

### `a time names no stress period of this run`

Step 0 reads every date of `[[export]]` and `[display]` against the stress periods that
{toml}`simulation.time.start_datetime` and {toml}`simulation.time.end_datetime` give. A date
outside the record, or a step index past the end, is refused before any solve. Under the
first line, each line gives the key and the reason.

```text
a time names no stress period of this run ([simulation.time] resolves to 36 periods):
  export[6].time: 2035-01-01 is outside the record: the record runs from 2000-01-01 to 2003-01-01.
```

Example 04 ends here:

```{hmp-resolved} simulation.time.end_datetime
:config: step4_transient.toml
```

Ask for a date inside the record:

```toml
base_config = "step4_transient.toml"

[[export__append]]
variables = "watertable_depth"
time = "2002-06-15"
```

(ts-fetching)=
## Fetching data

### `Failed to load data manager '<type>': <reason>`

A type of {toml}`data.types` could not be read or downloaded. The text after the colon is
the real cause, so look it up in this section. The consequence depends on
{toml}`data.inference_mode`. A type that you listed yourself in `data.types` stops the run. A
type that HydroModPy added by inference, with the `warn` mode, only logs a warning and the
run goes on without it.

```{hmp-params}
data.inference_mode
```

With the `strict` mode the file must declare what it needs. A file that does not is refused
with `data.inference_mode='strict' requires at least one explicit data type in data.types`
or with `data.inference_mode='strict' requires explicit data sections for inferred types:`
and the list of the types.

### `Data manager '<type>' is active but <detail>.`

A type is in {toml}`data.types` and its table is missing. For hydrography, the detail reads
`missing [data.hydrography] section`. Add the table and its source, or take the type out of
the list. {doc}`get-the-data` and {doc}`use-your-own-files` show a table per type.

### `Unsupported data type '<name>'. Allowed values: ...`

A name of {toml}`data.types` is not a data type. The message lists the names that exist.

```{hmp-params}
data.types
```

### `data.<type>: date_end is missing: declare date_start and date_end together ...`

The window of a data type is two keys that go together. Declare both, or neither: with
neither, the window comes from `[simulation.time]`. The mirror message, about `date_start`,
exists too, and so does `date_start must be before date_end`.

```{hmp-params}
data.hydrometry.date_start
data.hydrometry.date_end
```

```toml
base_config = "step3_api_data.toml"

[data.hydrometry]
date_start = "2000-01-01"
date_end = "2002-12-31"
```

### `Custom <variable> path not found: <path>`

A source with `source = "custom"` points to a file or a folder that does not exist. The
message exists for each variable: `Custom DEM path not found:`,
`Custom geology path not found:`, `Custom lake-geometry path not found:` and the others.
The DEM source says `[data.dem] custom source path not found:` and prints the path made
absolute from the folder of the TOML file you run. Compare the printed path with
the file on disk.

```{hmp-params}
data.hydrometry.sources.path
```

`hmp data check` validates the custom files of `data/<variable>/` without ingesting them.

### `<variable>: station_ids declares [...], absent from <file>. Known ids: ...`

You asked for a station that the location file of the folder does not list. A silent drop
would have left an empty observed series, so the run stops. The message prints the first ten
known ids. Copy one with its exact case.

```text
hydrometry: station_ids declares ['NANCN'], absent from hydrometry_custom_LOC.csv. Known ids: <ids>.
```

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
```

### `No <variable>_custom_LOC.* in <folder>` and `Custom data directory not found: <folder>`

A folder of station data needs a location file named `<variable>_custom_LOC` with the
extension csv, shp, gpkg or geojson, next to one chronicle file per station. The first
message says the location file is missing. The second says the folder itself is. A third
message of that reader, `No unit for station '<id>'. Add a 'unit' column in the LOC file.`,
says the location file gives no unit for a station.

### `HTTP GET <url> -> <status>` and `HTTP <method> <url> failed after <n> retries`

The providers that download share one HTTP client. The first message means the provider
answered with an error status. The second means it did not answer at all, or the connection
failed, on every try. The client retries the statuses that can be temporary, with a delay
that doubles, before it gives up.

Look at the status. A 5xx or a timeout is the provider: retry later, or serve the data from
files (see {doc}`work-offline`). A 4xx means the request is wrong: the station id, the
period or the product. The related message `Response from <url> is not valid JSON` means
the provider sent something that is not an answer, a maintenance page for example.

### `--frozen: hydromodpy.lock not found at <path>; --frozen requires a prior run.`

`hmp run --frozen` refuses any fresh download and checks every input against the
`hydromodpy.lock` of the project. It stops when the lock does not exist yet, when the data
cache is not there (`Data cache not found at <path>; --frozen requires a populated
workspace.`), or when an input differs from its record (`<n> lockfile mismatch(es); first:`
and the first difference). Run once without `--frozen`, with network access, then freeze.
{doc}`work-offline` has the whole procedure.

(ts-building)=
## Building the model

### `Snapping outlet 'outlet' found no data cell in a snap window of <d> m around (<x>, <y>).`

The delineation moves your outlet to the cell of highest flow accumulation inside a square
window, and the window holds only empty cells. The message continues with `Check
geographic.x_outlet / geographic.y_outlet, increase geographic.snap_dist, or verify that the
corrected DEM and flow-accumulation rasters cover the outlet.` The keys of the file carry
one more word than the message says: they sit under `[geographic.catchment]`. Check that the
point is inside the DEM and in the project CRS, then widen the window.

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

### `Delineation produced an empty catchment: <path>`

The delineation returned no polygon for the outlet. When the DEM is conditioned by breaching,
HydroModPy tries once more with filling and logs `Catchment delineation returned an empty
polygon with dem_correc_type=...; retrying geographic preprocessing with
dem_correc_type='fill'.` If the error stays, check the outlet and the snap window as for the
previous message.

```{hmp-params}
geographic.dem_correc_type
```

### The DEM cannot be opened

The DEM named by {toml}`geographic.catchment.dem_init_path` is read in the step
`build_geographic`. `hmp config check` does not look for the file. When it is missing, the
step fails with the error of the raster library, and the path is made absolute from the folder
of the TOML file you run:

```text
step 'build_geographic' failed: RasterioIOError: <path>: No such file or directory
```

When the file exists and cannot be read, the same error says why. Check the path and the
format of the file.

### `domain.depth_model kind = '<kind>' reads the raster declared under [data.substratum]`

The depth model reads a raster of the substratum and `[data.substratum]` has none. Declare
it with one custom source, as the message says.

```{hmp-params}
domain.depth_model.kind
```

### `geographic.crossings is enabled without a path` and its relatives

The ground corrections of `[geographic]` read files and say which one is wrong:
`geographic.crossings.path points to nothing: <path>`, `geographic.crossings.path <path>
carries no CRS ...`, `geographic.crossings.path holds no 'kind' column ...`, and for the
lakes and the dam `geographic.enforce_lakes.lake_geometry_path not found:` and
`geographic.dam_carve.line_path not found:`. Fix the file or the key the message names.

(ts-solving)=
## Solving

### `[HMPY.E401] Flow solver '<solver>' failed for run '<id>'.`

The solver did not converge. The message ends with the path of the listing to open. This is
the subject of {doc}`non-convergence`, which says where the listing lives, how long it
stays and which settings exist.

### `Solver '<name>' not found under <folder> after download attempt.`

```text
step 'run_solver' failed: FileNotFoundError: Solver '<name>' not found under <folder> after download attempt. Expected file: <path>.
```

The solver executables are downloaded to the cache folder of HydroModPy the first time a run
needs them (`~/.cache/hydromodpy/bin` on Linux). This message says the download ended
without producing the file. The usual cause is no network at that moment. Download them once,
then work offline:

```bash
hmp install-binaries
```

The command prints `Already cached` when the files are there, and `--upgrade` downloads them
again. Its options are in {doc}`../reference/cli/install-binaries`.

### `Boussinesq runtime_backend='petsc' requires petsc4py to be installed in the active Linux environment.`

The Boussinesq solver was asked for the PETSc runtime and `petsc4py` is not installed. The
runtime is also refused on a platform other than Linux, with
`Boussinesq runtime_backend='petsc' is only supported on Linux.` Install `petsc4py`, or
choose another runtime.

```{hmp-params}
flow.runtime_backend
```

### `MF6 API subprocess for <folder> timed out after <n>s.`

With the `api` runner, each solve runs in a subprocess under a time budget. The message says
the budget guards against one stuck trial blocking a parallel calibration, and that a long
chronicle can need more. Raise it:

```{hmp-params}
modflow6.runtime.mf6_api_timeout_s
modflow6.runtime.mf6_runner
```

The sibling message `MF6 API subprocess for <folder> exited (code <n>) without a result;
libmf6 likely crashed.` is not a timeout. Run the same file with the `subprocess` runner to
see whether the crash comes from the library.

### `The 'cma' package is required for the cma_es method; install via 'pip install cma'.`

A calibration asked for `cma_es` and the `cma` package is not installed. The Optuna TPE
sampler comes with HydroModPy. The CMA-ES method and the `cmaes` sampler of Optuna need the
`calibration` extra, `pip install "hydromodpy[calibration]"`.

```{hmp-params}
calibration.method
```

An unknown method name gives `Unknown optimizer: '<name>'. Available built-ins: [...]`, with
the names this installation serves.

(ts-exporting)=
## Exporting

The blocks of `[[export]]` are checked twice: by `hmp config check` and by step 0 of
`hmp run`. The message names the block, counted from 0, as `export[<n>]`. The blocks of a
base file count first.

### `no run can export export[<n>]: '<name>'`

A name of {toml}`export.variables` is not something a run can write. The message continues
with the names that exist, by kind: fields, series, vector layers, raster layers and tables.
After a run, `hmp export <run> --list` prints what that run holds.

```{hmp-params}
export.variables
```

### `export[<a>] and export[<b>] both write <file>`

Two blocks plan the same file. Give one of them its own {toml}`export.file` or
{toml}`export.folder`, or merge them.

```{hmp-params}
export.file
export.folder
```

### `export[<n>]: ... variables is missing: name what to export`

A block has no {toml}`export.variables`. The message gives the three forms: one name, a list,
and `"all"`. Its relatives are `variables is empty` and the message that says `"all"` cannot
be mixed with names.

### `time = '<value>' is not a date. Write ...`

A selector of {toml}`export.time` is not a date, `"first"` or `"last"`. The same check
applies to the time of `[display]`. `time = "all" is the default: leave time out to export the
whole simulation.` answers the value `"all"`. The message `time and period are both given`
says a block uses {toml}`export.time` and {toml}`export.period` together, which it must not.

```{hmp-params}
export.time
export.period
```

### `... does not reproject` and `resolution = <r> sizes the pixels of a GeoTIFF`

An {toml}`export.crs` or an {toml}`export.resolution` only means something for some formats.
A CSV file is written in the model CRS, and a resolution sizes the pixels of a GeoTIFF. The
message tells you to drop the key or to ask for a format that takes it.

```{hmp-params}
export.crs
export.resolution
export.format
```

### `run '<name>' holds no '<variable>'.`

This one comes from `hmp export`, once the run exists. The run does not hold what you asked
for, and the message prints `It can export:` and what it holds. For the simulated stream
network, a line after the first one gives the reason the run has none. See
{doc}`results-and-exports`.

### `the request selects no stress period.`

`hmp export` was given a date or a period that holds no stress period of the run. Name a
date in `--time`, a window in `--period`, or leave both out to export the whole simulation.

### `VTU export requires meshio: pip install meshio`

The VTU format needs `meshio`. Install it in the environment of HydroModPy.

### `No .hmp archive at <path>` and `Simulation '<id>' already exists. Use force=True to overwrite.`

`hmp data import <archive>` was pointed at a file that does not exist, or at an archive whose
run is already in the catalog. The second message speaks of the Python argument. On the
command line the option is `--force`. `--dry-run` validates the archive and writes nothing.
`hmp export <run> all --format package` writes an archive.

### `Zarr store not found at <path>`

Packaging a run reads its `fields.zarr` folder, and the folder is gone. Run the simulation
again, or restore the run folder from a backup.

### `CSV time series not found: <path>` and `NetCDF file not found: <path>`

These come from the importers `import_csv_timeseries` and `import_netcdf_fields` of the
Python package. No command calls them. The path is tested as you wrote it: a relative path
is read from the working directory of the Python process, not from the folder of a TOML
file. See {doc}`drive-from-python`.

## What can go wrong with a fix

- A fix that makes the next message appear is normal: the file is read in the order of this
  page. Run `hmp config check` again after each change.
- A message that names a key path may use an older spelling of it. Two exist today:
  `flow.ic.type` stands for {toml}`flow.ic.h.type`, and `geographic.x_outlet`,
  `geographic.y_outlet` and `geographic.snap_dist` stand for the keys under
  `[geographic.catchment]`. Search the {doc}`parameter reference <../reference/parameters/index>`
  for the last word of the path.
- A step fails with a Python error that is not listed here, such as `KeyError` or
  `ValueError`. The text after the error type is the cause. Run again with `--debug` and keep
  the traceback.

## Where to go next

- {doc}`non-convergence` for a solver that stops or a budget that does not close.
- {doc}`get-the-data`, {doc}`use-your-own-files` and {doc}`work-offline` for the data steps.
- {doc}`results-and-exports` for what a run keeps and how to write it out.
- {doc}`../reference/cli/exit-codes` for the exit codes of `hmp`.

To report a message that is not listed, open an issue with the whole message, the TOML file
or a reduced copy of it, and the output of `hmp --version`.
