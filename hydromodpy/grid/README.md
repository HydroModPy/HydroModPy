# Grid

`hydromodpy/grid/` contains utilities used to build model grids for HydroModPy.

## Directory Map

```text
hydromodpy/grid/
|-- sgrid_generation.py
|-- sgrid_config.py
|-- sgrid_config.toml
|-- tgrid_generation.py
|-- __init__.py
`-- README.md
```

## What This Module Does

### Spatial grid (`SGrid_Generation`)

`SGrid_Generation` builds a FloPy `StructuredGrid` from:

- one top raster (DEM),
- one bottom definition method,
- one vertical layering strategy.

It is used by the MODFLOW workflow in
`hydromodpy/modeling/modflow.py` to feed `flopy.modflow.ModflowDis`.

Supported bottom generation methods:

- `filepath` (from `bot_path` raster file),
- `raster` (from `bot_raster` array),
- `constant_thickness` (from `thick`),
- `constant_altitude` (from `zbot`).

Supported layering methods:

- `constant` (`nlay`),
- `decay` (`nlay`, `lay_decay`),
- `list` (`lay_proportions`).

Current limitation:

- only `sgrid_type = "structured"` is implemented,
- `unstructured` and `vertex` are placeholders.
- TOML interface currently supports `genmtd_bot` in
  `filepath|constant_thickness|constant_altitude`.

### Temporal grid (`TGrid_Generation`)

`TGrid_Generation` is a skeleton for temporal discretization settings.
It defines parameters such as:

- `itmuni`, `sim_state`,
- `nper`, `lenper`,
- chronology file options (`chron_path`, `chron_dateformat`, ...).

Current limitation:

- `run()` dispatches to `_create_synthetic_regular_tgrid` and
  `_create_tgrid_from_chron`, but those methods are not implemented in
  `tgrid_generation.py` yet.

## Minimal Example (Spatial Grid)

```python
from hydromodpy.grid.sgrid_generation import SGrid_Generation

grid = SGrid_Generation()
grid.top_path = "path/to/top_dem.tif"
grid.crs = "EPSG:2154"
grid.nodata = -9999

grid.genmtd_bot = "constant_thickness"
grid.thick = 100.0

grid.genmtd_lay = "constant"
grid.nlay = 3

sgrid = grid.run()

print(sgrid.nlay, sgrid.nrow, sgrid.ncol)
```

## TOML + Pydantic Interface (Spatial Grid)

You can configure `SGrid_Generation` directly from TOML:

```python
from hydromodpy.grid.sgrid_generation import SGrid_Generation

sgrid = SGrid_Generation.from_toml("hydromodpy/grid/sgrid_config.toml").run()
print(sgrid.nlay, sgrid.nrow, sgrid.ncol)
```

Associated files:

- `hydromodpy/grid/sgrid_config.py`: Pydantic schema + TOML loading helpers.
- `hydromodpy/grid/sgrid_config.toml`: ready-to-run configuration example.

## Returned Object

`SGrid_Generation.run()` returns a FloPy `StructuredGrid` exposing standard
attributes used downstream by MODFLOW setup:

- `lenuni`, `nlay`, `nrow`, `ncol`,
- `delr`, `delc`,
- `top`, `botm`,
- offsets and extent metadata.
