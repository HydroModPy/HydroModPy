"""Workspace scaffolding.

Called by ``hmp workspace init`` to create the HydroModPy workspace: one
``data/<variable>/`` folder per variable, a shared cache, and a ``projects/``
directory.

Called by ``hmp new <project>`` to create a project inside the workspace.

Each ``data/<variable>/`` folder is a flat drop zone. The provider is encoded
in the file NAME, never in the directory: ``<variable>_custom_*`` for files the
user provides, ``<variable>_<api>_*`` for files HydroModPy downloads from an
API. Both live side by side. The runtime data loaders read these folders
directly (``hydromodpy.data.loading.store.DataStore``); ``hydromodpy.data.auto_scan``
indexes the custom files in ``data/cache.duckdb`` at the start of every
``hmp run``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME

DEFAULT_ROOT = Path.home() / "hydromodpy"


@dataclass(frozen=True, slots=True)
class VariableSpec:
    """One variable folder created under ``<workspace>/data/``."""

    name: str
    file_prefix: str  # filename token (e.g. water_quality -> "waterquality")
    category: str  # "point" | "grid" | "dem" | "geology" | "hydrography"
    kind: str  # auto_scan scanner: "timeseries" | "raster" | "vector"
    unit: str
    label_fr: str
    pivot: str  # parquet | geoparquet | geotiff_cog | netcdf


VARIABLES: tuple[VariableSpec, ...] = (
    VariableSpec("hydrometry", "hydrometry", "point", "timeseries", "m3/s", "debits", "parquet"),
    VariableSpec(
        "piezometry", "piezometry", "point", "timeseries", "m", "niveaux piezometriques", "parquet"
    ),
    VariableSpec(
        "intermittency",
        "intermittency",
        "point",
        "timeseries",
        "code",
        "etat d'ecoulement (ONDE)",
        "parquet",
    ),
    VariableSpec(
        "water_quality",
        "waterquality",
        "point",
        "timeseries",
        "mg/L",
        "qualite des eaux",
        "parquet",
    ),
    VariableSpec("recharge", "recharge", "grid", "timeseries", "mm/day", "recharge", "parquet"),
    VariableSpec(
        "precipitation",
        "precipitation",
        "grid",
        "timeseries",
        "mm/day",
        "precipitations",
        "parquet",
    ),
    VariableSpec("etp", "etp", "grid", "timeseries", "mm/day", "evapotranspiration", "parquet"),
    VariableSpec("runoff", "runoff", "grid", "timeseries", "mm/day", "ruissellement", "parquet"),
    VariableSpec(
        "temperature", "temperature", "grid", "timeseries", "degC", "temperature", "parquet"
    ),
    VariableSpec("wind", "wind", "grid", "timeseries", "m/s", "vent", "parquet"),
    VariableSpec("humidity", "humidity", "grid", "timeseries", "%", "humidite", "parquet"),
    VariableSpec(
        "radiation", "radiation", "grid", "timeseries", "MJ/m2/j", "rayonnement", "parquet"
    ),
    VariableSpec(
        "soil_moisture",
        "soil_moisture",
        "grid",
        "timeseries",
        "%",
        "humidite du sol",
        "parquet",
    ),
    VariableSpec("oceanic", "oceanic", "grid", "timeseries", "m", "niveau marin", "parquet"),
    VariableSpec("dem", "dem", "dem", "raster", "m", "modele numerique de terrain", "geotiff_cog"),
    VariableSpec("geology", "geology", "geology", "vector", "-", "carte geologique", "geoparquet"),
    VariableSpec(
        "hydrography",
        "hydrography",
        "hydrography",
        "vector",
        "-",
        "reseau hydrographique",
        "geoparquet",
    ),
    VariableSpec(
        "lake_geometry",
        "lake_geometry",
        "hydrography",
        "vector",
        "-",
        "emprise lac / reservoir",
        "geoparquet",
    ),
    VariableSpec(
        "lake_bathymetry",
        "lake_bathymetry",
        "dem",
        "raster",
        "m",
        "bathymetrie du lac",
        "geotiff_cog",
    ),
    VariableSpec(
        "lake_abacus",
        "lake_abacus",
        "table",
        "table",
        "m|m3|m2",
        "abaque hauteur-volume-surface",
        "parquet",
    ),
    VariableSpec(
        "lake_levels",
        "lake_levels",
        "point",
        "timeseries",
        "m",
        "niveaux de lac observes",
        "parquet",
    ),
    VariableSpec(
        "lake_inflow",
        "lake_inflow",
        "point",
        "timeseries",
        "m3/s",
        "apports volumiques au lac",
        "parquet",
    ),
    VariableSpec(
        "lake_outflow",
        "lake_outflow",
        "point",
        "timeseries",
        "m3/s",
        "debits sortants du lac",
        "parquet",
    ),
    VariableSpec(
        "lake_withdrawal",
        "lake_withdrawal",
        "point",
        "timeseries",
        "m3/s",
        "prelevements sur le lac",
        "parquet",
    ),
)


_README_HEADER = """\
# data/{name}/ - {label_fr}

