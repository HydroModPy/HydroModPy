# spatial/field

This package gives a parameter such as K, Sy or Ss a value in every cell. A parameter is one number for the whole domain, or one number per zone (geology class, band, ring), and it can fall with depth. The package reads the zone map on the cells of a mesh, weights each zone value by the share of the zone in the cell, and returns one value per cell. It also holds the TOML sections of a field parameter and a few small demos on a unit square.

## How the work flows

1. A `FieldParam` (`field_param.py`) holds the values of one parameter in SI units, and its depth profile if it has one. It is read from a TOML file or a mapping by `field_param_io.py`, and checked by `field_param_config.py`.
2. A `Field` (`field_spatial.py`) is a zone map. Its `on_mesh` method cuts a mesh into zones and returns, for each zone, the share of every cell.
3. The shares come from sample points in each cell (`cell_sampling.py`) or from the polygons of the zones (`zone_fractions.py`).
4. `FieldParam.to_mesh_field` weights the zone values with the shares, applies the depth factor of `vertical_profile.py`, and returns a `MeshWithValues` (`mesh_cells.py`), the mesh with one value per cell.

```text
field_param_config.toml          field_spatial_config.toml / geology / support
        |                                   |
        v                                   v
    FieldParam                           Field.on_mesh(cell_mesh)
        |                                   |
        +---------->  to_mesh_field  <------+
                           |
                           v
                    MeshWithValues
```

The bands, rings and catchment zones that a project uses are built in `spatial/domain/`. This package holds the base class they derive from, the geology field `GeologyField`, and `FieldSquare`.

## The folder map

```text
field/
├── field_param.py          FieldParam, values per parameter and the mapping to cells
├── field_param_config.py   the schema of a field-parameter TOML payload and its resolution
├── field_param_sections.py the sections of that payload, including the vertical profile
├── field_param_units.py    unit aliases and their normalization
├── field_param_io.py       the loader of a FieldParam from TOML and CSV
├── vertical_profile.py     the depth factor of a parameter
├── field_spatial.py        Field and FieldDiscretization, the weighted-fraction discretization
├── cell_sampling.py        the sample points of a cell and the zone shares they give
├── zone_fractions.py       the share of each zone in each cell, from polygons or engine zones
├── mesh_cells.py           the cells of a PlanarCellMesh, MeshWithValues, the square grid builder
├── geology_config.py       the config models of a geology field
├── geology_field.py        GeologyField, a field from geology classes
├── two_zone_field.py       FieldSquare, a field of two zones split by a line
├── unit_square_mesh.py     the meshes of the unit square used by the demos
├── plotting.py             plot_cell_values, one value per cell on a matplotlib axes
│
└── cases/                  the square demos
    ├── review_cases.py         runs the demos one after another for a visual review
    └── square/                 one demo on the unit square
        ├── run_field_demo.py       the launcher
        ├── field_param_config.toml the parameter of the demo
        ├── field_spatial_config.toml  the two-zone field of the demo
        └── mesh_config.toml        the mesh of the demo
```

`__init__.py` exports no names. A name is imported from the module that defines it, for example `FieldParam` from `field_param.py` and `FieldSquare` from `two_zone_field.py`.

## Where to start

| To change | Open first |
|-----------|------------|
| a key of the field-parameter TOML | `field_param_sections.py`, then `field_param_config.py` |
| the accepted units or their aliases | `field_param_units.py` |
| the depth profile | `vertical_profile.py`, then `FieldVerticalProfileSection` in `field_param_sections.py` |
| how zone values become one value per cell | `FieldParam.to_mesh_field` in `field_param.py`, then `WeightedAverageFieldDiscretization` in `field_spatial.py` |
| the sample points in a cell | `cell_sampling.py` |
| the share of a zone in a cell | `zone_fractions.py` |
| the geology field | `geology_config.py` and `geology_field.py` |
| a new kind of zone map | `Field` in `field_spatial.py`, then `spatial/domain/support_fields.py` |

## Rules between the folders

