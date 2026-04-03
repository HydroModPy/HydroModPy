# 10 km2, Strahler 3 Mesh, Outlet 1, Geology + rivers, 30% buffer

This family captures repeated conformal meshing runs on the 10 km2 Strahler-3 selection, keeping geology and rivers active while comparing multiple outlets under one stable gallery layout.

## Gallery Metadata

- Scale: `10 km2`
- Outlet: `1`
- Variant: `Geology + rivers, 30% buffer`
- Bundle constraints mode: `geology_rivers`

## Files

- `case.json`: gallery metadata consumed by `tools.doc_gallery`
- `viewer_config.toml`: standalone mesh-viewer config kept as fallback and used for bundle metrics
- `bundle/`: versioned mesh bundle imported from one local meshing run
- `figures/mesh_overview.png`: copied original figure reused on the documentation page
- `figures/mesh_regional.png`: copied regional context figure

## Reproduction

```bash
python -m launchers mesh-catchment run launchers/mesh_catchment/config_s3_10km2.toml
```
