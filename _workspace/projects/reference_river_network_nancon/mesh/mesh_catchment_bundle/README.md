# Catchment Mesh Bundle

Self-contained export for external numerical workflows.

Files:
- `mesh_2d.msh`: original planar Gmsh mesh.
- `nodes.csv`: node coordinates, topography (`z_top`) and substratum (`z_bottom`).
- `cells.csv`: per-cell geometry, topography, substratum, geology, and hydraulic summary.
- `edges.csv`: edge adjacency and boundary/interface flags.
- `cell_geology_fractions.csv`: one row per non-zero geology fraction.
- `metadata.json`: bundle schema, CRS, and field semantics.

Conventions:
- all indices are zero-based,
- coordinates are expressed in the CRS declared in `metadata.json`,
- empty values in CSV mean missing / not available.

Geology exported: no
Hydraulic properties exported: no
