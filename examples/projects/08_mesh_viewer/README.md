# 08 - Mesh viewer

Visual inspection of pre-exported mesh bundles (Gmsh + CSV + JSON sidecars). No
solver runs here: the viewer reloads a bundle and renders it as a PNG overview
plus a JSON summary. CRS is EPSG:2154.

The TOML files in this project are not `HydroModPyConfig`. They use the
`[mesh_distribution]` schema consumed by `tools/mesh_bundle_viewer/`, a
standalone package with its own CLI. `hmp run` and `hmp config check` do not
apply to them.

## Run

```bash
python -m tools.mesh_bundle_viewer --config examples/projects/08_mesh_viewer/config_example.toml
python -m tools.mesh_bundle_viewer --config examples/projects/08_mesh_viewer/config_mesh_catchment_outlet_5.toml
```

Run from the repository root. Each command prints the computed summary as
JSON and, since `show_window = false` in both configs, writes a PNG and a
JSON summary under `outputs/mesh_viewer/`. Measured runtime: about 1.7 s for
the default bundle (2 cells), a few seconds for the catchment bundle (3760
cells).

## Data

| File / folder | Role |
|---|---|
| `config_example.toml` | Reference configuration, points at `default_bundle/`. |
| `config_mesh_catchment_outlet_5.toml` | Configuration for the headwater 100 km² bundle (`mesh_catchment_outlet_5_bundle/`). |
| `default_bundle/` | Minimal 2-cell bundle (placeholder Gmsh mesh). |
| `sample_bundle/` | Full bundle for an external workflow, not referenced by either config. |
| `mesh_catchment_outlet_5_bundle/` | Real bundle exported from a `mesh_catchment` run. |

Each `*_bundle/` folder has its own README describing its CSV files
(`nodes`, `cells`, `edges`, `cell_geology_fractions`) and its JSON sidecars
(`metadata.json`, `mesh_summary.json`).

## What it shows

- How the standalone viewer turns one exported mesh bundle into a figure with
  a structural panel (geology, rivers, edges) and a topography panel.
- The difference between a small placeholder bundle and a real catchment mesh
  with hydraulic properties attached to each cell.
