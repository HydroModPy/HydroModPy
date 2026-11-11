# Hydrometry data variable

`hydromodpy.data.variables.hydrometry` loads river discharge or stage time
series from custom CSV files or from the Hub'Eau API.

## Layout

- `variable.py`: `HydrometryVariable`, which dispatches to the configured source
  (`custom` or `hubeau`).
- `config.py`: `HydrometrySourceConfig` and `HydrometryConfig` (Pydantic v2,
  `extra="forbid"`).
- `apis/hubeau.py`: Hub'Eau client.
- `catchment_area_check.py`: compares station drainage area with the model
  catchment.
