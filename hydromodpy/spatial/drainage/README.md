# spatial/drainage

This folder answers: where does water go on the cells of the model top, and how far is a cell from the
stream down that path? It works on a mesh and never changes the surface the solver reads.

It is not the D8 work on pixels. `spatial/terrain/` and `spatial/geographic/` route flow on a raster
before any mesh exists, and `terrain/` stays free of the rest of HydroModPy. This folder starts from the
cells of the mesh, so `solver`, `results` and `calibration` read it.

## Modules, in the order a caller uses them

1. `graph.py` builds the receiver graph: which cell drains into which (`build_downhill_graph`, `DownhillGraph`), and what accumulates downhill (`accumulate_on_downhill_graph`).
2. `filling.py` raises closed depressions until every path reaches an outlet (`fill_depressions_on_graph`, `DepressionFillReport`).
3. `pins.py` reads the pinned cells a descent must pass through (`resolve_pins`, `with_pins`, `cell_mask`).
4. `descent.py` builds the descent D, the surface on which every cell drains (`build_descent`, `Descent`, `descent_from_stored_mesh`). It is computed on a copy of the top.
5. `distance.py` measures the downslope distance from a cell to the first cell of a target mask (`downslope_distance_to_mask`, `build_downslope_metric`, `resolve_outlet`). It also holds `CATCHMENT_MISMATCH_WARNING_SHARE`, the gap between the graph catchment and the delineated one above which a warning is logged.

## What other layers import from it

`solver` (most), `results`, `calibration` and `spatial/mesh/planning/height_above_stream.py`. `display` does not: a figure that needs a flood or a routing surface asks `results/derive/stream/`. The stream criterion in `results/derive/stream/` builds its own graph on top of `graph.py` and `filling.py`.

## Imports

This folder imports `core` and itself. `distance.py` takes `D8_DESCENT_BY_DEFAULT` from `core/scoring/stream_defaults.py`, where the criterion keeps its other defaults.

## Where to add what

- A new routing rule: `graph.py` or `descent.py`.
- A new distance measure: `distance.py`.
- A helper used by one layer only: in that layer, not here.

The tests are in `tests/unit/drainage/`. The layer rules are checked by `tests/unit/architecture/`.
