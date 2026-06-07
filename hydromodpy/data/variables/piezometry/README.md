# Piezometry Data Manager

`hydromodpy.data.variables.piezometry` loads groundwater level time series
from custom CSV files or from the Hub'Eau API.

## Current layout

- `manager.py`: `PiezometryManager`, orchestrator that dispatches to the
  configured source (`custom` or `hubeau`).
- `config.py`: `PiezometrySourceConfig` and `PiezometryConfig` (Pydantic v2,
  `extra="forbid"`).
- `custom.py`: `load_custom`, loader for user-provided location and chronicle
  CSVs.
- `apis/hubeau.py`: Hub'Eau client (`level` and `depth` products).
- `discovery.py`: spatial discovery helpers (bbox, nearest station).
- `examples/run_examples.py`: runnable examples for each source mode.

## Run the examples

```bash
python -m hydromodpy.data.variables.piezometry.examples.run_examples
```
