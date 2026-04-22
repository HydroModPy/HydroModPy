# Data Managers — Architecture complete

> Derniere mise a jour : 2026-04-02

---

## 1. Vue d'ensemble

Le module `data_managers` orchestre le chargement, la mise en cache et
l'export de toutes les donnees d'entree d'HydroModPy.

**Pipeline principal :**

```
TOML [data]
  -> DataManagersConfig        (validation Pydantic)
  -> DataPlanner       (inference explicite + implicite)
  -> DataLoadPlan              (contrat immutable)
  -> DataManagersRuntimeLoader (dispatch par variable)
  -> VariableManager.load()    (fetch API / custom / cache)
  -> LoadResult                (contrat de sortie unifie)
```

**API publique** (`__init__.py`) :
`DataManagers`, `DataManagersConfig`, `DataLoadPlan`,
`DataPlanner`, `DataManagersRuntimeLoader`.

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
├── registry/                   # Catalogue DuckDB
│   ├── catalog_duckdb.py       # DataCatalogDuckDB (DuckDB natif, retry backoff)
│   └── constants.py            # SENTINEL_CUSTOM, SENTINEL_EMPTY
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
    warnings: list[str]          # Erreurs non-bloquantes (source indisponible, etc.)
```

- `len()` = points + fields
- `bool()` = True si au moins un enregistrement
- `all_records` = liste plate (retro-compat)
- `warnings` : trace les sources en echec partiel sans bloquer le chargement

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
    quality: dict | None     # Rapport de qualite automatique (voir ci-dessous)
```

Validation `__post_init__` : colonnes `datetime`/`value` requises, coercion dtypes.

**Champ `quality`** (rempli automatiquement au `load()` si `data` non vide) :

```python
quality = {
    "completeness_pct": 94.5,    # % jours presents vs attendus
    "n_expected": 365,
    "n_actual": 345,
    "n_missing": 20,
    "n_gaps": 2,                 # nombre de trous (periodes consecutives manquantes)
    "n_duplicates": 0,           # doublons datetime detectes
}
```

Calcule via `compute_completeness()` qui existe deja dans `common/validation.py`.

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

**Lazy loading** : quand `data` est un `Path`, le `FieldRecord` charge le
dataset a la demande via une propriete `dataset` qui ouvre le fichier
(NetCDF ou GeoTIFF) au premier acces. Evite les `isinstance(rec.data, Path)`
dans le code consommateur.

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

> **A aligner** : `HydrographyManager` retourne un `HydrographyResult` custom
> qui casse le contrat `LoadResult`. Objectif : retourner un `LoadResult` avec
> `FieldRecord` pour le raster + metadonnees specifiques dans un champ dedie,
> sans perdre les attributs existants (`streams_shp`, etc.).

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

## 6. Catalogue DuckDB (`registry/catalog_duckdb.py`)

### Technologie

**DuckDB natif** (API Python `duckdb.connect()`), fichier
`workspace/catalog.duckdb`. SQLAlchemy est supprime du framework.

Le catalogue data est au **niveau workspace** (partage entre tous les projets
du workspace). Les resultats de simulation sont dans un fichier DuckDB
separe au niveau projet (`projects/{name}/project.duckdb`).

### Concurrence

`catalog.duckdb` est partage entre projets. Ecritures concurrentes gerees
par WAL mode (DuckDB par defaut) + retry avec backoff exponentiel sur
`IOException`. Voir `simulation/results/ARCHITECTURE.md` §2 pour les details.

### Schema

```sql
CREATE TABLE entries (
    id            INTEGER PRIMARY KEY,
    variable      VARCHAR NOT NULL,
    source        VARCHAR NOT NULL,
    station_id    VARCHAR,              -- NULL pour les grilles
    bbox_xmin     DOUBLE,
    bbox_ymin     DOUBLE,
    bbox_xmax     DOUBLE,
    bbox_ymax     DOUBLE,
    crs           VARCHAR,
    date_start    VARCHAR,              -- ISO format
    date_end      VARCHAR,
    frequency     VARCHAR,
    unit          VARCHAR,
    source_unit   VARCHAR,              -- unite d'origine de l'API
    file_path     TEXT NOT NULL,         -- relatif ou absolu
    file_mtime    DOUBLE,               -- Unix mtime
    created_at    TIMESTAMP NOT NULL DEFAULT now(),
    is_custom     INTEGER NOT NULL DEFAULT 0,  -- 0=API, 1=utilisateur
    fetch_metadata JSON                 -- URL, params, timestamp du telechargement
);

CREATE INDEX ix_entries_var_src_station ON entries(variable, source, station_id);
CREATE INDEX ix_entries_bbox ON entries(bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax);

CREATE TABLE api_coverage (
    id            INTEGER PRIMARY KEY,
    variable      VARCHAR NOT NULL,
    source        VARCHAR NOT NULL,
    country       VARCHAR,
    description   TEXT,
    bbox_xmin     DOUBLE,
    bbox_ymin     DOUBLE,
    bbox_xmax     DOUBLE,
    bbox_ymax     DOUBLE
);

-- Registre inter-projets des simulations (annuaire leger).
-- Alimente automatiquement par ResultStore.finalize().
-- Voir simulation/results/ARCHITECTURE.md §6 pour le schema complet.
CREATE TABLE simulation_registry (
    sim_id         UUID PRIMARY KEY,
    project        VARCHAR NOT NULL,
    project_path   TEXT NOT NULL,
    name           VARCHAR,
    solver         VARCHAR NOT NULL,
    process_types  VARCHAR[],
    status         VARCHAR NOT NULL,
    n_cells        INTEGER,
    n_layers       INTEGER,
    bbox           DOUBLE[4],
    period_start   DATE,
    period_end     DATE,
    duration_s     DOUBLE,
    best_nse       DOUBLE,
    best_kge       DOUBLE,
    best_rmse      DOUBLE,
    tags           VARCHAR[],
    forcing_sources VARCHAR[],
    config_hash     VARCHAR,
    created_at     TIMESTAMP DEFAULT now()
);
```

