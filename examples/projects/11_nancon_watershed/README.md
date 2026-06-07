# Nancon watershed - complete workflow showcase (v2)

A self-contained example project that walks through **every public way
to drive HydroModPy** on the Nancon catchment (Brittany, France). It is
designed as a teaching ground: each TOML is short, every block carries
the official CLI comments (exported by `hmp config template`), every
Python script exercises a different entry point.

This is the v2 layout of the original `02_nancon_watershed` example.
The old folder is kept untouched as a migration record.

## What you will see here

* The two execution paths: **TOML / CLI** and **Python API**.
* Every workflow mode wired into the CLI dispatcher: `simulation`,
  `overview`, `calibration`, `comparison`, `testbed`.
* Both solver backends: **MODFLOW-NWT** and **MODFLOW 6**.
* All three override mechanisms: `base_config` inheritance,
  `--overlay` stacking, and `--set path=value` dotted overrides.
* The full Python phase API (`Project.lazy(...)` + `build_*` verbs).
* Parameter sweeps and Python-driven calibration.
* Catalog inspection (DuckDB + Zarr) from Python.

## Prerequisites

```bash
mamba activate hmp_refact
hmp install-binaries      # one-time MODFLOW download
hmp doctor                # confirm the env is healthy
```

The example data shipped under `examples/data/` is auto-resolved
through the workspace scaffold (HydroModPy walks up from this folder
and finds the sibling `data/` directory).

## Folder layout

```text
11_nancon_watershed/
|-- README.md                              <- this file
|-- project.toml                           <- canonical base config
|
|-- 01_run_simulation_nwt.toml             <- workflow = simulation, MODFLOW-NWT
|-- 02_run_simulation_mf6.toml             <- workflow = simulation, MODFLOW 6
|-- 03_run_overview.toml                   <- workflow = overview (data report)
|-- 04_run_hydrographic_compare.toml       <- workflow = simulation + hydro figures
|-- 05_run_calibration_k.toml              <- workflow = calibration (K only)
|-- 06_run_calibration_k_sy.toml           <- workflow = calibration (K + Sy)
|-- 07_run_comparison.toml                 <- workflow = comparison (low-K vs high-K)
|-- 08_run_testbed.toml                    <- workflow = testbed (K sensitivity)
|
|-- overlays/
|   |-- overlay_short_window.toml          <- --overlay, shrink dates
|   |-- overlay_no_display.toml            <- --overlay, kill figures
|   |-- overlay_high_resolution.toml       <- --overlay, 200x200 grid
|
|-- python/
|   |-- 01_run_from_toml.py                <- Project("01_run_simulation_nwt.toml")
|   |-- 02_full_python_config.py           <- HydroModPyConfig.from_dict(...)
|   |-- 03_toml_plus_overrides.py          <- load TOML, patch via model_copy
|   |-- 04_lazy_phase_api.py               <- Project.lazy + phase API
|   |-- 05_sweep_sy.py                     <- two ways to sweep Sy
|   |-- 06_python_calibration.py           <- TOML mode + Python mode
|   |-- 07_inspect_catalog.py              <- read DuckDB + Zarr after a run
|
|-- figures/        <- auto-created (one subfolder per simulation name)
|-- simulations/    <- auto-created (Zarr v2 stores, CF-1.11 + UGRID-1.0)
`-- catalog.duckdb  <- per-project catalog (auto-created on first run)
```

The shared input cache lives at `<workspace>/data/cache.duckdb` and
the machine-wide registry at `<state>/index.duckdb` (managed by
`hmp index register|search|forget|prune`).

## The base TOML (`project.toml`)

`project.toml` is the **canonical, fully-annotated configuration for
the Nancon basin**. Every run TOML in this folder inherits from it via
`base_config = "project.toml"` and only redefines the orchestration
block plus the parameter values used for that specific run.

Comments above each option come from `hmp config template --profile user`
and explain what the field means and how its value is read. Use it as
your map of the public surface.

Validate this TOML without running anything:

```bash
hmp config check examples/projects/11_nancon_watershed/project.toml
```

Regenerate a fresh template from the CLI (no Nancon values, every
option commented out):

```bash
hmp config template ref.toml --profile user
hmp config template ref_expert.toml --profile expert      # more knobs visible
hmp config template --list-modules                         # see all modules
```

## Suggested reading order

### Step 0 - check the environment

```bash
hmp doctor --toml examples/projects/11_nancon_watershed/project.toml
hmp config schema > /tmp/hmp_schema.json    # JSON Schema (handy for IDE plugins)
```

### Step 1 - one simulation, the CLI way

```bash
hmp run examples/projects/11_nancon_watershed/01_run_simulation_nwt.toml
```

Inspect the result:

```bash
hmp list 11_nancon_watershed                       # all runs in this project
hmp show nancon_sim_nwt                            # metadata + metrics
hmp inspect nancon_sim_nwt                         # mesh / storage layout
hmp display 01_run_simulation_nwt.toml --list      # which figures exist
```

### Step 2 - swap the solver, layer overlays, override one field

```bash
# MODFLOW 6 instead of MODFLOW-NWT.
hmp run 02_run_simulation_mf6.toml

