# Standalone Mesh Viewer

`mesh_bundle_viewer/` is a small self-contained package used to reload one exported 2D
catchment mesh bundle, render a compact overview figure, and write a stable
JSON summary.

Inside this repository, the package lives under `tools/mesh_bundle_viewer/`, so the canonical command is `python -m tools.mesh_bundle_viewer`. When copied as a standalone directory into another project, the canonical command becomes `python -m mesh_bundle_viewer`.

It is designed to be copied as a directory into another repository such as
`rbflow-v1`, without any dependency on the rest of HydroModPy.

## Start Here

If you are discovering the package for the first time, read it in this order:

1. [README.md](README.md)
2. [cli.py](cli.py)
3. [visualization_runner.py](runner/visualization_runner.py)
4. [schema.py](schema.py) and [bundle_contracts.py](bundle_contracts.py)
5. [reader.py](reader.py)
6. [figure.py](display/figure.py) and [summary.py](display/summary.py)

That reading path keeps the mental model simple:

`TOML -> VisualizationConfig -> MeshVisualizationData -> figure + summary`

## Scope

What it does:

- load one exported mesh bundle from disk
- validate and resolve one TOML configuration file
- render one pedagogical matplotlib figure
- optionally write one JSON summary

What it does not do:

- generate meshes
- modify bundles
- require code inside the bundle directory
- require a project-specific Python package next to it

## Package Layout

The root of `mesh_bundle_viewer/` intentionally stays small:

- `reader.py`: versioned bundle reader
- `schema.py`: shared bundle contracts and runtime dataclasses

Supporting code lives in three subdirectories:

- `loading/`: TOML loading and bundle loading
- `display/`: figure rendering and summary building
- `runner/`: end-to-end orchestration

Additional root modules keep the public contracts easy to discover:

- `bundle_contracts.py`: bundle protocols and concrete dataclasses
- `visualization_summary.py`: typed JSON summary contract
- `cli.py`: reusable CLI entry point used by `python -m mesh_bundle_viewer`

Minimal tree:

```text
mesh_bundle_viewer/
  __main__.py
  cli.py
  bundle_contracts.py
  reader.py
  schema.py
  visualization_summary.py
  loading/
    bundle_loader.py
    toml_contracts.py
    toml_docs.py
    toml_loader.py
    toml_validation.py
  display/
    geometry.py
    figure.py
    panels.py
    summary.py
  runner/
    visualization_runner.py
examples/
  mesh_viewer/
    config_example.toml
    sample_bundle/
      ...
outputs/
  mesh_viewer/
    .gitignore
```

## Public API

Recommended entry points:

- CLI: [cli.py](cli.py)
- simple Python API: [visualization_runner.py](runner/visualization_runner.py) via `run_visualization_from_toml(...)`
- lower-level Python API: [reader.py](reader.py), [toml_loader.py](loading/toml_loader.py), and [figure.py](display/figure.py)

Internal helper modules live under `loading/`, `display/`, and `runner/`. They
are stable inside this repository, but they are not the first modules a new
caller should depend on.

## Runtime Dependencies

The package only needs:

- Python 3.12
- `matplotlib`

Minimal conda environment:

```bash
conda env create -f environment.yml
conda activate mesh-distribution
```

## Quick Start

```bash
python -m mesh_bundle_viewer
```

This default command uses:

- `../examples/mesh_viewer/config_example.toml`
- `../examples/mesh_viewer/sample_bundle/`

Outputs are written into `../outputs/mesh_viewer/`.

## CLI Usage

Standard usage:

```bash
python -m mesh_bundle_viewer --config examples/mesh_viewer/config_example.toml
```

Available options:

- `--config`: path to the TOML file to load
- `--section`: TOML section name, default `mesh_distribution`
- `--output-json`: optional override for the JSON summary output path

The command prints the computed summary to stdout as JSON.

Minimal Python usage:

```python
from mesh_bundle_viewer.runner.visualization_runner import run_visualization_from_toml

summary = run_visualization_from_toml(
    "examples/mesh_viewer/config_example.toml"
)
print(summary["cell_count"])
```

## TOML Contract

The default section is:

```toml
[mesh_distribution]
```

The section name is historical. The code now consistently talks about
"visualization", but the public TOML contract keeps `[mesh_distribution]` for
stability.

Minimal example:

```toml
[mesh_distribution]
bundle_dir = "../delivered_bundle"
figure_output_path = "../outputs/mesh_overview.png"
summary_output_path = "../outputs/mesh_overview_summary.json"
show_window = false

[mesh_distribution.plot]
color_field = "geology_key"
show_topography_panel = true
show_mesh_edges = true
show_boundaries = true
show_geology_interfaces = true
show_river_edges = true
```

Supported `color_field` values:

- `area_m2`
- `z_top_centroid`
- `z_top_mean`
- `z_bottom_centroid`
- `z_bottom_mean`
- `hydraulic_conductivity_m_s`
- `storage_coefficient`
- `geology_code`
- `geology_key`

Supported `topography_field` values:

- `z_top_centroid`
- `z_top_mean`

Prefer relative paths in distributed TOML files. Windows absolute paths such
as `C:/...` are not portable to macOS or Linux.

## Bundle Contract

The bundle is a data package only. The reader is shipped in `mesh_bundle_viewer/reader.py`.
No `reader.py` or other Python helper is expected inside `bundle_dir`.

Required bundle files:

- `mesh_2d.msh`
- `nodes.csv`
- `cells.csv`
- `edges.csv`
- `cell_geology_fractions.csv`
- `metadata.json`
- `mesh_summary.json`

Optional bundle files:

- `README.md`

Notes on data fields:

- `nodes.csv` is expected to expose at least `node_id`, `x`, `y`, `z_top`
  and can also expose `z_bottom`
- `cells.csv` is expected to expose geometry, centroid, area, geology, and can
  also contain `z_bottom_centroid`, `z_bottom_mean`,
  `hydraulic_conductivity_m_s`, and `storage_coefficient`
- `edges.csv` is expected to expose edge topology, `edge_kind`, and `is_river`

## Copy Into Another Repository

To vendor the viewer into another repository, copy at minimum:

1. the whole `mesh_bundle_viewer/` directory
2. one real bundle directory
3. one TOML file pointing to that bundle

If you want the zero-argument demo command `python -m mesh_bundle_viewer`
to work out of the box, also copy one example pack under `examples/mesh_viewer/`.

Typical layout:

```text
project/
  mesh_bundle_viewer/
    ...
  examples/
    mesh_viewer/
      mesh_view.toml
      delivered_bundle/
        mesh_2d.msh
        nodes.csv
        cells.csv
        edges.csv
        cell_geology_fractions.csv
        metadata.json
        mesh_summary.json
  outputs/
    mesh_viewer/
```

Then run:

```bash
python -m mesh_bundle_viewer --config examples/mesh_viewer/mesh_view.toml
```

## Notes

- `mesh_bundle_viewer/` is meant to be portable as a directory
- example data and generated outputs intentionally live outside `mesh_bundle_viewer/` so the
  module stays code-only
- the standalone package is now the only implementation; there is no shim or
  compatibility wrapper to keep in sync elsewhere

## Glossary

- `bundle`: one exported mesh directory on disk
- `VisualizationConfig`: resolved runtime configuration derived from TOML
- `MeshVisualizationData`: in-memory pair `(mesh, config)` passed through the runner
- `summary`: stable JSON-friendly report of what was loaded and rendered
- `plot config`: figure-specific rendering options nested under `VisualizationConfig`


