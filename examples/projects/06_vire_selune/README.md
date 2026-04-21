# Vire / Selune outlets

This example shows how to start from two outlet coordinates in EPSG:2154 and
build:

1. A light watershed overview to confirm the available data.
2. Simple transient reference runs.
3. A first steady-state MODFLOW 6 irregular setup with conformal
   geology+rivers meshes.

Validated outlets:

- `Vire`: `x=400866.1983`, `y=6923974.693`
- `Selune`: `x=379541.3716`, `y=6845659.878`

Quick checks done from this repository:

- both outlets are covered by `examples/data/dem/DEM_armorican_massif.tif`
- both watersheds can be delineated with `catch_def = "from_outlet_coord"`
- indicative delineated areas are about `1258 km2` for Vire and `367 km2`
  for Selune

The example mixes local and API-backed inputs:

- local DEM: `examples/data/dem/DEM_armorican_massif.tif`
- local geology: BRGM 1:1M map bundled in `examples/data/geology/`
- API hydrography: `bdtopage`
- API hydrometry: `hubeau` in overview configs
- API recharge: `sim2` in transient simulation configs
- synthetic recharge: constant annual placeholder in the steady configs
  (`220 mm/an`, injected internally as annual-average `mm/day`)

## Run the watershed overview

```bash
hmp run overview_vire.toml
hmp run overview_selune.toml
```

## Run the simplified transient flow simulations

```bash
hmp run run_vire_nwt.toml
hmp run run_selune_nwt.toml
```

## Run the steady conformal irregular simulations

```bash
hmp run run_vire_mf6_irregular_steady.toml
hmp run run_selune_mf6_irregular_steady.toml
```

Notes:

- the first run may download data from BD Topage, Hub'Eau, and SIM2
- the simulation setup is intentionally simple: homogeneous parameters,
  drainage top boundary, constant aquifer thickness, transient recharge
- the steady runs use a constant synthetic recharge of `220 mm/an`
- the permanent `K` field is heterogeneous by geology and read from
  `examples/data/geology/geology_K_dummy_demo.csv`
- this CSV is the repository demonstration transfer table bundled with the
  BRGM 1M geology and is explicitly marked `dummy_demo_not_for_scientific_use`
- the steady irregular runs activate `mesh_catchment` with
  `constraints_mode = "geology_rivers"` so the generated mesh follows both
  river lines and geology interfaces
- if you want gauging constraints, start from the overview outputs and then
  pin the preferred hydrometry station ids in a derived config
