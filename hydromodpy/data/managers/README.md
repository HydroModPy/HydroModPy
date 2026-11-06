# data/managers

The base classes that every variable manager and every variable config inherit from. A variable
under `variables/` writes only what is its own: its provider calls, its units, its extra fields.

## Which base for which variable

| base | for | variables |
|---|---|---|
| `BaseVariableManager` | stations: one chronicle per station, cached per station | `hydrometry`, `piezometry`, `water_quality`, `intermittency`, the four lake chronicles |
| `BaseFieldManager` | grids: one NetCDF or GeoTIFF per box and period, cached per box | the SIM2 and Explore2 variables, `recharge`, `oceanic` |
| `BaseFileManager` | variables read only from the user's own file | `lake_abacus`, `lake_geometry`, and the rasters `lake_bathymetry`, `substratum`, `soil_capacity`, `layer_base` |

`RasterFileManager` is the file base of the raster variables. `dem`, `geology`, `hydrography`
and `crossings` are written by hand and inherit only `SourceTable`, the `SOURCES` dispatch of
`base_manager_common.py`.

## The folder map

```text
managers/
├── base_manager_common.py    state shared by all managers and the SOURCES dispatch
├── base_manager_variable.py  the station manager: custom files, API fetch, cache, frozen mode
├── base_manager_field.py     the grid manager: custom grids, SIM2, mask and clip
├── base_manager_file.py      the user-file manager
├── base_config.py            BaseVariableConfig: the date window every [data.<name>] section has
└── timeseries_config.py      the CSV column names, station selection and cache options of the
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

- `custom` is never in `SOURCES`. The base class loads the user's files itself.
- A manager imports no other manager. Shared code goes to `common/` or here.
- A manager does not read the project geometry. The caller gives it an extent or a mask.

## Changing the code

The tests are in `tests/unit/data/managers/`.