### Champ `fetch_metadata` (provenance API)

Enregistre les details du telechargement pour la reproductibilite :

```python
fetch_metadata = {
    "fetched_at": "2026-03-15T14:32:00",
    "api_url": "https://hubeau.eaufrance.fr/api/v1/...",
    "params": {"code_station": "J7214001", "size": 20000},
    "http_status": 200,
    "n_records_raw": 3650,        # avant filtrage/dedup
}
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
date_end, file_path, is_custom, fetch_metadata.

### Migration SQLite → DuckDB

```python
import duckdb
conn = duckdb.connect("workspace/catalog.duckdb")
conn.execute("INSTALL sqlite; LOAD sqlite")
conn.execute("ATTACH 'catalog.db' AS legacy (TYPE SQLITE)")
conn.execute("CREATE TABLE entries AS SELECT * FROM legacy.entries")
conn.execute("CREATE TABLE api_coverage AS SELECT * FROM legacy.api_coverage")
conn.execute("DETACH legacy")
# Ajouter la colonne fetch_metadata (absente de l'ancien schema)
conn.execute("ALTER TABLE entries ADD COLUMN fetch_metadata JSON")
```

Migration automatique au premier lancement si `catalog.db` (SQLite) detecte.

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
- **Catalogue** : DuckDB `workspace/catalog.duckdb` (migration auto depuis SQLite)

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
    project_crs: str | None = None     # CRS cible (ex. "EPSG:2154")
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

**`project_crs`** : si specifie, toutes les coordonnees des `StationLocation`
et les grilles `FieldRecord` sont reprojetees vers ce CRS au chargement.
Evite les melanges WGS84/Lambert dans le code consommateur.

Si absent, infere automatiquement depuis `geographic.crs_project`
(`GeographicConfig.crs_project`, defini dans
`spatial/geographic/geographic_config.py:242`). Valeur typique : `"EPSG:2154"`.

---

## 9. Inference (`DataPlanner`)

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

### Chargement parallele

Les managers sont independants les uns des autres (pas de dependances
croisees entre variables). `load_all()` peut paralleliser les appels
`manager.load()` via `concurrent.futures.ThreadPoolExecutor`.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def load_all(self, result):
    loaders = self._build_loaders(result)  # list[(type_name, callable)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): name for name, fn in loaders}
        for future in as_completed(futures):
            type_name = futures[future]
            try:
                load_result = future.result()
                setattr(result.loaded_data, type_name, load_result)
            except Exception as exc:
                logger.error("Chargement %s echoue : %s", type_name, exc)
                setattr(result.loaded_data, type_name, LoadResult(
                    warnings=[f"{type_name}: {exc}"],
                ))
```

Le parallelisme est I/O-bound (appels HTTP vers Hub'Eau, SIM2) donc
`ThreadPoolExecutor` suffit — pas besoin d'`asyncio`.

### Gestion d'erreur partielle

Si un manager echoue (API indisponible, timeout, format inattendu), le
chargement continue pour les autres variables. L'erreur est tracee dans
`LoadResult.warnings` et loguee. Le consommateur en aval (forcing bridge,
display) recoit un `LoadResult` vide avec le warning, et peut decider
de continuer ou d'echouer.

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

### Resampling (`resample.py`)
- `resample_timeseries(df, freq, method='mean')` : resampling standardise
  des chroniques (datetime, value) → evite la duplication de code dans les
  consommateurs (forcing bridge fait `resample('D').mean()`, display fait
  `resample('ME').mean()`)
- `align_timeseries(series_list, freq)` : aligne N series sur un index commun
- Methodes supportees : `mean`, `sum`, `min`, `max`, `nearest`

### Export (`export.py`)
- `export_records()` : 1 CSV par station + metadata.csv + table_of_contents.csv

### Grilles custom (`custom_grid_loader.py`)
- `load_custom_nc()` : NetCDF → `list[FieldRecord]`, clip temporel optionnel
- `load_custom_tif()` : GeoTIFF → `list[FieldRecord]` statique

### Administratif (`administrative/france.py`)
- `find_departments_in_bbox()` : bbox → codes departement (GeoPackage IGN)

---

## 12. DataStore (facade unifiee)

`store.py` est le **seul point d'entree** pour le chargement de donnees,
que ce soit en mode interactif ou via le pipeline de simulation.

```python
store = DataStore(workspace_root="~/hydromodpy")
result = store.load_hydrometry(config)
result = store.load_precipitation(config)
store.cache_info("precipitation")    # DataFrame du catalogue
store.clear_cache(variable="precipitation", delete_files=True)
store.cleanup()                      # Purger orphelins
```

### Fusion DataStore / DataManagersRuntimeLoader

Actuellement deux points d'entree coexistent :
- `DataStore` (facade interactive, registre `_MANAGER_REGISTRY`)
- `DataManagersRuntimeLoader` (pipeline simulation, dispatch `_LOADER_DISPATCH`)

**Objectif** : `DataManagersRuntimeLoader` delegue a `DataStore` en interne.
Un seul registre de managers, un seul chemin d'instantiation. L'ajout d'un
18e manager ne se fait qu'a un seul endroit.

**Approche retenue** : methodes nommees dans `DataStore` avec kwargs
specifiques par variable, plus un registre unique. Certains managers
ont besoin d'arguments supplementaires (GeologyManager → `geographic`,
DemManager → `geographic`, OceanicManager → centroide bassin). Des methodes
nommees rendent ces dependances explicites et faciles a maintenir.

