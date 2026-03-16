"""Workspace scaffolding.

Called by ``hmp init`` to create the HydroModPy workspace:
shared data, cache, and an example watershed project.
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


BV_CONFIG_TEMPLATE = """\
# ===========================================================================
# HydroModPy - Configuration data_managers
# ===========================================================================
# Bassin versant : {bv_name}
#
# Les donnees custom sont dans le dossier partage ../data/
# Les telechargements API sont aussi sauves dans ../data/<variable>/
# Le registre de metadonnees est dans ../catalog.db
#
# Utilisation :
#
#   from hydromodpy.data_managers.store import DataStore
#   from hydromodpy.data_managers.variables.hydrometry.config import HydrometryConfig
#
#   store = DataStore(
#       workspace_root="{root_path}",
#       project_period=(datetime(2015, 1, 1), datetime(2023, 12, 31)),
#       project_extent=(-1.9, 47.8, -1.3, 48.4),  # bbox du bassin
#   )
#   cfg = HydrometryConfig.from_toml("data_managers.toml")
#   records = store.load_hydrometry(cfg)
#
# ===========================================================================


# --- Hydrometry : debits ---
[hydrometry]

[[hydrometry.sources]]
source = "custom"
path = "{data_path}/hydrometry"

# Filtrer certaines stations (optionnel)
# station_ids = ["ST001", "ST002"]

# Masque spatial (optionnel)
# mask_path = "masque_bassin.shp"

# Ajouter l'API Hub'Eau en complement :
# [[hydrometry.sources]]
# source = "hubeau"
# product = "QmnJ"
# extent = "watershed"
# require_observations = true
# fallback_search_radius_km = 30.0


# --- Piezometry : niveaux piezometriques ---
[piezometry]

[[piezometry.sources]]
source = "custom"
path = "{data_path}/piezometry"

# [[piezometry.sources]]
# source = "hubeau"
# product = "level"
# extent = "watershed"
# require_observations = true
# fallback_search_radius_km = 50.0


# --- Water quality : qualite des eaux ---
[water_quality]

[[water_quality.sources]]
source = "custom"
path = "{data_path}/water_quality"

# [[water_quality.sources]]
# source = "hubeau"
# site_type = "river"
# extent = "watershed"
# parameters = ["pH", "Nitrates"]


# --- Recharge : recharge ---
# [recharge]
# [[recharge.sources]]
# source = "custom"
# path = "{data_path}/recharge"
# [[recharge.sources]]
# source = "synthetic"
# values = [0.9589]
# freq = "YE"
# periods = 1


# --- Precipitation : precipitations ---
# [precipitation]
# [[precipitation.sources]]
# source = "custom"
# path = "{data_path}/precipitation"


# --- ETP : evapotranspiration ---
# [etp]
# [[etp.sources]]
# source = "custom"
# path = "{data_path}/etp"


# --- Temperature : temperature ---
# [temperature]
# [[temperature.sources]]
# source = "custom"
# path = "{data_path}/temperature"


# --- Wind : vent ---
# [wind]
# [[wind.sources]]
# source = "custom"
# path = "{data_path}/wind"


# --- Humidity : humidite ---
# [humidity]
# [[humidity.sources]]
# source = "custom"
# path = "{data_path}/humidity"


# --- Radiation : rayonnement ---
# [radiation]
# [[radiation.sources]]
# source = "custom"
# path = "{data_path}/radiation"


# --- Soil moisture : humidite du sol ---
# [soil_moisture]
# [[soil_moisture.sources]]
# source = "custom"
# path = "{data_path}/soil_moisture"


# --- Runoff : ruissellement ---
# [runoff]
# [[runoff.sources]]
# source = "custom"
# path = "{data_path}/runoff"


# --- Oceanic : niveau marin ---
# [oceanic]
# [[oceanic.sources]]
# source = "constant"
# value = 0.0

# Ou custom CSV/NC/TIF :
# [[oceanic.sources]]
# source = "custom"
# path = "{data_path}/oceanic"
# col_datetime = "timestamp"

# Ou API SHOM :
# [[oceanic.sources]]
# source = "shom"
# nearest = true
# fallback_search_radius_km = 100.0


# --- Hydrography : reseau hydrographique ---
# [hydrography]
# [[hydrography.sources]]
# source = "custom"
# path = "data/streams.shp"
# rasterize_field = "FID"

# Ou API OSM :
# [[hydrography.sources]]
# source = "osm"

# Ou BD Topage (France) :
# [[hydrography.sources]]
# source = "bdtopage"

# Ou EU-Hydro (Europe) :
# [[hydrography.sources]]
# source = "euhydro"
"""


def scaffold(root_dir: str | Path | None = None) -> Path:
    """Create the HydroModPy workspace.

    Structure:
        hydromodpy/
            catalog.db                          <- registre central (SQLite)
            data/
                hydrometry/
                    hydrometry_custom_LOC.csv
                    hydrometry_custom_EXAMPLE_20200101_20201231_D.csv
                piezometry/
                    piezometry_custom_LOC.csv
                    piezometry_custom_EXAMPLE_20200101_20201231_D.csv
                water_quality/
                    waterquality_custom_LOC.csv
                    waterquality_custom_EXAMPLE_20200101_20201231_D.csv
            bv_example/
                data_managers.toml

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

    # bv_example/ with complete TOML
    _create_bv(root, "bv_example")

    return root


def _create_bv(root: Path, bv_name: str) -> Path:
    """Create a watershed project folder with its TOML config."""
    bv_dir = root / bv_name
    bv_dir.mkdir(parents=True, exist_ok=True)

    toml_path = bv_dir / "data_managers.toml"
    if not toml_path.exists():
        data_path = str(root / "data")
        toml_path.write_text(
            BV_CONFIG_TEMPLATE.format(
                bv_name=bv_name,
                root_path=str(root),
                data_path=data_path,
            )
        )

    return bv_dir
