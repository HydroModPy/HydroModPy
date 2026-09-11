# 19 - Cheze reservoir

The Cheze reservoir (Plelan-le-Grand, Brittany, EPSG:2154), a managed dam on a
1.58 km2 lake. The reservoir is a native MODFLOW 6 **LAK** package (abacus
stage-volume-area, bathymetry-carved bed, WEIR spillway, dam cutoff wall as an
HFB barrier), fed by its own catchment through a delineated **SFR** network:
reaches capture aquifer baseflow, hillslope drainage converges to the nearest
reach, and the terminal reaches hand the accumulated flow to the lake through
MVR. Four calibration configs fit the aquifer and lake parameters against the
observed reservoir level.

## Run

```bash
# Weekly 2019 demo: LAK with active-littoral marnage (bathymetry-carved bed,
# exposed shoreline runoff) + the SFR feed. Needs the mf6api extra, below.
hmp run examples/projects/19_cheze_reservoir/project.toml
python examples/projects/19_cheze_reservoir/run_cheze_reservoir.py

# Full daily chronicle 2007-2025, fixed-area lake (no marnage, no mf6api).
hmp run examples/projects/19_cheze_reservoir/project_chronicle.toml
python examples/projects/19_cheze_reservoir/compare_chronicle.py   # obs-vs-sim scores + figure

# Two-lake variant: reservoir + Pont Musard forebay, reciprocal sill weirs.
hmp run examples/projects/19_cheze_reservoir/project_preretenue.toml

# Lake-level calibration (KGE on bedleak / K / Sy against the observed level).
hmp calibrate examples/projects/19_cheze_reservoir/cheze_calibration_level.toml
hmp report render -w examples/projects/19_cheze_reservoir --open
```

`project.toml` and `project_preretenue.toml` carve an active-littoral lake bed
(`exposed_band_runoff = true`), which runs on the in-process MF6 BMI API and
needs `pip install hydromodpy[mf6api]` (modflowapi + xmipy). Without it, the
mesh and model build in about 55 s and the run stops at `run_solver` with
`ImportError: run_mf6_api requires the optional 'modflowapi' package`.
`project_chronicle.toml` and the four calibration configs use the plain
subprocess mf6 runner and do not need that extra; their SIM2 fetch and solve
are network- and duration-dependent (the chronicle run is ~6940 daily stress
periods), unmeasured here.

## Data

| Family | File | Content |
|---|---|---|
| `dem` | `dem/DEM_armorican_massif.tif` | shared regional DEM |
| `lake_geometry` | `lake_geometry/reservoir_cheze.gpkg`, `lakes_cheze_preretenue.gpkg` | reservoir / two-lake footprint polygons |
| `lake_abacus` | `lake_abacus/reservoir_cheze.csv`, `preretenue_cheze.csv` | stage-volume-area table, one per lake |
| `lake_bathymetry` | `lake_bathymetry/reservoir_cheze.tif`, `bathy_preretenue_cheze.tif` | bed raster carved into the LAK bed |
| `lake_inflow` | `lake_inflow/` | managed transfers into the lake (Meu + Canut), m3/day, 2007-2026 |
| `lake_withdrawal` | `lake_withdrawal/` | managed abstraction + restitution leaving the lake, m3/day, 2007-2026 |
| `lake_levels` | `lake_levels/` | observed reservoir level, m NGF, 2007-2026; the calibration target |
| `cutoff_wall` | `cutoff_wall/injection_cheze.gpkg` | grout-curtain axis under the dam, modeled as an HFB barrier |

`recharge`, `precipitation`, `etp` and `runoff` are fetched live from the SIM2
Meteo-France API (`source = "sim2"`); a network connection or a warm SIM2
cache is required.

## What it shows

- The reservoir's water balance closes through three paths, all inside the
  MF6 budget: SFR baseflow capture on the reach beds, hillslope DRN discharge
  converging to the nearest reach (`route_drainage`), and SIM2 catchment
  runoff routed along the network. All three arrive at the lake through MVR,
  not as a direct forcing.
- `project.toml` carves the real lake bed from bathymetry: cells stay active
  in the marnage band, MF6 toggles recharge/ET per cell as the shoreline
  moves, and the exposed band sheds its own runoff to the lake.
- `project_preretenue.toml` adds a second LAK lake (Pont Musard forebay)
  linked to the reservoir by a pair of reciprocal sill weirs at the same
  crest, so the two levels equalize above the sill and stay independent
  below it.
- The four calibration configs span one smoke test
  (`cheze_calib_apitest.toml`, 4 trials), two single-lake production runs on
  the chronicle base (`cheze_calibration_level.toml`, one year;
  `cheze_calibration_chronicle.toml`, 2010-2020 on 10-12 cores), and one
  two-lake production run (`cheze_calibration_preretenue.toml`, 2010-2020,
  API-parallel). All target `lake_level` with KGE.
