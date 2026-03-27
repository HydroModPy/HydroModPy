# Minimal Catchment Mesh Bundle

Small 2-cell bundle used as the default standalone example for
`python -m mesh_bundle_viewer`.

Files:
- `mesh_2d.msh`: minimal placeholder Gmsh file
- `nodes.csv`: node coordinates and topography
- `cells.csv`: two triangular cells with one geology key each
- `edges.csv`: boundary, river, and geology-interface edges
- `cell_geology_fractions.csv`: one full geology fraction per cell
- `metadata.json`: bundle schema and basic semantics
- `mesh_summary.json`: compact sidecar used by the viewer
