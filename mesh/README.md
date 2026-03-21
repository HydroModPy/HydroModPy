# Standalone Mesh Viewer

`mesh/` is a small self-contained package used to reload one exported 2D
catchment mesh bundle, render a compact overview figure, and write a stable
JSON summary.

It is designed to be copied as a directory into another repository such as
`rbflow-v1`, without any dependency on the rest of HydroModPy.

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

The root of `mesh/` intentionally stays small:

- `run_visualization.py`: CLI entry point
- `reader.py`: versioned bundle reader
- `schema.py`: shared bundle contracts and runtime dataclasses

Supporting code lives in three subdirectories:

- `loading/`: TOML loading and bundle loading
- `display/`: figure rendering and summary building
- `runner/`: end-to-end orchestration

Minimal tree:

```text
mesh/
  run_visualization.py
  reader.py
  schema.py
  loading/
    bundle_loader.py
    toml_loader.py
    toml_schema.py
  display/
    figure.py
    summary.py
  runner/
    visualization_runner.py
  examples/
    config_example.toml
  sample_bundle/
    ...
  outputs/
    .gitignore
```

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

From the `mesh/` directory:

```bash
python run_visualization.py
```

This default command uses:

- `examples/config_example.toml`
- `sample_bundle/`

Outputs are written into `mesh/outputs/`.

## CLI Usage

Standard usage:

```bash
python run_visualization.py --config examples/config_example.toml
```

Available options:

- `--config`: path to the TOML file to load
- `--section`: TOML section name, default `mesh_distribution`
- `--output-json`: optional override for the JSON summary output path

The command prints the computed summary to stdout as JSON.

## TOML Contract

The default section is:

```toml
[mesh_distribution]
```

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

The bundle is a data package only. The reader is shipped in `mesh/reader.py`.
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

1. the whole `mesh/` directory
2. one real bundle directory
3. one TOML file pointing to that bundle

Typical layout:

```text
project/
  mesh/
    ...
  delivered_bundle/
    mesh_2d.msh
    nodes.csv
    cells.csv
    edges.csv
    cell_geology_fractions.csv
    metadata.json
    mesh_summary.json
  config/
    mesh_view.toml
```

Then run:

```bash
python mesh/run_visualization.py --config config/mesh_view.toml
```

## Notes

- `mesh/` is meant to be portable as a directory
- the bundled `sample_bundle/` is intentionally tiny and exists mainly to
  validate the package layout and the default command
- the standalone package is now the only implementation; there is no shim or
  compatibility wrapper to keep in sync elsewhere
