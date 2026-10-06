# `hydromodpy/data`

Everything a run reads from outside: provider APIs, user files, their cache
and the typed records handed to the layers above. This file is the map of the
package: what each subpackage answers, the import rules, the template of a
variable, how data flows, and where to add what.

## Variables

Each `[data.<name>]` section of a project TOML is one variable. The single
list of the 27 sections is `VARIABLE_SPECS` in `loading/_dispatch.py`.

| family | variables | sources besides `custom` | manager base |
|---|---|---|---|
| grids (10) | `precipitation`, `etp`, `temperature`, `wind`, `humidity`, `radiation`, `soil_moisture`, `runoff`, `recharge`, `oceanic` | `sim2` (all but `oceanic`), `explore2` (`precipitation`, `etp`), `synthetic` (`recharge`), `shom` and `constant` (`oceanic`) | `BaseFieldManager` |
| stations (4) | `hydrometry`, `piezometry`, `water_quality`, `intermittency` | `hubeau` | `BaseVariableManager` |
| terrain and subsurface (3) | `dem`, `geology`, `hydrography` | `ign_geoplateforme_dem`; `brgm_1m`, `brgm_50k`; `bdtopage`, `euhydro`, `osm` | written by hand |
| structures (1) | `crossings` | `bdtopo`, `roe` | `SourceTable`, written by hand |
| lake chronicles (4) | `lake_inflow`, `lake_levels`, `lake_outflow`, `lake_withdrawal` | none | `BaseVariableManager` |
| user files (5) | `lake_abacus` (table), `lake_bathymetry` (raster), `lake_geometry` (vector), `substratum` (raster), `soil_capacity` (raster) | none | `BaseFileManager` |

## Subpackages

In dependency order, lowest first.

| subpackage | answers |
|---|---|
| `contracts/` | the records handed upward: `PointRecord`, `FieldRecord`, `TableRecord`, `LoadResult` |
| `schemas/` | pandera schemas of the input tables (stations, chronicles, abacus, lithology, DEM), each with its `validate()` |
| `source/` | the `DataSource` port (`port.py`) and the registry of sources, plugins included (`registry.py`) |
| `common/` | helpers with no variable config and no cache: HTTP, units, geometry, file naming, and the one mask loader (`source_extent.py`); `clients/` holds what several variables share: the SIM2 product table and download, the Hub'Eau station helpers, the local DRIAS Explore2 NetCDF reader (`explore2_files.py`, read by `precipitation` and `etp`) |
| `ingest/` | a user file to the storage format and to records: rasters, vectors, tables, station folders, grids |
| `provenance/` | what sits next to a file on disk: sidecars, derived copies, `hydromodpy.lock` |
| `registry/` | the DuckDB index of the cache (`data/cache.duckdb`); the files and their sidecars stay the truth |
| `managers/` | the bases the variable managers inherit: shared state and the `SOURCES` dispatch, the grid cache, the per-station cache, the user-file-only variables |
| `variables/` | one package per `[data.<name>]` section, all on the template below |
| `loading/` | `[data]` of the TOML to the variables it activates to the data loaded: `DataManagersConfig`, `DataPlanner`, `DataManagersRuntimeLoader`, `DataStore` |
| `workspace/` | the workspace data folder: scaffold and scan of custom files |
| `request/` | data asked for from outside a project: `DataRequest`, `run_request`, the `data-request` process |
| `cases/` | demonstrators driven by a TOML, with their data (golden tests, gallery) |

## Import rules

A subpackage imports only the subpackages its row of
`tests/unit/architecture/data_layout.yaml` allows, and
`tests/unit/architecture/test_package_layouts.py` checks every import: at module
level, inside a function, under `TYPE_CHECKING`, or as a dotted path in a
lazy-attribute table. Every subpackage may import `core`. Six more rules:

1. A variable never imports another variable.
2. Another layer of HydroModPy imports only the modules listed under `public`
   in `data_layout.yaml`. Managers, `common`, `schemas`, and the inside of
   `loading` and of the variables stay private.
