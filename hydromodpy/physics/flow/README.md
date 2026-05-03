# Flow Module Guide

This directory contains the runtime and configuration logic for the flow
process used by HydroModPy.

Main files:

- `flow.py`: runtime `Flow` object consumed by solvers.
- `flow_config.py`: Pydantic schema and TOML parsing for `[flow]`.
- `initial_conditions.py`: typed flow initial-condition models.
- `initial_conditions_config.py`: normalization/validation of `[flow.ic]`.


## 1. End-to-End Data Path

Configuration flow is:

1. `HydroModPyConfig.from_toml(...)`
2. `FlowConfig.from_toml_section(...)`
3. `Flow(config=FlowConfig(...))`
4. Runtime normalization into:
   - `flow.parameters`
   - `flow.initial_conditions`
   - `flow.boundary_conditions`
   - `flow.sinks_sources`

`Flow` relies on `ProcessSpatial` and stores normalized runtime objects, not raw
TOML dictionaries.


## 2. TOML Layout for `[flow]`

Expected structure:

```toml
[flow]
flow_regime = "transient"          # "steady" or "transient"
param_list = ["K", "Ss", "Sy"]     # ordered parameter ids

[flow.param.K.field]
id = "K"
kind = "heterogeneous"
unit = "m/s"

[flow.param.K.field_heterogeneous]
values_source = "csv"
values_csv_file = "../../data/France/geology/geology_K_dummy_demo.csv"
csv_key_column = "zone_key"
csv_value_column = "K_value"
field_spatial_id = "field_geology"

[flow.ic]
type = "custom"                     # top | bottom | custom
value = "12.5 m"                    # "<value> <unit>" in one field

[flow.bc.dirichlet.ocean]
value = "1.0 m"
type = "dirichlet"
data_value = true

[flow.bc.cauchy.drainage]
application_domain = "top"
type = "cauchy"
value = "0.0 m2/s"

[flow.sinks_sources.wells.W1]
cell = [0, 39, 39]                  # legacy: [lay, row, col], 0-based
units = "m3/day"

[flow.sinks_sources.wells.W1.forcing]
mode = "constant"
value = -200.0
```


## 3. Parameter Section (`[flow.param.<id>]`)

`FlowConfig` expects:

- `param_list`: ordered list of parameter IDs.
- `param`: payload map, usually loaded from `[flow.param.<id>]` sections.

Consistency checks:

- every ID in `param_list` must exist in `param`.
- `param` cannot contain undeclared IDs.
- IDs must be non-empty and unique.

Payload resolution:

- FieldParam-style payloads are resolved/validated via
  `resolve_field_param_config_payload(...)`.
- At runtime, compatible payloads are coerced to `FieldParam` objects by
  `ProcessSpatial.set_parameters_from_config(...)`.


## 4. Initial Conditions (`[flow.ic]`)

`[flow.ic]` is a single payload with direct keys:

- `type`: `top`, `bottom`, or `custom`
- `value`: required when `type = "custom"`, accepts numeric or `"<value> <unit>"`
- `unit` or `units`: optional fallback when `value` has no inline unit (default `m`)
- `description`: optional

Important behavior:

- no nested shape (`[flow.ic.h]`) is supported.
- no scalar shorthand (`flow.ic = 10.0`) is supported.
- normalized runtime object is:
  `FlowInitialConditions(h=FlowInitialCondition(...))`.

Semantics:

- `top`: initialize head from top surface.
- `bottom`: initialize head from bottom surface.
- `custom`: initialize head from provided scalar value.


## 5. Boundary Conditions (`[flow.bc]`)

Boundary parsing is implemented by `_parse_flow_bc_sections(...)`.

### 5.1 Supported Sections

Dirichlet:

```toml
[flow.bc.dirichlet.ocean]
[flow.bc.dirichlet.stream]
[flow.bc.dirichlet.north_side]
[flow.bc.dirichlet.south_side]
[flow.bc.dirichlet.east_side]
[flow.bc.dirichlet.west_side]
```

Drainage:

```toml
[flow.bc.cauchy.drainage]
# or
[flow.bc.robin.drainage]
```

Generic fallback:

```toml
[flow.bc.<custom_id>]
```

### 5.2 Validation Rules

Common:

- `value` is required and accepts numeric or `"<value> <unit>"`.
- `unit` and `units` are both accepted as optional fallback.
- `data_value` is optional boolean.
- `description` is optional string.

`application_domain` allowed values:

- `top`
- `north side`
- `south side`
- `east side`
- `west side`

Type constraints:

- `[flow.bc.dirichlet.*]`: type must be `dirichlet`.
- drainage sections: type must be `cauchy` or `robin`.
- generic fallback: type must be one of `dirichlet`, `cauchy`, `robin`.

