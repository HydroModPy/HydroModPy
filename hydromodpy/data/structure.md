# Data Managers — Architecture complete

> Derniere mise a jour : 2026-03-18

---

## 1. Vue d'ensemble

Le module `data_managers` orchestre le chargement, la mise en cache et
l'export de toutes les donnees d'entree d'HydroModPy.

**Pipeline principal :**

```
TOML [data]
  -> DataManagersConfig        (validation Pydantic)
  -> DataManagersPlanner       (inference explicite + implicite)
  -> DataLoadPlan              (contrat immutable)
  -> DataManagersRuntimeLoader (dispatch par variable)
  -> VariableManager.load()    (fetch API / custom / cache)
  -> LoadResult                (contrat de sortie unifie)
```

**API publique** (`__init__.py`) :
`DataManagers`, `DataManagersConfig`, `DataLoadPlan`,
`DataManagersPlanner`, `DataManagersRuntimeLoader`.

---

## 2. Arborescence

```
data_managers/
├── __init__.py                 # API publique
├── README.md                   # Doc orchestration racine
├── structure.md                # Ce fichier
├── data_managers_config.py     # Schema Pydantic [data]
├── planner.py                  # Moteur d'inference
├── plan.py                     # DataLoadPlan (frozen dataclass)
├── data_managers.py            # Conteneur runtime leger
├── runtime_loader.py           # Dispatch chargement par type
├── store.py                    # DataStore (facade utilisateur)
├── scaffold.py                 # Initialisation workspace (hmp init)
│
├── contracts/                  # Contrats de sortie
│   ├── load_result.py          # LoadResult
│   ├── timeseries.py           # PointRecord
│   ├── spatial_field.py        # FieldRecord
│   └── location.py             # StationLocation
│
├── registry/                   # Catalogue SQL
│   └── catalog.py              # DataCatalog (SQLAlchemy ORM)
│
├── common/                     # Utilitaires partages
│   ├── base_manager.py         # BaseVariableManager (donnees ponctuelles)
│   ├── base_field_manager.py   # BaseFieldManager (donnees grille)
│   ├── api_helpers.py          # HTTP retry / pagination
│   ├── io_helpers.py           # Parsing fichiers, lecture CSV/LOC
│   ├── geo_helpers.py          # Bbox, haversine, masques spatiaux
│   ├── unit_helpers.py         # Conversions d'unites
│   ├── validation.py           # Completude, colonnes requises
│   ├── export.py               # Export CSV (chroniques + metadata)
│   ├── custom_grid_loader.py   # Chargement NetCDF / GeoTIFF custom
│   ├── administrative/         # Subdivisions France (departements)
│   │   └── france.py           # find_departments_in_bbox()
│   └── clients/                # Clients API multi-variables
│       ├── sim2_edr.py         # Client SIM2 EDR (auth, grilles)
│       └── sim2_variables.py   # Registre SIM2 (11 variables)
│
├── variables/                  # 17 managers par variable
│   ├── dem/                    # MNT
│   ├── geology/                # Geologie
│   ├── hydrography/            # Reseau hydrographique
│   ├── hydrometry/             # Debits
│   ├── piezometry/             # Niveaux piezometriques
│   ├── water_quality/          # Qualite physico-chimique
│   ├── intermittency/          # Etat d'ecoulement (ONDE)
│   ├── oceanic/                # Maregraphie / niveau marin
│   ├── precipitation/          # Precipitations
│   ├── etp/                    # Evapotranspiration potentielle
│   ├── recharge/               # Recharge
│   ├── runoff/                 # Ruissellement
│   ├── temperature/            # Temperature
│   ├── wind/                   # Vent
│   ├── humidity/               # Humidite relative
│   ├── radiation/              # Rayonnement
│   └── soil_moisture/          # Indice d'humidite du sol
│
└── climatic/                   # DEPRECATED (legacy, ne pas utiliser)
```

---

## 3. Contrats de sortie (`contracts/`)

Tous les managers retournent un `LoadResult`.

### LoadResult

