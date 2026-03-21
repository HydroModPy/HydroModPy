# Sample Bundle

This directory is a tiny self-contained mesh bundle shipped with the standalone
mesh viewer examples.

It exists so that `python mesh/run_visualization.py` works out of the box in a
repository layout where:

- `mesh/` contains only the standalone viewer code
- `examples/mesh_viewer/` contains example TOML files and sample data
- `outputs/mesh_viewer/` receives generated figures and summaries

The files follow the standard catchment mesh bundle contract:

- `mesh_2d.msh`
- `nodes.csv`
- `cells.csv`
- `edges.csv`
- `cell_geology_fractions.csv`
- `metadata.json`
- `mesh_summary.json`

No per-bundle `reader.py` is required because the standalone viewer ships its
own internal reader in `mesh/reader.py`.
