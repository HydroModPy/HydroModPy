# Field

`hydromodpy/field/` provides generic field parameterization utilities
(homogeneous and heterogeneous), plus a square-case example with mesh support.

## Directory Map

```text
hydromodpy/field/
|-- core/
|   |-- field_param.py
|   |-- field_param_config.py
|   |-- field_spatial.py
|   |-- field_spatial_weighted_discretization.py
|   `-- field_mesh.py
|-- cases/
|   `-- square/
|       |-- field_param_config.toml
|       |-- field_spatial_config.toml
|       |-- mesh_config.toml
|       |-- field_spatial_square.py
|       |-- field_mesh_square.py
|       |-- run_field_demo.py
|       `-- outputs/
|-- __init__.py
`-- README.md
```

## Structure (What Goes Where)

- `core/`: generic interfaces and reusable implementations.
- `core/field_param.py`: parameter values, config loading, and mapping rules.
- `core/field_param_config.py`: Pydantic validation for field-parameter TOML
  payloads.
- `core/field_spatial.py`: abstract field geometry contract and abstract
  discretization contract.
- `core/field_spatial_weighted_discretization.py`: weighted-fraction
  discretization implementation.
- `core/field_mesh.py`: abstract mesh contracts (`BaseFieldMesh`, `FieldMesh`)
  and generic containers (`MeshCell`, `MeshWithValues`).
- `cases/square/`: concrete square geometry, concrete mesh factory, runnable
  demonstration, and example TOML files.
- geology case integration now lives under
  `hydromodpy/data_managers/geology/` with runnable scripts in
  `hydromodpy/data_managers/geology/cases/`.

## Core Concepts

- `FieldParam`: values for one parameter identifier (`id`, for example `K` or
  `Sy`).
  - homogeneous mode: one scalar for all cells.
  - heterogeneous mode: one value per zone key + `field_spatial_id`.
- `Field` (abstract): geometry model that can discretize itself on a mesh via
  `on_mesh(mesh)`.
- `FieldDiscretization` (abstract): bridge object containing the aggregation
  logic required by `FieldParam.to_mesh_field(...)`.
- `BaseFieldMesh` (abstract): one mesh API for all mesh kinds.
- `FieldMesh` (abstract): mesh factory API loaded from config.

## Shared API

1. Build or load one `FieldParam`.
2. Build or load one mesh (`FieldMeshSquare.from_*` in the square case).
3. For heterogeneous mode, build/load one spatial field and compute
   `field.on_mesh(mesh)`.
4. Convert to cell values with `FieldParam.to_mesh_field(...)`.

Output object:
- `MeshWithValues(mesh, cell_values, label)`

## TOML Convention

Field parameter file (`field_param_config.toml`):
- `[field]`: `id`, `kind`, `unit`
- `[field_homogeneous]`: `value`
- `[field_heterogeneous]`: `field_spatial_id` + value source:
  - inline: `values = {...}`
  - csv: `values_source = "csv"` + `values_csv_file` + CSV column names
- optional `[field_vertical_profile]`: depth dependency shared over whole domain
  - `mode = "none"` (default)
  - `mode = "exponential"` + `characteristic_depth` with factor `exp(-z/characteristic_depth)`
    and optional floor `min_factor`:
    `max(exp(-z/characteristic_depth), min_factor)`
  - `mode = "tabulated"` + `depths` + `factors` (+ `interpolation = "linear"|"step"`)

Unit notes:
- `K`: use `m/s` (other accepted inputs: `m/day`, `cm/s`, `cm/day`).
- `Sy`: use `-` (dimensionless standard).
- `Ss`: use `m-1` (also accepts `cm-1`).
- Internally, `FieldParam` stores values converted to SI units.

Mesh file (`mesh_config.toml`):
- `[mesh]`: `kind`, `target_n_cells`, optional `seed`

Spatial field file (`field_spatial_config.toml`):
- `[field]`: `id`, `line`, `zone1_side`, `zone1_name`, `zone2_name`

## How To Run

From repository root (square case):

```bash
python hydromodpy/field/cases/square/run_field_demo.py
```

Useful option:

```bash
python hydromodpy/field/cases/square/run_field_demo.py --no-show-plot
```

Default output:
- `hydromodpy/field/cases/square/outputs/field_demo.png`

Standalone geology run (no external mesh):

```bash
python hydromodpy/data_managers/geology/cases/run_geology_map_case.py
```

Default output:
- `hydromodpy/data_managers/geology/cases/outputs/geology_france_global.png`

Geology-to-property transfer demo via `FieldParam`:

```bash
python hydromodpy/data_managers/geology/cases/run_geology_property_case.py
```

Default output:
- `hydromodpy/data_managers/geology/cases/outputs/geology_property_demo.png`

In this geology demo:
- value correspondence can be inline TOML or CSV (`values_source`),
- CSV can include extra descriptive columns (for example `geology_name`),
- figure layout follows square-case style with three panels.

## Tests

```bash
python -m pytest tests/unit/field -q
```

## UML

- Canonical UML sources: `docs/readthedocs/source/architecture/field/diagrams/`
- Architecture page: `docs/readthedocs/source/architecture/field/field-uml-diagrams.rst`
