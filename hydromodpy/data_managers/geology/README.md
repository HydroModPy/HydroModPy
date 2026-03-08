# Geology Case

This case adapts geology sources (raster or vector polygons) to the generic
`Field` interface so they can be used with `FieldParam` in heterogeneous mode.

## Why This Exists

The geology workflow separates two responsibilities:

- `GeologyField`: "where are the zones in space?"
- `FieldParam`: "what value does each zone receive?"

This is the same separation used in the rest of `field`:
- spatial structure in one object,
- physical values in another object.

That design makes calibration easier: geometry can stay fixed while values are
updated by optimization/calibration.

## Files

- `geology_field.py`:
  `GeologyField` implementation (`Field` subclass).
- `geology_mesh.py`:
  structured rectangular mesh used by geology property demo.
- `geology_config.py`:
  Pydantic schema and TOML loader/validator.
- `geology_io.py`:
  source loading, clipping, rasterization, and encoding.
- `geology_processing.py`:
  pure processing helpers (encoding/landsea override).
- `cases/common.py`:
  shared launcher helpers (path/output resolution, local clipping, axis format).
- `cases/run_geology_case.toml`:
  example configuration.
- `cases/run_geology_property_case.toml`:
  `FieldParam` configuration for geology-property mapping.
- `cases/data/geology_property_values.csv`:
  full correspondence table (`zone_key` -> `K_value`) with geology names.
- `cases/run_geology_property_case.py`:
  runnable demo of transfer `zone_key -> property` via `FieldParam`.
- `cases/run_geology_map_case.py`:
  standalone geology visualization (global or local window).

## Minimal Usage

```python
from hydromodpy.data_managers.geology import GeologyField
from hydromodpy.field.core.field_param import FieldParam

field = GeologyField.from_toml(
    "hydromodpy/data_managers/geology/cases/run_geology_case.toml",
    section="geology",
)

# Example heterogeneous values by geology code/key.
param = FieldParam(
    identifier="K",
    kind="heterogeneous",
    values_by_key={"1": 10.0, "2": 3.0},
    field_spatial_id="field_geology",
)

discretization = field.on_mesh(mesh)
values_mesh = param.to_mesh_field(discretization)
```

## FieldParam Mapping (Inline Or CSV)

For heterogeneous geology-to-property mapping, `FieldParam` now supports:
- inline table in TOML,
- CSV table (recommended when many geology units exist).

Example with CSV source:

```toml
[field]
id = "K"
kind = "heterogeneous"

[field_heterogeneous]
values_source = "csv"
values_csv_file = "data/geology_property_values.csv"
csv_key_column = "zone_key"
csv_value_column = "K_value"
field_spatial_id = "field_geology"
```

The CSV then contains the long correspondence list:
- `zone_key`,
- `geology_name` (human-readable unit name),
- property value column (`K_value` in this example).

## Brittany Data Paths

The shared Brittany dataset is now grouped by thematic data type:
- geology: `data/France/geology/`
- DEM: `data/Brittany/dem/`
- climate: `data/France/climate/`
- hydrometry stations: `data/France/hydrometry/`
- onde stations: `data/France/onde/`
- auxiliary notes: `data/France/docs/`

## Property Transfer Demo (`FieldParam`)

Run from repository root:

```bash
python hydromodpy/data_managers/geology/cases/run_geology_property_case.py
```

This demo:
1. loads geology polygons,
2. loads `FieldParam` from TOML,
3. resolves values from CSV,
4. builds one local `GeologyField` (derived from abstract `Field`) and one mesh,
5. applies the generic pipeline:
   `field.on_mesh(mesh, cell_samples_per_axis=...)` then
   `field_param.to_mesh_field(field_discretization)`.
6. renders one figure with three panels (same spirit as square case):
   - left: geology zones,
   - middle: value correspondence by zone,
   - right: mapped property values on mesh cells.

Default run uses one inland 10-km Brittany window (same preset as
`run_geology_map_case.py`).

Output behavior:
- by default: `hydromodpy/data_managers/geology/cases/outputs/geology_property_demo.png`
- if `--output-file` is only a filename (for example `demo.png`), it is
  automatically saved in `cases/outputs/demo.png`.

Useful options:
- `--target-n-cells` to control mesh size for mapping.
- `--cell-samples-per-axis` to control `on_mesh(...)` intra-cell sampling.

## Standalone Run (Global Geology Map)

You can run a standalone visual check of the geology case without any mesh:

```bash
python hydromodpy/data_managers/geology/cases/run_geology_map_case.py
```

This generates one figure with the global geology map and prints checks in
console, including:
- number of unique geology classes,
- top classes by polygon count.
- sea-uniformization status.

Sea polygons are uniformized by default (`TERRE_MER == "M"` -> `"SEA"`).
Disable it with:

```bash
python hydromodpy/data_managers/geology/cases/run_geology_map_case.py --no-uniform-sea
```

### Local 10-km Window in Brittany

Predefined Brittany window (10 km x 10 km):

```bash
python hydromodpy/data_managers/geology/cases/run_geology_map_case.py --bretagne-10km
```

Equivalent explicit coordinates in EPSG:2154:
- center `x=355000`, `y=6715000` (inland, no sea expected)

Custom local window:

```bash
python hydromodpy/data_managers/geology/cases/run_geology_map_case.py --center-x 355000 --center-y 6715000 --window-km 10
```

The figure includes a legend mapping colors to geology names.
On large maps, legend size is limited to keep readability. You can adjust:

```bash
python hydromodpy/data_managers/geology/cases/run_geology_map_case.py --max-legend-classes 50
```

Legend labels use geology names from attribute `LITHOLOGIE` by default.
You can choose another attribute:

```bash
python hydromodpy/data_managers/geology/cases/run_geology_map_case.py --legend-name-field LITHOLOGIE
```

When a local window is used, the output figure contains two panels in the same
window:
- left: local geology map,
- right: location of the studied window on a Brittany-scale map.

To save without opening the interactive window:

```bash
python hydromodpy/data_managers/geology/cases/run_geology_map_case.py --no-show-plot
```

Default output path:
- `hydromodpy/data_managers/geology/cases/outputs/geology_france_global.png`

Output behavior for `--output-file` is the same as above:
- bare filenames are redirected to `outputs/`,
- relative paths are resolved from `hydromodpy/data_managers/geology/cases/`.


