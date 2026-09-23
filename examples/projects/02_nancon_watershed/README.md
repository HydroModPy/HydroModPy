# 02 - Nancon watershed

Nancon catchment (Brittany, EPSG:2154), same DEM and outlet as the curated
`04_streamflow_intermittence_in_transient`. This example solves the same
transient window (2000-2002, monthly steps) with **MODFLOW-NWT** instead of
MODFLOW 6, and adds what 04 does not: an Optuna calibration of K against
observed discharge, an `overview` workflow that pulls its data live from
BRGM/BD TOPAGE/Hub'Eau/SIM2, and both `hmp run` and Python-API entry points
for the same base config.

## Run

```bash
hmp run examples/projects/02_nancon_watershed/run_transient_nwt.toml
hmp run examples/projects/02_nancon_watershed/run_hydrographic_network_comparison.toml
hmp config check examples/projects/02_nancon_watershed/<file>.toml  # validate without running
hmp viz gallery examples/projects/02_nancon_watershed/run_transient_nwt.toml
python examples/projects/02_nancon_watershed/run_full_python.py    # same run, Python API
python examples/projects/02_nancon_watershed/run_cellular.py       # lazy Project, phase by phase
```

`run_transient_nwt.toml` and `run_full_python.py`: ~45 s (36 steps, 27004
cells, 8 figures). `run_hydrographic_network_comparison.toml`: ~44 s, 5
figures. `run_cellular.py`: ~44 s; this project has no `[mesh_catchment]`
block, so its mesh-size loop only runs the default size.

## Data

| Source | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | regional 75 m DEM |
| BD TOPAGE, provider `bdtopage` | hydrography | observed stream network |
| BRGM 1:1M, provider `brgm_1m` | geology | background lithology |
| `hydrometry/` | hydrometry | observed discharge, used by the calibration |
| `recharge/` (station `EX04`) | recharge | monthly recharge forcing |
| `runoff/` (station `EX04`) | runoff | monthly runoff, added to simulated baseflow |

`project.toml` no longer loads an `etp` source: the shipped SIM2 sample for
this 2000-2002 window was removed from the repo. `run_overview_all_apis.toml`
pulls ETP live from the SIM2 API instead, so it does not need that file.

## Other entries

- `run_calibration_k.toml` - Optuna calibration of K against observed
  discharge (KGE), Sy/Ss frozen, `max_iter = 3`. `hmp calibrate
  run_calibration_k.toml` completes its three trials (KGE 0.13, 0.20, 0.18,
  measured 2026-09-24) and promotes the best one to `runs/optuna_iter_0001`.
  The earlier `No DRAIN component in CBC` crash came from reading the
  single-precision NWT budget as double, fixed in b8da0ca4f; the RCH and DRN
  budgets were always written, since `ModflowOc.reset_budgetunit` routes
  every package to the `.cbc` unit. `water_budget`, `hydrograph` and
  `recharge_map` stay off `project.toml`'s figure list: dropped under that
  wrong diagnosis, not re-checked since.
- `run_overview_all_apis.toml` - standalone `overview` workflow, every data
  family loaded from a live API except the DEM (local file, IGN's WCS
  currently answers 403). Needs internet; the first run downloads and caches
  under `examples/data/`. Runtime unmeasured here (documented as several
  minutes).
