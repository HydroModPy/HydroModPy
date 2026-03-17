# Distribution

This annex folder hosts small, practical helpers to distribute HydroModPy mesh
products to colleagues.

The first tool is a pedagogical viewer for one exported catchment-mesh bundle.

## What it reads

The viewer expects one bundle directory produced by the mesh-catchment launcher.
A bundle typically contains:

- `mesh_2d.msh`
- `nodes.csv`
- `cells.csv`
- `edges.csv`
- `cell_geology_fractions.csv`
- `metadata.json`
- `mesh_summary.json`
- `reader.py`

## Why this is useful

The raw `.msh` file alone is not very pedagogical for an external user. The
bundle reorganizes the mesh into explicit tables:

- nodes with coordinates and topography
- cells with connectivity, area, and dominant geology
- edges with adjacency, boundary flags, geology-interface flags, and river flags
- metadata with CRS and bundle schema

This viewer reads that organized bundle and builds one overview figure from a
simple TOML file. By default, it writes two side-by-side panels:

- one panel for the mesh structure and geology-oriented display
- one panel for a topography-style display based on bundle elevation fields

For the topography panel, the viewer first uses nodal topography (`nodes.csv`,
field `z_top`) to build a continuous surface on the mesh. If nodal elevations
are not available, it falls back to cell values such as `z_top_mean`.

## Files

- [mesh_bundle_viewer.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh_bundle_viewer.py)
  Thin facade: orchestration, summary export, backward-compatible public API.
- [mesh_bundle_viewer_io.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh_bundle_viewer_io.py)
  Reading side: TOML loading, viewer config dataclasses, loaded bundle-viewer object.
- [mesh_bundle_visualization.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh_bundle_visualization.py)
  Visualization side: figure construction and plotting helpers.
- [run_mesh_bundle_viewer.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/run_mesh_bundle_viewer.py)
  Direct script entrypoint.
- [mesh_bundle_viewer_example.toml](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh_bundle_viewer_example.toml)
  Example configuration.

## Run

From repository root:

```bash
python hydromodpy_annex/distribution/run_mesh_bundle_viewer.py
```

or with an explicit config:

```bash
python hydromodpy_annex/distribution/run_mesh_bundle_viewer.py --config hydromodpy_annex/distribution/mesh_bundle_viewer_example.toml
```

## TOML structure

Minimal example:

```toml
[mesh_bundle_viewer]
bundle_dir = "C:/results/HydromodPy/mesh_catchment_bretagne_outlet_34/results_stable/mesh/gmsh/mesh_catchment_outlet_34_bundle"
output_figure = "outputs/mesh_bundle_overview.png"
output_summary_json = "outputs/mesh_bundle_overview_summary.json"
show_plot = false

[mesh_bundle_viewer.plot]
color_by = "geology_key"
cmap = "tab20"
figsize = [16.0, 8.0]
dpi = 170
show_topography_panel = true
topography_color_by = "z_top_mean"
topography_cmap = "terrain"
show_mesh_edges = true
show_boundary_edges = true
show_geology_interfaces = true
show_river_edges = true
annotate_cell_ids = false
```

`color_by` can be:

- `geology_key`
- `geology_code`
- `area_m2`
- `z_top_mean`
- `z_top_centroid`

For the second panel, `topography_color_by` can be:

- `z_top_mean`
- `z_top_centroid`

## Recommended distribution pattern

If you want to share a mesh with someone outside the HydroModPy codebase, the
most robust package is:

1. the whole bundle directory
2. the copied `reader.py` shipped inside that bundle
3. one small README that explains the CRS and the intended downstream workflow

This annex viewer is mainly there to make that bundle easier to inspect and to
demonstrate a clean TOML-driven entry point.
