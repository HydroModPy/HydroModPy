# Read the results of a run

```{hmp-task}
Task
: Open the tables, the fields and the series of a finished run from Python, without running anything again.

Time
: Seconds. A field is read lazily, so a long record costs nothing until you use it.

Needs
: A project that has run at least once. The worked case is example 04, run `step4_transient.toml`. The name of the run: `hmp catalog ls` lists them.

Gives
: Parquet tables as pandas data frames, fields as xarray arrays, series as pandas series, and a clear idea of what the run folder holds.
```

A run keeps its results as plain files, in a folder named after the run. The files are
readable without HydroModPy. To write results out as GeoTIFF, NetCDF, CSV or GeoPackage, see
{doc}`export-results`.

## Where a run keeps its results

A run writes one folder, `runs/<name>/`. The arrays are Zarr, the tables are Parquet, the
frozen configuration is TOML, the seal and the provenance are JSON. Nothing is packed in an
archive.

```text
<project>/
├── project.toml                shared settings, and the marker of the project root
├── runs/
│   └── nancon_step4_transient/
│       ├── config.toml         the resolved configuration of this run
│       ├── fields.zarr/        arrays: head, mesh, forcings
│       ├── tables.parquet/     one Parquet file per table
│       ├── figures/            figures rendered for this run
│       ├── provenance.json     versions, git commit, solver binary
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

The contract of the layout, the content of `manifest.json`, `provenance.json` and
`annotations.json`, and the exact files are in {doc}`/contribute/architecture/storage-layout`.
`config.toml` is the resolved configuration of the run, after `base_config`, overlays and
`--set` overrides. `hmp catalog rerun` replays it.

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

## 2. Read the fields and the series

`fields.zarr/` holds the arrays. Read it through `hmp.read`, which finds the variable by its
name and hands back a lazy `xarray.DataArray`.

```python
import hydromodpy as hmp

catalog = hmp.open("path/to/project")
run = catalog.latest()

head = hmp.read(run, "head")                       # lazy DataArray
last = hmp.read(run, "head", time=-1, layer=0)     # eager numpy array
```

`time` picks one period of a field. It is an index (negative counts from the end), a date,
`"first"` or `"last"`. A date reads the stress period that holds it, so one date names the
same month on a monthly run and on a daily run. Without `time`, every stored period is
loaded lazily. `layer`, `sel` and `bbox` narrow the read. A series or a vector layer goes
through the same door, and refuses `time`:

```python
oct_2002 = hmp.read(run, "head", time="2002-10-15", layer=0)   # the period that holds the date
q = hmp.read(run, "discharge")                                 # pandas Series
watershed = hmp.read(run, "watershed")                         # GeoDataFrame
q_2002 = hmp.read(run, "discharge", sel={"period": ("2002-01-01", "2002-12-31")})
```

The `Run` object also hands back the tables as data frames: `run.parameters`, `run.metrics`,
`run.mass_balance`, `run.budget()` and `run.timeseries("discharge")`. For raw access to the
arrays, open the folder with `zarr.open_group(path, mode="r")`.

The control figure for a series is the hydrograph. `hmp.read(run, "discharge")` is the line
below, one value per month, and `hmp viz show <run> hydrograph` draws it for your own run:

```{figure} /_static/figures/guides/hydrograph.webp
:alt: Simulated monthly discharge at the outlet of the Nançon catchment, 2000 to 2002.
:width: 100%

`hydrograph` of the calibrated run of example 04. Each point is the mean discharge of one
month, stamped at the end of that month.
```

### The time stamps

A run stores one record per stress period and stamps it with the end of the period. A flux
is the mean over the period, and a state is the value at the stamp. The simulated `discharge`
series is therefore indexed on the end stamp of each period: put it on `run.periods.edges[:-1]`
before you compare it with a gauge averaged by month. The convention is written once, with
its consequences, in {doc}`/theory/time-alignment`.

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

### Compact precision

A field that varies in time is stored as float32 with its mantissa rounded to 16 bits, which
moves a value by at most 7.6e-6 of itself. `hmp.read` hands back float64 and your code sees
no change. Raw `zarr` access sees the stored float32. Choose `"exact"` when you compare two
runs to a tolerance below 1e-5 relative:

```toml
base_config = "step4_transient.toml"

[simulation.results.persistence]
field_precision = "exact"
```

The card of {toml}`simulation.results.persistence.field_precision` says what is rounded and
what is not. A calibration has its own switch, {toml}`calibration.persistence.field_precision`.
The attributes that mark a rounded array are described in
{doc}`/contribute/architecture/storage-layout`.

## 3. Find a run from the command line

`hmp catalog ls` lists the runs of the project, `hmp catalog show <run>` prints one, and
`hmp catalog query` runs SQL on the index. {doc}`find-and-compare-runs` covers these
commands and every way to name a run.

## How to check it worked

- `hmp.read(run, "head")` returns an array whose last dimension is the number of cells that
  `hmp catalog show <run>` prints.
- The first stamp of `hmp.read(run, "discharge")` is the end of the first period: for a
  monthly run from 2000-01-01, it is 2000-02-01.
- `hmp viz show <run> hydrograph` draws the same series as `hmp.read(run, "discharge")`.

## What can go wrong

| What you see | Why, and what to do |
|---|---|
| `FieldNotFoundError: Variable '<x>' not found in any backend (field_registry, timeseries, geographic_features).` | The name is not a field, a series or a layer of this run. `hmp export <run> --list` prints the names the run holds. |
| `'discharge' is a series, and time= selects a period of a field. Use sel={"period": (start, end)}.` (`ValueError`) | A `time=` was given to a series or a vector layer. Window a series with `sel`. |
| `TypeError: time must be a period index, a slice of indexes, a date, 'first' or 'last'; got float.` | `time` is of a kind that is not read. Pass an integer, a date, `"first"`, `"last"` or a slice. |
| `TimeSelectionError: 1999-01-01 is outside the record: the record runs from 2000-01-01 to 2003-01-01.` | The date is outside the record of the run. |
| `TimeSelectionError: '<text>' is not a date (YYYY-MM-DD), "first", "last" or a period index.` | The text is not a date. Write `2002-10-15`. |
| `outflow_drain` or `fluxes_from_budget` is missing | The run did not store the per-cell budget. Switch on `simulation.results.budget.spatial_fields` (step 2) and run again. |
| A run folder with no `manifest.json` | The run did not finish. Do not read it. Run the file again. |
| `Catalog at <path> is open read-only; writes are refused.` | `hmp.open` is read-only by default. Open with `hmp.open(folder, read_only=False)` to tag, note or delete. |
| `FileNotFoundError: No catalog at <folder>/.hmp` | The folder has no index. Give a project folder, or run `hmp catalog reindex` if it holds runs. |
| Two runs differ by 1e-6 on a head | The compact precision rounds the stored heads. Choose `"exact"` for a comparison below 1e-5 relative. |

## Where to go next

- {doc}`export-results` writes GeoTIFF, NetCDF, CSV, GeoPackage and packages.
- {doc}`read-a-value-at-a-point` reads one cell of a finished run.
- {doc}`find-and-compare-runs` ranks, tags and renames runs.
- {doc}`drive-from-python` runs and reads from a script.
- {doc}`/understand/reading-results` reads the figures of example 04.
