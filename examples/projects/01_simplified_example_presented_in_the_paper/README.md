# 01 - Simplified example presented in the paper

Canut catchment (Brittany, EPSG:2154), extracted from the regional 75 m DEM
by outlet snapping. **Steady-state** groundwater flow, five layers that
thicken with depth, hydraulic conductivity and storage **decaying
exponentially with depth**, solved with **MODFLOW 6**, followed by particle
tracking.

This is the paper's running example: delineation, a layered aquifer with a
depth profile, and residence-time trajectories.

## Run

```bash
hmp run examples/projects/01_simplified_example_presented_in_the_paper/project.toml

# residence times from the trajectories, via the Python API
python examples/projects/01_simplified_example_presented_in_the_paper/run_manual.py

hmp viz gallery examples/projects/01_simplified_example_presented_in_the_paper/project.toml
```

Runtime: about 4 s (catchment ~9300 cells, 5 layers, 300 particles).

## Data

| File | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | regional 75 m DEM (covers the Canut) |
| synthetic recharge | recharge | steady-state average recharge, 0.96 mm/d (350 mm/year) |

## Depth profile

Surface conductivity (2e-5 m/s) decays as `exp(-depth / 20 m)`: about half
at 14 m, a floor at 1e-3 of the surface value. This is the signature of a
fractured bedrock aquifer (conductive weathered zone at the surface,
impermeable sound bedrock at depth). Expressed with
`[flow.param.K.field_vertical_profile]` mode `exponential`.

## Figures

| Figure | What it shows |
|---|---|
| `watershed_id_card` | catchment identity card |
| `mesh_map` | solver grid colored by topography |
| `piezometric_map` | watertable elevation |
| `watertable_depth_map` | watertable depth + seepage |
| `seepage_map` | seepage zones |
| `particle_tracks` | tracks colored by travel time |
| `cross_section` | topography / watertable / 5 thickening layers cross section |
| `simulated_active_network` | active draining cells |
| `water_budget` | budget per component |

## Particle tracking: forward

MODFLOW 6 PRT only tracks particles downstream: they are released over the
domain and end where the watertable outcrops, which gives recharge to
seepage residence times. The legacy script tracked backward from the
seepage zones; see example 00 for the switch to NWT + MODPATH if backward
tracking is needed.

`run_manual.py` reads the trajectories and summarizes the residence-time
distribution (median ~1 year, p90 ~7 years for this parameter set).

## Not ported from the legacy script

The interactive 3D visualization and the clickable cross section from the
original script are inherently interactive; they are not part of the
registry's static figures. The observed discharge signature (interannual
Q/A) and the geology maps belong to the `overview` workflow (see examples
04 and 05 for data).
