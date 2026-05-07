"""Workspace scaffolding.

Called by ``hmp init`` to create the HydroModPy workspace:
drag-and-drop custom data folders, cache, and a projects/ directory.

Called by ``hmp new <project>`` to create a project inside the workspace.

The custom folders (``{variable}_custom/``) are the primary drop zone for
user-provided data. Files dropped in these folders are picked up by
``hydromodpy.data.auto_scan`` at the start of every ``hmp run``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path.home() / "hydromodpy"


@dataclass(frozen=True, slots=True)
class VariableSpec:
    """One drag-and-drop variable exposed at ``hmp init``."""

    name: str
    kind: str  # "timeseries" | "raster" | "vector"
    unit: str
    label_fr: str
    pivot: str  # parquet | geoparquet | geotiff_cog | netcdf


VARIABLES: tuple[VariableSpec, ...] = (
    VariableSpec("hydrometry", "timeseries", "m3/s", "debits", "parquet"),
    VariableSpec("piezometry", "timeseries", "m", "niveaux piezometriques", "parquet"),
    VariableSpec("water_quality", "timeseries", "mg/L", "qualite des eaux", "parquet"),
    VariableSpec("recharge", "timeseries", "mm/day", "recharge", "parquet"),
    VariableSpec("precipitation", "timeseries", "mm/day", "precipitations", "parquet"),
    VariableSpec("etp", "timeseries", "mm/day", "evapotranspiration", "parquet"),
    VariableSpec("temperature", "timeseries", "degC", "temperature", "parquet"),
    VariableSpec("wind", "timeseries", "m/s", "vent", "parquet"),
    VariableSpec("humidity", "timeseries", "%", "humidite", "parquet"),
    VariableSpec("radiation", "timeseries", "W/m2", "rayonnement", "parquet"),
    VariableSpec("soil_moisture", "timeseries", "-", "humidite du sol", "parquet"),
    VariableSpec("runoff", "timeseries", "mm/day", "ruissellement", "parquet"),
    VariableSpec("oceanic", "timeseries", "m", "niveau marin", "parquet"),
    VariableSpec("dem", "raster", "m", "modele numerique de terrain", "geotiff_cog"),
    VariableSpec("geology", "vector", "-", "carte geologique", "geoparquet"),
    VariableSpec("hydrography", "vector", "-", "reseau hydrographique", "geoparquet"),
)


LOC_HEADER = "id,x,y,crs,unit\n"
CHRONICLE_HEADER = "datetime,value\n"


_README_TIMESERIES = """\
# {name}_custom - drag-and-drop for {label_fr}

Drop your files into this folder and run `hmp run`. HydroModPy will auto-scan
new or modified files, validate them, and index them in `data/cache.duckdb`
with `provider="custom"`.

## Expected layout

```
{name}_custom/
├── example_locations.csv        # station coordinates (template provided)
└── chronicles/
    ├── <STATION_ID>.csv         # time series per station
    └── ...
```

## Station location file (`example_locations.csv`)

Tabular file with one row per station:

| column | required | type   | description                               |
|--------|----------|--------|-------------------------------------------|
| id     | yes      | string | unique alphanumeric station identifier    |
| x      | yes      | float  | X coordinate in the given CRS             |
| y      | yes      | float  | Y coordinate in the given CRS             |
| crs    | yes      | string | EPSG code (e.g. `EPSG:4326`, `EPSG:2154`) |
| unit   | yes      | string | measurement unit (e.g. `{unit}`)          |

## Chronicle file (`chronicles/<STATION_ID>.csv`)

One file per station, named after its `id` column:

| column   | required | type          | description                    |
|----------|----------|---------------|--------------------------------|
| datetime | yes      | ISO-8601 text | timestamp (tz-aware preferred) |
| value    | yes      | float         | measurement in `{unit}`        |

## Power-user commands (optional)

- `hmp data check --variable {name}` - validate files without ingesting.
- `hmp data list --variable {name}` - list indexed artefacts.
- `hmp data add <file> --type {name}` - explicit ingest with metadata.
"""


_README_RASTER = """\
# {name}_custom - drag-and-drop for {label_fr}

Drop raster files (GeoTIFF or Esri ASCII grid) into this folder and run
`hmp run`. HydroModPy converts ASC to Cloud Optimized GeoTIFF (COG)
internally and indexes the artefact in `data/cache.duckdb`.

## Accepted formats

| user format          | internal pivot      |
|----------------------|---------------------|
| GeoTIFF (`*.tif`)    | COG GeoTIFF         |
| Esri ASCII (`*.asc`) | COG GeoTIFF         |

Each file must carry its CRS (either via tags for GeoTIFF or via a `.prj`
sidecar for ASC). Units ({unit}) and nodata values are read from the file.

## Power-user commands (optional)

- `hmp data check --variable {name}` - validate files without ingesting.
- `hmp data list --variable {name}` - list indexed artefacts.
- `hmp data add <file> --type {name}` - explicit ingest with metadata.
"""


_README_VECTOR = """\
# {name}_custom - drag-and-drop for {label_fr}

Drop vector files (Shapefile, GeoJSON, GeoPackage, or GeoParquet) into
this folder and run `hmp run`. HydroModPy converts everything to
GeoParquet internally and indexes the artefact in `data/cache.duckdb`.

## Accepted formats

| user format               | internal pivot |
|---------------------------|----------------|
| Shapefile (`*.shp` + ...) | GeoParquet     |
| GeoJSON (`*.geojson`)     | GeoParquet     |
| GeoPackage (`*.gpkg`)     | GeoParquet     |
| GeoParquet (`*.parquet`)  | GeoParquet     |