Drop your `{name}` files in this folder. HydroModPy reads them directly: the
provider is encoded in the file NAME, not in a subfolder.

- `{prefix}_custom_*`  -> files you provide
- `{prefix}_<api>_*`   -> files HydroModPy downloads from an API (do not edit)

Files whose name contains `EXAMPLE` are templates shipped by
`hmp workspace init`. They are never loaded as data: replace them with your own
files using the same naming, or delete them.
"""

_README_POINT_BODY = """\
## Accepted formats

| role      | format                       | file name                                          |
|-----------|------------------------------|----------------------------------------------------|
| chronicle | CSV (`datetime,value`)       | `{prefix}_custom_<ID>_<start>_<end>_<freq>.csv`     |
| locations | CSV, SHP, GPKG, or GeoJSON   | `{prefix}_custom_LOC.csv` (or `.shp`/`.gpkg`/`.geojson`) |

- CSV location columns: `id,x,y,crs,unit` (one row per station).
- Vector location files carry an `id` attribute; the CRS comes from the geometry.
- `<freq>` is a pandas offset: `D` daily, `ME` month-end, `YE` year-end.

## Wire it in your run TOML

    [[data.{name}.sources]]
    source = "custom"
    path = "data/{name}"

## Example files in this folder

- `{prefix}_custom_LOC.csv` - empty template, add one row per station.
- `{prefix}_custom_EXAMPLE_20000101_20000131_D.csv` - chronicle format.
"""

_README_GRID_BODY = """\
## Accepted formats

| role          | format                     | file name                                       |
|---------------|----------------------------|-------------------------------------------------|
| stations      | CSV (`datetime,value`)     | `{prefix}_custom_<ID>_<start>_<end>_<freq>.csv` + `{prefix}_custom_LOC.csv` |
| grid, dynamic | NetCDF (`.nc`)             | `{prefix}_custom_<name>.nc`                      |
| grid, static  | GeoTIFF (`.tif`)           | `{prefix}_custom_<name>.tif`                     |

NetCDF needs a `crs` attribute and a `nodata` value. GeoTIFF needs its CRS and
nodata in the file.

## Wire it in your run TOML

    [[data.{name}.sources]]
    source = "custom"
    path = "data/{name}"                                 # directory of station CSVs
    # path = "data/{name}/{prefix}_custom_my_grid.nc"    # or a single grid file

## Example files in this folder

- `{prefix}_custom_LOC.csv` + `{prefix}_custom_EXAMPLE_20000101_20000131_D.csv` - station mode.
- `{prefix}_custom_EXAMPLE.nc` - dynamic grid. `{prefix}_custom_EXAMPLE.tif` - static grid.
"""

_README_DEM_BODY = """\
## Accepted formats

