# 07 - Mesh gallery bundles

This is not a runnable catchment. It is the canonical repository of mesh
bundles behind the documentation capability gallery, so the gallery pages
build from versioned artifacts instead of private local result folders.
It holds 24 imported cases across three scale buckets (10, 100, 1000 km2),
each a Gmsh triangular mesh in EPSG:2154.

## Layout

Each case lives under its scale bucket (`10km2/`, `100km2/`, `1000km2/`) and
contains:

- `case.json`: gallery metadata consumed by `tools.doc_gallery`
- `viewer_config.toml`: standalone mesh-viewer config (`tools.mesh_bundle_viewer`
  contract, not a `HydroModPyConfig`)
- `README.md`: case-level description
- `figures/`: copied mesh figures reused on the doc page
- `bundle/`: the mesh export (`mesh_2d.msh`, `nodes.csv`, `cells.csv`,
  `edges.csv`, `cell_geology_fractions.csv`, `metadata.json`,
  `mesh_summary.json`)

Two canonical variants recur per scale:

- `geology_rivers_buffer30`: geology interfaces and rivers both constrain the
  mesh, watershed boundary and outside coarsening active, 30% buffer
- `rivers_only_buffer30`: only river traces constrain the mesh, same boundary
  and buffer settings

A case is discovered automatically by `tools.doc_gallery` as soon as its
`case.json` is present under this tree.

## Import

Import one local bundle into the canonical layout:

```bash
python -m tools.doc_gallery.import_mesh_bundle \
  --source-bundle C:/results/HydromodPy/mesh_catchment_runs/headwater_100km2/mesh_outlet_27/mesh_catchment_outlet_27_bundle \
  --scale 100km2 \
  --variant geology_rivers_buffer30 \
  --outlet-id 27
```

Refresh the repeated batch-backed cases already committed here, straight from
the existing batch outputs, and rebuild the gallery pages in one step:

```bash
python -m tools.doc_gallery.sync_mesh_catchment_runs --update-gallery
```

After a manual import, review `case.json` and `viewer_config.toml`, then run
`python -m tools.doc_gallery` to regenerate the gallery pages. Runtime depends
on the local batch outputs available; unmeasured here.