```python
@dataclass
class LoadResult:
    points: list[PointRecord]    # Chroniques stationnelles
    fields: list[FieldRecord]    # Grilles / vecteurs spatiaux
```

- `len()` = points + fields
- `bool()` = True si au moins un enregistrement
- `all_records` = liste plate (retro-compat)

### PointRecord

```python
@dataclass
class PointRecord:
    station_id: str          # Identifiant station
    variable: str            # ex. "hydrometry"
    source: str              # ex. "hubeau", "custom", "sim2"
    unit: str                # ex. "m3/s"
    frequency: str           # ex. "D"
    data: pd.DataFrame       # Colonnes obligatoires : datetime, value
    date_start: datetime
    date_end: datetime
    location: StationLocation | None
    is_constant: bool        # True si valeur unique etendue
    file_path: Path | None   # Fichier source
```

Validation `__post_init__` : colonnes `datetime`/`value` requises, coercion dtypes.

### FieldRecord

```python
@dataclass
class FieldRecord:
    variable: str                 # ex. "precipitation"
    source: str                   # ex. "sim2"
    unit: str                     # ex. "mm/day"
    data: xr.Dataset | Path       # En memoire ou reference fichier
    bbox: tuple                   # (xmin, ymin, xmax, ymax)
    crs: str                      # ex. "EPSG:2154"
    date_start: datetime | None   # None = statique
    date_end: datetime | None
    frequency: str | None
```

- `is_static` : True si pas de bornes temporelles
- `is_file_reference` : True si `data` est un `Path`

### StationLocation

```python
@dataclass(frozen=True)
class StationLocation:
    id: str
    x: float
    y: float
    crs: str
    metadata: dict
```

---

## 4. Deux familles de managers

### 4.1 BaseVariableManager (donnees ponctuelles)

Heritage : `HydrometryManager`, `PiezometryManager`, `IntermittencyManager`,
`WaterQualityManager`.

**Sortie** : `LoadResult(points=[...])`

**Cache intelligent :**
1. Verifier le sentinelle vide (`file_path="empty"`) → skip
2. Charger le cache CSV via `find_cached(variable, source, station_id)`
3. Calculer les periodes manquantes (`_compute_missing_periods`)
4. Si manquant → fetch API partiel → `_merge_into_record` (concat + dedup datetime)
5. Persister le CSV fusionne + MAJ catalogue

**Persistance API :**
- Fichier chronique : `{variable}_{source}_{station}_{YYYYMMDD}_{YYYYMMDD}_{freq}.csv`
- Fichier LOC : `{variable}_{source}_LOC.csv` (id, x, y, crs, metadata...)
- Upsert catalogue par cle `(variable, source, station_id)`

**Sentinelle stations vides :**
- Stations API sans donnees → `register(file_path="empty")`
- Evite les appels API redondants aux runs suivants
- Bypass avec `force_refresh=True`

### 4.2 BaseFieldManager (donnees grille)

Heritage : `PrecipitationManager`, `EtpManager`, `RechargeManager`,
`RunoffManager`, `TemperatureManager`, `WindManager`, `HumidityManager`,
`RadiationManager`, `SoilMoistureManager`, `OceanicManager`.

**Sortie** : `LoadResult(points=[...], fields=[...])`

**Cache grille :**
1. `_find_cached_fields(source, variable_names, bbox)` → logique tout-ou-rien
   - Si 1 des N sous-variables manque → cache miss complet
2. Si miss → fetch API → `_persist_field_records`
3. Persistence : sauvegarde `.nc`, register catalogue, **subsumption**
4. Nom deterministe : `{variable}_{source}_{bbox_hash}_{YYYYMMDD}_{YYYYMMDD}.nc`

**Subsumption :**
Apres enregistrement d'une grande grille, supprime les grilles plus petites
entierement contenues (spatialement ET temporellement) dans la nouvelle.
- Ne subsume jamais les donnees custom (`is_custom=1`)
- Supprime les fichiers `.nc` du disque

### 4.3 Managers custom (pas d'heritage de base)

`DemManager`, `GeologyManager`, `HydrographyManager` ont leur propre
architecture car leurs pipelines sont specifiques :

