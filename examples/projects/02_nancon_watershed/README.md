# Nançon watershed - example project

Small end-to-end project that simulates the Nançon watershed
(Brittany, France) with HydroModPy. It is meant as a working
reference for the two ways to drive HydroModPy: the TOML/CLI route
and the Python API.

## Folder layout

```
02_nancon_watershed/
├── project.toml                 # shared base config (data, geo, flow defaults)
├── run_transient_nwt.toml       # overlay: one transient MODFLOW-NWT run
├── run_calibration_k.toml       # overlay: Optuna calibration of K
├── run_sweep_sy.toml            # overlay: design draft for the future sweep
├── run_full_python.py           # full Python equivalent of run_transient_nwt
├── run_cellular.py              # Spyder/Jupyter cellular workflow
├── run_transient_prototype.py   # Python sweep prototype (Sy sensitivity)
├── figures/                     # output figures (created on first run)
└── README.md
```

## Prerequisites

- A working HydroModPy environment. With mamba/conda activate the
  env (e.g. `mamba activate hmp_refact`) so `hmp` is on your PATH;
  with uv prepend `uv run` to every command below.
- MODFLOW binaries. Run `hmp install-binaries` once after the env
  is set up; otherwise the solver step fails with
  `An executable name or path must be provided`.
- The example data shipped with the repo, under
  `examples/data/`. Paths in the TOMLs are relative to this
  project folder, so do not move the project out of
  `examples/projects/`.

## How each entry point works

There are two execution paths:

1. **TOML / CLI path** - `hmp run <toml>`. Parses the TOML, validates
   it against the Pydantic schema, dispatches to the workflow listed
   in `workflow = "..."` (`simulation`, `calibration`, `batch`,
   `overview`, or `mesh`). All TOMLs in this folder use a
   `base_config = "project.toml"` overlay so they only carry their
   delta on top of the shared description.

2. **Python API path** - `hmp.Project(...)`. Same pipeline behind the
   scenes; the configuration is loaded through the canonical
   `HydroModPyConfig` model and the run is triggered by
   `project.run(**overrides)`. Use this when you want to sweep
   parameters, drive a notebook cell by cell, or call HydroModPy
   from a larger Python program.

Both paths read and write the same project workspace (DuckDB
catalog + Zarr stores + figures), so they can be mixed freely.

## Run each example

All commands assume your working directory is the repository root.

### TOML files

| Command | What it does |
| --- | --- |
| `hmp run examples/projects/02_nancon_watershed/run_transient_nwt.toml` | One transient MODFLOW-NWT run, monthly steps, 2000-2002. |
| `hmp run examples/projects/02_nancon_watershed/run_calibration_k.toml` | Optuna calibration on K against observed discharge (NSE objective). Sy / Ss / thickness frozen. |
| `run_sweep_sy.toml` | Forward-looking design TOML for a Sy sweep. **Not runnable with `hmp run` in v1**. Use `run_transient_prototype.py` until then. |

To validate any TOML without running it:
`hmp config check examples/projects/02_nancon_watershed/<file>.toml`.

### Python scripts

| Command | What it does |
| --- | --- |
| `python examples/projects/02_nancon_watershed/run_full_python.py` | Builds the same configuration as `run_transient_nwt.toml` but entirely in Python. No TOML is read. |
| `python examples/projects/02_nancon_watershed/run_cellular.py` | Lazy Project mode. Builds geographic + data once, iterates on mesh cell sizes, then runs one final simulation. Cells are marked `# %%` for Spyder / Jupyter. |
| `python examples/projects/02_nancon_watershed/run_transient_prototype.py` | Reads `project.toml`, runs three transient simulations with Sy in {0.001, 0.05, 0.30}, then reads the catalog (DuckDB + Zarr) to render comparison figures into `figures/`. |

## Difference between the TOML and Python entry points

- The TOML files are declarative. They are the recommended way to
  freeze a configuration for reproducibility and for sharing with
  collaborators. They go through the same dispatcher used by the CI.
- The Python scripts are imperative. They are convenient when you
  want to:
  - sweep / calibrate parameters from a loop you control,
  - keep a persistent project handle across multiple runs,
  - drive HydroModPy from a notebook,
  - read the catalog (`run.field`, `run.fields`, `run.timeseries`,
    `run.saturated_fraction`, ...) right after a simulation.

The two entry points are equivalent in terms of validation and
storage: every script ultimately calls `Project.run`, which writes
exactly the same Zarr stores and DuckDB rows as `hmp run`.

## Outputs

Running any of the entries above creates / updates:

- `<workspace>/hydromodpy.duckdb` - shared catalog of every run.
- `<workspace>/simulations/<sim_id>.zarr` - per-run gridded outputs.
- `figures/<run_name>/` - figures listed in `[display].figures`.

The Python sweep script also writes its own comparison figures to
`figures/`:

- `cross_section_comparison.png`
- `streamflow_comparison.png`
- `drainage_density_comparison.png`
- `saturation_maps_comparison.png`
- `persistency_comparison.png`