3. A manager reaches its providers through its `SOURCES` table, never through
   an `if` on the source name.
4. No module uses a `_private` attribute of another. Ruff rule `SLF001`
   checks it.
5. The three modules that hold a `DataSource` class import geopandas, pandas,
   rasterio or requests inside their functions: looking a source up by name
   loads nothing heavy. `tests/unit/architecture/test_data_source_port_stands_alone.py`
   checks it.
6. One exception to the import rules: the source registry
   (`source/registry.py`) names the three built-in classes by a dotted path
   written as text and imports each on first use, so that a third-party plugin
   joins the same table.

## Template of a variable

```
variables/<v>/
├── __init__.py   imports only the config: validating a TOML loads no manager
├── config.py     <V>Config and <V>SourceConfig; the `source` field lists the allowed values
├── manager.py    VARIABLE_NAME, INTERNAL_UNIT, SOURCES
├── apis/         one module per network provider of the variable, if it has one
└── custom.py     only when loading the user's files takes real work
```

A manager maps each value a user may write in `source =` to the function that
fetches it:

```python
class HydrometryManager(BaseVariableManager):
    VARIABLE_NAME = "hydrometry"
    INTERNAL_UNIT = "m3/s"
    RECORD_VARIABLE = "discharge"
    SOURCES = {"hubeau": hubeau.fetch_for_config}
```

- `RECORD_VARIABLE` is optional. It names what a record carries when that
  differs from `VARIABLE_NAME`.
- `custom` is never in `SOURCES`. The base class loads the user's files through
  `load_custom`; a variable whose format takes real work overrides it or keeps
  a `custom.py`.
- A `SOURCES` function receives the validated config, the extent and a
  `SourceContext` (project extent, cache folder, section dates, nearest
  point). A grid: `fetch(cfg, *, bbox, period, context)`. Stations:
  `fetch(cfg, *, bbox, station_ids, start, end, context)`. The base class owns
  the cache: `BaseFieldManager` keeps grids, `BaseVariableManager` keeps
  chronicles per station and asks only for the missing periods.
- The `source` field stays a closed `Literal`; the JSON schema and the config
  reference publish it. `hydrography` is the exception: its sources resolve
  through the registry, plugins included.
- `tests/unit/data/test_the_variable_families_agree.py` ties the lists: the
  `source` values of each variable (but `custom`) are the keys of `SOURCES`, and
  each has an entry (licence, network hosts) in `hydromodpy/schema/sources.py`.

## The DataSource port

`source/port.py` holds the `DataSource` Protocol and its value types. A source
answers one question about one provider, conforms structurally (no base class)
and declares eight things about itself: `source_id`, `variables`, `payload_kind`
(`points`, `fields`, `features` or `files`), `extent_crs`, `selectors`
(`extent`, `station_ids`), `period_need` (`required` or `refused`), `hosts` (every
host it contacts) and `writes_out_dir`. `variables` belongs to the instance, the
other seven to the class.

An `Extent` is a bounding box **and** its CRS. `extent_for()` converts it into
the CRS the source declares, densifying the edges rather than transforming four
corners, because a projected box is not the image of its own corners. A box that
crosses the antimeridian is refused.

Three sources ship, the river networks that `[data.hydrography]` resolves through
the registry: `BdTopageSource`, `EuHydroSource` and `OsmSource`, on the shared
`FeatureSource` base (`variables/hydrography/apis/features.py`). A third-party
package adds a source by declaring a `DataSource` class on the
`hydromodpy.data.source` entry-point group. It is then nameable in a hydrography
section, and for any payload kind under the `installed` member of a data request.
`tests/contract/test_data_source_contract.py` compares each declaration with a
real fetch.

`source/registry.py` maps `source_id` to class. The in-tree sources are declared
once, as dotted paths in `_BUILTIN_PATHS`, and imported on first lookup.
`builtin_source_ids()` answers what this build ships, `list_source_ids()` what
this installation resolves. `source/permanence.py` names the one canonical
`permanence` column a source writes when it knows whether water flows all year.

## How data flows