| format                | file name                       |
|-----------------------|---------------------------------|
| GeoTIFF (`.tif`/`.tiff`) | `dem_custom_<name>.tif`      |
| Esri ASCII (`.asc`)   | `dem_custom_<name>.asc`         |
| NetCDF (`.nc`)        | `dem_custom_<name>.nc`          |

Each file must carry its CRS: GeoTIFF tags, a `.prj` sidecar for `.asc`, or a
`crs` attribute for `.nc`.

## Wire it in your run TOML

    [[data.dem.sources]]
    source = "custom"
    path = "data/dem/dem_custom_my_dem.tif"   # a file, or "data/dem" for a directory

## Example files in this folder

- `dem_custom_EXAMPLE.tif`, `dem_custom_EXAMPLE.asc`, `dem_custom_EXAMPLE.nc`.
"""

_README_GEOLOGY_BODY = """\
## Accepted formats

| type   | format                   | notes                                             |
|--------|--------------------------|---------------------------------------------------|
| vector | SHP, GPKG, GeoJSON       | needs `code_field` (attribute holding geology codes) |
| raster | GeoTIFF (`.tif`/`.tiff`) | numeric class per pixel                           |
| points | CSV (`x,y,geology_code`) | interpolated to polygons (Voronoi)                |

## Wire it in your run TOML

    [[data.geology.sources]]
    source = "custom"
    path = "data/geology/geology_custom_my_map.gpkg"
    code_field = "CODE"                       # vector sources only

## Example files in this folder

- `geology_custom_EXAMPLE.gpkg`, `.shp`, `.geojson` - vector, attribute `CODE`.
- `geology_custom_EXAMPLE.tif` - raster classes. `geology_custom_EXAMPLE.csv` - Voronoi points.
"""

_README_HYDROGRAPHY_BODY = """\
## Accepted formats

| type   | format                   | notes                          |
|--------|--------------------------|--------------------------------|
| vector | SHP, GPKG, GeoJSON       | lines (stream network) or polygons |
| raster | GeoTIFF (`.tif`/`.tiff`) | stream mask                    |

## Wire it in your run TOML

    [[data.hydrography.sources]]
    source = "custom"
    path = "data/hydrography/hydrography_custom_my_network.gpkg"

## Example files in this folder

- `hydrography_custom_EXAMPLE.gpkg`, `.shp`, `.geojson` - vector network.
- `hydrography_custom_EXAMPLE.tif` - raster mask.
"""

_README_TABLE_BODY = """\
## Accepted formats

| format                       | file name                              |
|------------------------------|----------------------------------------|
| CSV (`stage,volume,sarea`)   | `{prefix}_custom_<lake_id>.csv`        |
| Parquet                      | `{prefix}_custom_<lake_id>.parquet`    |

`stage` (m) must be strictly increasing per lake; `volume` (m3) and `sarea`
(m2) must be non-negative. A `lake_id` column is optional: when omitted it is
taken from the file name.

## Wire it in your run TOML

    [[data.{name}.sources]]
    source = "custom"
    path = "data/{name}/{prefix}_custom_lac0.csv"
    lake_id = "lac0"

## Example files in this folder

- `{prefix}_custom_EXAMPLE.csv` - stage/volume/sarea abacus.
"""

_README_FOOTER = """\
## Validate without running a simulation

- `hmp data check --variable {name}` - validate dropped files, no ingestion.
- `hmp data list --variable {name}` - list what is indexed in the cache.
"""

_README_BODY = {
    "point": _README_POINT_BODY,
    "grid": _README_GRID_BODY,
    "dem": _README_DEM_BODY,
    "geology": _README_GEOLOGY_BODY,
    "hydrography": _README_HYDROGRAPHY_BODY,
    "table": _README_TABLE_BODY,
}


def _render_readme(spec: VariableSpec) -> str:
    body = _README_BODY[spec.category]
    parts = (_README_HEADER, body, _README_FOOTER)
    return "\n".join(
        part.format(name=spec.name, prefix=spec.file_prefix, label_fr=spec.label_fr)
        for part in parts
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
solvers = ["modflow_nwt"]
"""


