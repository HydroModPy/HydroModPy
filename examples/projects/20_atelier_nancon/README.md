# 20 - Nancon workshop

Nancon catchment (Brittany, EPSG:2154), 64.6 km2 delineated from a 25 m regional
DEM. A single-layer, 30 m constant-thickness aquifer with diffuse recharge and a
Cauchy drainage condition on top, solved either by MODFLOW-NWT or MODFLOW 6,
steady or monthly transient. This is workshop material: ten TOML configs that
build on one shared `project.toml` through inheritance and overlays, plus five
Python scripts that drive the same project through the `hydromodpy` API instead
of the CLI.

## Run

```bash
# steady state, one solver each, then compare them
hmp run examples/projects/20_atelier_nancon/sim_steady_nwt.toml
hmp run examples/projects/20_atelier_nancon/sim_steady_mf6.toml
python examples/projects/20_atelier_nancon/compare_solvers.py

# three years, monthly, MODFLOW-NWT
hmp run examples/projects/20_atelier_nancon/sim_transient_nwt.toml
python examples/projects/20_atelier_nancon/read_results.py

# add a pumping well without editing the base run
hmp run examples/projects/20_atelier_nancon/sim_steady_nwt.toml \
  --overlay examples/projects/20_atelier_nancon/overlay_well.toml

# data-only pass: no solver, one panel per variable
hmp run examples/projects/20_atelier_nancon/overview.toml

# Optuna calibration of K against a head target
hmp run examples/projects/20_atelier_nancon/calibration_head.toml
hmp report render --open
```

Measured on this checkout: `sim_steady_nwt.toml` ~24 s, `sim_steady_mf6.toml`
~48 s (both include the BD Topage WFS fetch), `sim_transient_nwt.toml`
(36 monthly steps) ~38 s, `overview.toml` ~39 s (includes a live Hub'Eau
fetch), `calibration_head.toml` at its shipped `max_iter = 15` is unmeasured
here but one iteration takes ~2 s. `sim_mf6_unstructured.toml` builds a
triangulated DISV mesh with gmsh first; its runtime is unmeasured.

`lazy_pipeline.py` and `explore_catalog.py` drive the same project through
`hydromodpy.Project` and `hydromodpy.open()` instead of the CLI; both run in a
few seconds once `sim_transient_nwt.toml` has produced a catalog to read.

## Data

Shared inputs under `examples/data/`, resolved by bare filename from
`[geographic]` and `[data]`:

| Source | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | regional DEM, catchment delineation |
| BRGM 1:1M, provider `brgm_1m` | geology | background lithology |
| BD Topage, provider `bdtopage` | hydrography | reference stream network |
| `hydrometry/*_EX04_*` | hydrometry | observed discharge, 2000-2002 |
| `recharge/*_EX04_*` | recharge | monthly recharge forcing |
| `runoff/*_EX04_*` | runoff | surface runoff added to simulated discharge |
| ONDE stations, provider `hubeau` | intermittency | live fetch, `overview.toml` only |

`project.toml` also declares an `etp` source
(`etp_sim2_5347fa22_20000101_20251231.nc`) for the EVT package, but that file
is not present under `examples/data/etp/` in this checkout: every run logs a
warning and continues with ETP skipped.

## What it shows

`project.toml` carries the geography, data sources and flow defaults; every
`sim_*.toml` and `calibration_*.toml` sets `base_config = "project.toml"` and
overrides only what changes (regime, solver, name). `sim_steady_nwt_well.toml`
chains a second level on top of `sim_steady_nwt.toml` to show inheritance
depth; `overlay_well.toml` shows the same well added at run time with
`--overlay` instead. Both add a run named `steady_nwt` on top of an existing
one: HydroModPy trashes the old run and versions the new one (`steady_nwt.v2`)
rather than colliding.

`sim_mf6_unstructured.toml` swaps the regular grid for a gmsh triangulation
refined along the stream network (`[mesh_catchment]`), the DISV case that only
MODFLOW 6 can solve.

MODFLOW-NWT in this checkout does not extract a per-cell DRAIN budget
component: `water_budget`, `hydrograph_sim_obs` and `recharge_map` are skipped
on NWT runs, and `calibration_discharge.toml` (KGE against simulated
discharge) fails every trial for the same reason. MODFLOW 6 is unaffected
(`sim_steady_mf6.toml` renders all six configured figures); `read_results.py`
plots the mass-balance `total_in` series instead of a discharge timeseries so
it works with either solver. `stream_matching.py` needs the same missing DRAIN
field and does not run today.
