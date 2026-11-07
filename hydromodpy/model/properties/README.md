# model/properties

This package gives a parameter such as K, Sy or Ss a value in every cell. A parameter is one number for
the whole domain, or one number per zone (geology class, band, ring), and it can fall with depth. The
package reads the zone map on the cells of a mesh, weights each zone value by the share of the zone in
the cell, and returns one value per cell. `property_table.py` then maps the properties of a flow onto the
cells for every solver, in one place. The TOML sections of a field parameter live in
`core/config_kit/field_param/`, because `model/flow_config.py` reads them too. The unit-square mesh and
the two-zone field serve the demos of `tools/cases/field/` and the tests.

## How the work flows

1. A `FieldParam` (`field_param.py`) holds the values of one parameter in SI units, and its depth profile
   if it has one. It is read from a TOML file or a mapping by `field_param_io.py`, and checked by
   `core/config_kit/field_param/config.py`.
2. A `Field` (`field_spatial.py`) is a zone map. Its `on_mesh` method cuts a mesh into zones and returns,
   for each zone, the share of every cell.
3. The shares come from sample points in each cell (`cell_sampling.py`) or from the polygons of the zones
   (`zone_fractions.py`).
4. `FieldParam.to_mesh_field` weights the zone values with the shares, applies the depth factor of
   `vertical_profile.py`, and returns a `MeshWithValues` (`mesh_cells.py`), the mesh with one value per
   cell.
5. `property_table.map_flow_properties` does this for K, Kv, Sy, Ss and the K tensor of a flow, per layer
   for MODFLOW and once for Boussinesq, and refuses a conductivity or a storage that is not positive.
   `resolve_flow_property_runtime_overrides` applies the values a calibration trial writes, and
   `resolve_required_flow_properties` lists the properties a regime needs.

The bands, rings and catchment zones that a project uses are built in `model/domain/`. This package holds
the base class they derive from, the geology field `GeologyField`, and `FieldSquare`.

## Modules

| module | answers |
|---|---|
| `cell_sampling.py` | Deterministic interior sampling of mesh cells for support-field fractions |
| `field_param.py` | Field parameter container supporting homogeneous and heterogeneous values |
| `field_param_io.py` | The loader of a `FieldParam` from TOML and CSV |
| `field_spatial.py` | Generic field interface and shared discretization structure |
| `geology_config.py` | Geology polygons or raster a mesh follows, and one geology field definition |
| `geology_field.py` | Geology spatial field for heterogeneous parameter mapping on simulation meshes |
| `mesh_cells.py` | The cells of a `PlanarCellMesh`, `MeshWithValues` and the square grid builder |
| `physical_properties.py` | `FlowPhysicalProperties`, the properties of a flow with their units |
| `plotting.py` | Draw one value per cell of a planar mesh on a matplotlib axes |
| `property_ids.py` | The one table of the ids of `[flow.param.<id>]` |
| `property_table.py` | The one mapping of K, Kv, Sy, Ss and the rest of the K tensor onto the cells of a mesh |
| `two_zone_field.py` | `FieldSquare`, a field of two zones split by a line |
| `unit_square_mesh.py` | The meshes of the unit square used by the demos |
| `vertical_profile.py` | Depth profile of a field parameter: a multiplicative factor f(depth) |
| `zone_fractions.py` | Zone fractions of a spatial support on the cells of a planar cell mesh |

`__init__.py` exports no name. A name is imported from the module that defines it.

## Where to start

| To change | Open first |
|---|---|
| a key of the field-parameter TOML | `core/config_kit/field_param/sections.py`, then `config.py` there |
| the accepted units or their aliases | `core/config_kit/field_param/units.py` |
| the depth profile | `vertical_profile.py`, then `FieldVerticalProfileSection` in `core/config_kit/field_param/sections.py` |
| how zone values become one value per cell | `FieldParam.to_mesh_field` in `field_param.py`, then `WeightedAverageFieldDiscretization` in `field_spatial.py` |
| the sample points in a cell | `cell_sampling.py` |
| the share of a zone in a cell | `zone_fractions.py` |
| the geology field | `geology_config.py` and `geology_field.py` |
| the ids of `[flow.param.<id>]` | `property_ids.py` |
| how the properties reach the cells of a solver | `property_table.py` |
| a new kind of zone map | `Field` in `field_spatial.py`, then `model/domain/support_fields.py` |

## Rules between the modules

The package reads `core`, `schema` and, until `spatial` is emptied, the mesh model in `mesh/planar/`.

- `geology_config.py` reads `core` and no mesh. `field_param_io.py` reads `field_param.py`,
  `core.config_kit.field_param.config` and `field_spatial.py`.
- `field_param.py` reads `core.units`, `core.config_kit.field_param.units`, `mesh_cells.py` and
  `vertical_profile.py`. `vertical_profile.py` reads `mesh_cells.py` and `core.units`.
- `mesh_cells.py`, `plotting.py`, `field_spatial.py`, `zone_fractions.py` and `unit_square_mesh.py` read
  the mesh model. The mesh never imports this package.
- `cell_sampling.py` reads `mesh_cells.py`. It imports `PlanarCellMesh` only for typing.
- `geology_field.py` reads `spatial.protocols` for the geology data source, so it imports no `data`
  module.
- `property_table.py` reads `property_ids.py`, `time/regime.py`, `field_spatial.py`, `zone_fractions.py`
  and `core`.
- Nothing in this package imports `model/domain/`. The domain reads `Field` and `cell_sampling` from here.

## What lives outside the package

The geology data is managed in `data/variables/geology/`, and `field.py` there builds a `GeologyField`
from the loaded data. The geology demo that goes through `FieldParam` is
`tools/cases/geology/run_geology_property_case.py`. The solvers call `property_table.py` from their
builders, for example `solver/modflow6/support/property_mapping.py`. The flow config embeds the
field-parameter sections in `FlowParam` (`model/flow_config.py`).

## Changing the code

The unit tests are in `tests/unit/model/properties/`, and a test file carries the name of the module it
tests. The cell meshes, TOML files and geology maps come from `tests/_helpers/field_cases.py`. The CI job
`mesh-coverage` in `.github/workflows/main-ci.yml` keeps a coverage floor for this package.

```bash
pytest tests/unit/model/properties -q
```

A new key of the field-parameter TOML is a field of a Pydantic model in
`core/config_kit/field_param/sections.py`, with its description. The parameter reference is built from
the models. The square demos run from the repository root with
`python -m tools.cases.field.square.run_field_demo`. The developer page of this layer is
`docs/source/contribute/architecture/field/index.rst`, and the theory is in
`docs/source/theory/solvers/field-to-cell-parameter-transfer.md`.
