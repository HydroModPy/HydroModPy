# HydroModPy - examples

`examples/` is itself a **HydroModPy workspace**: the projects live under
[`projects/`](projects/) and share their inputs through [`data/`](data/), which
the workspace path resolution reaches by bare filename.

## Prerequisites

```bash
micromamba activate hmp_dev
pip install -e .
hmp install-binaries     # MODFLOW 6, MODFLOW-NWT, MODPATH, MT3D-USGS
hmp doctor               # environment diagnosis
```

## The ported suite

Twelve examples, ported from the v1 example scripts of tag `v1.0.0`, all
solved with **MODFLOW 6**. Each folder is self-contained: a `README.md`, a
`project.toml`, and the scripts the case needs.

| # | Folder | Theme | Regime | Runtime |
|---|---|---|---|---|
| 00 | [`00_quick_test_of_wide_hydromodpy_capabilities`](projects/00_quick_test_of_wide_hydromodpy_capabilities/) | wide slice of the toolbox: Aber catchment, pumping wells, particles | monthly transient | ~25 s |
| 01 | [`01_simplified_example_presented_in_the_paper`](projects/01_simplified_example_presented_in_the_paper/) | the paper walkthrough: Canut, depth-decaying five-layer aquifer | steady | ~35 s |
| 02 | [`02_basic_features_and_overview_of_possibilities`](projects/02_basic_features_and_overview_of_possibilities/) | the whole chain on a conceptual domain, fully offline | steady | ~10 s |
| 03 | [`03_hydrographic_network_in_steady_state`](projects/03_hydrographic_network_in_steady_state/) | observed, delineated and simulated stream networks side by side | steady | ~45 s |
| 04 | [`04_streamflow_intermittence_in_transient`](projects/04_streamflow_intermittence_in_transient/) | seepage expanding and contracting with the seasons, Nancon | monthly transient | ~1 min |
| 05 | [`05_piezometry_in_a_heterogeneous_coastal_aquifer`](projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/) | coastal water table between a recharge mound and the sea | steady | ~5 s |
| 06 | [`06_particle_tracking_and_residence_times`](projects/06_particle_tracking_and_residence_times/) | where the seepage water comes from, and how old it is | steady + PRT | ~5 s |
| 07 | [`07_analytical_solution_for_streamflow_recession`](projects/07_analytical_solution_for_streamflow_recession/) | recession against the late-time Boussinesq 1904 solution | transient | ~2 s |
| 08 | [`08_exponential_distribution_of_residence_times`](projects/08_exponential_distribution_of_residence_times/) | travel times against the exponential law of a well-mixed store | steady + PRT | ~5 s |
| 09 | [`09_transport_model_for_an_agricultural_catchment`](projects/09_transport_model_for_an_agricultural_catchment/) | nitrate through an agricultural headwater, MODFLOW 6 GWT | monthly transient | ~8 min |
| 10 | [`10_coupling_with_land_surface_model_pyhelp`](projects/10_coupling_with_land_surface_model_pyhelp/) | recharge computed by PyHELP, then K found from the network | steady + calibration | ~3 min |
| 11 | [`11_run_from_scratch_without_plots`](projects/11_run_from_scratch_without_plots/) | headless run: artefacts only, no figure | steady + PRT | ~25 s |

Run any of them the same way:

```bash
hmp run examples/projects/<folder>/project.toml
```

### Suggested reading order

1. **02** - the smallest complete `project.toml`, one second, no download.
2. **01** - the paper case: delineation, a layered aquifer, particle tracks.
3. **03** - what a water table does to a stream network.
4. **04** - the same question in time rather than in space.
5. **07** and **08** - two synthetic cases where the answer is known in closed
   form, so the solver can be checked rather than illustrated.
6. **09** and **10** - the two couplings: a solute, and a land surface model.

## Where a run puts its results

Nothing is written next to `project.toml`. A run leaves:

```
projects/<name>/
├── project.toml
├── hydromodpy.lock           # what the run resolved, for a replay
├── runs/<run name>/          # fields.zarr, tables.parquet, figures/, config.toml
├── share/<run name>/         # exports asked for under [export]
└── .hmp/index.duckdb         # catalog index, rebuildable by `hmp catalog reindex`
```

Disk is the truth and the index is derived: `hmp catalog reindex` rebuilds the
DuckDB from the run directories, and a deleted `.hmp/` costs nothing.

## Data

`data/` is organised by variable family, which is what a bare filename in a
TOML resolves against: `path = "DEM_nancon_25m.tif"` reads
`data/dem/DEM_nancon_25m.tif`.

| Family | Holds |
|---|---|
| `dem/` | elevation rasters |
| `hydrography/` | observed stream networks |
| `recharge/`, `runoff/`, `etp/`, `precipitation/`, `temperature/` | forcings |
| `hydrometry/`, `piezometry/`, `water_quality/`, `intermittency/` | observations |
| `geology/`, `masks/`, `watershed_polygon/`, `wells/` | context layers |
| `pyhelp/` | land-surface model inputs, consumed by a script rather than a TOML |

Provider caches (`bdtopage_*.gpkg`, `*_sim2_*.nc`, `*_hubeau_*.csv`) are
regenerated on demand and stay out of version control.

## Legacy scripts

The v1 example scripts the suite above was ported from, with their original
data, live in the history under tag `v1.0.0`, folder `examples/`, also at
<https://github.com/HydroModPy/HydroModPy/tree/v1.0.0/examples>. They are not
runnable against the current API. Each ported example states in its own README what it changed
and why.

## Other projects

`projects/` also carries development and gallery projects that are not part of
this suite. They follow their own conventions and are not covered here.
