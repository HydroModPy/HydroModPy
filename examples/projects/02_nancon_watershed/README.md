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
  discharge (KGE), Sy/Ss frozen. Documents the calibration TOML shape, but
  every trial currently crashes: `ObservableNotAvailableError: No DRAIN
  component in CBC`. The MODFLOW-NWT package builder never sets `ipakcb` on
  the RCH/DRN packages
  (`hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py`), so no backend
  ever writes their cell-by-cell budget, independent of
  `[simulation.results.budget] spatial_fields`. `water_budget`, `hydrograph`
  and `recharge_map` are dropped from `project.toml`'s figure list for the
  same reason.
- `run_overview_all_apis.toml` - standalone `overview` workflow, every data
  family loaded from a live API except the DEM (local file, IGN's WCS
  currently answers 403). Needs internet; the first run downloads and caches
  under `examples/data/`. Runtime unmeasured here (documented as several
  minutes).
- `run_sweep_sy.toml` - design draft for a `[sweep]` workflow. `hmp config
  check` rejects it (`Unknown top-level TOML section(s): sweep`): the
  `sweep` dispatcher does not exist yet. Kept as a specification, not a
  runnable command.
- `run_transient_prototype.py.draft` - pre-catalog Sy sweep script, not
  ported to the current `hmp.Project` API. Use `run_cellular.py` as the
  template for a Python-driven loop instead.
