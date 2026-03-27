# Mesh Gallery Inputs

This directory is the canonical repository location for future mesh-gallery
cases used by the documentation capability gallery.

The goal is to keep the documentation reproducible from versioned bundle
artifacts, instead of pointing the docs at private `C:/results/...` folders.

## Layout

Each imported case lives under one scale bucket:

- `10km2/`
- `100km2/`
- `1000km2/`

Each case directory should contain:

- `case.json`
- `viewer_config.toml`
- `README.md`
- `bundle/`

The `bundle/` directory follows the standard catchment mesh bundle contract:

- `mesh_2d.msh`
- `nodes.csv`
- `cells.csv`
- `edges.csv`
- `cell_geology_fractions.csv`
- `metadata.json`
- `mesh_summary.json`

## Canonical Variants

The gallery is currently organized around two mesh variants per scale:

- `geology_rivers_buffer30`
  - geology interfaces and rivers both constrain the mesh
  - watershed boundary remains active
  - outside coarsening remains active
  - the geographic support uses a `30%` buffer
- `rivers_only_buffer30`
  - only river traces constrain the internal mesh
  - watershed boundary remains active
  - outside coarsening remains active
  - the geographic support uses a `30%` buffer

## Import Workflow

Import one local bundle into this canonical layout with:

```bash
python -m tools.doc_gallery.import_mesh_bundle \
  --source-bundle C:/results/HydromodPy/mesh_catchment_runs/headwater_100km2/mesh_outlet_27/mesh_catchment_outlet_27_bundle \
  --scale 100km2 \
  --variant geology_rivers_buffer30 \
  --outlet-id 27
```

After import:

1. review `case.json` and `viewer_config.toml`
2. run `python -m tools.doc_gallery`
3. rebuild the docs

Imported cases are discovered automatically by `tools.doc_gallery` as soon as
their `case.json` file is present under this tree.
