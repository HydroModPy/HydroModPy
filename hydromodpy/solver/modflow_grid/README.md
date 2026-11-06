# solver/modflow_grid

The grid the MODFLOW family reads, for structured and unstructured meshes.

## Modules

1. `solver_mesh.py` is `SolverMesh`: the cells of the planar mesh stacked in layers, with their top, bottoms and `idomain`, and the DISV arguments MODFLOW 6 takes.
2. `discretization_spatial.py` builds the `SolverMesh` from the domain, the vertical layering and the `sgrid` table, and wraps it in `SolverGridContext`, the view both backends read.
3. `top_sampling.py` samples the DEM onto the cell tops, by point or by zone, with the channel pixels kept apart from the hillslope.
4. `discretization_temporal.py` turns the launcher time grid into stress periods, steps and steady flags.
5. `sgrid_config.py` is the `sgrid` table of a backend: how the top is sampled.
6. `active_connectivity.py` counts the groups of active cells and warns when the grid falls apart in pieces.

MODFLOW 6 writes DISV for every grid. MODFLOW-NWT writes DIS and only takes a structured grid.
