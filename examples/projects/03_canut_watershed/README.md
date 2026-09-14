# 03 - Canut watershed

Canut catchment (Brittany, EPSG:2154), delineated from the regional DEM by
outlet snapping. Steady-state groundwater flow solved with MODFLOW 6, with
geology from BRGM and the stream network from BD Topage.

`hydromodpy/config/hydromodpy_config.py` points at this project's
`project.toml` as the reference example of a full expert configuration.

## Run

```bash
hmp run examples/projects/03_canut_watershed/project.toml
python examples/projects/03_canut_watershed/run_steady_prototype.py
```

`config_expert_generated.toml` is the fully expanded configuration, written by
`hmp config` from the project file. It is there to be read, not to be run.

## Data

Shared inputs under `examples/data/`, resolved by file name.

| Source | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | regional 75 m DEM |
| BRGM 1M | geology | aquifer layering |
| BD Topage | hydrography | observed stream network |