EXAMPLE_PROJECT_NAME = "example"

PROJECTS_README = """\
# projects/ - your HydroModPy projects

Each project lives in its own subfolder here, e.g. `projects/example/`. You
work *inside* a project folder, never directly in `projects/`.

A project folder holds:

- `project.toml` - shared settings (geographic, domain, data, flow).
- `run_*.toml`      - one runnable configuration each, inheriting the above.

Create a new project:

    hmp project new <name>

Then run it:

    hmp run projects/<name>/run_demo.toml

`projects/example/` is a ready-to-run synthetic demo. Copy it or start fresh.
"""

PROJECT_GITIGNORE = """\
# HydroModPy generated artefacts - do not edit or commit.
# Internal runtime (index, trash, scratch, logs) lives under .hmp/.
.hmp/
runs/
sessions/
share/
"""


def scaffold(root_dir: str | Path | None = None, *, with_examples: bool = True) -> Path:
    """Create the HydroModPy workspace folder layout.

    Layout::

        <workspace>/
        |-- data/
        |   |-- cache.duckdb              (input cache, created on first run)
        |   |-- hydrometry/
        |   |   |-- README.md
        |   |   |-- hydrometry_custom_LOC.csv
        |   |   |-- hydrometry_custom_EXAMPLE_20000101_20000131_D.csv
        |   |-- geology/
        |   |   |-- README.md
        |   |   |-- geology_custom_EXAMPLE.gpkg / .shp / .geojson / .tif / .csv
        |   |-- dem/ ...
        |-- projects/
        |   |-- README.md                 (how projects are organised)
        |   |-- example/                  (ready-to-run synthetic demo project)
        |   |   |-- project.toml
        |   |   |-- run_demo.toml

    Each ``data/<variable>/`` folder ships a README plus one example file per
    accepted input format. ``projects/`` gets a README and an ``example/``
    starter project so the ``projects/<name>/`` convention is obvious. Example
    files carry the ``EXAMPLE`` id token and are never loaded as data.
    Idempotent for user files: existing READMEs and data files are never
    overwritten. Pass ``with_examples=False`` to skip the (geospatial) data
    examples and the example project.
    """
    root = Path(root_dir).expanduser().resolve() if root_dir else DEFAULT_ROOT
    root.mkdir(parents=True, exist_ok=True)

    data_root = root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    (root / "projects").mkdir(parents=True, exist_ok=True)

    for spec in VARIABLES:
        var_dir = data_root / spec.name
        var_dir.mkdir(parents=True, exist_ok=True)

        readme = var_dir / "README.md"
        if not readme.exists():
            readme.write_text(_render_readme(spec), encoding="utf-8")

        if with_examples:
            from hydromodpy.data.scaffold_examples import write_variable_examples

            write_variable_examples(
                var_dir,
                category=spec.category,
                file_prefix=spec.file_prefix,
                unit=spec.unit,
            )

    projects_readme = root / "projects" / "README.md"
    if not projects_readme.exists():
        projects_readme.write_text(PROJECTS_README, encoding="utf-8")

    if with_examples:
        # A ready-to-run demo so the projects/<name>/ convention is obvious:
        # work inside a project subfolder, not directly in projects/.
        create_project(root, EXAMPLE_PROJECT_NAME)

    return root


def create_project(workspace_root: Path, name: str) -> Path:
    """Create a new project inside the workspace.

    Structure::

        projects/<name>/
            project.toml   <- base template
            run_demo.toml     <- executable template

    Returns the project directory path.
    """
    workspace_root = Path(workspace_root).expanduser().resolve()
    project_dir = workspace_root / "projects" / name
    project_dir.mkdir(parents=True, exist_ok=True)

    project_toml = project_dir / PROJECT_MARKER_FILENAME
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

    gitignore = project_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(PROJECT_GITIGNORE, encoding="utf-8")

    return project_dir
