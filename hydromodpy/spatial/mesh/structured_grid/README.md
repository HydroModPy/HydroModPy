# structured_grid package

`hydromodpy/spatial/mesh/structured_grid/` holds the structured grid of the regular
engine and the `sgrid` table of the MODFLOW backends.

The vertical layering is not here. `[domain.layers]` is read by every solver, so its
models (`layers_config.py`) and the code that turns it into layer bottoms and `idomain`
(`layering.py`) live in `hydromodpy/spatial/domain/`.

## Modules

- `sgrid_config.py` defines `TopSamplingConfig` (how the top is sampled from the DEM)
  and `SolverSGridConfig`, the `sgrid` table that holds it. `SolverSGridConfig` refuses
  the retired `planar`, `grid_dual` and `vertical` keys and names the table that
  replaces each.
- `sgrid_generation.py` builds a `StructuredGridSpec` from two absolute-elevation
  surfaces. `StructuredGridBuilder` checks that the surfaces describe the same domain,
  asks `domain/layering.py` for the layer bottoms and `idomain`, and assembles the
  vertices.

The horizontal grid is not built here. It comes from the mesh engine
(`engines/regular/`), and `Surface.resample_to_shape(...)` resamples the surfaces to
its shape beforehand.
