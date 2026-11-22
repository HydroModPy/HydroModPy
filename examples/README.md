# HydroModPy - examples

`examples/` is itself a **HydroModPy workspace**: the projects live under
[`projects/`](projects/) and share their inputs through [`data/`](data/), where
a TOML names a file with `workspace:<name>`.

## Prerequisites

```bash
micromamba activate hmp_dev
pip install -e .
hmp install-binaries     # MODFLOW 6, MODFLOW-NWT, MODPATH, MT3D-USGS
hmp doctor               # environment diagnosis
```

## The suite

The twelve examples of HydroModPy version 1, tag `v1.0.0`, remade for this version and all
solved with MODFLOW 6. Each folder holds a `project.toml`, a Python script that plays it step
by step in `hmp.Lab` and draws or prints what each step built, and a `README.md`.

| # | Folder | Theme | Regime | Run |
|---|---|---|---|---|
| 00 | [`00_quick_test_of_wide_hydromodpy_capabilities`](projects/00_quick_test_of_wide_hydromodpy_capabilities/) | Aber catchment, two pumping wells, particle tracks | monthly transient + PRT | ~5 s |
| 01 | [`01_simplified_example_presented_in_the_paper`](projects/01_simplified_example_presented_in_the_paper/) | the case of the paper: Canut, five layers, K and Sy falling with depth, particle tracks | steady + PRT | ~1 min |
| 02 | [`02_basic_features_and_overview_of_possibilities`](projects/02_basic_features_and_overview_of_possibilities/) | a conceptual relief taken whole: recharge per cell, base under sea level, K by depth | steady + PRT | ~25 s |
| 03 | [`03_hydrographic_network_in_steady_state`](projects/03_hydrographic_network_in_steady_state/) | the network a water table feeds, Canut, ten values of K solved in the lab | steady | ~35 s |
| 04 | [`04_streamflow_intermittence_in_transient`](projects/04_streamflow_intermittence_in_transient/) | seepage expanding and contracting with the seasons, Nancon, three values of Sy | monthly transient | ~1.5 min |
| 05 | [`05_piezometry_in_a_heterogeneous_coastal_aquifer`](projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/) | Gouville: a coastal strip in two zones of K, the sea level and a piezometer | daily transient | ~40 s |
| 06 | [`06_particle_tracking_and_residence_times`](projects/06_particle_tracking_and_residence_times/) | Lasset: where the seepage water comes from, and how old it is | steady + PRT | ~30 s |
| 07 | [`07_analytical_solution_for_streamflow_recession`](projects/07_analytical_solution_for_streamflow_recession/) | a hillslope recession against the Boussinesq solution | daily transient | ~15 s |
| 08 | [`08_exponential_distribution_of_residence_times`](projects/08_exponential_distribution_of_residence_times/) | travel times against the exponential law of a well-mixed store | steady + PRT | ~5 s |
| 09 | [`09_transport_model_for_an_agricultural_catchment`](projects/09_transport_model_for_an_agricultural_catchment/) | nitrate through an agricultural headwater, Kervidy, MODFLOW 6 GWT | transient + GWT | ~20 min |
| 10 | [`10_coupling_with_land_surface_model_pyhelp`](projects/10_coupling_with_land_surface_model_pyhelp/) | Urse: the flow under a recharge grid computed by PyHELP, then K from the network | steady + calibration | ~40 s |
| 11 | [`11_run_from_scratch_without_plots`](projects/11_run_from_scratch_without_plots/) | a run that writes files and draws nothing | steady + PRT | ~25 s |

Run any of them from its folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
```

The script of example 11 is `py1_run.py`, since it draws nothing.

### In a workspace of your own

After `pip install hydromodpy` there is no `examples/` folder. `hmp example` fetches the
examples into a workspace, each one as a project under `projects/` with its data in the shared
`data/` folder:

```bash
hmp workspace init
cd ~/hydromodpy
hmp example list          # what this version ships
hmp example add 04        # one example
hmp example add 00 07 08  # several
hmp example add --all     # every one
```

The list comes from `hydromodpy/project/examples/catalog.toml`, which
`python -m tools.dev examples manifest` writes from this folder. A folder `NN_name` that holds
a `project.toml` and a `README.md` is an example: its id is `NN`, the first heading of the
README is its title, and the first paragraph its summary, with the sentence "A run takes about
...". A new example needs no code. Write the folder, run the command, commit the catalog.

### Suggested reading order

1. **00** - a quick tour: wells, particles, the lab.
2. **02** - a conceptual relief, no download, and other inputs tried from Python.
3. **01** - the paper case: delineation, a layered aquifer, particle tracks.
4. **03** and **04** - what a water table does to a stream network, in space then in time.
5. **07** and **08** - two synthetic cases where the answer is known in closed form, so the
   solver can be checked rather than illustrated.
6. **05**, **06**, **09** and **10** - a coast, travel times, a solute and a land surface model.

## Where a run puts its results

Nothing is written next to `project.toml`. A run leaves:

```
projects/<name>/
├── project.toml
├── hydromodpy.lock           # what the run resolved, for a replay
├── runs/<run name>/          # fields.zarr, tables.parquet, figures/, config.toml
│   ├── README.md             # what the run is, how it went, its label
│   ├── outcome.json          # its status, written before the first step
│   ├── request.json          # the request as it came, when given as JSON or as a dict
│   ├── products.json         # the products it read from the store, one per kind
│   ├── final_state/          # last head and stages in float64, read by a restart
│   ├── mesh/                 # the mesh it built, when its engine caches one
│   ├── profile.json          # time and memory of each step, outside the seal
│   ├── manifest.json         # the seal, written last, only for a completed run
│   └── exports/              # exports asked for under [export]
├── sessions/<case>/          # the trials of a calibration
├── summary/                  # the tables and figures of `hmp campaign collect`
└── .hmp/index.duckdb         # catalog index, rebuildable by `hmp catalog reindex`
```

Disk is the truth and the index is derived: `hmp catalog reindex` rebuilds the
DuckDB from the run directories, and a deleted `.hmp/` costs nothing.

## Data

`data/` is organized by variable, and a TOML names a file there with
`workspace:`. `path = "workspace:DEM_nancon_25m.tif"` in `[[data.dem.sources]]`
reads `data/dem/DEM_nancon_25m.tif`, and `path = "workspace:."` in
`[[data.hydrometry.sources]]` reads the station folder `data/hydrometry/`. A
bare filename is refused. Some examples still write the path from the project
root, `../../data/dem/...`, which reads the same file and is sealed as
`workspace:<name>`.

| Family | Holds |
|---|---|
| `dem/` | elevation rasters |
| `hydrography/` | observed stream networks |
| `recharge/`, `runoff/`, `etp/`, `precipitation/`, `temperature/` | forcings |
| `hydrometry/`, `piezometry/`, `water_quality/`, `intermittency/` | observations |
| `geology/`, `masks/`, `watershed_polygon/`, `wells/` | context layers |
| `substratum/` | the base of an aquifer, read by `raster_substratum` |
| `pyhelp/` | land-surface model inputs, consumed by a script rather than a TOML |

Provider caches (`bdtopage_*.gpkg`, `*_sim2_*.nc`, `*_hubeau_*.csv`) are
regenerated on demand and stay out of version control.

## Legacy scripts

The v1 example scripts the suite above was ported from, with their original
data, live in the history under tag `v1.0.0`, folder `examples/`, also at
<https://github.com/HydroModPy/HydroModPy/tree/v1.0.0/examples>. They are not
runnable against the current API.
