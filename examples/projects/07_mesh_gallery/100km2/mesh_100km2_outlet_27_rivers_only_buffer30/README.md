# 100 km2, headwater Mesh, Outlet 27, Rivers only, 30% buffer

This case is reserved for a catchment mesh where geology is removed from the internal constraint set, but the watershed boundary, support extent, and outside de-refinement stay aligned with the standard gallery workflow.

## Gallery Metadata

- Scale: `100 km2`
- Outlet: `27`
- Variant: `Rivers only, 30% buffer`
- Bundle constraints mode: `rivers_only`

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
