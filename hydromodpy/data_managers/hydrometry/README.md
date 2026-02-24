# Chronicles Module

`hydromodpy.data_managers.hydrometry` provides tools to load, inspect, and export hydrometric
time series as station-level datasets.

## Main Entry Point

- `station_set.py`: contains `StationSet`, the high-level orchestrator for
  multi-station loading from:
  - Hub'Eau API (`source_mode="api"`)
  - local exported CSV files (`source_mode="local"`)
- `run_hydrometry_example.py`: executable example script for a full load/report/plot run.

## Core Data Object

- `station.py`: contains `Station`, a single-station object with:
  - metadata normalization
  - date filtering
  - completeness diagnostics
  - plotting helper

## Loaders

Loaders are available directly in `hydrometry`:

- `loaders_api.py`: API loading + normalization.
- `loaders_local.py`: local CSV loading + normalization.

## Configuration

- `hydrometry_config.toml`: example configuration file.
- `hydrometry_config.py`: parser and validator for TOML configuration.

## Minimal Example

```python
from hydromodpy.data_managers.hydrometry.station_set import StationSet

stations = StationSet.from_toml("hydromodpy/data_managers/hydrometry/hydrometry_config.toml")
report = stations.get_missing_data_summary()
```
