"""Workspace scaffolding.

Called by ``hmp init`` to create the HydroModPy workspace:
shared data, catalog, and a projects/ directory.

Called by ``hmp new <name>`` to create a project inside the workspace.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_ROOT = Path.home() / "hydromodpy"

# Variables with custom data support.
# (folder_name, loc_prefix, unit, label_fr)
VARIABLES = [
    ("hydrometry", "hydrometry_custom", "m3/s", "debits"),
    ("piezometry", "piezometry_custom", "m", "niveaux piezometriques"),
    ("water_quality", "waterquality_custom", "mg/L", "qualite des eaux"),
    ("recharge", "recharge_custom", "mm/day", "recharge"),
    ("precipitation", "precipitation_custom", "mm/day", "precipitations"),
    ("etp", "etp_custom", "mm/day", "evapotranspiration"),
    ("temperature", "temperature_custom", "degC", "temperature"),
    ("wind", "wind_custom", "m/s", "vent"),
    ("humidity", "humidity_custom", "%", "humidite"),
    ("radiation", "radiation_custom", "W/m2", "rayonnement"),
    ("soil_moisture", "soilmoisture_custom", "-", "humidite du sol"),
    ("runoff", "runoff_custom", "mm/day", "ruissellement"),
    ("oceanic", "oceanic_custom", "m", "niveau marin"),
]

LOC_HEADER = "id,x,y,crs,unit\n"

CHRONICLE_HEADER = "datetime,value\n"
CHRONICLE_EXAMPLE = "# 2020-01-01,0.0\n"


PROJECT_TOML_TEMPLATE = """\
# ===========================================================================
# HydroModPy — Project configuration
# ===========================================================================
# Project : {project_name}
#
# This file defines the shared settings for all runs in this project:
# geographic, domain, data sources, and flow parameters.
#
# Run files (run_*.toml) inherit from this file via:
#   base_config = "project.toml"
# ===========================================================================


# --- Geographic -----------------------------------------------------------

[geographic]
catch_def = "from_outlet_coord"
# x_outlet = -1.68
# y_outlet = 48.12
# dem_init_path = "../../data/dem/DEM_armorican_massif.tif"


# --- Domain ---------------------------------------------------------------

[domain]
domain_depth = 50.0


# --- Data -----------------------------------------------------------------

[data]
# types = ["geology", "hydrometry", "piezometry"]


# --- Flow -----------------------------------------------------------------

[flow]
# param_list = ["K", "Sy"]
"""

RUN_TOML_TEMPLATE = """\
# ===========================================================================
# HydroModPy — Run configuration
# ===========================================================================
# Run : {run_name}
# Inherits from : project.toml
# ===========================================================================

base_config = "project.toml"

[workspace]
project_root = "."

[simulation]
name = "{run_name}"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflownwt"]
"""


def scaffold(root_dir: str | Path | None = None) -> Path:
    """Create the HydroModPy workspace.

    Structure:
        hydromodpy/
            data/cache.duckdb                   <- data cache (DuckDB)
            data/
                hydrometry/
                    hydrometry_custom_LOC.csv
                    hydrometry_custom_EXAMPLE_20200101_20201231_D.csv
                piezometry/ ...
                water_quality/ ...
            projects/                           <- empty, ready for hmp new

    Returns the workspace root path.
    """
    root = Path(root_dir).resolve() if root_dir else DEFAULT_ROOT
    root.mkdir(parents=True, exist_ok=True)

    # data/ with variable subdirectories
    data_dir = root / "data"
    for folder, prefix, unit, label in VARIABLES:
        var_dir = data_dir / folder
        var_dir.mkdir(parents=True, exist_ok=True)

        loc_path = var_dir / f"{prefix}_LOC.csv"
        if not loc_path.exists():
            loc_path.write_text(
                f"# Localisation des stations - {label}\n"
                f"# Remplir une ligne par station\n"
                + LOC_HEADER
                + f"# STATION_01,-1.68,48.12,EPSG:4326,{unit}\n"
            )

        example_path = var_dir / f"{prefix}_EXAMPLE_20200101_20201231_D.csv"
        if not example_path.exists():
            example_path.write_text(
                f"# Chronique exemple - {label} ({unit})\n"
                f"# Renommer ce fichier : {prefix}_<ID>_YYYYMMDD_YYYYMMDD_D.csv\n"
                f"# ou <ID> correspond a l'identifiant dans le fichier LOC\n"
                + CHRONICLE_HEADER
                + CHRONICLE_EXAMPLE
            )

    # projects/ directory (empty, ready for hmp new)
    projects_dir = root / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    return root


def create_project(workspace_root: Path, name: str) -> Path:
    """Create a new project inside the workspace.

    Structure:
        projects/<name>/
            project.toml      <- base template
            run_demo.toml     <- executable template

    Returns the project directory path.
    """
    workspace_root = Path(workspace_root).resolve()
    project_dir = workspace_root / "projects" / name
    project_dir.mkdir(parents=True, exist_ok=True)

    project_toml = project_dir / "project.toml"
    if not project_toml.exists():
        project_toml.write_text(
            PROJECT_TOML_TEMPLATE.format(project_name=name)
        )

    run_toml = project_dir / "run_demo.toml"
    if not run_toml.exists():
        run_toml.write_text(
            RUN_TOML_TEMPLATE.format(run_name="demo")
        )

    return project_dir