# Same TOML, layered overlays + a dotted override.
hmp run 01_run_simulation_nwt.toml \
    --overlay overlays/overlay_short_window.toml \
    --overlay overlays/overlay_no_display.toml \
    --set flow.param.K.field.value=1e-4

# Print the resolved plan WITHOUT executing anything.
hmp run 01_run_simulation_nwt.toml --dry-run
```

Compare the two solvers head to head:

```bash
hmp compare nancon_sim_nwt nancon_sim_mf6
```

### Step 3 - watershed identity card

```bash
hmp run 03_run_overview.toml
# -> PNG panels under figures/overview/
```

This one hits live APIs (BRGM, BD TOPAGE, Hub'Eau, SIM2). The first
run may take several minutes; downloads are cached under
`examples/data/`.

### Step 4 - hydrographic network comparison

```bash
hmp run 04_run_hydrographic_compare.toml
```

Outputs the canonical `hydrographic_network_comparison.png` plus four
companion figures under `figures/nancon_hydrographic_compare/`.

### Step 5 - calibration

```bash
# One parameter (K) optimised with Optuna against KGE(discharge).
hmp run 05_run_calibration_k.toml

# Two parameters (K + Sy) with the same objective.
hmp run 06_run_calibration_k_sy.toml

# Browse the resulting sessions:
hmp catalog query "SELECT session_id, n_iterations FROM all_calibration_sessions"

# HTML report for one session:
hmp report <session_id> --open
```

### Step 6 - method comparison and testbed

```bash
# Side-by-side run of two K values, with diff maps and metrics.
hmp run 07_run_comparison.toml