During a run:

```
[data] of the TOML
  -> loading/config_schema.DataManagersConfig   validation
  -> loading/planner.DataPlanner.build()        asked-for and inferred variables
  -> loading/loader.DataManagersRuntimeLoader   simulation window, basin mask
  -> variables/<v>/manager.<V>Manager.load()    custom files, or SOURCES[source]
  -> contracts.LoadResult(points, fields, tables, warnings)
```

From outside a project, one engine (`request/engine.run_request`) serves a
`DataRequest`: `[data]` sections with the models of the TOML, an extent that
is exactly one of a box with its CRS, a vector mask or station codes, an
optional period, and plugin sources under `installed`. It writes one file per
variable and source, cut to the extent and period, beside a report
`request.json`. Three ways in:

| entry | output |
|---|---|
| `hmp data get request.json --out DIR`, or `hmp data get <variable> --bbox ... --crs ... --out DIR` | `DIR/` |
| `hmp process run data-request --job DIR` (or a step of `hmp process chain`) | a sealed job directory, one JSON document on stdout |
| `run_request(DataRequest(...), out_dir)` | a `RequestReport` |

From Python, without a project:

```python
from hydromodpy.data import DataStore

store = DataStore()  # no folder: in-memory index, nothing written
store = DataStore(data_root="cache/")  # a cache folder of your choice
result = store.load_variable("hydrometry", cfg)
```

## What `request/` holds

| module | answers |
|---|---|
| `model.py` | what is a request? `DataRequest`: the `[data]` sections with the models of the TOML, an extent that is exactly one of a box with its CRS, a vector mask (a file link, pinnable by `sha256`) or station codes, an optional period, and plugin sources under `installed`, whose options are bound against their constructor before anything runs |
| `engine.py` | `run_request` loads each section through its manager, over the extent written as a polygon mask in its own CRS. `hydrography` and the installed sources go through the source registry, never through the Whitebox manager. A source that fails loses its files and is listed with its error; the others keep theirs. An empty answer (a box at sea) is a success marked `"empty": true` |
| `artefacts.py` | each answer cut to the extent and period, whatever the cache held: chronicles in one Parquet table, grids in one NetCDF, rasters in GeoTIFF, vectors in one GeoPackage layer, tables in Parquet |
| `job.py` | the `data-request` declaration and its body: resolution and refusal before anything is written, a cache under `$TMPDIR` indexed in memory, the seal, the reuse short-circuit. A `custom` source is refused, and a failed variable fails the job |

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
  cells, not its footprint: a catchment mask is `1` on the catchment and nodata
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
- `hydromodpy.data.source.{DataSource, Extent, Period, FetchRequest, FetchResult,
  BdTopageSource, EuHydroSource, OsmSource}` and
  `hydromodpy.data.source.registry.{get, get_serving, register, list_source_ids,
  builtin_source_ids}`.
- `hydromodpy.data.request.job.{DATA_REQUEST, run}`.

## Layer neighbours

`data` imports `core`, `schema` and `spatial`
(`tests/unit/architecture/layer_matrix.yaml`). `config`, `simulation`,
`calibration`, `analysis`, `workflow`, `catalog`, `project`, `cli` and the root
facade import it, plus the documented `spatial` to `data` tolerance for the
optional hydrography fetch of site selection. `data` never imports `catalog`.

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
| a provider for an existing variable | a function in `variables/<v>/apis/<provider>.py` (or `common/clients/` when several variables share it), a key in the manager's `SOURCES`, a value in the `source` `Literal`, an entry in `schema/sources.py` |
| a plugin source, out of tree | a `DataSource` class declared on the `hydromodpy.data.source` entry-point group; see `docs/source/contribute/architecture/how-to/add-a-data-source.rst` |
| a variable | a package on the template above, a field of `DataManagersConfig`, a row of `VARIABLE_SPECS`; see `docs/source/contribute/architecture/how-to/add-a-data-variable.rst` |
| a user-file format | `ingest/` |
| an import rule | `tests/unit/architecture/data_layout.yaml` |