The package is part of the spatial layer, which may import `core`, `schema` and itself. The architecture tests check that rule.

- `field_param_units.py`, `field_param_sections.py`, `field_param_config.py` and `geology_config.py` read `core` and each other, and no mesh. `field_param_io.py` reads `field_param.py`, `field_param_config.py` and `field_spatial.py`.
- `field_param.py` reads `core.units`, `field_param_units.py`, `mesh_cells.py` and `vertical_profile.py`. `vertical_profile.py` reads `mesh_cells.py` and `core.units`.
- `mesh_cells.py`, `plotting.py`, `field_spatial.py`, `zone_fractions.py` and `unit_square_mesh.py` read the mesh model in `spatial/mesh/model/`. The mesh never imports this package.
- `cell_sampling.py` reads `mesh_cells.py`. It imports `PlanarCellMesh` only for typing.
- `geology_field.py` reads `spatial.protocols` for the geology data source, so it imports no `data` module.
- Nothing in this package imports `spatial/domain/`. The domain reads `Field` and `cell_sampling` from here.
- `field_param_config.py` imports `core.units.physical_bounds` inside the validator that checks the physical bounds of a value. The other imports of HydroModPy are at the top of their module, except in `cases/review_cases.py` below.
- `cases/review_cases.py` imports its four demo modules inside the function that runs them. The demo sets the matplotlib backend when it is imported, so listing the cases does not.
- `cases/square/run_field_demo.py` also reads `spatial/geographic/cases/plotting_utils.py` for the figure windows.

## What lives outside the package

The geology data is managed in `hydromodpy/data/variables/geology/`, and `field.py` there builds a `GeologyField` from the loaded data. The geology demo that goes through `FieldParam` is `hydromodpy/data/cases/geology/run_geology_property_case.py`.

The solvers read the parameter through `hydromodpy/solver/field_property_mapping.py`, which asks for the zone shares and the weighted discretization. The flow config embeds the field-parameter section (`hydromodpy/physics/flow/flow_param_config.py`), a tolerated edge in `layer_matrix.yaml`.

The supports a project declares in `[domain.supports]` live in `spatial/domain/`: the zone maps are built there and their zone shares are computed with `cell_sampling.py` from this package.

## Changing the code

The unit tests are in `tests/unit/field/`. A test file carries the name of the module it tests, for example `test_zone_fractions.py` for `zone_fractions.py`. `vertical_profile.py`, `field_param_sections.py` and `field_param_units.py` have no test file of their own. `test_field_param.py` and `test_field_param_config.py` cover them. `plotting.py` is covered by `test_plotting.py`, and the review launcher by `tests/unit/field/cases/test_review_cases.py`. The cell meshes, TOML files and geology maps of the tests come from `tests/_helpers/field_cases.py`.

`tests/contract/test_case_review_contract.py` checks the review launcher. The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` fails when the coverage of this package drops below 98.4.

```bash
pytest tests/unit/field -q
```

```bash
pytest tests/unit/architecture -q
```

A new key of the field-parameter TOML is a field of a Pydantic model in `field_param_sections.py`, with its description. The parameter reference is built from the models.

To run the square demo from the repository root:

```bash
python -m hydromodpy.spatial.field.cases.square.run_field_demo
```

## Documentation

- `docs/source/contribute/architecture/field/index.rst` is the developer page of this layer. Its UML sources are in `docs/source/contribute/architecture/field/diagrams/`.
- `docs/source/theory/solvers/field-to-cell-parameter-transfer.md` covers the weighted average, the depth factor and the shares of each zone in a cell.
- `docs/source/theory/groundwater-flow.md` covers the depth factor in the flow problem.
- `docs/source/contribute/architecture/mesh/mesh-pivot.rst` covers `FieldParam`, `Field` and the cell mesh.
- `docs/source/contribute/architecture/spatial_support/` covers the supports a field is zoned by.
- `docs/source/reference/parameters/flow/param.md` is the generated reference of the field-parameter section.