- **DEM** : raster (TIF, ASC, NetCDF) → `FieldRecord`
- **Geology** : vecteur/raster/CSV (Voronoi) → `FieldRecord` + encodage
  categoriel + override terre/mer optionnel
- **Hydrography** : vecteur → clip bassin → rasterisation (WhiteBox) →
  `HydrographyResult(streams_shp, tif_streams, streams_array)`

---

## 5. Les 17 variables

### Variables climatiques (9) — BaseFieldManager + SIM2 EDR

| Variable | INTERNAL_UNIT | Code SIM2 | Sources |
|----------|--------------|-----------|---------|
| precipitation | mm/day | PRELIQ_Q + PRENEI_Q | sim2, custom |
| etp | mm/day | ETP_Q | sim2, custom |
| recharge | mm/day | DRAINC_Q | sim2, custom, synthetic |
| runoff | mm/day | RUNC_Q | sim2, custom |
| temperature | degC | T_Q | sim2, custom |
| wind | m/s | FF_Q | sim2, custom |
| humidity | % | HU_Q | sim2, custom |
| radiation | MJ/m2/j | DLI_Q + SSI_Q | sim2, custom |
| soil_moisture | % | SWI_Q | sim2, custom |

**Variables composees** : precipitation (liquide + solide), radiation
(atmospherique + visible). Le cache est tout-ou-rien sur les composantes.

**Source synthetic** (recharge uniquement) : valeur scalaire avec modulation
sinusoidale optionnelle (amplitude, periode, offset).

### Variables hydrologiques ponctuelles (4) — BaseVariableManager

| Variable | INTERNAL_UNIT | API | Sources |
|----------|--------------|-----|---------|
| hydrometry | m3/s | Hub'Eau Hydrometrie | hubeau, custom |
| piezometry | m | Hub'Eau Piezometrie | hubeau, custom |
| intermittency | code | Hub'Eau ONDE | hubeau, custom |
| water_quality | mg/L | Hub'Eau Qualite | hubeau, custom |

**Hydrometry** : produits QmnJ/QmM/HmnJ/etc., chunks 20 000 jours,
conversion L/s → m3/s.
**Piezometry** : option `nearest=True` (station la plus proche du centroide).
**Intermittency** : codes 1-5 (Sec → Visible), frequence irreguliere.
**Water Quality** : `site_type` (river/piezometer), filtre par parametres.

**Discovery** (`hydrometry/discovery.py`, `piezometry/discovery.py`) :
recherche par bbox, masque, rayon de repli, tri haversine par centroide.

### Variables spatiales (3) — Architecture custom

| Variable | Sources | Sortie |
|----------|---------|--------|
| dem | ign_bdalti, custom | FieldRecord (TIF/NC) |
| geology | brgm_1m, brgm_50k, custom | FieldRecord (GPKG/TIF) |
| hydrography | bdtopage, euhydro, osm, custom | HydrographyResult |

### Oceanic (1) — BaseFieldManager

| Variable | INTERNAL_UNIT | Sources |
|----------|--------------|---------|
| oceanic | m | shom, constant, custom |

Necessite l'objet `geographic` (centroide bassin pour la recherche SHOM).
Source `constant` : valeur scalaire etendue en serie journaliere.

---

## 6. Catalogue SQL (`registry/catalog.py`)

### Technologie

SQLAlchemy ORM, backend SQLite (defaut : `workspace/catalog.db`),
PostgreSQL ready.

### Schema

```sql
CREATE TABLE entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    variable    VARCHAR NOT NULL,   -- index
    source      VARCHAR NOT NULL,   -- index
    station_id  VARCHAR,            -- NULL pour les grilles
    bbox_xmin   FLOAT,
    bbox_ymin   FLOAT,
    bbox_xmax   FLOAT,
    bbox_ymax   FLOAT,
    crs         VARCHAR,
    date_start  VARCHAR,            -- ISO format
    date_end    VARCHAR,
    frequency   VARCHAR,
    unit        VARCHAR,
    file_path   TEXT NOT NULL,      -- relatif ou absolu
    file_mtime  FLOAT,              -- Unix mtime
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_custom   INTEGER DEFAULT 0   -- 0=API, 1=utilisateur
);

CREATE TABLE api_coverage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    variable    VARCHAR NOT NULL,
    source      VARCHAR NOT NULL,
    country     VARCHAR,
    description TEXT,
    bbox_xmin   FLOAT,
    bbox_ymin   FLOAT,
    bbox_xmax   FLOAT,
    bbox_ymax   FLOAT
);
```

