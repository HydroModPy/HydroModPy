# cartesian_grid package

`hydromodpy/spatial/mesh/cartesian_grid/` holds the vertical layering of the regular
grid and the `sgrid` table of the MODFLOW backends.

## Modules

- `sgrid_config.py` defines `VerticalGridConfig` (layering), `TopSamplingConfig`
  (how the top is sampled from the DEM) and `SolverSGridConfig`, the `sgrid` table
  that holds them. `SolverSGridConfig` refuses the retired `planar` and `grid_dual`
  keys and names the `[mesh]` key that replaces each.
- `sgrid_generation.py` builds a `StructuredGridSpec` from two absolute-elevation
  surfaces. `StructuredGridBuilder` checks that the surfaces describe the same domain,
  computes the layer proportions and the layer bottoms. The helpers
  `coerce_vertical_config`, `layer_proportions` and `assert_bottom_below_top` are also
  called by `solver/modflow_grid/discretization_spatial.py`, so the layering has one
  implementation.
- `spatial_interpolation.py` interpolates scattered or gridded values onto the cell
  centres of a grid. The forcing readers use it.

## Layering

Supported methods of `VerticalGridConfig.genmtd_lay`:

- `constant` (`nlay`),
- `decay` (`nlay`, `lay_decay`),
- `list` (`lay_proportions`).

The horizontal grid is not built here. It comes from the mesh engine
(`engines/regular/`), and `Surface.resample_to_shape(...)` resamples the surfaces to
its shape beforehand.
