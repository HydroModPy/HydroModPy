# Architecture cible — Contrats de données HydroModPy

**Document** : `architecture_cible/03_data_contracts.md`
**Date** : 2026-04-18
**Auteur** : Expert Data Engineering (CF-conventions 1.11, UGRID 1.0, OGC SensorThings v1.1, WaterML 2.0, Frictionless Data, GeoParquet 1.1, Zarr v3)
**Portée** : redéfinir les formats d'entrée, de sortie et le pattern manager du package `data/` + refonte de la couche de persistance des résultats.
**Statut attendu** : design complet à implémenter, pas un patch.

> **Légende des tags**
> `[NOUVEAU]` n'existe pas · `[RENOMME]` existe sous un autre nom · `[REFACTORE]` existe mais doit changer · `[CONSERVE]` existe et est bien.

---

## Table des matières

0. [Principes directeurs](#0-principes-directeurs)
1. [Contrats d'entrée — tous types de données](#1-contrats-dentrée)
2. [Contrats de sortie — tous types de résultats](#2-contrats-de-sortie)
3. [Représentation unifiée des grilles (UGRID)](#3-représentation-unifiée-des-grilles)
4. [Pattern Data Manager — interface minimale](#4-pattern-data-manager)
5. [Cache DuckDB et registre de provenance](#5-cache-duckdb-et-registre-de-provenance)
6. [Récapitulatif par variable](#6-récapitulatif-par-variable)
7. [Feuille de route migration](#7-feuille-de-route-migration)

---

## 0. Principes directeurs

| # | Principe | Conséquence |
|---|----------|-------------|
| 1 | **Standards externes, pas formats maison** | GeoTIFF (COG), GeoParquet, CF-NetCDF, Zarr, GeoPackage, WaterML 2.0. Zéro CSV propriétaire en entrée/sortie principale. |
| 2 | **Lecture directe par l'écosystème** | `xarray.open_dataset()`, `geopandas.read_parquet()`, `rioxarray.open_rasterio()` doivent fonctionner sans adapter. |
| 3 | **Métadonnées CF dans le fichier** | Unités, calendrier, `standard_name`, `Conventions="CF-1.11"`, CRS en WKT2 via `grid_mapping`. Pas d'info hors fichier. |
| 4 | **Schéma typé et validé** | `pandera.DataFrameSchema` ou `pydantic.TypeAdapter` pour tout ingress. Rejet explicite, pas de coercion silencieuse. |
| 5 | **UGRID 1.0 unique pour toutes les grilles** | Regulière (DIS), vertex (DISV), triangulaire (DISU/MODFLOW-NWT) : même dimension `face`, même topologie. Post-traitement unique. |
| 6 | **Provenance portable** | SHA-256 + URI source + timestamp + version loader dans le catalog. Rejouable à 6 mois. |
| 7 | **CRS typé `pyproj.CRS`, jamais `str`** | Validation à l'entrée, WKT2 en persistance, EPSG seulement pour log humain. |
| 8 | **Un seul CRS par artefact, celui du workspace** | Toute reprojection est faite en amont par le manager. Les outputs NE mélangent JAMAIS WGS84 (stations) et L-93 (rasters). |
| 9 | **Séparation contrat / implémentation** | Les contrats sont des dataclass frozen + pandera schemas. Les managers sont remplaçables. |
| 10 | **Cache invalidé par SHA-256, pas par mtime** | Robuste aux copies, synchronisations, filesystems hétérogènes. |

### 0.1 Comparaison aux projets de référence

| Projet | Ce qu'il fait bien | Ce qu'on reprend | Ce qu'on ne reprend pas |
|--------|--------------------|------------------|--------------------------|
| **Pangeo / xarray** | NetCDF + Zarr + dask ; `xr.Dataset` CF-compliant | API `open_dataset`, `chunks=auto`, `rio.crs` | Pas de `intake` : overhead YAML jugé excessif pour un hydrogéologue |
| **Frictionless Data** | `datapackage.json` + `tableschema.json` pour CSV | **Sidecar JSON Schema** pour chaque Parquet de chronique | Pas l'outil `frictionless validate` (on utilise pandera) |
| **OGC WaterML 2.0** | Standard XML pour chroniques hydro | **Export sortant optionnel** | Pas en format pivot interne (trop verbeux) |
| **OGC SensorThings API v1.1** | Modèle `Thing/Location/Observation` JSON-LD | **Structure logique** (station = Thing, chronique = Observations) | Pas l'API REST, pas de JSON-LD strict |
| **UGRID 1.0** | Topologie unstructured + attributs CF | **Schéma grille unique** (face/node/edge) | — |
| **GeoParquet 1.1** | Métadonnées spatiales dans les métadonnées Parquet | **Format natif stations & vecteurs** | — |
| **CF-NetCDF 1.11** | Standard climatique universel | **Format natif grilles 2D+T** | — |
| **COG (Cloud-Optimized GeoTIFF)** | Raster HTTP range-read | **Format natif DEM & géologie raster** | — |
| **STAC 1.0** | Catalog d'items raster | **Inspire `SimulationCatalog` mais pas repris** (DuckDB plus simple) | Pas de STAC Collections JSON |

---

## 1. Contrats d'entrée

### 1.1 Format pivot par type de donnée

Règle unique : **un format canonique par type de géométrie**. L'entrée custom n'est acceptée que dans ce format. Les APIs (Hub'Eau, BRGM…) sont normalisées vers ces formats avant caching.

| Type de donnée | Géométrie | Format pivot d'entrée | Lecteur standard |
|---|---|---|---|
| DEM | Raster continu | **COG GeoTIFF** (1 bande, Float32) | `rioxarray.open_rasterio` |
| Géologie (lithologie) | Raster catégoriel | **COG GeoTIFF** (1 bande, UInt16) + table d'attributs sidecar GeoParquet | `rioxarray.open_rasterio` + `geopandas.read_parquet` |
| Géologie (polygones) | Vecteur | **GeoParquet** (GeoPandas 1.1) | `geopandas.read_parquet` |
| Hydrographie (cours d'eau) | Vecteur linéaire | **GeoParquet** (LineString) | `geopandas.read_parquet` |
| Hydrographie (BV) | Vecteur polygone | **GeoParquet** (Polygon) | `geopandas.read_parquet` |
| Océanique (trait côte) | Vecteur linéaire | **GeoParquet** | `geopandas.read_parquet` |
| Stations (hydro/piézo/qualité/ONDE) | Vecteur points | **GeoParquet** (Point) | `geopandas.read_parquet` |
| Chronique ponctuelle | Tabulaire temporel | **Parquet** avec `DatetimeIndex` UTC | `pandas.read_parquet` |
| Grille climatique (SIM2 etc.) | Grille raster 2D+T | **CF-NetCDF 1.11** ou **Zarr v3** | `xarray.open_dataset` / `xarray.open_zarr` |
| Marégraphe | Tabulaire temporel | **Parquet** (idem chronique) | `pandas.read_parquet` |

Tout autre format (CSV, SHP, ASC) est **ingéré par un adapter** en aval, pas accepté en amont. L'adapter convertit en format pivot avant enregistrement au cache.

### 1.2 Schémas Pandera et Pydantic (contrats typés)

Les schémas ci-dessous vivent dans `hydromodpy/data/schemas/` `[NOUVEAU]` et sont importés par les managers.

#### 1.2.1 Chronique ponctuelle — `schemas/timeseries.py` `[NOUVEAU]`

```python
# hydromodpy/data/schemas/timeseries.py
from __future__ import annotations
import pandera.pandas as pa
from pandera.typing import Index, Series, DataFrame
import pandas as pd

class TimeSeriesSchema(pa.DataFrameModel):
    """Contrat Pandera pour toute chronique ponctuelle (hydro, piézo, qualité).

    Index : DatetimeIndex UTC, monotone croissant, pas de doublons.
    value : valeur mesurée, unité documentée par les métadonnées Parquet.
    qflag : code qualité Hub'Eau/WaterML (voir QualityFlag enum).
    """
    # Index
    datetime: Index[pa.DateTime] = pa.Field(
        unique=True,
        nullable=False,
        check_name=True,
    )
    # Colonnes
    value: Series[float] = pa.Field(nullable=True, coerce=True)
    qflag: Series[pa.Category] = pa.Field(
        isin=["valid", "pre-validated", "raw", "reconstructed", "missing"],
        nullable=False,
    )
    origin: Series[pa.Category] = pa.Field(
        isin=["observed", "interpolated", "filled", "provider_default"],
        nullable=False,
    )

    class Config:
        strict = True            # rejet de toute colonne supplémentaire
        ordered = True           # ordre des colonnes imposé
        coerce = True

    @pa.dataframe_check
    def monotonic_time(cls, df: pd.DataFrame) -> bool:
        return df.index.is_monotonic_increasing
```

**Validation à l'entrée** :

```python
df = pd.read_parquet(path)
TimeSeriesSchema.validate(df, lazy=True)   # lazy=True collecte toutes les erreurs
```

**Métadonnées Parquet obligatoires** (via `pyarrow.parquet.write_metadata`) :

```json
{
  "hydromodpy": {
    "version": "1.0",
    "variable": "piezometry",
    "unit": "m_NGF69",
    "frequency": "P1D",
    "timezone": "UTC",
    "station_id": "BSS002GNSS",
    "source": {
      "provider": "hubeau",
      "endpoint": "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/chroniques",
      "fetched_at": "2026-04-18T09:31:02Z",
      "sha256": "3f2a…"
    },
    "quality_codes": {
      "valid": "Validée par producteur",
      "pre-validated": "Pré-validée",
      "raw": "Brute",
      "reconstructed": "Reconstituée",
      "missing": "Absente"
    }
  }
}
```

#### 1.2.2 Stations (collection de points) — `schemas/stations.py` `[NOUVEAU]`

```python
# hydromodpy/data/schemas/stations.py
import pandera.pandas as pa
from pandera.typing.geopandas import GeoSeries
import geopandas as gpd

class StationCollectionSchema(pa.DataFrameModel):
    """Contrat GeoParquet pour toute collection de stations de mesure."""
    station_id: pa.typing.Series[str] = pa.Field(unique=True, nullable=False,
        str_matches=r"^[A-Z0-9_\-]{3,32}$")
    name: pa.typing.Series[str] = pa.Field(nullable=False)
    variable: pa.typing.Series[pa.Category] = pa.Field(
        isin=["hydrometry", "piezometry", "water_quality", "intermittency", "oceanic"]
    )
    provider: pa.typing.Series[pa.Category] = pa.Field(
        isin=["hubeau", "shom", "brgm", "custom"]
    )
    altitude_m: pa.typing.Series[float] = pa.Field(nullable=True, ge=-500, le=5000)
    active_from: pa.typing.Series[pa.DateTime] = pa.Field(nullable=True)
    active_to:   pa.typing.Series[pa.DateTime] = pa.Field(nullable=True)
    geometry: GeoSeries = pa.Field(nullable=False)

    class Config:
        strict = True
        coerce = True
```

Un fichier `stations.geoparquet` typique :

```python
gdf = gpd.read_parquet("workspace/data/stations.geoparquet")
# gdf.crs est un pyproj.CRS lu automatiquement depuis les métadonnées GeoParquet
# gdf.geometry est shapely.Point
assert gdf.crs.to_epsg() == 2154
```

**Un seul fichier stations par workspace, toutes variables confondues** : permet les jointures SQL DuckDB (`SELECT * FROM stations JOIN timeseries USING (station_id)`).

#### 1.2.3 DEM — `schemas/raster_dem.py` `[NOUVEAU]`

```python
# hydromodpy/data/schemas/raster_dem.py
from pydantic import BaseModel, Field, ConfigDict, field_validator
from pyproj import CRS
import rioxarray, xarray as xr

class DEMContract(BaseModel):
    """Contrat de validation pour un raster DEM COG avant ingestion."""
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    path: Path
    crs: CRS
    resolution_m: float = Field(gt=0, le=500)
    band_count: int = Field(eq=1)
    dtype: str = Field(pattern=r"^(float32|float64)$")
    nodata: float
    is_cog: bool          # drapeau : doit être tuilé + overviews

    @field_validator("crs", mode="before")
    @classmethod
    def _parse_crs(cls, v): return CRS.from_user_input(v)

    @classmethod
    def from_path(cls, path: Path) -> "DEMContract":
        da = rioxarray.open_rasterio(path, chunks="auto")
        crs = CRS.from_wkt(da.rio.crs.to_wkt())
        res = abs(da.rio.resolution()[0])
        return cls(
            path=path, crs=crs, resolution_m=res, band_count=da.sizes["band"],
            dtype=str(da.dtype), nodata=float(da.rio.nodata or -9999),
            is_cog=_is_cog(path),   # helper qui teste IFD tuilé + overview
        )
```

**Exemple de fichier d'entrée valide** : un COG GeoTIFF produit par IGN BD ALTI 25 m, projeté en Lambert-93, tagué via :

```bash
gdal_translate input.tif dem_cog.tif \
    -of COG -co COMPRESS=DEFLATE -co BLOCKSIZE=512 \
    -a_srs EPSG:2154 -a_nodata -9999
```

Header GDAL minimal attendu :

```
Driver: GTiff/GeoTIFF
Files: dem_cog.tif
Size is 4000, 3000
Coordinate System: PROJCRS["RGF93 v1 / Lambert-93", ...]
Band 1: Type=Float32, ColorInterp=Gray, NoData=-9999
Metadata: LAYOUT=COG
Overviews: 2000x1500, 1000x750, 500x375
```

#### 1.2.4 Géologie raster — `schemas/raster_geology.py` `[NOUVEAU]`

Même structure que DEM, mais :
- `dtype` accepte `uint8`/`uint16` (codes lithologiques discrets)
- Un sidecar `lithology_table.geoparquet` `[NOUVEAU]` associe `code → {name, k_init, ss_init, …}`

```python
class LithologyTableSchema(pa.DataFrameModel):
    code: pa.typing.Series[int] = pa.Field(unique=True, ge=0, le=65535)
    name: pa.typing.Series[str]
    brgm_code: pa.typing.Series[str] = pa.Field(nullable=True)
    class_hydro: pa.typing.Series[pa.Category] = pa.Field(
        isin=["aquifer", "aquitard", "aquiclude", "unknown"])
    k_init_m_s: pa.typing.Series[float] = pa.Field(nullable=True, gt=0, le=1e-1)
    ss_init_1_m: pa.typing.Series[float] = pa.Field(nullable=True, gt=0, le=1e-1)
    sy_init: pa.typing.Series[float] = pa.Field(nullable=True, gt=0, le=1.0)
```

#### 1.2.5 Grille climatique — `schemas/field_cf.py` `[NOUVEAU]`

Validation structurelle d'un NetCDF CF entrant :

```python
# hydromodpy/data/schemas/field_cf.py
REQUIRED_CF_ATTRS = {"units", "standard_name"}
REQUIRED_GLOBAL = {"Conventions", "title", "source", "history"}

def validate_cf_field(ds: xr.Dataset, variable: str) -> list[str]:
    errors: list[str] = []
    if "Conventions" not in ds.attrs or "CF-1" not in ds.attrs["Conventions"]:
        errors.append("missing Conventions=CF-1.x in ds.attrs")
    if variable not in ds.data_vars:
        errors.append(f"variable {variable!r} not found")
    da = ds[variable]
    for a in REQUIRED_CF_ATTRS:
        if a not in da.attrs: errors.append(f"{variable}.attrs missing {a!r}")
    if "time" in da.dims:
        t = ds["time"]
        if "calendar" not in t.encoding and "calendar" not in t.attrs:
            errors.append("time missing CF calendar")
    if ds.rio.crs is None:
        errors.append("missing CRS (grid_mapping)")
    return errors
```

Exemple de fichier valide (extrait `ncdump -h`) :

```
netcdf recharge_sim2_2000-2024 {
dimensions:
    time = UNLIMITED ;
    y = 142 ; x = 178 ;
variables:
    double time(time) ;
        time:units = "days since 1970-01-01 00:00:00" ;
        time:calendar = "proleptic_gregorian" ;
        time:standard_name = "time" ;
    double y(y) ;  y:units = "m" ;  y:standard_name = "projection_y_coordinate" ;
    double x(x) ;  x:units = "m" ;  x:standard_name = "projection_x_coordinate" ;
    float recharge(time, y, x) ;
        recharge:units = "kg m-2 s-1" ;
        recharge:standard_name = "surface_downward_water_flux" ;
        recharge:grid_mapping = "lambert_conformal_conic" ;
        recharge:_FillValue = -9999.f ;
    char lambert_conformal_conic ;
        lambert_conformal_conic:grid_mapping_name = "lambert_conformal_conic" ;
        lambert_conformal_conic:crs_wkt = "PROJCRS[\"RGF93 v1 / Lambert-93\", …]" ;
// global:
    :Conventions = "CF-1.11" ;
    :title = "Recharge SIM2 interpolated" ;
    :source = "Météo-France SIM2 via EDR API" ;
    :history = "2026-04-18T09:00Z created by hydromodpy.data.variables.recharge" ;
}
```

### 1.3 Pipeline d'ingestion standard

```
┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  HTTP API   │──▶│  Adapter     │──▶│  Validation  │──▶│  Cache       │
│  Hub'Eau/…  │   │  to pivot    │   │  pandera/CF  │   │  DuckDB+file │
└─────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
                         ▲                                    │
┌─────────────┐          │                                    ▼
│  Custom     │──────────┘                           ┌──────────────┐
│  file user  │                                      │  LoadResult  │
└─────────────┘                                      └──────────────┘
```

Règle : **aucun manager ne crée un `LoadResult` sans passer par la validation pandera**. Échec = exception `DataContractViolation` `[NOUVEAU]` avec le rapport pandera en pièce jointe.

---

## 2. Contrats de sortie

### 2.1 Vue d'ensemble

La couche résultats (`results/` dans l'architecture cible) produit trois classes d'artefacts :

| Artefact | Format | Où | Utilisé par |
|---|---|---|---|
| **Champs spatio-temporels** (head, WT, budget spatial) | **Zarr v3 CF-UGRID** | `simulations/<uuid>.zarr/` | xarray, dask, post-traitement ML |
| **Séries ponctuelles** (station, outlet) | **Parquet + GeoParquet stations** | `simulations/<uuid>.zarr/timeseries.parquet` **ou** DuckDB | pandas, DuckDB SQL |
| **Vecteurs géographiques** (watershed, drains) | **GeoParquet** | `simulations/<uuid>.zarr/geographic/*.parquet` | QGIS, GeoPandas |
| **Métadonnées catalog** | **DuckDB** | `workspace/hydromodpy.duckdb` | SQL, SimulationCatalog API |
| **Paquet portable** | **`.hmp` = tar.zst** de l'ensemble | `exports/<sim>.hmp` | partage inter-workspaces |

### 2.2 Champs : Zarr v3 CF-UGRID

Pourquoi Zarr et pas NetCDF ? Parce qu'une simulation doit s'écrire en streaming (1 pas de temps → 1 chunk) sans ré-ouvrir le fichier. NetCDF-HDF5 n'est pas friendly en écriture concurrente.

**Layout détaillé** `[REFACTORE]` (remplace le layout actuel) :

```
simulations/<uuid>.zarr/
│
├── .zgroup                         # Zarr v3 group root
├── .zattrs                         # attrs CF globaux + sim_id + git_sha + pkg_version
│
├── mesh/                           # UGRID unique (voir §3)
│   ├── node_x, node_y, node_z
│   ├── face_node_connectivity
│   ├── face_x, face_y              # centroïdes
│   ├── edge_node_connectivity
│   └── z_interfaces                # (n_layers+1, n_face) pour MODFLOW
│
├── head/                           # DataArray (time, layer, face)
├── drawdown/
├── concentration/                  # si transport
│
├── derived/
│   ├── watertable_elevation        # (time, face)
│   ├── watertable_depth            # (time, face)
│   └── seepage_mask                # (time, face), bool
│
├── budget/
│   ├── recharge                    # (time, layer, face), kg m-2 s-1
│   ├── drain                       # (time, layer, face)
│   ├── river
│   ├── storage
│   └── well
│
├── pathlines/                      # groupe optionnel MODPATH
│   ├── particle_id
│   ├── x, y, z, time               # trajectoires
│
├── geographic/
│   ├── dem                         # raster 2D régulier (y, x)
│   ├── geology                     # raster catégoriel
│   └── watershed.parquet           # GeoParquet polygone
│
└── timeseries/                     # séries ponctuelles extraites
    ├── observations.parquet        # (station_id, datetime, variable, value, qflag)
    └── stations.geoparquet         # collection de points
```

### 2.3 Attributs CF obligatoires pour chaque DataArray

Extrait du `.zattrs` d'un array `head` :

```json
{
  "units": "m",
  "standard_name": "water_table_altitude",
  "long_name": "Hydraulic head above NGF69 datum",
  "_FillValue": -9999.0,
  "grid_mapping": "crs",
  "mesh": "mesh",
  "location": "face",
  "coordinates": "time face_x face_y"
}
```

Règle : **zéro attribut dans DuckDB qu'on ne retrouve pas dans les `.zattrs` du Zarr**. DuckDB est une projection du Zarr, pas une source primaire.

### 2.4 Séries ponctuelles : Parquet plat

Un seul fichier `timeseries/observations.parquet` par simulation, schéma long :

| Colonne | Type | Description |
|---|---|---|
| `station_id` | `string` | clé étrangère vers `stations.geoparquet` |
| `variable` | `dictionary<string>` | `head`, `discharge`, `concentration`, … |
| `datetime` | `timestamp[ns, UTC]` | index partiel |
| `value` | `float32` | mesure |
| `qflag` | `dictionary<string>` | flag qualité |
| `source` | `dictionary<string>` | `simulated` / `observed` / `interpolated` |

Indexé `(station_id, variable, datetime)`. Lisible directement :

```python
import duckdb
df = duckdb.sql("""
    SELECT station_id, datetime, value
    FROM 'simulations/abc-123.zarr/timeseries/observations.parquet'
    WHERE variable = 'head' AND station_id = 'P01'
""").df()
```

### 2.5 Paquet portable `.hmp`

**`[NOUVEAU]`** : `.hmp` = archive **tar compressée zstd niveau 6** contenant :

```
<uuid>.hmp
├── simulation.zarr/            # le Zarr complet
├── catalog_rows.json           # les lignes DuckDB de cette simulation (export 12 tables)
├── config.toml                 # TOML qui a généré la simulation
├── manifest.json               # version hydromodpy, pydantic schema version, sha256 des artefacts
└── LICENSE.txt                 # EPL-2.0
```

Export : `hmp export <sim_id> → xxx.hmp`. Import : `hmp import xxx.hmp` → reinsert dans le DuckDB cible + déplace le Zarr dans `simulations/`.

### 2.6 Accès direct sans adapter — exemples concrets

**Chercheur en IA (Python, pandas/xarray)** :

```python
import xarray as xr, pandas as pd
ds = xr.open_zarr("simulations/abc.zarr/")
head = ds["head"]                             # DataArray (time, layer, face)
ts_obs = pd.read_parquet("simulations/abc.zarr/timeseries/observations.parquet")
# features ML : head moyen par station × variables climatiques
features = ts_obs.pivot_table(index="datetime", columns="variable", values="value")
```

**Hydrogéologue (QGIS)** :

- `simulations/abc.zarr/geographic/watershed.parquet` → « Add Vector Layer », QGIS lit GeoParquet nativement depuis 3.32.
- `simulations/abc.zarr/head/` → nécessite plugin `xarray-zarr` pour QGIS (issue connue), sinon export TIF via `hmp export abc --format tif`.

**Étudiant (Jupyter)** :

```python
import hydromodpy as hmp
sim = hmp.open("~/workspace").best(project="canut", metric="nse")
sim.head.isel(time=-1).plot()                # xarray + matplotlib direct
```

**Framework de validation (pandera/great_expectations)** :

```python
from hydromodpy.data.schemas import TimeSeriesSchema
df = pd.read_parquet(sim.path / "timeseries/observations.parquet")
TimeSeriesSchema.validate(df, lazy=True)     # lève SchemaErrors si non conforme
```

---

## 3. Représentation unifiée des grilles

### 3.1 Problème

Aujourd'hui la chaîne post-traitement connaît trois types de grilles :
- DIS régulière (MODFLOW classique) : `(nrow, ncol)` avec `delr`, `delc`
- DISV vertex (MODFLOW 6) : `ncpl` cellules polygonales + table `iverts`
- DISU (MODFLOW-NWT) : `nodes` + `iac`, `ja`, `ihc`

Chaque solveur a son adapter et ses tracés custom. Le post-traitement est dupliqué.

### 3.2 Choix : UGRID 1.0

**UGRID (Unstructured Grid conventions)** est une extension CF. Elle définit une topologie unique pour toute grille 2D par :

- `node_x`, `node_y`, `node_z` — coordonnées des sommets
- `face_node_connectivity(face, nMaxFaceNodes)` — padding avec FillValue pour faces à n_nodes variables
- `face_x`, `face_y` — centroïdes optionnels (dérivables mais pré-calculés pour la vitesse)
- `edge_node_connectivity(edge, 2)` — arêtes, optionnel mais utile pour les flux

Une grille régulière DIS s'exprime comme un cas particulier UGRID où chaque face a exactement 4 nœuds organisés en quad. Une DISV est déjà UGRID par nature. Une DISU se convertit par triangulation des cellules.

**Conséquence** : la chaîne post-traitement ne voit qu'une dimension `face`. Le nombre de couches est séparé (`layer`). Les champs 3D sont `(time, layer, face)`.

### 3.3 Comparaison avec les alternatives

| Option | Pour | Contre | Choix |
|---|---|---|---|
| **UGRID 1.0** | Standard CF, lu par `uxarray`, VTK, ParaView | Plus verbeux qu'un simple `(y, x)` pour grilles régulières | ✅ **Retenu** |
| xarray MultiIndex | Simple, pur xarray | Aucune sémantique géométrique, pas de connectivity | ❌ |
| Schéma Zarr custom | Flexible | Pas standard, à documenter soi-même | ❌ |
| `meshio` natif | Multi-format | Pas CF, pas de time | ❌ |
| `uxarray.UxDataset` | UGRID wrapper xarray | Jeune (2024), instable | 🟡 **Support prévu en lecture** |

### 3.4 Skeleton de code

`hydromodpy/spatial/mesh/ugrid.py` `[NOUVEAU]` :

```python
# hydromodpy/spatial/mesh/ugrid.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import numpy as np, xarray as xr

FILL = -1  # UGRID CF fill value for ragged connectivity

@dataclass(frozen=True)
class UGridMesh:
    """Unified mesh representation for any MODFLOW grid topology."""
    node_x: np.ndarray                  # (n_node,)
    node_y: np.ndarray
    node_z: np.ndarray | None           # (n_node,) or None if 2D
    face_node: np.ndarray               # (n_face, max_nodes), int32, -1 padded
    face_x: np.ndarray                  # (n_face,)
    face_y: np.ndarray
    z_interfaces: np.ndarray | None     # (n_layers+1, n_face) float
    crs_wkt: str
    topology: Literal["dis", "disv", "disu"]   # indicatif, lu par l'adapter

    # --- constructeurs --------------------------------------------------
    @classmethod
    def from_modflow_dis(cls, delr, delc, xoff, yoff, crs) -> "UGridMesh": ...
    @classmethod
    def from_modflow_disv(cls, vertices, cell2d, crs) -> "UGridMesh": ...
    @classmethod
    def from_modflow_disu(cls, iverts, verts, crs) -> "UGridMesh": ...

    # --- sérialisation CF-UGRID dans un Dataset xarray -----------------
    def to_dataset(self) -> xr.Dataset:
        ds = xr.Dataset(
            data_vars={
                "face_node_connectivity": (("face", "max_nodes"), self.face_node,
                    {"cf_role": "face_node_connectivity", "_FillValue": FILL,
                     "start_index": 0}),
                "face_x": (("face",), self.face_x, {"units": "m",
                    "standard_name": "projection_x_coordinate"}),
                "face_y": (("face",), self.face_y, {"units": "m",
                    "standard_name": "projection_y_coordinate"}),
                "node_x": (("node",), self.node_x, {"units": "m"}),
                "node_y": (("node",), self.node_y, {"units": "m"}),
            },
            attrs={
                "Conventions": "CF-1.11 UGRID-1.0",
                "mesh_topology": "mesh",
                "topology_dimension": 2,
            },
        )
        ds["mesh"] = xr.DataArray(np.int32(0), attrs={
            "cf_role": "mesh_topology",
            "topology_dimension": 2,
            "node_coordinates": "node_x node_y",
            "face_coordinates": "face_x face_y",
            "face_node_connectivity": "face_node_connectivity",
        })
        if self.z_interfaces is not None:
            ds["z_interfaces"] = (("layer_interface", "face"), self.z_interfaces,
                {"units": "m", "standard_name": "altitude"})
        ds.rio.write_crs(self.crs_wkt, inplace=True)
        return ds

    @classmethod
    def from_dataset(cls, ds: xr.Dataset) -> "UGridMesh": ...
```

### 3.5 API de lecture / écriture d'un champ, identique pour toutes les topologies

`hydromodpy/results/io/field_io.py` `[NOUVEAU]` :

```python
# hydromodpy/results/io/field_io.py
import xarray as xr, numpy as np
from hydromodpy.spatial.mesh.ugrid import UGridMesh

def write_field(store: str, name: str, values: np.ndarray, mesh: UGridMesh,
                times: np.ndarray, unit: str, standard_name: str) -> None:
    """values shape : (time, layer, face) or (time, face). Always face-indexed."""
    da = xr.DataArray(
        values, dims=("time", "layer", "face")[-values.ndim:],
        coords={"time": times},
        attrs={
            "units": unit, "standard_name": standard_name,
            "grid_mapping": "crs", "mesh": "mesh", "location": "face",
            "_FillValue": np.float32(-9999),
        },
    )
    ds = mesh.to_dataset()
    ds[name] = da.astype("float32")
    ds.to_zarr(store, mode="a", consolidated=True)

def read_field(store: str, name: str) -> xr.DataArray:
    """Always returns DataArray indexed by face, whatever the source grid."""
    ds = xr.open_zarr(store, consolidated=True)
    return ds[name]   # dim 'face' unique quelle que soit la topologie d'origine
```

**L'utilisateur ne voit JAMAIS `row`/`col`/`node`**. Une grille régulière est face-indexée avec un ordre row-major documenté (attribut `face_ordering: "row_major_C"` dans le Dataset). Un helper `mesh.face_to_row_col()` est fourni pour la régulière uniquement.

### 3.6 Migration des sorties existantes

| Actuel | Cible | Action |
|---|---|---|
| `head_MODFLOW_*.nc` (nrow, ncol) | Zarr `head(time, layer, face)` | Extracteur MODFLOW convertit `ibound`/`idomain` → UGRID |
| `grid_geometry.vtu` | dérivé du Zarr via `uxarray.Grid.to_vtk()` | Suppression de l'écriture VTU primaire |
| `head_MODFLOW6_*.nc` DISV | Zarr `head(time, layer, face)` | Déjà face-indexé, conversion triviale |

---

## 4. Pattern Data Manager

### 4.1 Interface minimale

Problème actuel : `BaseVariableManager` (492 L) + `BaseFieldManager` + DEM/Géologie/Hydrographie hors pattern. God Object.

Cible `[REFACTORE]` : **un seul `Protocol`**, plus une fonction `load()`. Les managers deviennent des classes dataclass stateless composées de *fonctions* enregistrées par décorateur.

```python
# hydromodpy/data/base.py  [NOUVEAU, remplace common/base_manager.py]
from __future__ import annotations
from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from pathlib import Path
import pyproj, datetime as dt
from hydromodpy.data.contracts import LoadResult

@runtime_checkable
class DataSource(Protocol):
    """One-method protocol. A source loads data for one variable + provider."""
    name: str                               # "hubeau", "brgm_50k", "sim2"
    variable: str                           # "piezometry", "geology", "recharge"
    def fetch(self,
              extent: "Extent",             # bbox + crs
              period: "Period",             # date range or None
              cache: "DataCache",           # DuckDB-backed cache, injected
              **kwargs) -> LoadResult: ...

# hydromodpy/data/registry.py  [NOUVEAU]
_SOURCES: dict[tuple[str, str], type[DataSource]] = {}

def register_source(variable: str, name: str):
    def _decorator(cls):
        _SOURCES[(variable, name)] = cls
        return cls
    return _decorator

def get_source(variable: str, name: str) -> type[DataSource]:
    try: return _SOURCES[(variable, name)]
    except KeyError:
        raise KeyError(f"No source '{name}' for variable '{variable}'. "
                       f"Available: {[k for k in _SOURCES if k[0]==variable]}")
```

### 4.2 Ajout d'un nouveau type de donnée en ~20 lignes

Exemple : intégrer un nouveau provider de débits DREAL (fictif, illustratif).

```python
# hydromodpy/data/variables/hydrometry/sources/dreal.py   [NOUVEAU file]
from hydromodpy.data.registry import register_source
from hydromodpy.data.contracts import LoadResult, PointRecord, StationLocation
from hydromodpy.data.common.http_client import HTTPClient
from hydromodpy.data.schemas import TimeSeriesSchema
import pandas as pd, pyproj, shapely.geometry as sg

@register_source(variable="hydrometry", name="dreal")
class DrealHydrometrySource:
    name = "dreal"
    variable = "hydrometry"
    http = HTTPClient(base="https://hydro.dreal.example/api", timeout=(10, 60))

    def fetch(self, extent, period, cache, **kw) -> LoadResult:
        stations = self._list_stations(extent)
        records = []
        for stn in stations:
            key = cache.key(variable=self.variable, source=self.name,
                            station_id=stn.id, period=period)
            if hit := cache.get(key):         # cache hit → read Parquet
                df = pd.read_parquet(hit.path)
            else:
                df = self._fetch_chronicle(stn.id, period)
                cache.put(key, df, sidecar={"provider": "dreal"})
            TimeSeriesSchema.validate(df, lazy=True)
            records.append(PointRecord(station=stn, data=df, source=self.name))
        return LoadResult(points=records)
```

20 lignes effectives, pas d'héritage, pas de template method. Toutes les étapes (validation, cache, HTTP robuste, métadonnées Parquet) sont déléguées aux composants partagés.

### 4.3 Orchestration : `load()` comme fonction pure

```python
# hydromodpy/data/loader.py   [NOUVEAU, remplace runtime_loader.py]
from hydromodpy.data.registry import get_source
from hydromodpy.data.contracts import LoadResult

def load(variable: str, source: str, extent, period, cache, **kw) -> LoadResult:
    """Pure entry point. No class state, trivially testable."""
    src = get_source(variable, source)()
    return src.fetch(extent, period, cache, **kw)
```

Test unitaire : on instancie un `DataCache` fake (mémoire) et un fake `HTTPClient`. Pas besoin de `WorkflowContext`, pas besoin de `project_extent` globale. Chaque fonction = une chose.

### 4.4 Renommage / refactoring du code existant

| Actuel | Cible | Statut |
|---|---|---|
| `data/common/base_manager.py` (492 L) | `data/base.py` (~40 L, `DataSource` Protocol) | `[REFACTORE]` |
| `data/common/base_field_manager.py` | supprimé, même `DataSource` pour grilles | `[K]` |
| `data/runtime_loader.py` | `data/loader.py` (fonction `load()` pure) | `[RENOMME+REFACTORE]` |
| `data/store.py` (registry) | `data/registry.py` | `[RENOMME]` |
| `data/planner.py` | `data/inference.py` (règles via décorateur) | `[RENOMME+REFACTORE]` |
| `data/variables/hydrometry/apis/hubeau.py` | `data/variables/hydrometry/sources/hubeau.py` | `[RENOMME]` |
| `data/contracts/timeseries.py::PointRecord` (90 L) | `data/contracts/point_record.py` (45 L, voir §4.5) | `[REFACTORE]` |
| `data/contracts/spatial_field.py::FieldRecord` | `data/contracts/field_record.py` (voir §4.5) | `[REFACTORE]` |
| `data/climatic/climatic.py` (618 L) | supprimé | `[K]` |
| `data/climatic/sim2.py` (932 L) | consolidé dans `data/common/clients/sim2.py` | `[REFACTORE]` |
| `data/climatic/drias*.py`, `safransurfex.py` | archivés hors runtime | `[K]` |

### 4.5 Contrats typés modernisés

```python
# hydromodpy/data/contracts/point_record.py   [REFACTORE]
from dataclasses import dataclass
from typing import Optional
import pandas as pd, shapely.geometry as sg, pyproj

@dataclass(frozen=True, slots=True)
class Station:
    id: str
    name: str
    point: sg.Point                         # shapely, JAMAIS (x,y,crs) plat
    crs: pyproj.CRS
    variable: str
    provider: str
    altitude_m: Optional[float] = None
    active_from: Optional[pd.Timestamp] = None
    active_to: Optional[pd.Timestamp] = None

@dataclass(frozen=True, slots=True)
class PointRecord:
    """Time series + metadata. `values` is a pandas.Series with DatetimeIndex UTC."""
    station: Station
    values: pd.Series                       # index tz-aware UTC, name=variable
    source: str                             # provider key, for lineage
    unit: str                               # CF unit string, e.g. 'm3 s-1'
    frequency: str                          # ISO-8601 duration: 'PT1H', 'P1D'
    qflags: pd.Series | None = None         # same index, Categorical
    sha256: str | None = None               # fingerprint of the source bytes

    @property
    def completeness_pct(self) -> float:
        from hydromodpy.data.quality import completeness
        return completeness(self.values, freq=self.frequency)
```

```python
# hydromodpy/data/contracts/field_record.py   [REFACTORE]
@dataclass(frozen=True, slots=True)
class FieldRecord:
    """Gridded dataset. `dataset` is ALWAYS xr.Dataset (lazy loaded if needed)."""
    dataset: "xr.Dataset"                   # CF-compliant, rio.crs set
    variable: str
    source: str
    sha256: str | None = None

    @property
    def unit(self) -> str:   return self.dataset[self.variable].attrs["units"]
    @property
    def crs(self) -> pyproj.CRS:
        return pyproj.CRS.from_wkt(self.dataset.rio.crs.to_wkt())
    @property
    def period(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        if "time" not in self.dataset.dims: return None
        t = self.dataset["time"]
        return (pd.Timestamp(t.min().item()), pd.Timestamp(t.max().item()))
```

Plus de `Union[Dataset, Path]`. Plus de mutation silencieuse de `self.data`. Le lazy load est délégué à xarray (dask). Les métadonnées sont *dans* le Dataset.

---

## 5. Cache DuckDB et registre de provenance

### 5.1 Vue d'ensemble

Deux DuckDB distincts :

| DuckDB | Chemin | Rôle | Visibilité |
|---|---|---|---|
| `data_cache.duckdb` | `workspace/data/cache.duckdb` | Cache d'ingestion (chroniques + stations + fichiers) | partagé tous projets |
| `hydromodpy.duckdb` | `workspace/hydromodpy.duckdb` | Catalog des simulations | partagé tous projets |

Les deux partagent la **même table `provenance`** lue par `ATTACH` depuis l'autre DB (DuckDB supporte l'ATTACH multi-DB).

### 5.2 Schéma du cache `data_cache.duckdb` `[REFACTORE]`

Remplace `entries` + `api_coverage` actuels. Six tables, toutes avec `PRIMARY KEY` et contraintes `CHECK`.

```sql
-- workspace/data/cache.duckdb
CREATE SCHEMA IF NOT EXISTS cache;
SET schema 'cache';

-- Version du schéma, pour migrations.
CREATE TABLE IF NOT EXISTS _schema_version (
    version       INTEGER PRIMARY KEY,
    applied_at    TIMESTAMP NOT NULL DEFAULT current_timestamp,
    description   VARCHAR
);

-- 1) Artefacts physiques : 1 ligne = 1 fichier cachée sur le disque.
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id   UUID       PRIMARY KEY DEFAULT uuid(),
    variable      VARCHAR    NOT NULL,
    provider      VARCHAR    NOT NULL,        -- hubeau, brgm_50k, sim2, custom
    station_id    VARCHAR    NULL,            -- NULL pour grilles
    bbox          BOX_2D     NULL,            -- DuckDB box type, en CRS artefact
    crs_wkt       VARCHAR    NOT NULL,        -- WKT2 complet
    date_start    TIMESTAMP  NULL,            -- TIMESTAMP, pas VARCHAR
    date_end      TIMESTAMP  NULL,
    frequency     VARCHAR    NULL,            -- ISO-8601 duration
    unit          VARCHAR    NOT NULL,        -- CF unit
    format        ENUM('parquet', 'geoparquet', 'netcdf', 'zarr', 'geotiff_cog')
                             NOT NULL,
    path          VARCHAR    NULL,            -- NULL pour sentinelles
    status        ENUM('cached', 'empty', 'failed', 'custom')
                             NOT NULL DEFAULT 'cached',
    size_bytes    BIGINT     NULL,
    sha256        VARCHAR    NULL,            -- SHA-256 hex du fichier
    created_at    TIMESTAMP  NOT NULL DEFAULT current_timestamp,
    CHECK (status != 'cached' OR path IS NOT NULL)
);
CREATE UNIQUE INDEX ux_artifacts_key
  ON artifacts(variable, provider, station_id, date_start, date_end);
CREATE INDEX ix_artifacts_bbox ON artifacts USING RTREE(bbox);

-- 2) Provenance : lineage HTTP ou fichier-source.
CREATE TABLE IF NOT EXISTS provenance (
    artifact_id   UUID PRIMARY KEY REFERENCES artifacts(artifact_id),
    source_type   ENUM('http_api', 'custom_file', 'derived') NOT NULL,
    url           VARCHAR NULL,
    http_status   INTEGER NULL,
    http_etag     VARCHAR NULL,
    request_sha   VARCHAR NULL,               -- SHA des params de requête
    fetched_at    TIMESTAMP NOT NULL,
    loader_name   VARCHAR NOT NULL,           -- 'HubEauHydrometrySource'
    loader_version VARCHAR NOT NULL,          -- git sha or semver
    extras        JSON                        -- libre : pagination, token, …
);

-- 3) Stations (extraction des features, indexable).
CREATE TABLE IF NOT EXISTS stations (
    station_id    VARCHAR NOT NULL,
    provider      VARCHAR NOT NULL,
    variable      VARCHAR NOT NULL,
    name          VARCHAR,
    x             DOUBLE  NOT NULL,
    y             DOUBLE  NOT NULL,
    crs_epsg      INTEGER NOT NULL,            -- EPSG only, WKT stored separately
    altitude_m    DOUBLE,
    active_from   TIMESTAMP,
    active_to     TIMESTAMP,
    metadata      JSON,
    PRIMARY KEY (station_id, provider, variable)
);

-- 4) Couverture temporelle par station (cache smart pour inféré manquant).
CREATE TABLE IF NOT EXISTS coverage (
    station_id    VARCHAR,
    provider      VARCHAR,
    variable      VARCHAR,
    frequency     VARCHAR,
    period_start  TIMESTAMP,
    period_end    TIMESTAMP,
    completeness_pct DOUBLE,
    PRIMARY KEY (station_id, provider, variable, frequency, period_start)
);

-- 5) Échecs : pour ne pas re-tenter indéfiniment une station 404.
CREATE TABLE IF NOT EXISTS failures (
    variable      VARCHAR, provider VARCHAR, station_id VARCHAR,
    period_start  TIMESTAMP, period_end TIMESTAMP,
    error_type    VARCHAR,                    -- 'http_404', 'empty_response', 'schema_violation'
    error_message VARCHAR,
    failed_at     TIMESTAMP,
    retry_after   TIMESTAMP,                  -- backoff logique
    PRIMARY KEY (variable, provider, station_id, period_start)
);

-- 6) Validation : rapport pandera conservé pour audit.
CREATE TABLE IF NOT EXISTS validation_reports (
    artifact_id   UUID REFERENCES artifacts(artifact_id),
    validated_at  TIMESTAMP NOT NULL DEFAULT current_timestamp,
    schema_name   VARCHAR NOT NULL,           -- 'TimeSeriesSchema'
    schema_version VARCHAR NOT NULL,
    passed        BOOLEAN NOT NULL,
    errors_json   JSON,                       -- compact error report
    PRIMARY KEY (artifact_id, schema_name, validated_at)
);
```

### 5.3 Schéma du catalog `hydromodpy.duckdb` (extensions)

Le catalog simulation existant (§ Storage dans CLAUDE.md) reste globalement correct. Deux ajustements `[REFACTORE]` :

```sql
-- Ajouter vue unifiée cross-DB pour la provenance
ATTACH 'data/cache.duckdb' AS cache_db (READ_ONLY);

CREATE OR REPLACE VIEW simulation_inputs_provenance AS
SELECT
    sim.sim_id,
    art.variable,
    art.provider,
    art.path,
    art.sha256,
    prov.fetched_at,
    prov.loader_name,
    prov.loader_version
FROM simulations sim
JOIN provenance prov    USING (sim_id)          -- simu-level provenance table (existe)
LEFT JOIN cache_db.cache.artifacts art USING (sha256);
```

### 5.4 Invalidation

**Règle unique** : invalidation sur **SHA-256 changé OU `fetched_at` > TTL**.

```python
# hydromodpy/data/cache.py   [NOUVEAU]
@dataclass(frozen=True)
class CacheKey:
    variable: str; provider: str; station_id: str | None
    period: tuple[pd.Timestamp, pd.Timestamp] | None
    bbox: tuple[float, float, float, float] | None

class DataCache:
    def __init__(self, duckdb_path: Path, data_dir: Path, default_ttl: timedelta):
        self._conn = duckdb.connect(str(duckdb_path))
        self._data_dir = data_dir
        self._ttl = default_ttl

    def get(self, key: CacheKey) -> CacheHit | None:
        row = self._conn.execute("""
            SELECT path, sha256, fetched_at
            FROM artifacts a JOIN provenance p USING (artifact_id)
            WHERE variable = ? AND provider = ?
              AND COALESCE(station_id,'')=COALESCE(?,'')
              AND date_start = ? AND date_end = ?
              AND status = 'cached'
        """, [key.variable, key.provider, key.station_id, *key.period]).fetchone()
        if row is None: return None
        path, sha, fetched = row
        if not Path(path).exists(): return None
        if _sha256(path) != sha: return None          # invalide si muté
        if _age(fetched) > self._ttl:  return None    # expiré
        return CacheHit(path=Path(path), sha256=sha, fetched_at=fetched)

    def put(self, key: CacheKey, payload: pd.DataFrame | xr.Dataset, *,
            sidecar: dict) -> Path:
        with self._conn.begin():       # <-- transaction explicite
            path = self._write_payload(key, payload)
            sha  = _sha256(path)
            artifact_id = uuid.uuid4()
            self._conn.execute("INSERT INTO artifacts (...) VALUES (...)", ...)
            self._conn.execute("INSERT INTO provenance (...) VALUES (...)", ...)
        return path
```

### 5.5 Requêtes types

**1) Tout ce qui concerne un bassin donné (via bbox RTREE)** :

```sql
SELECT a.variable, a.provider, a.path, a.sha256
FROM artifacts a
WHERE ST_Intersects(a.bbox, ST_MakeBox2D(100000, 6000000, 200000, 6100000))
  AND a.status = 'cached';
```

**2) Toutes les stations piézométriques actives en 2020 sur une emprise** :

```sql
SELECT station_id, name, x, y
FROM stations
WHERE variable = 'piezometry'
  AND provider = 'hubeau'
  AND active_from <= '2020-01-01'
  AND (active_to IS NULL OR active_to >= '2020-12-31')
  AND x BETWEEN 100000 AND 200000;
```

**3) Artefacts expirés (pour purge)** :

```sql
SELECT artifact_id, path
FROM artifacts a JOIN provenance p USING (artifact_id)
WHERE p.fetched_at < current_timestamp - INTERVAL 180 DAY
  AND a.status = 'cached';
```

**4) Dernier rapport de validation pandera échoué par variable** :

```sql
SELECT a.variable, v.schema_name, v.errors_json
FROM validation_reports v JOIN artifacts a USING (artifact_id)
WHERE NOT v.passed
QUALIFY row_number() OVER (PARTITION BY a.variable ORDER BY v.validated_at DESC) = 1;
```

**5) Join provenance entre cache d'entrée et simulation de sortie** :

```sql
ATTACH 'data/cache.duckdb' AS cdb (READ_ONLY);
SELECT sim.sim_id, sim.project,
       cart.variable, cart.provider, cart.sha256, cart.fetched_at
FROM simulations sim
JOIN provenance sp USING (sim_id)           -- table déjà existante (output)
JOIN cdb.cache.artifacts cart USING (sha256);
```

### 5.6 Migrations

```python
# hydromodpy/data/cache_migrations.py   [NOUVEAU]
MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial schema", "... CREATE TABLE _schema_version; ..."),
    (2, "add status enum to artifacts", "ALTER TABLE artifacts ADD COLUMN status ..."),
    (3, "add validation_reports", "CREATE TABLE validation_reports ..."),
]

def migrate(conn: duckdb.DuckDBPyConnection) -> None:
    current = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM _schema_version"
    ).fetchone()[0]
    for version, desc, sql in MIGRATIONS:
        if version <= current: continue
        with conn.begin():
            conn.execute(sql)
            conn.execute("INSERT INTO _schema_version VALUES (?, ?, ?)",
                         [version, dt.datetime.utcnow(), desc])
```

### 5.7 Concurrence multi-processus

- Toutes les écritures sont dans un `with conn.begin():` (BEGIN/COMMIT explicite).
- Table `failures` avec `retry_after` empêche les re-essais simultanés agressifs.
- Sur systèmes partagés (NFS, Ceph), recommandation : **un DuckDB par worker** avec merge final par `INSERT INTO … SELECT … FROM cdb2`. Documenté dans `core/workspace/concurrency.md`.

---

## 6. Récapitulatif par variable

| Variable | Format d'entrée canonique | Schéma | Format de sortie interne | Exemple de fichier |
|---|---|---|---|---|
| `dem` | COG GeoTIFF (Float32) | `DEMContract` | Zarr `geographic/dem` + GeoTIFF export | `dem_bdalti25_L93.tif` |
| `geology` (raster) | COG GeoTIFF (UInt16) + GeoParquet sidecar | `LithologyTableSchema` | Zarr `geographic/geology` + GeoParquet | `geology_brgm50k.tif` + `lithology_table.parquet` |
| `geology` (vector) | GeoParquet (Polygon) | `GeologyVectorSchema` | GeoParquet dans Zarr | `geology_brgm50k.geoparquet` |
| `hydrography` | GeoParquet (LineString/Polygon) | `HydrographySchema` | GeoParquet | `hydrography_bdtopage.geoparquet` |
| `hydrometry` | Parquet chronique + GeoParquet stations | `TimeSeriesSchema` + `StationCollectionSchema` | Parquet | `hydrometry_hubeau_K123_P1H.parquet` |
| `piezometry` | idem | idem | Parquet | `piezometry_hubeau_BSS002_P1D.parquet` |
| `water_quality` | idem + colonne `parameter_code` | `WaterQualityTimeSeriesSchema` | Parquet | `wq_hubeau_06_NO3.parquet` |
| `intermittency` | idem + colonne `state` (categorical) | `IntermittencySchema` | Parquet | `onde_hubeau_F1234.parquet` |
| `oceanic` | Parquet chronique (tide) + GeoParquet marégraphes | idem hydrometry | Parquet | `oceanic_shom_BREST_P1H.parquet` |
| `recharge` | CF-NetCDF ou Zarr | `validate_cf_field` | Zarr CF | `recharge_sim2_2000-2024.nc` |
| `runoff`, `etp`, `precipitation`, `temperature`, `humidity`, `wind`, `radiation`, `soil_moisture` | idem | idem | Zarr CF | `<var>_sim2_<period>.nc` |

---

## 7. Feuille de route migration

### 7.1 Sprint 1 — Fondations contrats (S1, 3 semaines)

1. Créer `data/schemas/` avec `TimeSeriesSchema`, `StationCollectionSchema`, `DEMContract`, `LithologyTableSchema`, `validate_cf_field`.
2. Créer `data/contracts/point_record.py` et `field_record.py` refactorés (`pd.Series`, `xr.Dataset` obligatoires). Supprimer `Union[Dataset, Path]`.
3. Introduire `DataContractViolation` exception.
4. Ajouter sidecar metadata Parquet (`variable`, `unit`, `station_id`, `provider`, `sha256`).

### 7.2 Sprint 2 — Pattern Manager & Registry (S2, 3 semaines)

5. Créer `data/base.py` avec `DataSource` Protocol.
6. Créer `data/registry.py` avec `@register_source` decorator.
7. Migrer hydrometry/piezometry/water_quality/intermittency vers le nouveau pattern (~4×30 lignes).
8. Migrer oceanic, puis le bloc climatique SIM2 (consolidation 9 wrappers → 1 client paramétré).
9. Supprimer `base_manager.py`, `base_field_manager.py`, `runtime_loader.py` (remplacés par `loader.py`).

### 7.3 Sprint 3 — DEM / Géologie / Hydrographie (S3, 2 semaines)

10. Migrer DEM, Geology, Hydrography vers `DataSource`.
11. Ingérer au format pivot unique (COG pour raster, GeoParquet pour vecteur).
12. Factoriser `_resolve_bbox*` dans `spatial/crs.py`.

### 7.4 Sprint 4 — Cache DuckDB refondu (S4, 2 semaines)

13. Implémenter le nouveau schéma `data_cache.duckdb` (6 tables).
14. Migration depuis l'ancien schéma via script one-shot.
15. Invalidation par SHA-256 + TTL.
16. Transactions explicites.
17. Tests concurrents (pytest-xdist + tempdir).

### 7.5 Sprint 5 — UGRID unifié & sorties Zarr CF (S5, 4 semaines)

18. `hydromodpy/spatial/mesh/ugrid.py` avec les trois constructeurs (DIS, DISV, DISU).
19. Refactor extracteurs solveurs (`simulation/results/extractors/*`) pour écrire en UGRID face-indexé.
20. Valider par `cf-checker` et `uxarray.Grid.validate()`.
21. Migration des simulations existantes via script `hmp migrate-zarr`.

### 7.6 Sprint 6 — Exports & interopérabilité (S6, 2 semaines)

22. Ajouter exports WaterML 2.0 (chroniques) et COG (rasters).
23. Paquet portable `.hmp` (tar.zst) + `hmp import/export`.
24. Documentation CF-1.11 + UGRID-1.0 vérifiée par `cfchecks`.

**Total estimé : ~16 semaines, 1 développeur senior Data Engineering. ROI : conformité CF/UGRID/GeoParquet, -30 à -40 % LOC sur `data/`, +robustesse cache multi-processus, portabilité scientifique (ESSD/HESS).**

---

## 8. Conclusion

La refonte proposée remplace **trois formats propriétaires** (CSV LOC, CSV chronique, FieldRecord/Path hybrid) par **trois standards industriels** (GeoParquet, Parquet + sidecar Frictionless, CF-NetCDF/Zarr UGRID). La chaîne de post-traitement devient **topologie-agnostique** grâce à UGRID, et le cache **fiable en multi-processus** grâce aux transactions explicites et au SHA-256.

Trois invariants guident l'implémentation :

1. **Un contrat = un schéma pandera/pydantic typé + un format canonique + un sidecar métadonnées**. Rien d'autre. Pas de dataclass qui duplique ce qu'un Series/Dataset encode déjà.
2. **Un manager = une fonction `fetch(extent, period, cache) → LoadResult`**. Le reste (validation, cache, HTTP robuste) est délégué à des composants partagés.
3. **Une grille = UGRID**. Toute sortie spatiale est indexée par `face` ; la chaîne d'analyse ne voit jamais `row`/`col`/`node`.

Les utilisateurs cibles y gagnent simultanément :

- **Chercheur IA** : `xr.open_zarr()` + `pd.read_parquet()`, aucun code spécifique HydroModPy.
- **Hydrogéologue QGIS** : GeoParquet et COG ouverts nativement.
- **Étudiant Jupyter** : `sim.head.plot()` fonctionne sans configurer quoi que ce soit.
- **Framework de validation** : pandera `validate()` sur chaque Parquet, `cf-checker` sur chaque NetCDF.

Cette architecture est **le strict minimum pour un usage scientifique publiable**. Elle n'est pas plus complexe que l'existant — elle est plus *standard*.
