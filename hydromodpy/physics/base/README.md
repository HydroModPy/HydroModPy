# physics/base

What every spatial process shares. `flow` and `transport` build on it.

## Modules, in the order a caller meets them

1. `process_spatial.py` is `ProcessSpatial`, the runtime parent of `Flow` and `Transport`. It holds `parameters`, `initial_conditions`, `boundary_conditions` and `sinks_sources`, and turns a parameter payload into a field parameter through the factory of `physics/contracts.py`.
2. `forcing.py` is the dated forcing of a boundary or a sink: one shape, `TimeSeriesForcing` (constant, seasonal, piecewise or CSV), read as a volume rate, a surface rate or a head.
3. `payloads.py` holds the generic `InitialCondition`, `BoundaryCondition` and `SinkSource` models, their three normalizers, and `declared_unit`, the one reader of a `unit` or `units` key.

`__init__.py` gives these names lazily. Nothing here imports `flow` or `transport`.
