# Sample Bundle

This directory is a tiny self-contained mesh bundle shipped with the standalone
`mesh/` package.

It exists so that `python run_visualization.py` works out of the box after
copying `mesh/` into another repository such as `rbflow-v1`.

The files follow the standard catchment mesh bundle contract:

- `mesh_2d.msh`
- `nodes.csv`
- `cells.csv`
- `edges.csv`
- `cell_geology_fractions.csv`
- `metadata.json`
- `mesh_summary.json`

No per-bundle `reader.py` is required because the standalone package now ships
its own internal reader in `mesh/reader.py`.
