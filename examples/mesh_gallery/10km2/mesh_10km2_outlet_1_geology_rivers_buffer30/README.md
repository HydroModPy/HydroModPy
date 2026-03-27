# 10 km2 Mesh, Outlet 1, Geology + rivers, 30% buffer

This case is reserved for a conformal catchment mesh where HydroModPy keeps both river traces and geology interfaces as active constraints while preserving the current watershed-boundary handling and de-refinement outside the basin.

## Gallery Metadata

- Scale: `10 km2`
- Outlet: `1`
- Variant: `Geology + rivers, 30% buffer`
- Bundle constraints mode: `geology_rivers`

## Files

- `case.json`: gallery metadata consumed by `tools.doc_gallery`
- `viewer_config.toml`: standalone mesh-viewer config used to render the page figure
- `bundle/`: versioned mesh bundle imported from one local meshing run

## Reproduction

```bash
python -m launchers mesh-catchment run launchers/mesh_catchment/config_s3_10km2.toml
```
