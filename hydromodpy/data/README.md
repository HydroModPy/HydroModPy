# `hydromodpy/data`

Everything a run reads from outside: provider APIs, user files, their cache
and the typed records handed to the layers above. This file is the map of the
package: what each subpackage answers, the import rules, the template of a
variable, how data flows, and where to add what.

## Variables

Each `[data.<name>]` section of a project TOML is one variable. The single
list of the 28 sections is `VARIABLE_SPECS` in `loading/_dispatch.py`.

| family | variables | sources besides `file` |
|---|---|---|
| grids (10) | `precipitation`, `etp`, `temperature`, `wind`, `humidity`, `radiation`, `soil_moisture`, `runoff`, `recharge`, `oceanic` | `url`, `sim2` (all but `oceanic`), `explore2` (`precipitation`, `etp`), `synthetic` (`recharge`), `shom` and `constant` (`oceanic`) |
| stations (4) | `hydrometry`, `piezometry`, `water_quality`, `intermittency` | `hubeau` |
| terrain and subsurface (3) | `dem`, `geology`, `hydrography` | `url`; `ign_geoplateforme_dem`; `brgm_1m`, `brgm_50k`; `bdtopage`, `euhydro`, `osm` |
| structures (1) | `crossings` | `url`, `bdtopo`, `roe` |
| lake chronicles (4) | `lake_inflow`, `lake_levels`, `lake_outflow`, `lake_withdrawal` | none |
| user files (6) | `lake_abacus` (table), `lake_bathymetry` (raster), `lake_geometry` (vector), `substratum` (raster), `soil_capacity` (raster), `layer_base` (raster) | `url` |

Every value of this column is a key of `data_sources` for its section (the
two-part key of `source/`), alongside the `file` source that every section
accepts. The variable still owns its cache, whatever the source:
grids in `GridVariable`, stations in `StationVariable`, user files in
`FileVariable`.

## Subpackages

In dependency order, lowest first.

