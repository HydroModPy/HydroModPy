# Nancon watershed - example project

Small end-to-end project that simulates the Nancon watershed
(Brittany, France) with HydroModPy. It is meant as a working
reference for the two main ways to drive HydroModPy: the TOML/CLI
route and the Python API.

## Folder layout

```text
02_nancon_watershed/
|-- project.toml
|-- run_transient_nwt.toml
|-- run_transient_nwt_html_report.toml
|-- run_hydrographic_network_comparison.toml
|-- run_calibration_k.toml
|-- run_sweep_sy.toml                       # design draft (sweep workflow non câblé)
|-- run_overview_all_apis.toml
|-- run_full_python.py
|-- run_cellular.py
|-- run_transient_prototype.py.draft        # quarantaine v1 : à réécrire
|-- figures/
`-- README.md
```

> **Mise en quarantaine v1.** `run_transient_prototype.py.draft` n'a
> pas survécu à la migration database/catalog/workflow : sa réécriture
> attend l'API stabilisée (`hmp.open_catalog`, journal
> `workflow_steps`). En attendant, utiliser `run_cellular.py` ou les
> entrées du showcase `11_nancon_watershed/python/`.

## Prerequisites

- A working HydroModPy environment. With mamba/conda, activate the env so
  `hmp` is on your PATH. With uv, prepend `uv run` to the commands below.
- MODFLOW binaries. Run `hmp install-binaries` once after the env is set up,
  otherwise the solver step fails with `An executable name or path must be provided`.
- The example data shipped with the repo under `examples/data/`. Paths in the
  TOMLs are relative to this project folder, so keep the project under
  `examples/projects/`.

## How each entry point works

There are two execution paths:

1. `hmp run <toml>` parses one TOML, validates it against the Pydantic schema,
   dispatches to the workflow declared in `[workflow].mode = "..."`, and persists the
   run in the project workspace.
2. `hmp.Project(...)` drives the same pipeline from Python. Use it when you want
   to sweep parameters, work from notebooks, or inspect the catalog directly.

Both paths read and write the same workspace, so they can be mixed freely.

## Run each example

All commands assume your working directory is the repository root.

### TOML files

| Command | What it does |
| --- | --- |
| `hmp run examples/projects/02_nancon_watershed/run_transient_nwt.toml` | One transient MODFLOW-NWT run, monthly steps, 2000-2002. |
| `hmp run examples/projects/02_nancon_watershed/run_transient_nwt_html_report.toml` | Same transient run pattern, with `[report.html].build_at_end = true`; the final HTML report consumes the produced artifacts after the simulation and display steps. |
| `hmp run examples/projects/02_nancon_watershed/run_hydrographic_network_comparison.toml` | Same Nancon base case, but with DEM-derived river-network extraction enabled and the standard `hydrographic_network_comparison` figure rendered at the end. |
| `hmp run examples/projects/02_nancon_watershed/run_calibration_k.toml` | Optuna calibration on K against observed discharge (NSE objective). Sy / Ss / thickness frozen. |
| `hmp run examples/projects/02_nancon_watershed/run_sweep_sy.toml` | Design draft for a Sy sweep. Not runnable: the `sweep` workflow is not wired into the v1 dispatcher. See `11_nancon_watershed/python/05_sweep_sy.py` for the supported Python-driven sweep. |

To validate any TOML without running it:
`hmp dev config check examples/projects/02_nancon_watershed/<file>.toml`.

### Python scripts

| Command | What it does |
| --- | --- |
| `python examples/projects/02_nancon_watershed/run_full_python.py` | Builds the same configuration as `run_transient_nwt.toml`, but entirely in Python. |
| `python examples/projects/02_nancon_watershed/run_cellular.py` | Lazy Project mode. Builds geographic and data once, iterates on mesh cell sizes, then runs one final simulation. |

## Difference between the TOML and Python entry points

- The TOML files are declarative. They are the recommended way to freeze a
  configuration for reproducibility and for sharing with collaborators.
- The Python scripts are imperative. They are convenient when you want to:
  - sweep or calibrate parameters from a loop you control,
  - keep a persistent project handle across multiple runs,
  - drive HydroModPy from a notebook,
  - read the catalog (`run.field`, `run.fields`, `run.timeseries`, ...) right
    after a simulation.

Both entry points ultimately write the same Zarr stores and DuckDB rows.

## Outputs

Running any of the entries above creates or updates:

- `<workspace>/catalog.duckdb` - per-project catalog (simulations + flow heads/budget).
- `<workspace>/data/cache.duckdb` - shared input cache (DEM, hydrography, BRGM, ...).
- `<workspace>/simulations/<sim_id>.zarr/` - per-run gridded outputs (CF-1.11 + UGRID-1.0).
- `figures/<run_name>/` - figures listed in `[display].figures`.
- for `run_transient_nwt_html_report.toml`, the optional HTML report under
  `../16_nancon_natural_calibration/outputs/nancon_transient_nwt_html_report/web/index.html`.

Open `hmp.open_catalog(<workspace>)` from Python to reach the three
namespaces (`.simulations`, `.inputs`, `.projects`). The legacy
`hmp.open(<workspace>)` still works and returns the simulations-only
facade.

For the hydrographic-network demo run, the main artifact is:

- `figures/nancon_hydrographic_network_compare/hydrographic_network_reference.png`
- `figures/nancon_hydrographic_network_compare/hydrographic_network_generated.png`
- `figures/nancon_hydrographic_network_compare/hydrographic_network_comparison.png`
- `figures/nancon_hydrographic_network_compare/hydrographic_network_reference_missing_only.png`
- `figures/nancon_hydrographic_network_compare/hydrographic_network_generated_extra_only.png`

That run also stores both canonical geographic features in the catalog:

- `hydrographic_network_reference`
- `hydrographic_network_generated`

The same per-run metrics are available later from Python through
`run.hydrographic_network_comparison_metrics()`, and the naming contract can be
inspected with `run.hydrographic_network_naming("reference" | "generated")`.

When one network is missing:

- `run.available_hydrographic_network_roles()` lists what is actually stored.
- `run.has_hydrographic_network("reference" | "generated")` gives a simple boolean.
- the standalone figures stay available only for the roles that exist.
- the comparison figures are not exposed in `run.display_capabilities`.
- `run.hydrographic_network_comparison()` raises a clear error telling you which
  role is missing and which roles are available.

The historical Python sweep script (`run_transient_prototype.py`) is
currently in quarantine under the `.draft` suffix; once rewritten it
will land back here. See `11_nancon_watershed/python/05_sweep_sy.py`
for the supported sweep template.
