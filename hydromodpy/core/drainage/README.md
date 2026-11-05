# core/drainage

This folder answers: where does water go on the model top, and how far is a cell from the stream down
that path? It works on a mesh and never changes the surface the solver reads.

## Modules, in the order a caller uses them

1. `graph.py` builds the receiver graph: which cell drains into which (`build_downhill_graph`, `DownhillGraph`), and what accumulates downhill (`accumulate_on_downhill_graph`).
2. `filling.py` raises closed depressions until every path reaches an outlet (`fill_depressions_on_graph`, `DepressionFillReport`).
3. `pins.py` reads the pinned cells a descent must pass through (`resolve_pins`, `with_pins`, `cell_mask`).
4. `descent.py` builds the descent D, the surface on which every cell drains (`build_descent`, `Descent`, `descent_from_stored_mesh`). It is computed on a copy of the top.
5. `distance.py` measures the downslope distance from a cell to the first cell of a target mask (`downslope_distance_to_mask`, `build_downslope_metric`, `resolve_outlet`).

## What other layers import from it

`solver` (most), `results`, `display`, `spatial` and `calibration`. The stream criterion in `core/stream/` builds its own graph on top of `graph.py` and `filling.py`.

## Where to add what

- A new routing rule: `graph.py` or `descent.py`.
- A new distance measure: `distance.py`.
- A helper used by one layer only: in that layer, not here.

The layer rules are checked by `tests/unit/architecture/`.
