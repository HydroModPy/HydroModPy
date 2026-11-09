# data/families

The base classes that every variable and every variable config inherit from. A variable
under `variables/` writes only what is its own: its provider calls, its units, its extra fields.

## Which base for which variable

| base | for | variables |
|---|---|---|
| `StationVariable` | stations: one chronicle per station, cached per station | `hydrometry`, `piezometry`, `water_quality`, `intermittency`, the four lake chronicles |
| `GridVariable` | grids: one NetCDF or GeoTIFF per box and period, cached per box | the SIM2 and Explore2 variables, `recharge`, `oceanic` |
| `FileVariable` | variables read only from the user's own file | `lake_abacus`, `lake_geometry`, and the rasters `lake_bathymetry`, `substratum`, `soil_capacity`, `layer_base` |

`RasterFileVariable` is the file base of the raster variables. `dem`, `geology`, `hydrography`
and `crossings` are written by hand and inherit only `SourceTable`, the `SOURCES` dispatch of
`common.py`.

## The folder map

```text
families/
├── common.py            state shared by all variables and the SOURCES dispatch
├── stations.py          stations: API fetch, one chronicle per station under a lock, frozen mode
├── grids.py             grids: one NetCDF per box and period, its sidecar, the smaller grids it replaces
├── files.py             user files: read where they lie, a copy goes under `blobs/`, never a row of the cache
├── base_config.py       BaseVariableConfig: the date window every [data.<name>] section has
└── timeseries_config.py the CSV column names, station selection and cache options of the
                         chronicle configs, and the two source bases of the twin variables
```

## The twin configs

Five SIM2 grid variables (`temperature`, `humidity`, `runoff`, `soil_moisture`, `wind`) share
`Sim2GridSourceConfig`. The four lake chronicles share `LakeChronicleSourceConfig`. A subclass
declares its own `path` field, because the `role` of its `InputFile` is the variable name and that
role is part of the TOML schema. The JSON schema of `[data]` is pinned by
`tests/unit/data/test_the_data_surfaces_hold_still.py`: a moved field or a changed description
changes its digest.

## Rules

- `file` is never in `SOURCES`. The base class loads the user's files itself, and a user file is no row of the cache.
- A fetched file is written beside its name and renamed in place, then its sidecar is written through `CacheIndex.record`. A station chronicle is written inside `index.chronicle(folder, stem)`, which holds the lock of that station, and the old file of the station leaves in the same lock.
- A variable that downloads needs the data folder of the call. Without one it is refused, and nothing is written under the cache of the user.
- A variable imports no other variable. Shared code goes to `common/` or here.
- A variable does not read the project geometry. The caller gives it an extent or a mask.

## Changing the code

The tests are in `tests/unit/data/families/`.