| subpackage | answers |
|---|---|
| `contracts/` | the records handed upward: `PointRecord`, `FieldRecord`, `TableRecord`, `LoadResult` |
| `schemas/` | pandera schemas of the input tables (stations, chronicles, abacus, lithology, DEM), each with its `validate()` |
| `source/` | the `DataSource` port (`port.py`), its README being the contract, and the registry of sources, plugins included (`registry.py`), with generic `file` and `url` sources |
| `common/` | functions with no variable config and no cache: HTTP, units, geometry, file naming, and the one mask loader (`source_extent.py`); `clients/` holds what several variables share: the SIM2 product table and download, the Hub'Eau station helpers, the local DRIAS Explore2 NetCDF reader (`explore2_files.py`, read by `precipitation` and `etp`) |
| `ingest/` | a user file to the storage format and to records: rasters, vectors, tables, station folders, grids, and the observation series a run keeps beside the simulated ones (`observations.py`) |
| `provenance/` | what sits next to a file on disk, and the cache that is made of it: sidecars and `CacheIndex` (`sidecars.py`), derived copies, `hydromodpy.lock` (`lockfile.py`), the cache archive (`archive.py`) |
| `families/` | the bases the variables inherit: shared state, the cache calls, and the `FetchRequest` the family builds and hands to the class of the source port |
| `variables/` | one package per `[data.<name>]` section on the template below, and four flat modules that each hold a family of thin variables: `sim2_series.py` (wind, humidity, runoff, soil moisture, temperature), `forcing_series.py` (radiation, ETP, precipitation), `lake_series.py` (lake levels, inflow, outflow, withdrawal) and `user_rasters.py` (soil capacity, substratum, layer base) |
| `sites/` | the sites of the workspace: `data/sites/catalog.csv` in `SiteRow` rows (`catalog.py`, its only reader and writer, with the name and `near_site_m` checks), the importers behind `hmp site import` (site table, outlet layer, Hub'Eau stations), `[site] gauge` as the station of the series sources (`gauge.py`), and `single_site.py`, which resolves a `[site]` against the site catalog of the workspace (`match_site`, `resolve_single_site`, `SiteMismatchError`) |
| `loading/` | `[data]` of the TOML to the variables it activates to the data loaded: `DataConfig`, `DataPlanner`, `DataLoader`, `DataStore` |
| `workspace/` | the workspace data folder: scaffold of file templates, and `folders.py`, the creation, listing, deletion and cleaning of workspace and project folders behind `hmp workspace init`, `hmp workspace clean`, `hmp project new`, `hmp project list` and `hmp project delete` |
| `request/` | data asked for from outside a project: `DataRequest`, `run_request`, the `data-request` process, and `cache_verbs.py`, the verbs of `hmp data` on the data folder (`ls`, `get`, `remove`, `archive`, `restore`, and `prune` through `project`, which knows what is cited). It is the one subpackage that reads the workspace, ingest, provenance and loading together |

## Import rules

A subpackage imports only the subpackages its row of
`tests/unit/architecture/data_layout.yaml` allows, and
`tests/unit/architecture/test_package_layouts.py` checks every import: at module
level, inside a function, under `TYPE_CHECKING`, or as a dotted path in a
lazy-attribute table. Every subpackage may import `core`. Six more rules:

1. A variable never imports another variable.
2. Another layer of HydroModPy imports only the modules listed under `public`
   in `data_layout.yaml`. The bases in `families`, `common`, `schemas` but the DEM contract
   that the check of the input files reads, the registry and the store of `loading` and the inside of
   the variables stay private.
3. A variable reaches its providers through the source registry, so adding a
   provider touches no variable body and an `if` on the source name has no
   reason to appear.
4. No module uses a `_private` attribute of another. Ruff rule `SLF001`
   checks it.
5. The modules that hold a `DataSource` class import geopandas, pandas,
   rasterio or requests inside their functions: looking a source up by name
   loads nothing heavy. `tests/unit/architecture/test_layers.py`
   checks it, one module per source.
6. One exception to the import rules: the source registry
   (`source/registry.py`) names the shipped classes by a dotted path
   written as text and imports each on first use, so that a third-party plugin
   joins the same table. The registry is `data_sources`, an instance of the engine of `core/plugin_registry.py`, keyed on the
   section and the `source_id` of the class.

## Template of a variable

```
variables/<v>/
├── __init__.py   a one-line docstring, no import: validating a TOML loads no variable
├── config.py     <V>Config and <V>SourceConfig; the `source` field is a name of the registry
├── variable.py    VARIABLE_NAME, INTERNAL_UNIT, the FetchRequest of the section
├── apis/         one module per network provider of the variable, if it has one
└── file.py       only when loading the user's files takes real work
```

A thin variable has no code of its own: a source config, a section config and a variable class
that names itself. It does not get a folder. Its three classes sit in the flat module of its
family, one section per variable with the same three names (`<V>SourceConfig`, `<V>Config`,
`<V>Variable`; `File<V>Source` and `Url<V>Source` for a raster the user brings). The first
`VARIABLE_SPECS` entry of a variable points `config_module` and `variable_module` at that module.
A variable that gets a provider, a resolver or a loader of its own moves to a folder.

`dem`, `crossings` and `hydrography` also keep a `resolver.py`: the geographic step runs before any variable loads, so it turns their sources into files on disk first (`resolve_dem`, `fill_crossings_path`, `resolve_network_map_path`).

A variable names itself and the unit its records carry, and leaves every
provider to the registry of sources:

```python
class HydrometryVariable(StationVariable):
    VARIABLE_NAME = "hydrometry"
    INTERNAL_UNIT = "m3/s"
    RECORD_VARIABLE = "discharge"
```

- `RECORD_VARIABLE` is optional. It names what a record carries when that
  differs from `VARIABLE_NAME`.
- `data_sources.get(VARIABLE_NAME, cfg.source)` answers the class, and
  `build_from_section` binds the fields of the section to its constructor. A
  family of stations builds `FetchRequest(out_dir, station_ids=...)`, or the
  extent with the period the cache misses; a family of grids builds the extent
  in `PROJECT_EXTENT_CRS` with its period. The base class owns the
  cache: `GridVariable` keeps grids, `StationVariable` keeps
  chronicles per station and asks only for the missing periods.
- `file` and `url` are registered classes of the port. The base class loads file
  sources through `load_file_source` or `load_file`; a variable whose format takes
  real work overrides it or keeps a dedicated loader.
- The `source` field is a string checked against
  `data_sources.names(section)` while the file is read, so a name this
  installation does not serve is refused with the names it serves; the JSON
  schema and the config reference publish the values. `dem`, `geology` and
  `crossings` keep a discriminated union, because each of their sources
  carries its own model of options.
- `tests/unit/data/test_the_variable_families_agree.py` ties the lists: the
  `source` values of each variable match `data_sources.names(section)`,
  and each has an entry (licence, network hosts) in `hydromodpy/schema/sources.py`.

## The DataSource port

`source/README.md` is the contract of the port, in full: the members a source
class declares, the `FetchRequest` (an extent and its CRS, stations, a period,
or a request with none of them for a source that selects nothing), the
`FetchResult` and its `FileRecord` entries, and the hosts a shipped source
reads from `hydromodpy.schema.sources`.

Three facts are worth carrying here. Every provider is one class of the
port, so a source is found the same way whatever it serves:
`data_sources.get(section, source_id)`, the two-part key joined by `_` (26
shipped keys today, from `hydrography_bdtopage` to `crossings_roe`). A
source's points and fields are written in the unit their record carries; the
SI is reached at the entry of the Model, through `core/units`, and the port
converts no value. And a source knows nothing of the catalog, the workspace,
a lock or a cache: the variable builds the request and keeps the cache, the
source fetches. `source/permanence.py` names the one canonical `permanence`
column a source writes when it knows whether water flows all year.

## How data flows

During a run:

```
[data] of the TOML
  -> loading/config_schema.DataConfig           validation
  -> loading/planner.DataPlanner.build()        asked-for and inferred variables
  -> loading/loader.DataLoader   simulation window, basin mask
  -> variables/<v>/variable.<V>Variable.load()    files, or the class of the port
                                                   named by data_sources.get(section, source)
  -> contracts.LoadResult(points, fields, tables, warnings)
```

From outside a project, one engine (`request/engine.run_request`) serves a
`DataRequest`: `[data]` sections with the models of the TOML, an extent that
is exactly one of a box with its CRS, a vector mask or station codes, an
optional period, and plugin sources under `installed`. It writes one file per
variable and source, cut to the extent and period, beside a report
`request.json`. Two ways in:

| entry | output |
|---|---|
| `hmp data get request.json --to DIR`, or `hmp data get <variable> --bbox ... --crs ... --to DIR` | `DIR/` |
| `run_request(DataRequest(...), out_dir)` | a `RequestReport` |

From Python, without a project:

```python
from hydromodpy.data.loading.store import DataStore
store = DataStore()  # no folder: nothing is read from or written to a cache
store = DataStore(data_root="data/")  # a data folder of your choice
result = store.load_variable("hydrometry", cfg)
```

## The cache is its sidecars

The data folder is the cache. Next to each fetched file, `<file>.json` records
the variable, the source, the station or product, the extent and period, the
sha256 and size, the licence and where the file came from. There is no database.
A folder that still holds a `cache.duckdb` of HydroModPy 2.0.0 is refused with
`hmp workspace clean --data-cache`, which removes it.

`scan(data_root)` walks the folder once and returns the rows. Three rules say
what is a row.

- A sidecar must name its `variable`, and it is written only with one. A sidecar
  without it is listed in the report of the scan and is no row.
- Locks (`*.lock`), writes in progress (`*.part`), hidden names, `blobs/`,
  `sites/` and `extracted_ign/` are skipped by name. A `.json` that is not a
  sidecar is skipped with them.
- A user file is no row. Your files live under `inputs/`, and a sidecar with
  `source = "file"` is counted apart in the report and never pruned.

`CacheIndex` scans once per object, keeps the rows in memory and answers `find`
by variable, source, station, product, extent and period. A station chronicle is
written inside `index.chronicle(folder, stem)`, a file lock, so two cases that
fetch the same station write the same bytes in turn. A thousand sidecars scan in
about 30 ms and ten thousand in 0.3 s.

`prune(data_root, keep=...)` receives from `project` the digests that a run or a
lockfile cites. It never removes such a file and names it in its report. If
`project` cannot read the inputs of a run, it refuses to prune.

`hydromodpy.lock` is written from the rows, so it carries the source and the
licence of each file. A lockfile older than `hydromodpy.lock.v2` is refused, and
the message says to write it again with `hmp data lock`.

A frozen run reads only what the lockfile names. `read_locked_inputs(project_root)` reads the lockfile once and gives a `LockedInputs`, and `project` builds it when the request is frozen. The run hands that object, as the argument `locked`, to the `DataStore`, the `CacheIndex`, the `FileSource` and the `reject_*` functions of `lockfile.py`. `None` means a run that is not frozen. No module global holds the mode, so two runs in two threads of one process do not see each other as frozen.

## The site catalog

A workspace declares its sites once, in `data/sites/catalog.csv`, one
`SiteRow` per line (`site, label, gauge, uri, x_outlet, y_outlet, crs, tags`,
`hydromodpy.core.site`). `hmp site add`, `hmp site import`, `hmp site ls` and
`hmp site show` read and write it through `sites/catalog.py`. A name is declared once. An outlet closer
than `[sites] near_site_m` of `workspace.toml` (default 500 m) to the outlet
of a site of another name is refused, since it is most likely the same
catchment twice; `--force` replaces a site of the same name and accepts a
close outlet. One conflict writes nothing.

`[site] gauge` is the station of a catchment. A `file` (chronicles) or
`hubeau` source of `hydrometry`, `recharge` or `runoff` with no `station_ids`
reads it, and a list that leaves it out is refused with the name of the key
(`sites/gauge.py:apply_site_gauge`). Without a gauge, a run that loads exactly
one discharge station takes that station as its gauge (`gauge_of_run`).

## What `request/` holds

| module | answers |
|---|---|
| `model.py` | what is a request? `DataRequest`: the `[data]` sections with the models of the TOML, an extent that is exactly one of a box with its CRS, a vector mask (a file link, pinnable by `sha256`) or station codes, an optional period, and plugin sources under `installed`, whose options are bound against their constructor before anything runs |
| `engine.py` | `run_request` loads each section through its variable, over the extent written as a polygon mask in its own CRS. `hydrography` and the installed sources go through the source registry, never through the Whitebox code. A source that fails loses its files and is listed with its error; the others keep theirs. An empty answer (a box at sea) is a success marked `"empty": true` |
| `artefacts.py` | each answer cut to the extent and period, whatever the cache held: chronicles in one Parquet table, grids in one NetCDF, rasters in GeoTIFF, vectors in one GeoPackage layer, tables in Parquet |
| `job.py` | the `data-request` declaration and its body: resolution and refusal before anything is written, a data folder under the scratch of the job, the seal, the reuse short-circuit. A `file` source is refused, and a failed variable fails the job |

`request.json` beside the files lists each one with its sha256, size, CRS, box,
period and unit, and the variables that failed.

## Where the extent of a variable comes from

A variable resolves the box it asks a provider over from the source config alone
(`resolve_source_extent` in `common/source_extent.py`): `mask_path` first, then
`extent` together with `project_extent`. No variable takes a project-scoped
object. During a run, `DataLoader` writes the delineated watershed
into `mask_path` before it hands the config to the store.

`common/source_extent.py` reads every mask:

- `mask_geometry(path)` returns the polygon and the CRS the file declares, and
  refuses a mask with no CRS. A raster mask goes through the hull of its valid
  cells rather than its footprint: a catchment mask is `1` on the catchment and nodata
  elsewhere in a rectangle.
- `mask_extent(path)` gives its box, and `mask_extent_in(path, crs)` the box of
  the reprojected shape, which is tighter than a reprojected box and keeps a
  cached download a superset of the request.
- `mask_geometry_wgs84(path)` is the polygon the station variables filter with: a
  mask with no CRS is read as WGS84.

`project_extent` is a bare tuple with no CRS of its own. The raster variables read
it in `PROJECT_EXTENT_CRS` (`EPSG:2154`), the station variables in
`STATION_EXTENT_CRS` (`EPSG:4326`).

## The records handed upward

Every variable returns a `LoadResult`:

```python
@dataclass
class LoadResult:
    points: list[PointRecord]
    fields: list[FieldRecord]
    tables: list[TableRecord]
    warnings: list[str]
```

- `PointRecord`: `station_id`, `variable`, `source`, `unit`, `frequency`, `data`
  (a table), `date_start`, `date_end`, `location` (`StationLocation`),
  `is_constant`, `file_path`, `source_unit`, `quality`.
- `FieldRecord`: `variable`, `source`, `unit`, `data` (an xarray dataset or a
  path), `bbox`, `crs`, `date_start`, `date_end`, `frequency`, `source_unit`,
  `metadata`.
- `TableRecord`: `variable`, `source`, `table_id` (a lake abacus), `data` (a table
  or a path to Parquet), `unit`, `crs`, `source_unit`, `metadata`.

## Key public symbols

- `hydromodpy.data.loading.config_schema.DataConfig`, `loading.planner.DataPlanner`,
  `loading.plan.DataLoadPlan`, `loading.loader.DataLoader`, `loading.store.DataStore`,
  `hydromodpy.data.request.model.DataRequest` and `request.engine.run_request`.
- `hydromodpy.data.provenance.sidecars.{CacheIndex, CacheRow, Sidecar, scan, prune}`: the cache, read from the sidecars.
- `hydromodpy.data.contracts.load_result.LoadResult` and the three records.
- `hydromodpy.data.source.port.{DataSource, Extent, Period, FetchRequest,
  FetchResult, require_selectors, require_period, extent_for, shipped_hosts}`,
  `hydromodpy.data.contracts.file_record.FileRecord` and
  `hydromodpy.data.source.registry.{data_sources, build_from_section}`. The
  source classes themselves are imported from the module of their provider,
  for example `hydromodpy.data.variables.hydrography.apis.bdtopage`.
- `hydromodpy.data.request.job.{DATA_REQUEST, run}`.
- `hydromodpy.data.sites.catalog.{read_catalog, write_catalog, nearest_site,
  add_sites, declare_sites, SITE_CATALOG_RELPATH}`, `hydromodpy.data.sites.importers`
  and `hydromodpy.data.sites.gauge.{apply_site_gauge, gauge_of_run}`.

## Layer neighbors

`data` imports `core`, `schema` and `catchment`
(`tests/unit/architecture/layer_matrix.yaml`). `config`, `calibration`,
`workflow`, `project`, `cli` and the root facade import `data`.
`catchment` does not import it, and `data` never imports
`results`.

## Reading path

1. This file.
2. `variables/hydrometry/` for a station variable, and
   `families/stations.py` for how it calls the cache.
3. `variables/sim2_series.py` for a grid variable, and `common/clients/sim2_products.py`
   for SIM2.
4. `loading/loader.py` for what a run loads, and `loading/planner.py` for the
   inference rules.
5. `request/engine.py` for a request from outside.
6. `provenance/sidecars.py` for the cache.

## Where to add what

| to add | where |
|---|---|
| a provider for an existing variable | a `DataSource` class in `variables/<v>/apis/<provider>.py` (or `common/clients/` when several variables share it), its section and key in `_BUILTIN_PATHS` of `source/registry.py`, a value the config validates against `data_sources.names(section)`, an entry in `schema/sources.py` |
| a plugin source, out of tree | a `DataSource` class published on the `hydromodpy.data.source` entry-point group under the name `<section>_<source_id>`; see `docs/source/contribute/architecture/how-to/add-a-data-source.rst` |
| a user file for a variable | declare `source = "file"` with a path relative to the project root, under `inputs/`; see `docs/source/how-to/use-your-own-files.md` |
| an online file for a variable | declare `source = "url"` with an `url` string and optional `sha256` or `license` |
| a variable | a package on the template above, or a class pair in one of the flat modules of `variables/` when it is a thin family, a field of `DataConfig`, a row of `VARIABLE_SPECS`; see `docs/source/contribute/architecture/how-to/add-a-data-variable.rst` |
| a user-file format | `ingest/` |
| an import rule | `tests/unit/architecture/data_layout.yaml` |
