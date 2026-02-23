# Field

`hydromodpy/field/` provides generic field parameterization utilities
(homogeneous and heterogeneous), plus a square-case example with mesh support.

## Directory Map

```text
hydromodpy/field/
|-- core/
|   |-- field_param.py
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
|-- uml/
|   |-- field_classes.wsd
|   |-- field_activity.wsd
|   `-- field_sequence.wsd
|-- __init__.py
`-- README.md
```

## Structure (What Goes Where)

- `core/`: generic interfaces and reusable implementations.
- `core/field_param.py`: parameter values, config loading, and mapping rules.
- `core/field_spatial.py`: abstract field geometry contract and abstract
  discretization contract.
- `core/field_spatial_weighted_discretization.py`: weighted-fraction
  discretization implementation.
- `core/field_mesh.py`: abstract mesh contracts (`BaseFieldMesh`, `FieldMesh`)
  and generic containers (`MeshCell`, `MeshWithValues`).
- `cases/square/`: concrete square geometry, concrete mesh factory, runnable
  demonstration, and example TOML files.
- `uml/`: PlantUML diagrams describing class structure and execution flows.

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
- `[field]`: `id`, `kind`
- `[field_homogeneous]`: `value`
- `[field_heterogeneous]`: `values`, `field_spatial_id`

Mesh file (`mesh_config.toml`):
- `[mesh]`: `kind`, `target_n_cells`, optional `seed`

Spatial field file (`field_spatial_config.toml`):
- `[field]`: `id`, `line`, `zone1_side`, `zone1_name`, `zone2_name`

## How To Run

From repository root:

```bash
python hydromodpy/field/cases/square/run_field_demo.py
```

Useful option:

```bash
python hydromodpy/field/cases/square/run_field_demo.py --no-show-plot
```

Default output:
- `hydromodpy/field/cases/square/outputs/field_demo.png`

## Tests

```bash
python -m pytest tests/unit/field -q
```

## UML

- Class diagram: `hydromodpy/field/uml/field_classes.wsd`
- Activity diagram: `hydromodpy/field/uml/field_activity.wsd`
- Sequence diagram: `hydromodpy/field/uml/field_sequence.wsd`