# K sensitivity testbed: materialise child TOMLs, optionally execute them.
hmp run 08_run_testbed.toml
```

### Step 7 - drive everything from Python

```bash
python python/01_run_from_toml.py            # simplest Python entry point
python python/02_full_python_config.py       # no TOML at all, Python dict
python python/03_toml_plus_overrides.py      # TOML + model_copy + run kwargs
python python/04_lazy_phase_api.py           # Project.lazy + phase API
python python/05_sweep_sy.py                 # Sy sweep, two ways
python python/06_python_calibration.py       # TOML mode + Python mode
python python/07_inspect_catalog.py          # read the catalog post-run
```

## TOML vs Python - which one should I use?

* **TOML / CLI** is the recommended way to freeze a configuration for
  reproducibility, share it with collaborators, and ship it through
  CI. Run TOMLs are short overlays on top of `project.toml`; the
  resolved configuration is stored in the catalog so any run can be
  replayed.
* **Python API** is convenient when you want to drive the same
  pipeline programmatically: sweep parameters in a loop you control,
  keep a persistent project handle across multiple runs, read the
  catalog right after a simulation, or work from a notebook.

Both paths write to the same Zarr stores and DuckDB rows, so they can
be mixed freely.

## Override mechanics

When `hmp run <toml>` is called, HydroModPy resolves the final
configuration in this order:

1. Load the leaf TOML and walk its `base_config` chain (recursively).
2. Apply every `--overlay overlay.toml` in declaration order (later
   overlays override earlier ones).
3. Apply every `--set path=value` dotted override.
4. Validate the merged document through `HydroModPyConfig` (Pydantic).
5. Auto-resolve `[workspace]` and `[data].*.path` against the
   workspace scaffold.

> **Heads-up.** The files in `overlays/` are intentionally minimal
> fragments (`[simulation.time]`, `[display].enabled = false`, ...).
> They do **not** validate standalone via `hmp config check`: they
> only make sense layered on top of a leaf TOML through `--overlay`.

The same precedence applies in Python: load the TOML, patch with
`HydroModPyConfig.model_copy(update=...)`, hand to `Project(cfg)`,
optionally pass run-level overrides at `project.run(**kw)` time.

## Outputs

After any run, the project root contains:

* `catalog.duckdb` - per-project catalog (simulations + flow heads/budget).
* `simulations/<sim_id>.zarr/` - per-run gridded outputs (Zarr v2 split, CF-1.11 + ACDD-1.3 + UGRID-1.0).
* `figures/<run_name>/` - figures from `[display].figures`.
* `exports/` - empty until you call `hmp export` or `hmp export-package`.

Export a simulation as a portable, signed `.hmp` archive (tar.zst +
RO-Crate manifest, optional COG GeoTIFF / STAC collection):

```bash
hmp export-package nancon_sim_nwt \
    --workspace examples/projects/11_nancon_watershed \
    -o /tmp/nancon_sim_nwt.hmp

# Round-trip into any other workspace:
hmp add /tmp/nancon_sim_nwt.hmp
hmp import /tmp/nancon_sim_nwt.hmp
```

Open a browser UI on top of the catalogs:

```bash
hmp manage --workspace examples/projects/11_nancon_watershed
```

Inspect the catalog from Python (recommended):

```python
import hydromodpy as hmp

catalog = hmp.open_catalog("examples/projects/11_nancon_watershed")
catalog.simulations.to_dataframe()
catalog.inputs.list()        # shared input cache
catalog.projects.list()      # registered projects
```

`hmp.open(...)` keeps returning the legacy simulations-only facade
(`SimulationCatalog`) for backwards-compatible flows.

## Resuming an interrupted run

The runtime writes an append-only journal (`workflow_steps`) and a
HeartbeatPulse so interrupted runs can be resumed cascade-aware:

```bash
hmp run 01_run_simulation_nwt.toml --resume <RUN_ID>
hmp run 01_run_simulation_nwt.toml --from <STEP>
```

Use `hmp gc` to garbage-collect zombie runs whose heartbeat went
stale.

## Cleaning up

```bash
hmp delete nancon_sim_nwt -y            # one simulation
hmp workspace clean --workspace .       # everything (be careful)
```

## Why this folder exists alongside `02_nancon_watershed/`

`02_nancon_watershed/` is the original example. `11_nancon_watershed/`
is a reorganised, fully-CLI-driven rewrite that will replace it. The
old folder is kept as a migration record until the swap lands.

## Validating everything before committing

```bash
for toml in project.toml [0-9][0-9]_*.toml; do
    hmp config check "$toml"
done

for toml in [0-9][0-9]_*.toml; do
    hmp run "$toml" --dry-run > /dev/null && echo "OK dry-run $toml" || echo "FAIL $toml"
done
```

`hmp config check` enforces the Pydantic schema of `HydroModPyConfig`
sections (simulation / overview / calibration). The `comparison` and
`testbed` schemas live in their own packages and are only validated
at `hmp run` time, so a `--dry-run` pass is the canonical check.
