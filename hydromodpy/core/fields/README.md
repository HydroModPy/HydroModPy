# core/fields

This folder answers: how is a grid or a field array described in plain words? It holds the nodata
sentinels, the shape of a solver grid, the vertical column of a layered model and the storage
precision of time-varying arrays. Nothing here reads a file.

## Modules, in the order a caller uses them

1. `nodata.py` has the shared nodata sentinels (`RASTER_NODATA`) and `valid_cells`, the mask of cells that hold a value.
2. `grid_reference.py` is `GridReference`, the plain geometric description of a solver grid.
3. `vertical_column.py` reads the stack of layers from `idomain` (`layer_interfaces`, `top_active_layer`, `values_at_layer`, `check_layer_interfaces`).
4. `precision.py` fixes how a field is stored: float32 with a rounded mantissa (`FieldPrecision`, `to_storage_precision`, `round_mantissa`).

## What other layers import from it

`solver` (most), `spatial`, `results`, `physics` and `display`.

## Where to add what

- A new nodata convention: `nodata.py`, once, never as a literal in a caller.
- A new way to store a field: `precision.py`, with its error bound.
- A new fact about the grid: a field of `GridReference`.

The layer rules are checked by `tests/unit/architecture/`.