Default units:

- `m` for dirichlet
- `m2/s` for cauchy/robin

Domain inference:

- dirichlet IDs imply a canonical domain:
  - `ocean`/`stream` -> `top`
  - `west_side` -> `west side`, etc.
- if `application_domain` is provided and conflicts with inferred domain, a
  validation error is raised.

### 5.3 Runtime Canonical IDs

After parsing, IDs are canonicalized:

- `ocean`, `stream`, `north_side`, `south_side`, `east_side`, `west_side`
- `drainage`
- custom IDs for generic entries


## 6. Wells (`[flow.sinks_sources.wells.<id>]`)

Each well payload:

- legacy `cell`: `[lay, row, col]`, integer, 0-based, non-negative.
- or `location_mode = "absolute_xy"` with `layer`, `x`, `y`.
- or `location_mode = "relative_xy"` with `layer`, `x_rel`, `y_rel` in `[0,1]`.
- preferred `forcing` block:
  - `mode = "constant"` with one `value`
  - or `mode = "csv"` with `path_file`, `date_column`, `value_column`
- legacy `flux`: numeric scalar or non-empty list of numerics.
- `units`: optional string (default `m3/s`).
- `description`: optional string.

Runtime note:

- `forcing` is resolved by launcher runtime against `[simulation.time]`, then
  converted internally to `flux`.
- scalar `flux` is expanded later by solver code across stress periods.
- list length consistency with `nper` is checked at solver preprocessing time.
- coordinate-based well locations are resolved to the solver cell after grid generation.

Example with constant forcing:

```toml
[flow.sinks_sources.wells.W1]
location_mode = "absolute_xy"
layer = 0
x = 265611.933
y = 6784182.776
units = "m3/day"

[flow.sinks_sources.wells.W1.forcing]
mode = "constant"
value = -200.0
```

Example with CSV forcing:

```toml
[flow.sinks_sources.wells.W2]
location_mode = "relative_xy"
layer = 0
x_rel = 0.70
y_rel = 0.70
units = "m3/day"

[flow.sinks_sources.wells.W2.forcing]
mode = "csv"
path_file = "data/wells/standard_wells_2003.csv"
date_column = "date"
date_format = "%Y-%m-%d"
value_column = "W2_m3_day"
aggregate = "mean"
```


## 7. Complete Example

```toml
[flow]
flow_regime = "transient"
param_list = ["K", "Sy", "Ss"]

[flow.ic]
type = "custom"
value = "12.5 m"
description = "Initial hydraulic head"

[flow.bc.dirichlet.ocean]
value = "0.0 m"
type = "dirichlet"
data_value = true

[flow.bc.dirichlet.west_side]
value = "3.0 m"
type = "dirichlet"

[flow.bc.cauchy.drainage]
application_domain = "top"
type = "cauchy"
value = "1e-6 m2/s"

[flow.sinks_sources.wells.P1]
location_mode = "relative_xy"
layer = 0
x_rel = 0.62
y_rel = 0.35
units = "m3/day"

[flow.sinks_sources.wells.P1.forcing]
mode = "constant"
value = -500.0
```


## 8. Common Validation Errors

- `flow.param_list declares ids without payload in flow.param`
  - `param_list` and `param` are out of sync.

- `flow.ic accepts only direct keys [type, value, unit, units, description]`
  - unsupported keys were provided in `[flow.ic]`.

- `flow.ic.value is required when type='custom'`
  - add `value` for custom initial condition.

- `...application_domain contains an invalid value`
  - use exactly one of:
    `top`, `north side`, `south side`, `east side`, `west side`.

- `well location requires either cell=[lay,row,col] or location_mode with coordinate fields`
  - add either the legacy `cell` field or one of the coordinate-based modes.

- `well requires either flux or forcing`
  - add a legacy `flux` payload or a `forcing` block.

- `well.flux and well.forcing are mutually exclusive`
  - keep only one input mode in the user config.


## 9. Programmatic Usage

```python
from pathlib import Path
from hydromodpy.master_config import HydroModPyConfig
from hydromodpy.physics.flow import Flow

cfg = HydroModPyConfig.from_toml(Path("examples_legacy/example12/config.toml"))
flow = Flow(config=cfg.flow)

print(flow.flow_regime)
print(flow.parameters.keys())
print(flow.initial_conditions.h.type if flow.initial_conditions else None)
print(flow.boundary_conditions.keys())
print(flow.sinks_sources.get("wells", {}).keys())
```


## 10. Notes for Contributors

- Keep user-facing TOML grammar in sync with:
  - `FlowConfig.bc` field description
  - `_parse_flow_bc_sections(...)` docstring
  - `examples_legacy/example12/config.toml` comments
