# `hydromodpy/data`

Everything a run reads from outside: provider APIs, user files, their cache
and the typed records handed to the layers above. This file is the map of the
package: what each subpackage answers, the import rules, the template of a
variable, how data flows, and where to add what.

## Variables

Each `[data.<name>]` section of a project TOML is one variable. The single
list of the 25 sections is `VARIABLE_SPECS` in `loading/_dispatch.py`.

| family | variables | sources besides `custom` | manager base |
|---|---|---|---|
| grids (10) | `precipitation`, `etp`, `temperature`, `wind`, `humidity`, `radiation`, `soil_moisture`, `runoff`, `recharge`, `oceanic` | `sim2` (all but `oceanic`), `synthetic` (`recharge`), `shom` and `constant` (`oceanic`) | `BaseFieldManager` |
| stations (4) | `hydrometry`, `piezometry`, `water_quality`, `intermittency` | `hubeau` | `BaseVariableManager` |
| terrain and subsurface (3) | `dem`, `geology`, `hydrography` | `ign_geoplateforme_dem`; `brgm_1m`, `brgm_50k`; `bdtopage`, `euhydro`, `osm` | written by hand |
| lake chronicles (4) | `lake_inflow`, `lake_levels`, `lake_outflow`, `lake_withdrawal` | none | `BaseVariableManager` |
| user files (4) | `lake_abacus` (table), `lake_bathymetry` (raster), `lake_geometry` (vector), `substratum` (raster) | none | `BaseFileManager` |

## Subpackages

In dependency order, lowest first.

| subpackage | answers |
|---|---|
| `contracts/` | the records handed upward: `PointRecord`, `FieldRecord`, `TableRecord`, `LoadResult` |
| `schemas/` | pandera schemas of the input tables (stations, chronicles, abacus, lithology, DEM), each with its `validate()` |
| `source/` | the `DataSource` port (`port.py`) and the registry of sources, plugins included (`registry.py`) |
| `common/` | helpers with no variable config and no cache: HTTP, units, geometry, file naming, and the one mask loader (`source_extent.py`); `clients/` holds what several variables share: the SIM2 product table and download, the Hub'Eau station helpers |
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

## Where to add what

| to add | where |
|---|---|
| a provider for an existing variable | a function in `variables/<v>/apis/<provider>.py` (or `common/clients/` when several variables share it), a key in the manager's `SOURCES`, a value in the `source` `Literal`, an entry in `schema/sources.py` |
| a plugin source, out of tree | a `DataSource` class declared on the `hydromodpy.data.source` entry-point group; see `docs/source/architecture/how-to/add-a-data-source.rst` |
| a variable | a package on the template above, a field of `DataManagersConfig`, a row of `VARIABLE_SPECS`; see `docs/source/architecture/how-to/add-a-data-variable.rst` |
| a user-file format | `ingest/` |
| an import rule | `tests/unit/architecture/data_layout.yaml` |
