# 1000 km2 Mesh, Outlet 4, Geology + rivers, 30% buffer

This family captures repeated conformal meshing runs on the 1000 km2 selection so the gallery can compare several larger outlets under one stable geology-plus-rivers setup.

## Gallery Metadata

- Scale: `1000 km2`
- Outlet: `4`
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
python -m tools.doc_gallery
```
