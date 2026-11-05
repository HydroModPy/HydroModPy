# Piezometry Data Manager

`hydromodpy.data.variables.piezometry` loads groundwater level time series
from custom CSV files or from the Hub'Eau API.

## Current layout

- `manager.py`: `PiezometryManager`, orchestrator that dispatches to the
  configured source (`custom` or `hubeau`).
- `config.py`: `PiezometrySourceConfig` and `PiezometryConfig` (Pydantic v2,
  `extra="forbid"`).
- `apis/hubeau.py`: Hub'Eau client (`level` and `depth` products).
