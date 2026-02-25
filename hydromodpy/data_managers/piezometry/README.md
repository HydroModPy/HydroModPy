# Piezometry Module

`hydromodpy.data_managers.piezometry` provides tools to load, inspect, and export
piezometric time series as piezometer-level datasets.

## Main Entry Point

- `piezometer_set.py`: contains `PiezometerSet`, the high-level orchestrator
  for multi-piezometer loading from:
  - Hub'Eau API (`source_mode="api"`)
  - local exported CSV files (`source_mode="local"`)
- `run_piezometry_example.py`: executable example script for a full
  load/report/plot run.

## Core Data Object

- `piezometer.py`: contains `Piezometer`, a single-piezometer object with:
  - metadata normalization
  - date filtering
  - completeness diagnostics
  - plotting helper

## Loaders

Loaders are available directly in `piezometry`:

- `loaders_api.py`: API loading + normalization.
- `loaders_local.py`: local CSV loading + normalization.

## Shared Core

Piezometry now reuses shared components from `hydromodpy.data_managers.common`:

- `BaseStation`: shared station-level parsing/completeness/georeferencing utilities.
- `BaseStationSet`: shared geometry-mask and load-summary helpers.
- `BaseApiLoader` / `BaseLocalLoader`: shared status/date/reference helper methods.

## Configuration

- `piezometry_config.toml`: example configuration file.
- `piezometry_config.py`: parser and validator for TOML configuration.

## Minimal Example

```python
from hydromodpy.data_managers.piezometry.piezometer_set import PiezometerSet

piezometers = PiezometerSet.from_toml(
    "hydromodpy/data_managers/piezometry/piezometry_config.toml"
)
report = piezometers.get_missing_data_summary()
```

## Discover Valid IDs

When input IDs are outdated or unknown, discover valid `code_bss` first:

```python
from hydromodpy.data_managers.piezometry.piezometer_set import PiezometerSet

ids = PiezometerSet.discover_piezometer_ids(
    bbox=(-1.90, 48.00, -1.70, 48.20),  # EPSG:4326
    require_observations=True,
    date_start="2020-01-01",
    date_end="2025-12-31",
    max_ids=10,
)
print(ids)
```