### Operations du catalogue

#### register() — Upsert

- **Cle point** : `(variable, source, station_id)` → update si existe
- **Cle grille** : `(variable, source, file_path)` → update si existe
- Retourne l'`id` de l'entree

#### find_cached() — Recherche superset

Retourne la premiere entree dont les bornes **contiennent** les bornes
demandees (bbox ET dates). Logique stricte : couverture partielle = miss.

```
Demande : bbox=(1,2,3,4), dates=[2020, 2025]
Cache   : bbox=(0,1,4,5), dates=[2019, 2026]  →  HIT (superset)
Cache   : bbox=(1,2,3,4), dates=[2020, 2023]  →  MISS (dates partielles)
```

#### subsume_entries() — Nettoyage grilles

Apres enregistrement d'une grande grille, supprime les entrees :
- Meme `(variable, source)`, `station_id IS NULL`
- `is_custom = 0` (ne touche jamais aux donnees utilisateur)
- Bbox **contenue** dans la nouvelle grille
- Dates **contenues** dans la nouvelle grille
- `id != exclude_id` (preserve l'entree nouvellement creee)

**Supprime aussi les fichiers .nc du disque.**

#### invalidate() — Suppression selective

Filtre par `variable`, `source`, `station_id` (tous optionnels).
`delete_files=True` → supprime les fichiers. Ignore les sentinelles
("custom", "empty").

#### cleanup() — Purge orphelins

Parcourt toutes les entrees, supprime celles dont le fichier n'existe plus.

#### list_entries() — Audit

DataFrame avec colonnes : id, variable, source, station_id, date_start,
date_end, file_path, is_custom.

### Fallback sans SQLAlchemy

`_FallbackDataCatalog` dans `store.py` : liste en memoire, `find_cached()`
retourne toujours `None`, pas de subsumption. Fonctionnel mais sans
persistence ni cache intelligent.

---

## 7. Formats de donnees supportes

### Entree (custom)

| Format | Variables | Usage |
|--------|-----------|-------|
| CSV chronique | Toutes ponctuelles + climatiques | `datetime,value[,quality]` |
| CSV LOC | Toutes ponctuelles + climatiques | `id,x,y,crs[,unit,...]` |
| SHP/GPKG/GeoJSON LOC | Toutes ponctuelles | Localisations vectorielles |
| NetCDF (.nc) | Climatiques, DEM | Grilles spatio-temporelles |
| GeoTIFF (.tif) | Climatiques, DEM, geology | Rasters statiques ou temporels |
| Esri ASCII Grid (.asc) | DEM | Raster legacy (converti en TIF) |
| SHP/GPKG/GeoJSON | Geology, hydrography | Vecteurs polygones/lignes |
| CSV (x, y, code) | Geology | Interpolation Voronoi |

### Nommage standardise

```
{VARIABLE}_{SOURCE}_{ID}_{YYYYMMDD}_{YYYYMMDD}_{FREQ}.{ext}
{VARIABLE}_{SOURCE}_LOC.{csv|shp|gpkg|geojson}
```

| Token | Description | Exemples |
|-------|-------------|----------|
| VARIABLE | Nom de la variable | hydrometry, precipitation |
| SOURCE | Provenance | hubeau, sim2, custom, brgm_1m |
| ID | Identifiant station | J7214001, synthetic |
| YYYYMMDD | Dates debut/fin | 20200101, 20251231 |
| FREQ | Pas de temps | D (jour), ME (mois), YE (an) |
| ext | Extension | csv, nc, tif |

**Exemples :**
```
hydrometry_hubeau_J7214001_20200101_20251231_D.csv
hydrometry_hubeau_LOC.csv
precipitation_sim2_a3f2b1c_20200101_20251231.nc
geology_brgm_1m.gpkg
dem_ign_bdalti.tif
hydrography_bdtopage_coursdeau.shp
oceanic_shom_185_20200101_20251231_D.csv
recharge_custom_synthetic_20200101_20251231_D.csv
```

### Cache disque

- **Point (API)** : CSV dans `workspace/data/{variable}/`
- **Grille (API)** : NetCDF dans `workspace/data/{variable}/`
- **Custom** : reference au fichier utilisateur (pas de copie)
- **Catalogue** : SQLite `workspace/catalog.db`

---

## 8. Configuration Pydantic

### Pattern variable

```python
class {VarName}SourceConfig(BaseModel):
    source: Literal["custom", "api1", "api2", ...]
    path: Path | None           # custom
    mask_path: Path | None      # filtre spatial
    extent: Literal["watershed", "study_area"] | None
    station_ids: list[str] | None
    force_refresh: bool = False
    # + champs specifiques API

class {VarName}Config(BaseModel):
    sources: list[{VarName}SourceConfig]
```

### Config racine (`DataManagersConfig`)

```python
class DataManagersConfig(BaseModel):
    types: list[str]                    # ["hydrometry", "precipitation", ...]
    inference_mode: Literal["warn", "strict"] = "warn"
    dem: DemConfig | None
    geology: GeologyConfig | None
    hydrography: HydrographyConfig | None
    hydrometry: HydrometryConfig | None
    intermittency: IntermittencyConfig | None
    oceanic: OceanicConfig | None
    piezometry: PiezometryConfig | None
    water_quality: WaterQualityConfig | None
    recharge: RechargeConfig | None
    runoff: RunoffConfig | None
    precipitation: PrecipitationConfig | None
    etp: EtpConfig | None
    temperature: TemperatureConfig | None
    wind: WindConfig | None
    humidity: HumidityConfig | None
    radiation: RadiationConfig | None
    soil_moisture: SoilMoistureConfig | None
```

Validation : normalisation `types` (lowercase, deduplique), verification
coherence `types` vs sections declarees, resolution chemins relatifs au TOML.

---

## 9. Inference (`DataManagersPlanner`)

Regles actuelles :

| Condition | Type infere | Raison |
|-----------|-------------|--------|
| `domain.zone_ids` contient "geology" | geology | structure domain |
| `domain.supports` provider "geology" | geology | support spatial |
| `flow.active_bc` contient "stream" | hydrography | condition limite |
| `flow.active_bc` contient "ocean" | oceanic | condition limite |

- Mode `warn` : infere et avertit
- Mode `strict` : exige une section `[data.<type>]` explicite pour les
  types inferes (sauf `geology` qui a un defaut automatique)
- Trace enregistree dans `DataLoadPlan.reasons_by_type`

---

## 10. Runtime loading

```python
DataManagersRuntimeLoader.load_all(result):
    for type_name in plan.types:
        section = _get_data_section(result, type_name)
        manager = {TypeManager}(
            config=section_config,
            catalog=self._catalog,
            project_extent=...,
            project_period=...,
            data_dir=workspace/data/{type_name}/,
        )
        load_result = manager.load()
        result.loaded_data.{type_name} = load_result
```

Dates de simulation injectees automatiquement si absentes du TOML
(`_apply_simulation_window_dates`).

---

## 11. Utilitaires communs

### API (`api_helpers.py`)
- `get_json()` : GET + retry exponentiel (3 essais, backoff x2)
- `paginate_json()` : pagination automatique (`page_size=1000`)

### I/O (`io_helpers.py`)
- `parse_chronicle_filename()` / `parse_loc_filename()` : regex d'extraction
- `read_locations_csv()` / `read_locations_vector()` : chargement LOC
- `read_timeseries_csv()` : normalisation colonnes datetime/value

### Spatial (`geo_helpers.py`)
- `bbox_contains()`, `haversine_km()`, `expand_bbox()`
- `filter_locations_by_bbox()`, `filter_locations_by_geometry()`
- `load_mask_geometry()` : SHP/GPKG/GeoJSON/TIF → geometrie shapely
- `nearest_location()` : station la plus proche

### Unites (`unit_helpers.py`)
- Conversions : L/s↔m3/s, mm/d↔m/s, mm/d↔m/d, cm↔m, mm↔m, ug/L↔mg/L
- `get_conversion_factor(from_unit, to_unit)` : facteur multiplicatif

### Validation (`validation.py`)
- `compute_completeness()` : jours attendus/reels/manquants, % completude
- `check_required_columns()` : verification colonnes DataFrame

### Export (`export.py`)
- `export_records()` : 1 CSV par station + metadata.csv + table_of_contents.csv

### Grilles custom (`custom_grid_loader.py`)
- `load_custom_nc()` : NetCDF → `list[FieldRecord]`, clip temporel optionnel
- `load_custom_tif()` : GeoTIFF → `list[FieldRecord]` statique

### Administratif (`administrative/france.py`)
- `find_departments_in_bbox()` : bbox → codes departement (GeoPackage IGN)

---

## 12. DataStore (facade utilisateur)

`store.py` fournit une API simplifiee pour le chargement interactif :

```python
store = DataStore(workspace_root="~/hydromodpy")
result = store.load_hydrometry(config)
result = store.load_precipitation(config)
store.cache_info("precipitation")    # DataFrame du catalogue
store.clear_cache(variable="precipitation", delete_files=True)
store.cleanup()                      # Purger orphelins
```

Utilise `DataCatalog` en interne, avec fallback `_FallbackDataCatalog` si
SQLAlchemy absent.

---

## 13. Workspace standard

```
workspace_root/                   (defaut: ~/hydromodpy)
├── catalog.db                    # SQLite
├── data/
│   ├── hydrometry/               # CSV chroniques + LOC
│   ├── piezometry/
│   ├── water_quality/
│   ├── intermittency/
│   ├── precipitation/            # .nc (grilles SIM2)
│   ├── etp/
│   ├── recharge/
│   ├── runoff/
│   ├── temperature/
│   ├── wind/
│   ├── humidity/
│   ├── radiation/
│   ├── soil_moisture/
│   ├── oceanic/
│   ├── dem/
│   ├── geology/
│   └── hydrography/
└── projects/
    └── {nom_projet}/
        ├── project.toml
        └── run_demo.toml
```

---

## 14. APIs externes integrees

| API | Variables | Couverture |
|-----|-----------|------------|
| Hub'Eau Hydrometrie | hydrometry | France metropolitaine |
| Hub'Eau Piezometrie | piezometry | France metropolitaine |
| Hub'Eau ONDE | intermittency | France metropolitaine |
| Hub'Eau Qualite | water_quality | France metropolitaine |
| SIM2 EDR (SAFRAN-ISBA) | 9 vars climatiques | France metropolitaine |
| SHOM | oceanic | Cotes francaises |
| IGN GeoPlateforme BD ALTI | dem | France metropolitaine |
| BRGM 1:1M / 1:50K | geology | France metropolitaine |
| Sandre WFS (BD Topage) | hydrography | France metropolitaine |
| EU-Hydro (EEA) | hydrography | Europe |
| OpenStreetMap (Overpass) | hydrography | Mondial |

---

## 15. Points d'attention

- **Subsumption** : ne touche **jamais** les donnees custom (`is_custom=1`).
- **Sentinelles vides** : les stations API sans donnees sont marquees
  `file_path="empty"` pour eviter les re-appels.
- **Cache partiel grille** : logique tout-ou-rien sur les variables composees.
- **Chemins relatifs** : le catalogue stocke des chemins relatifs pour la
  portabilite. Resolution via `data_dir / file_path`.
- **Conversion d'unites** : appliquee au chargement custom (LOC → colonne
  `unit`), transparente pour les APIs (unite interne fixee).
- **Masquage spatial** : `mask_path` filtre les stations ponctuelles et
  decoupe les grilles au chargement.
- **force_refresh** : bypass complet du cache pour une source donnee.
- **Legacy** : le dossier `climatic/` est deprecie et ne doit plus etre utilise.