```python
class DataStore:
    # Registre unique (remplace _MANAGER_REGISTRY et _LOADER_DISPATCH)
    _REGISTRY = {
        "hydrometry": ("...hydrometry.manager", "HydrometryManager"),
        "geology":    ("...geology.manager",    "GeologyManager"),
        # ... 17 entrees
    }

    def load_hydrometry(self, config) -> LoadResult:
        return self._load("hydrometry", config)

    def load_geology(self, config, *, geographic=None) -> LoadResult:
        return self._load("geology", config, geographic=geographic)

    def load_dem(self, config, *, geographic=None) -> LoadResult:
        return self._load("dem", config, geographic=geographic)

    def _load(self, variable, config, **extra_kwargs) -> LoadResult:
        cls = self._resolve_manager_class(variable)
        mgr = cls(config=config, catalog=self.catalog,
                  project_extent=self.project_extent,
                  project_period=self.project_period,
                  data_dir=self._data_dir(variable),
                  **extra_kwargs)
        return mgr.load()

# RuntimeLoader simplifie — delegue tout a DataStore
class DataManagersRuntimeLoader:
    def load_all(self, result):
        store = DataStore(workspace_root=..., ...)
        for type_name in self.data_plan.types:
            cfg = self._get_data_section(result, type_name)
            extra = self._extra_kwargs(result, type_name)
            load_result = store._load(type_name, cfg, **extra)
            setattr(result.loaded_data, type_name, load_result)
```

### Suppression de `_FallbackDataCatalog`

Le fallback en memoire (`_FallbackDataCatalog`) etait un workaround pour
l'absence de SQLAlchemy. Avec DuckDB comme dependance obligatoire, le
fallback n'a plus de raison d'etre. `duckdb` est toujours disponible.

---

## 13. Workspace standard

```
workspace_root/                   (defaut: ~/hydromodpy)
├── catalog.duckdb                # DuckDB (partage entre projets)
│                                 # tables: entries, api_coverage,
│                                 #         simulation_registry
├── data/                         # Cache partage entre projets
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
        ├── project.duckdb         # Resultats de simulation (par projet)
        ├── project_results.zarr/  # Champs volumiques (par projet)
        └── run_demo.toml
```

Le catalogue data (`catalog.duckdb`) est partage entre tous les projets du
workspace. Les donnees telechargees depuis les APIs sont mises en cache dans
`data/` et indexees dans `catalog.duckdb`. Un changement de projet ne
retelecharge pas les donnees deja en cache.

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

---

## 16. Evolutions planifiees

| Sujet | Statut | Section |
|-------|--------|---------|
| Migration catalogue SQLite → DuckDB | Planifie | §6 |
| Fusion DataStore / RuntimeLoader | Planifie | §12 |
| Suppression `_FallbackDataCatalog` | Planifie (apres migration DuckDB) | §12 |
| `LoadResult.warnings` (erreur partielle) | **Fait** — RuntimeLoader propage | §3, §10 |
| `PointRecord.quality` (`n_duplicates` dans completude) | **Fait** — `compute_completeness()` | §3 |
| `FieldRecord` lazy loading (`dataset` property) | **Fait** — `spatial_field.py` | §3 |
| `HydrographyResult` → `LoadResult` | Planifie | §4.3 |
| `project_crs` (reprojection auto) | **Fait** — champ dans `DataManagersConfig` | §8 |
| Chargement parallele (`ThreadPoolExecutor`) | **Fait** — `runtime_loader.py` | §10 |
| `fetch_metadata` (provenance API) | **Fait** — dans `list_entries()` | §6 |
| `resample.py` (resampling standardise) | **Fait** — stub dans `results/` | §11 |
| Suppression dependance SQLAlchemy | **Fait** — retiree des env_*.yml | §6 |