Each file must carry its CRS. For `.shp`, the `.prj` sidecar is required.

## Power-user commands (optional)

- `hmp data check --variable {name}` - validate files without ingesting.
- `hmp data list --variable {name}` - list indexed artefacts.
- `hmp data add <file> --type {name}` - explicit ingest with metadata.
"""


def _render_readme(spec: VariableSpec) -> str:
    template = {
        "timeseries": _README_TIMESERIES,
        "raster": _README_RASTER,
        "vector": _README_VECTOR,
    }[spec.kind]
    return template.format(name=spec.name, label_fr=spec.label_fr, unit=spec.unit)


def _render_example_locations(spec: VariableSpec) -> str:
    return (
        f"# example_locations.csv - {spec.label_fr}\n"
        "# Fill one row per station. Header is mandatory.\n"
        "# Lines starting with '#' are ignored.\n"
        + LOC_HEADER
        + f"# STATION_01,-1.68,48.12,EPSG:4326,{spec.unit}\n"
        + f"# STATION_02,350123.4,6789012.1,EPSG:2154,{spec.unit}\n"
    )


def _render_example_chronicle(spec: VariableSpec) -> str:
    return (
        f"# Example chronicle - {spec.label_fr} ({spec.unit})\n"
        "# Rename this file after the id column of example_locations.csv.\n"
        + CHRONICLE_HEADER
        + "# 2020-01-01,0.0\n"
    )


PROJECT_TOML_TEMPLATE = """\
# ===========================================================================
# HydroModPy - Project configuration
# ===========================================================================
# Project : {project_name}
#
# This file defines shared settings for all runs in this project:
# geographic support, domain, data sources, and flow parameters.
#
# Run files (run_*.toml) inherit from this file via:
#   base_config = "project.toml"
# ===========================================================================


[geographic]
source_mode = "synthetic"

[geographic.synthetic]
case_id = "{project_name}_synthetic"

[geographic.synthetic.grid]
length_x = "1000 m"
length_y = "1000 m"
nx = 20
ny = 20

[geographic.synthetic.topography]
kind = "linear"
base_elevation = 20.0
right_to_left_amplitude = 5.0

[data]
types = []

[domain]

[domain.depth_model]
kind = "constant_thickness"
thickness = "50 m"

[flow]
flow_regime = "steady"
param_list = ["K", "Sy"]

[flow.param.K.field]
kind = "homogeneous"
value = "1.0e-4 m/s"

[flow.param.Sy.field]
kind = "homogeneous"
value = "0.12 -"
"""

RUN_TOML_TEMPLATE = """\
# ===========================================================================
# HydroModPy - Run configuration
# ===========================================================================
# Run : {run_name}
# Inherits from : project.toml
# ===========================================================================

base_config = "project.toml"

[workflow]
mode = "simulation"

[workspace]
project_root = "."

[simulation]
name = "{run_name}"
description = "Scaffolded synthetic steady-flow run."

[simulation.time]
start_datetime = "2000-01-01T00:00:00"
end_datetime = "2000-12-31T00:00:00"
step_value = "1 year"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflownwt"]
"""


def scaffold(root_dir: str | Path | None = None) -> Path:
    """Create the HydroModPy workspace folder layout.

    Layout::

        <workspace>/
        |-- data/
        |   |-- cache.duckdb                (input cache, created on first run)
        |-- hydrometry_custom/
        |   |-- README.md
        |   |-- example_locations.csv
        |   |-- chronicles/
        |       |-- EXAMPLE.csv
        |-- piezometry_custom/ ...
        |-- dem_custom/
        |   |-- README.md
        |-- geology_custom/
        |   |-- README.md
        |-- projects/                       (empty, ready for hmp new)

    Idempotent for user-authored files (custom locations, chronicles,
    READMEs) - they are never overwritten. Simulation catalogs and
    ``simulations/`` directories are project-local.
    """
    root = Path(root_dir).expanduser().resolve() if root_dir else DEFAULT_ROOT
    root.mkdir(parents=True, exist_ok=True)

    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "projects").mkdir(parents=True, exist_ok=True)

    for spec in VARIABLES:
        var_dir = root / f"{spec.name}_custom"
        var_dir.mkdir(parents=True, exist_ok=True)

        readme = var_dir / "README.md"
        if not readme.exists():
            readme.write_text(_render_readme(spec), encoding="utf-8")

        if spec.kind == "timeseries":
            loc_path = var_dir / "example_locations.csv"
            if not loc_path.exists():
                loc_path.write_text(_render_example_locations(spec), encoding="utf-8")

            chronicles = var_dir / "chronicles"
            chronicles.mkdir(parents=True, exist_ok=True)
            example = chronicles / "EXAMPLE.csv"
            if not example.exists():
                example.write_text(_render_example_chronicle(spec), encoding="utf-8")

    return root


def create_project(workspace_root: Path, name: str) -> Path:
    """Create a new project inside the workspace.

    Structure::

        projects/<name>/
            project.toml      <- base template
            run_demo.toml     <- executable template

    Returns the project directory path.
    """
    workspace_root = Path(workspace_root).expanduser().resolve()
    project_dir = workspace_root / "projects" / name
    project_dir.mkdir(parents=True, exist_ok=True)

    project_toml = project_dir / "project.toml"
    if not project_toml.exists():
        project_toml.write_text(
            PROJECT_TOML_TEMPLATE.format(project_name=name),
            encoding="utf-8",
        )

    run_toml = project_dir / "run_demo.toml"
    if not run_toml.exists():
        run_toml.write_text(
            RUN_TOML_TEMPLATE.format(run_name="demo"),
            encoding="utf-8",
        )

    return project_dir
