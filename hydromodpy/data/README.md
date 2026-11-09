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
accepts. The manager of a variable still owns its cache, whatever the source:
grids in `BaseFieldManager`, stations in `BaseVariableManager`, user files in
`BaseFileManager`.

## Subpackages

In dependency order, lowest first.

| subpackage | answers |
|---|---|
| `contracts/` | the records handed upward: `PointRecord`, `FieldRecord`, `TableRecord`, `LoadResult` |
| `schemas/` | pandera schemas of the input tables (stations, chronicles, abacus, lithology, DEM), each with its `validate()` |
| `source/` | the `DataSource` port (`port.py`), its README being the contract, and the registry of sources, plugins included (`registry.py`), with generic `file` and `url` sources |
| `common/` | helpers with no variable config and no cache: HTTP, units, geometry, file naming, and the one mask loader (`source_extent.py`); `clients/` holds what several variables share: the SIM2 product table and download, the Hub'Eau station helpers, the local DRIAS Explore2 NetCDF reader (`explore2_files.py`, read by `precipitation` and `etp`) |
| `ingest/` | a user file to the storage format and to records: rasters, vectors, tables, station folders, grids, and the observation series a run keeps beside the simulated ones (`observations.py`) |
| `provenance/` | what sits next to a file on disk: sidecars, derived copies, `hydromodpy.lock` |
| `registry/` | the DuckDB index of the cache (`data/cache.duckdb`); the files and their sidecars stay the truth. `input_cache.py` reads it for a workspace: `InputCache(workspace).list(variable=, source=, limit=)` and `.find(...)`. `DataCatalogDuckDB` opens it read-write (one process), read-only (`hmp data` reads, the `--frozen` check) or layered inside a case the launcher started: writes go to a private cache, the shared file is read one query at a time, and `merge_private_cache` folds the private file in when the case ends |
| `managers/` | the bases the variable managers inherit: shared state, the caches, and the `FetchRequest` the family builds and hands to the class of the source port |
| `variables/` | one package per `[data.<name>]` section, all on the template below |
| `sites/` | the sites of the workspace: `data/sites/catalog.csv` in `SiteRow` rows (`catalog.py`, its only reader and writer, with the name and `near_site_m` checks), the importers behind `hmp site import` (site table, outlet layer, Hub'Eau stations), `[site] gauge` as the station of the series sources (`gauge.py`), and `single_site.py`, which resolves a `[site]` against the site catalog of the workspace (`match_site`, `resolve_single_site`, `SiteMismatchError`) |
| `loading/` | `[data]` of the TOML to the variables it activates to the data loaded: `DataManagersConfig`, `DataPlanner`, `DataManagersRuntimeLoader`, `DataStore` |
| `workspace/` | the workspace data folder: scaffold of file templates, and `folders.py`, the creation, listing, deletion and cleaning of workspace and project folders behind `hmp workspace init`, `hmp workspace clean`, `hmp project new`, `hmp project list` and `hmp project delete` |
| `request/` | data asked for from outside a project: `DataRequest`, `run_request`, the `data-request` process, and `cache_verbs.py`, the verbs of `hmp data` on the workspace cache (`ls`, `get`, `add`, `remove`, `prune`). It is the one subpackage that reads the registry, the workspace, ingest, provenance and loading together |

## Import rules

A subpackage imports only the subpackages its row of
`tests/unit/architecture/data_layout.yaml` allows, and
`tests/unit/architecture/test_package_layouts.py` checks every import: at module
level, inside a function, under `TYPE_CHECKING`, or as a dotted path in a
lazy-attribute table. Every subpackage may import `core`. Six more rules:

1. A variable never imports another variable.
2. Another layer of HydroModPy imports only the modules listed under `public`
   in `data_layout.yaml`. Managers, `common`, `schemas` but the DEM contract
   that the check of the input files reads, and the inside of `loading` and of
   the variables stay private.
3. A manager reaches its providers through the source registry, so adding a
   provider touches no manager body and an `if` on the source name has no
   reason to appear.
4. No module uses a `_private` attribute of another. Ruff rule `SLF001`
   checks it.
5. The modules that hold a `DataSource` class import geopandas, pandas,
   rasterio or requests inside their functions: looking a source up by name
   loads nothing heavy. `tests/unit/architecture/test_data_source_port_stands_alone.py`
   checks it, one module per source.
6. One exception to the import rules: the source registry
   (`source/registry.py`) names the shipped classes by a dotted path
   written as text and imports each on first use, so that a third-party plugin
   joins the same table. The registry is `data_sources`, an instance of the engine of `core/plugin_registry.py`, keyed on the
   section and the `source_id` of the class.

## Template of a variable

```
variables/<v>/
├── __init__.py   imports only the config: validating a TOML loads no manager
├── config.py     <V>Config and <V>SourceConfig; the `source` field is a name of the registry
├── manager.py    VARIABLE_NAME, INTERNAL_UNIT, the FetchRequest of the section
├── apis/         one module per network provider of the variable, if it has one
└── file.py       only when loading the user's files takes real work
```

`dem`, `crossings` and `hydrography` also keep a `resolver.py`: the geographic step runs before any data manager, so it turns their sources into files on disk first (`resolve_dem`, `fill_crossings_path`, `resolve_network_map_path`).

A manager names its variable and the unit its records carry, and leaves every
provider to the registry:

```python
class HydrometryManager(BaseVariableManager):
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
  cache: `BaseFieldManager` keeps grids, `BaseVariableManager` keeps
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
a lock or a cache: the manager builds the request and keeps the cache, the
source fetches. `source/permanence.py` names the one canonical `permanence`
column a source writes when it knows whether water flows all year.

## How data flows

During a run:

```
[data] of the TOML
  -> loading/config_schema.DataManagersConfig   validation
  -> loading/planner.DataPlanner.build()        asked-for and inferred variables
  -> loading/loader.DataManagersRuntimeLoader   simulation window, basin mask
  -> variables/<v>/manager.<V>Manager.load()    files, or the class of the port
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
from hydromodpy.data import DataStore

store = DataStore()  # no folder: in-memory index, nothing written
store = DataStore(data_root="cache/")  # a cache folder of your choice
result = store.load_variable("hydrometry", cfg)
```

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
| `engine.py` | `run_request` loads each section through its manager, over the extent written as a polygon mask in its own CRS. `hydrography` and the installed sources go through the source registry, never through the Whitebox manager. A source that fails loses its files and is listed with its error; the others keep theirs. An empty answer (a box at sea) is a success marked `"empty": true` |
| `artefacts.py` | each answer cut to the extent and period, whatever the cache held: chronicles in one Parquet table, grids in one NetCDF, rasters in GeoTIFF, vectors in one GeoPackage layer, tables in Parquet |
| `job.py` | the `data-request` declaration and its body: resolution and refusal before anything is written, a cache under `$TMPDIR` indexed in memory, the seal, the reuse short-circuit. A `file` source is refused, and a failed variable fails the job |

`request.json` beside the files lists each one with its sha256, size, CRS, box,
period and unit, and the variables that failed.

## Where a manager's extent comes from

A manager resolves the box it asks a provider over from the source config alone
(`resolve_source_extent` in `common/source_extent.py`): `mask_path` first, then
`extent` together with `project_extent`. No manager takes a project-scoped
object. During a run, `DataManagersRuntimeLoader` writes the delineated watershed
into `mask_path` before it hands the config to the store.

`common/source_extent.py` reads every mask:

- `mask_geometry(path)` returns the polygon and the CRS the file declares, and
  refuses a mask with no CRS. A raster mask goes through the hull of its valid
  cells rather than its footprint: a catchment mask is `1` on the catchment and nodata
  elsewhere in a rectangle.
- `mask_extent(path)` gives its box, and `mask_extent_in(path, crs)` the box of
  the reprojected shape, which is tighter than a reprojected box and keeps a
  cached download a superset of the request.
- `mask_geometry_wgs84(path)` is the polygon the station managers filter with: a
  mask with no CRS is read as WGS84.

`project_extent` is a bare tuple with no CRS of its own. The raster managers read
it in `PROJECT_EXTENT_CRS` (`EPSG:2154`), the station managers in
`STATION_EXTENT_CRS` (`EPSG:4326`).

## The records handed upward

Every manager returns a `LoadResult`:

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

- `hydromodpy.data.{DataManagersConfig, DataPlanner, DataLoadPlan,
  DataManagersRuntimeLoader, DataStore, DataRequest, run_request}`, resolved
  lazily.
- `hydromodpy.data.registry.catalog_duckdb.DataCatalogDuckDB`: the cache index.
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
   `managers/base_manager_variable.py` for its cache.
3. `variables/wind/` for a grid variable, and `common/clients/sim2_products.py`
   for SIM2.
4. `loading/loader.py` for what a run loads, and `loading/planner.py` for the
   inference rules.
5. `request/engine.py` for a request from outside.
6. `registry/catalog_duckdb.py` for the cache index.

## Where to add what

| to add | where |
|---|---|
| a provider for an existing variable | a `DataSource` class in `variables/<v>/apis/<provider>.py` (or `common/clients/` when several variables share it), its section and key in `_BUILTIN_PATHS` of `source/registry.py`, a value the config validates against `data_sources.names(section)`, an entry in `schema/sources.py` |
| a plugin source, out of tree | a `DataSource` class published on the `hydromodpy.data.source` entry-point group under the name `<section>_<source_id>`; see `docs/source/contribute/architecture/how-to/add-a-data-source.rst` |
| a user file for a variable | declare `source = "file"` with a path relative to the project root, preferably under `inputs/`; see `docs/source/how-to/use-your-own-files.md` |
| an online file for a variable | declare `source = "url"` with an `url` string and optional `sha256` or `license` |
| a variable | a package on the template above, a field of `DataManagersConfig`, a row of `VARIABLE_SPECS`; see `docs/source/contribute/architecture/how-to/add-a-data-variable.rst` |
| a user-file format | `ingest/` |
| an import rule | `tests/unit/architecture/data_layout.yaml` |
