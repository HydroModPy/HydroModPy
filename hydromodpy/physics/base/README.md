# Process Base Layer

This folder contains the shared, process-agnostic building blocks used by
concrete process implementations such as `flow` and `transport`.
It targets spatial processes formulated with partial differential equations
(PDE formalism).

The goal of this layer is to keep:

- generic runtime containers (`parameters`, `initial_conditions`,
  `boundary_conditions`, `sinks_sources`),
- generic Pydantic payload models,
- generic payload normalizers,

in one place so domain-specific modules can stay focused on their own logic.


## What This Layer Provides

### 1. Base Runtime Abstraction

`process_spatial.py` defines `ProcessSpatial`, the abstract parent class for
spatial processes.

Core responsibilities:

- store process runtime containers,
- normalize process parameters from configuration payloads,
- enforce an extension contract for subclasses:
  - `build_initial_conditions(...)`,
  - `set_boundary_conditions(...)`,
  - `set_sinks_sources(...)`.


### 2. Base Configuration Schema

`process_spatial_config.py` defines `ProcessSpatialConfig`, a minimal shared
Pydantic schema with:

- `param_list`,
- `param`,
- `ic`,
- `bc`,
- `sinks_sources`.

Concrete process configs (for example `FlowConfig`) can inherit from this base
schema and specialize validation.


### 3. Shared Payload Models

Generic Pydantic models live in:

- `initial_conditions.py`
- `boundary_conditions.py`
- `sinks_sources.py`

These are intentionally process-neutral and reusable.


### 4. Shared Payload Normalizers

Normalization helpers live in:

- `initial_conditions_config.py`
- `boundary_conditions_config.py`
- `sinks_sources_config.py`

They convert loose mapping-style inputs into validated model instances, while
handling small conveniences such as `unit` -> `units`.


## File Map

- `__init__.py`: public exports for the base layer.
- `process_spatial.py`: abstract runtime base class.
- `process_spatial_config.py`: base config schema.
- `initial_conditions.py`: generic initial-condition model.
- `initial_conditions_config.py`: initial-condition normalizer.
- `boundary_conditions.py`: generic boundary-condition model.
- `boundary_conditions_config.py`: boundary-condition normalizer.
- `sinks_sources.py`: generic sink/source model.
- `sinks_sources_config.py`: sink/source normalizer.


## Typical Integration Pattern

1. Define a process-specific config inheriting from `ProcessSpatialConfig`.
2. Parse and validate TOML into that config.
3. In the runtime process class (subclass of `ProcessSpatial`):
   - call `set_parameters_from_config(...)`,
   - implement `build_initial_conditions(...)`,
   - implement `set_boundary_conditions(...)`,
   - implement `set_sinks_sources(...)`.


## Minimal Example

```python
from collections.abc import Mapping
from hydromodpy.physics.base import ProcessSpatial


class MyInitialConditions:
    def __init__(self, value: float):
        self.value = float(value)


class MyProcess(ProcessSpatial[MyInitialConditions]):
    def build_initial_conditions(self, initial_conditions):
        if initial_conditions is None:
            return None
        if isinstance(initial_conditions, Mapping):
            return MyInitialConditions(initial_conditions["value"])
        raise TypeError("myprocess.ic must be a mapping")

    def set_boundary_conditions(self, boundary_conditions: dict):
        self.boundary_conditions = dict(boundary_conditions)

    def set_sinks_sources(self, sinks_sources: dict):
        self.sinks_sources = dict(sinks_sources)
```


## Design Notes

- This layer is intentionally generic and should not include flow-specific or
  transport-specific business rules.
- Process-specific rules belong in their own modules (`process/flow`,
  `process/transport`, etc.).
