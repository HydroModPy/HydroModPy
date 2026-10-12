# 11 - Run from scratch, without plots

Canut catchment delineated on the fly from the regional DEM, **steady-state**
flow with **MODFLOW 6** over a three-layer 50 m aquifer, with particle
tracking. Nothing is drawn: the example exists for the artefacts it leaves
behind, which is what a machine with no screen needs.

## Run

```bash
hmp run examples/projects/11_run_from_scratch_without_plots/project.toml
hmp catalog show canut_headless_mf6
```

Runtime: about 20 s, most of it in the delineation over the regional DEM
(4964 x 4773 cells to walk before the catchment is found).

## What a run without figures has to declare

Nothing. The run keeps the whole per-cell budget and every derived field is
rebuilt on read from the stored head and budget, so a headless run needs no `[simulation.results]`
key. Everything can be read again later, with `hmp export`, `hmp viz show` or
the Python API (below).

## Outputs

| Path | Contents |
|---|---|
| `runs/canut_headless_mf6/fields.zarr` | gridded fields (Zarr 3) |
| `runs/canut_headless_mf6/tables.parquet/` | series, budgets, metrics (Parquet) |
| `share/canut_headless_mf6/fields.nc` | NetCDF export of the fields |
| `share/canut_headless_mf6/*.csv` | catchment series as CSV |
| `.hmp/index.duckdb` | catalog index, rebuildable |

Read it back without replaying:

```python
import hydromodpy as hmp

with hmp.open("examples/projects/11_run_from_scratch_without_plots") as catalog:
    run = catalog.latest()
    print(run.parameters)
    depth = hmp.read(run, "watertable_depth", time=0)
```

## Differences with the legacy example

| Point | legacy | here |
|---|---|---|
| Solver | MODFLOW-NWT + MODPATH6 | MODFLOW 6 + PRT |
| Tracking direction | backward, from the seepage areas | forward, from the domain |
| Outputs | one `.tif` per variable per timestep + NetCDF | Zarr + Parquet + NetCDF export |

The legacy run wrote one GeoTIFF per variable and per timestep into a tree of
folders; storage is now a single Zarr store and GeoTIFFs are an export on
demand.
