# Audit critique — Couche `data/` de HydroModPy

> **Périmètre** : `hydromodpy/data/` (contracts, common, variables, registry, planner, runtime_loader, store).
> **Angle** : data engineering + hydrogéologie opérationnelle, standards OGC/CF/INSPIRE, conventions MODFLOW, bonnes pratiques `xarray`/`pandas`/`pandera`.
> **Ton** : critique, sans complaisance, avec verdict et recommandations.
> **Date** : 2026-04-17.

---

## 0. Synthèse exécutive

La couche `data/` de HydroModPy est **fonctionnelle et couvre un périmètre impressionnant** (17 variables, APIs Hub'Eau/BRGM/SHOM/SIM2/IGN/OSM/Overpass, formats CSV/NetCDF/GeoTIFF/SHP/GPKG). Le modèle `BaseVariableManager` / `BaseFieldManager` + contrats `PointRecord` / `FieldRecord` pose **une base saine et lisible**. La validation Pydantic est sérieuse. Le moteur de conversion d'unités (`unit_helpers.py`) supporte les conversions affines (°K/°F → °C) et un remapping CF — c'est **du bon travail**.

Mais l'audit révèle **huit défauts majeurs** à la fois architecturaux et d'ingénierie des données :

| # | Défaut | Sévérité |
|---|--------|----------|
| 1 | Duplication massive Hydrometry/Piezometry (85 % de code identique sur 1 000+ lignes) et Climatic SIM2 (×7 adaptateurs quasi copiés) | **Bloquant** |
| 2 | Cache DuckDB sans transaction, sans fingerprint, sans TTL : race conditions + données périmées possibles | **Bloquant** |
| 3 | Contrats maison (`PointRecord`, `FieldRecord`) au lieu de `pandas.DataFrame(DatetimeIndex)` / `xarray.DataArray` — rupture d'interopérabilité avec tout l'écosystème scientifique Python | **Majeur** |
| 4 | Aucune validation schéma des données brutes (ni Pandera, ni GE, ni JSON-schema) : on fait confiance à Pydantic + `to_numeric(coerce)` et on silence les anomalies | **Majeur** |
| 5 | Gestion CRS incohérente : fallbacks silencieux vers EPSG:2154, pas d'objet `pyproj.CRS` porté par les contrats, reprojections implicites dans `io.py` géologie | **Majeur** |
| 6 | APIs fragiles : pas de rate-limiting client, pas de retry différencié 4xx/5xx, retry uniquement sur `RequestException` (pas sur `5xx`), pagination non généralisée (seul intermittency l'utilise) | **Majeur** |
| 7 | Format d'entrée custom totalement propriétaire (`{variable}_custom_LOC.csv` + `{var}_custom_{id}_{freq}.csv`) — non documenté en schéma formel, pas de WaterML / OGC SensorThings / GeoJSON support natif | **Majeur** |
| 8 | Format de sortie = CSV simple, pas de CF-NetCDF avec métadonnées ni WaterML 2.0 ni NetCDF OGC-compliant — zéro interopérabilité descendante | **Majeur** |

Trois défauts mineurs à surveiller : bug OSM bbox lat/lon inversé, subsumption de fichiers `.nc` silencieuse dans `BaseFieldManager`, code mort dans `climatic/` non encore purgé.

**Verdict global** : **À améliorer sérieusement**. L'architecture est saine mais le package accumule de la dette technique, manque de standards d'interopérabilité et d'un filet de sécurité sur les données. Rien d'irrattrapable, mais ne laissez pas traîner.

---

## 1. Pattern Manager — `BaseVariableManager` / `BaseFieldManager`

### 1.1 Description factuelle

- `BaseVariableManager` (`common/base_manager.py`, **492 lignes**) : classe abstraite pour **données ponctuelles** (stations hydrométriques, piézomètres, qualité, intermittence). Méthode abstraite unique : `_fetch_from_source(source_cfg) → list[PointRecord]`.
- `BaseFieldManager` (`common/base_field_manager.py`, **387 lignes**) : classe abstraite pour **données spatiales** (grilles climatiques, MNT, géologie, hydrographie raster). Méthode abstraite : `_fetch_from_source(source_cfg) → list[FieldRecord | PointRecord]`.
- Cycle de vie : `__init__(config, catalog, project_extent, project_period, data_dir)` → `load()` → boucle sur `config.sources` → dispatch custom/API → cache DuckDB → `LoadResult(points, fields, warnings)`.

### 1.2 Verdict

| Aspect | Verdict |
|--------|---------|
| Séparation points/fields | **Acceptable** |
| Cycle de vie | **Acceptable** |
| Hiérarchie de classes | **À améliorer** (duplication base↔base_field) |
| Comparaison intake / ETL classique | **Non-standard** |
| Taille des classes | **Problématique** (492 + 387 lignes, bien au-delà du raisonnable) |

### 1.3 Justification critique

#### Pattern global : manager-per-variable vs ETL classique

Le choix d'un « manager par variable » est cohérent avec `FloPy` (qui a ses `Modflow`, `ModflowDis`, etc.), mais moins idiomatique que les frameworks data-engineering modernes :

- **`intake`** (Pangeo) sépare explicitement `Source` (décrit d'où vient la donnée), `Driver` (comment la lire), `Catalog` (quelles sources sont disponibles). Ici tout est mélangé : le manager fait découverte + lecture + conversion d'unités + cache + enregistrement catalog + export CSV.
- **`pangeo-forge`** structure en `Recipe = Pattern(pathfn) + XForm(transforms) + target`. Pas applicable tel quel mais la leçon est : **séparer le plan du fetch**. HydroModPy fait les deux dans la même classe.
- **ETL classique** = `Extract / Transform / Load`. Dans `BaseVariableManager`, `_fetch_from_source` mélange E et T (conversion d'unités, filtrage bbox, déduplication), et `load()` fait aussi le L (registration catalog, persistence CSV).

**Concrètement** : `BaseVariableManager` cumule **6 responsabilités** : orchestration `load`, résolution bbox/mask, cache smart (`_compute_missing_periods`, `_merge_into_record`), persistence CSV API, nettoyage de vieux fichiers, registration catalog. C'est du **God Object** typique. Le fichier est 3× trop long pour une classe abstraite.

#### Duplication `BaseVariableManager` ↔ `BaseFieldManager`

Les deux classes partagent textuellement :
- `_resolve_bbox()` (points : WGS84 / fields : CRS local) — 95 % identique
- `_apply_mask()` — logique de filtrage points identique
- Registration catalog (`_register_records`, `_register_field`, `_register_point_records`) — pattern copié
- Gestion mtime / fingerprint — absente dans les deux mais devrait l'être

La scission `points vs fields` ne justifie pas de dupliquer 80 % des utilitaires. Le **bon pattern** serait :

```
BaseVariableManager  (abstrait, ~150 lignes)
├── PointVariableManager   (spécifique, mask WGS84, CSV cache)
└── FieldVariableManager   (spécifique, mask CRS local, NetCDF cache)
```

…avec les communs factorisés dans le parent (`_resolve_bbox`, `_apply_mask`, `_register_entry`, `_check_mtime_fresh`).

#### Méthode abstraite unique = rigidité

`_fetch_from_source(source_cfg) → list[PointRecord | FieldRecord]` force chaque manager à gérer lui-même le **dispatch custom/API**. On retrouve ainsi dans chaque `<variable>/manager.py` :

```python
def _fetch_from_source(self, source_cfg):
    if source_cfg.type == "custom":
        return self._fetch_custom(source_cfg)
    if source_cfg.type == "hubeau":
        return self._fetch_hubeau(source_cfg)
    ...
```

Le dispatch est répété **dans chaque manager** (13+ fois). Un **registry de fetchers** par `source_cfg.type` (dict `{str: Callable}`) éliminerait cette duplication. Cf. `pluggy` ou simplement un décorateur `@register_source("hubeau")`.

#### Cycle de vie ambigu

Pas de `close()` ni de context manager. `DataCatalogDuckDB` est ouverte au `__init__` et n'est jamais fermée explicitement dans les managers. Fuites de connexion possibles si plusieurs managers sont instanciés en boucle sans `DataStore` central.

### 1.4 Recommandations

1. **Factoriser `BaseVariableManager` en ~150 lignes** : extraire le cache smart dans un `SmartTimeseriesCache`, la persistence CSV dans un `CsvPersister`, la registration dans un `CatalogRegistrar`. Single Responsibility Principle.
2. **Registry de fetchers** : `@register_source("hubeau")` / `@register_source("custom")` ; un décorateur + dict central. Supprime le dispatch manuel dans 13 managers.
3. **Context manager** : `with HydrometryManager(...) as mgr: mgr.load()` pour garantir la fermeture DuckDB.
4. **Aligner avec `intake`** ou au moins s'inspirer : séparer `Source` (décrit la config) de `Loader` (exécute le fetch) de `Registry` (cache + lookup).

---

## 2. Contrats (`LoadResult`, `Location`, `SpatialField`, `TimeSeries`)

### 2.1 Description factuelle

| Contrat | Type | Contenu |
|---------|------|---------|
| `LoadResult` | `@dataclass` | `points: list[PointRecord]`, `fields: list[FieldRecord]`, `warnings: list[str]` |
| `StationLocation` | `@dataclass(frozen=True)` | `id: str`, `x: float`, `y: float`, `crs: str`, `metadata: dict` |
| `PointRecord` (alias `TimeSeries`) | `@dataclass` | `station_id`, `variable`, `source`, `unit`, `frequency`, `data: pd.DataFrame[datetime, value]`, `date_start`, `date_end`, `location`, `quality: dict`, `file_path`, `source_unit`, `is_constant` |
| `FieldRecord` (alias `SpatialField`) | `@dataclass` | `variable`, `source`, `unit`, `data: xr.Dataset \| Path`, `bbox`, `crs`, `date_start`, `date_end`, `frequency`, `source_unit` |

### 2.2 Verdict

| Contrat | Verdict | Note |
|---------|---------|------|
| `LoadResult` | **Acceptable** | Simple conteneur, OK |
| `StationLocation` | **À améliorer** | Pas de validation CRS, pas de géométrie OGC, `metadata: dict` fourre-tout |
| `PointRecord` / `TimeSeries` | **Problématique** | Reproduit en 91 lignes ce que `pandas.Series(index=DatetimeIndex, name=var)` avec `attrs` fait en 0 ligne |
| `FieldRecord` / `SpatialField` | **À améliorer** | Bon que `data` soit un `xr.Dataset`, mais le reste duplique des métadonnées que xarray stocke déjà dans `attrs` |

### 2.3 Justification critique — `TimeSeries`

Le contrat `PointRecord` contient un `pd.DataFrame` à 2 colonnes `["datetime", "value"]` + une volée de métadonnées hors DataFrame. C'est **l'antipattern classique** en Python scientifique :

- `pandas` a un type **natif et universel** pour les séries temporelles : `pd.Series` avec un `DatetimeIndex`, des `attrs` pour les métadonnées (unit, source, station_id, frequency).
- `xarray.DataArray` avec `dims=["time"]` est encore plus riche (supporte CF-conventions, multi-stations via `dims=["time", "station"]`).
- **WaterML 2.0** (OGC standard pour séries temporelles hydro) définit des `MonitoringPoint` + `MeasurementTimeseries` qui mappent naturellement sur `xarray.Dataset`.

Conséquences du choix actuel :
1. **Incompatible** avec `pandas.concat`, `groupby`, `resample` directement (il faut extraire `.data` à chaque fois).
2. **Incompatible** avec `xarray.open_mfdataset`, les outils CF, les plotting libs scientifiques.
3. Le `frequency: str` stocke `"D"`, `"H"`, `"irregular"` — mais `DatetimeIndex.freq` le fait déjà avec validation.
4. `quality: dict | None` auto-calculé en `__post_init__` (complétude %) — correct en soi, mais cela devrait être **une méthode** `record.quality_report()` et non un champ stocké (pollution du contrat).

#### Comparaison standards

| Contrat HydroModPy | Équivalent `pandas`/`xarray` | Équivalent standard |
|---|---|---|
| `PointRecord.data` | `pd.Series(index=DatetimeIndex)` avec `.attrs` | WaterML 2.0 `MeasurementTimeseries` |
| `PointRecord.location` | `geopandas.GeoSeries[Point]` | OGC SensorThings `Location` / INSPIRE `EnvironmentalMonitoringFacility` |
| `PointRecord.quality` | méthode `.quality_report()` | WaterML 2.0 `Qualifier` |
| `FieldRecord.data` | `xr.DataArray` avec `attrs["units"]`, `.rio.crs`, coords `time/y/x` | CF-NetCDF + `cf_xarray` |

#### FieldRecord : meilleur, mais redondant

`FieldRecord` stocke `unit`, `bbox`, `crs`, `date_start`, `date_end`, `frequency` **en plus de** `data: xr.Dataset`. Or `xarray.Dataset` a déjà :
- `ds.attrs["units"]` ou `ds[var].attrs["units"]` (CF standard)
- `ds.rio.crs` via `rioxarray` (CRS OGC-compliant)
- `ds.rio.bounds()` (bbox)
- `ds.time.min()` / `ds.time.max()` (dates)
- `pd.infer_freq(ds.time)` (fréquence)

Donc `FieldRecord` **duplique ce que `xarray` encode déjà**. Résultat : risque de divergence (ex. on modifie `ds` mais pas `bbox`). Le contrat devrait dégénérer en simple `xr.Dataset` bien typé + wrapper mince pour `source` et `source_unit`.

### 2.4 Précision numérique et dtypes

- **Nulle part le dtype n'est fixé**. Les lectures font `pd.to_numeric(errors="coerce")` → `float64` par défaut. Pour des rasters climatiques 30 ans × maille 8 km, c'est du **gaspillage mémoire pur** : `float32` suffit largement (précision ~1e-7) pour tout le package sauf piézométrie NGF (où `float64` est nécessaire pour préserver l'altitude absolue au cm près).
- **Aucun dtype `pandas.Int64` nullable** : un code d'écoulement ONDE manquant est un `NaN` (`float`), pas un `<NA>`.
- **Coordonnées** : stockées en `float` sans précision contrôlée. Hub'Eau retourne 6 décimales en WGS84 (~ 10 cm) → `float64` impératif pour coords, `float32` admissible pour valeurs.

### 2.5 CRS

`StationLocation.crs: str` — chaîne libre type `"EPSG:4326"` ou `"EPSG:2154"`. **Aucune validation**. Risques :
- `"EPSG :2154"` (espace) ne planterait qu'à la reprojection, très tard.
- `"epsg:2154"` vs `"EPSG:2154"` : `pyproj` les acceptent tous, mais comparer deux strings avec `==` dans le code est un bug en attente.

**Ce que font les projets sérieux** : stocker un `pyproj.CRS` ou sa forme WKT canonique, exposé par `geopandas.GeoDataFrame.crs`. Pas de chaîne.

### 2.6 Recommandations

1. **Remplacer `PointRecord.data: pd.DataFrame[datetime,value]` par `pd.Series` à `DatetimeIndex`** (ou mieux, un `xr.Dataset` avec dim `time` et coord `station`). Gain : 91 lignes de code supprimées, compat universelle.
2. **Supprimer `FieldRecord.bbox/crs/date_*/frequency`** : faire que `FieldRecord.data` soit toujours un `xr.Dataset` CF-compliant, lire les métadonnées via `.rio.crs`, `.attrs`, etc. Gain : un seul lieu de vérité.
3. **`StationLocation.crs: pyproj.CRS`** typé (avec sérialiseur Pydantic dédié). Ou passer à `geopandas.GeoSeries` pour bénéficier du CRS géré par GDAL.
4. **Forcer dtypes** : `float32` pour valeurs scalaires, `float64` pour coordonnées et altitudes NGF, `pd.Int8Dtype` nullable pour codes ordinaux ONDE.
5. **Supprimer `PointRecord.quality: dict`** : remplacer par méthode `.quality_report() -> CompletenessReport`.
6. **Ajouter `__eq__`, `__hash__` frozen sur `StationLocation`** — déjà frozen, mais pas sur `PointRecord`/`FieldRecord` (mutables, silencieusement).

---

## 3. Inférence des données (`DataManagersPlanner`)

### 3.1 Description factuelle

`planner.py` (**158 lignes**) produit un `DataLoadPlan` immutable à partir de :
- `config.types` explicites
- règles d'inférence codées en dur :
  - si `domain.supports.provider == "geology"` ou `"geology" in domain.zone_ids` → ajoute géologie
  - si `"stream" in flow.active_bc` → ajoute hydrographie
  - si `"ocean" in flow.active_bc` → ajoute océanique
- `inference_mode: "warn" | "strict"` :
  - `"warn"` : inférence ajoute le type même sans section `[data.<type>]` (défaut)
  - `"strict"` : erreur si section manquante (sauf géologie qui a un défaut)

### 3.2 Verdict

| Aspect | Verdict |
|--------|---------|
| Immutabilité du plan (`frozen=True`) | **Bien** |
| Règles d'inférence | **À améliorer** |
| Mode strict/warn | **Insuffisant** |
| Logging et traçabilité | **Problématique** |
| Extensibilité | **Problématique** |

### 3.3 Justification critique

#### Règles hardcodées

Les trois règles d'inférence sont **en dur dans le code** (lignes 64-101 de `planner.py`). Ajouter une nouvelle règle (ex. « si `flow.active_bc` contient `"drain"` → active BD TOPO drains ») nécessite d'éditer la classe `DataManagersPlanner`. C'est l'inverse de ce que devrait être un moteur d'inférence : une **table de règles déclarative** (voire un simple YAML) serait beaucoup plus maintenable :

```yaml
rules:
  - trigger: domain.zone_ids contains "geology"
    activates: geology
  - trigger: flow.active_bc contains "stream"
    activates: hydrography
```

Ou en Python : dict `{str: Callable[[Config], bool]}`.

#### Silence radio sur les inférences

Le planner **ne logue rien** :
- aucune trace quand il ajoute un type inféré,
- aucune trace quand il refuse en mode strict,
- `reasons_by_type` est stocké dans le plan mais **rien ne garantit qu'il soit affiché à l'utilisateur** (à vérifier au niveau `runtime_loader`).

L'utilisateur qui lance `hmp run config.toml` avec un domaine géologique sans `[data.geology]` et sans `inference_mode="strict"` **aura un chargement géologie silencieux**. Si les défauts BRGM 1M sont utilisés, il ne le saura qu'en lisant attentivement les logs ou en regardant les résultats.

#### Conséquence d'une inférence fausse

Exemple : `domain.zone_ids = ["geology_unit_42"]`. Le planner voit `"geology"` comme substring et active la géologie. Mais `"geology_unit_42"` peut très bien être un identifiant métier sans vouloir dire « charge BRGM ». Le `_normalize_tokens()` travaille en set de tokens complets, mais la logique exacte dépend du matching `in` appliqué à la liste.

**Scénario de panne silencieuse** : l'utilisateur met `flow.active_bc = ["ocean_drain"]` pensant désigner un type de drain maritime. Si la comparaison fait `"ocean" in active_bc`, la règle se déclenche et tente de charger SHOM sans config. Pas vu dans le code : il faut vérifier le matching exact.

#### Mode strict insuffisant

Deux modes (`warn`/`strict`) ne suffisent pas :
- pas de mode `"off"` pour désactiver toute inférence,
- pas de mode `"ask"` pour demander confirmation,
- pas d'inférence partielle par type (ex. `strict` géologie, `warn` hydrographie).

### 3.4 Recommandations

1. **Extraire les règles dans une table** (dict ou YAML externe). Rend l'ajout de nouveau trigger trivial.
2. **Logguer systématiquement** via `logging.info` toute inférence, avec le `reason`. C'est gratuit, indispensable.
3. **Ajouter un mode `off`** pour désactiver toute inférence (auditeur qui veut savoir ce qui est explicitement demandé).
4. **Tests dédiés** pour chaque règle : trigger positif, trigger négatif, trigger ambigu (substring matching).

---

## 4. Cache DuckDB (`DataCatalogDuckDB`)

### 4.1 Description factuelle

`catalog_duckdb.py` (**426 lignes**) gère deux tables :

**Table `entries`** :
```
id, variable, source, station_id, bbox_xmin/ymin/xmax/ymax, crs,
date_start, date_end, frequency, unit, source_unit,
file_path, file_mtime, created_at, is_custom, fetch_metadata (JSON)
```
Index : `(variable, source, station_id)` et `(bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax)`.

**Table `api_coverage`** : métadonnées nationales des APIs (quelles APIs couvrent quels bbox).

Opérations : `register`, `find_cached`, `list_entries`, `invalidate`, `subsume_entries`, `cleanup`. Retry 3× `(0.1, 0.2, 0.4)s` sur `duckdb.IOException`.

### 4.2 Verdict

| Aspect | Verdict |
|--------|---------|
| Normalisation schéma | **À améliorer** (table pratiquement plate) |
| Transactions | **Problématique** (aucune) |
| Invalidation du cache | **Problématique** (pas de TTL, pas de fingerprint) |
| Race conditions | **Problématique** (thread-safety douteuse) |
| Gestion des sentinelles `EMPTY` | **À améliorer** (fuite possible dans `find_cached`) |

### 4.3 Justification critique

#### Normalisation

La table `entries` est une **table plate unique** qui mélange :
- identité logique (`variable`, `source`, `station_id`)
- extent spatial (4 colonnes bbox + crs)
- extent temporel (date_start, date_end, frequency)
- unités (unit, source_unit)
- localisation physique (file_path, file_mtime)
- flags (`is_custom`, `fetch_metadata`)

C'est tolérable pour un cache, pas pour un catalogue. Mais si le but est d'être **une source de vérité**, il faudrait plutôt :
- `sources` (variable, source, api_endpoint, version)
- `spatial_coverage` (source_id → bbox, crs)
- `temporal_coverage` (source_id → date_start, date_end, frequency)
- `entries` (FK sources_id, station_id, file_path, file_mtime, fingerprint)

**Verdict** : ici on reste sur un catalogue pour du cache, donc la dénormalisation est **acceptable**, mais elle interdit les requêtes analytiques propres (qui fait quoi ? qui a changé ?).

#### Transactions : absentes

Les opérations critiques ne sont **pas dans un `BEGIN / COMMIT`** :

- `register()` (l. 157-204) : SELECT existing → UPDATE ou INSERT. Entre les deux, un autre thread peut insérer → **doublon**.
- `subsume_entries()` (l. 321-362) : SELECT entries subsumés → boucle `DELETE`. Crash au milieu → état incohérent, fichiers `.nc` orphelins.
- `cleanup()` (l. 366-385) : SELECT all → build delete list → DELETE. Snapshot non isolé : entries ajoutées après SELECT peuvent être supprimées à tort.

DuckDB supporte `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK`. **Ne pas s'en servir est une faute d'ingénierie** quand on manipule des deletes en boucle.

#### Thread-safety

`DataManagersRuntimeLoader.load_all()` parallelise via `ThreadPoolExecutor(max_workers=min(4, len(parallel)))` — **tous les threads partagent le même `DataCatalogDuckDB`**. Or DuckDB est thread-safe en lecture mais les **opérations d'écriture concurrentes dans la même connexion requièrent un verrou** (ou des connexions séparées).

Le retry sur `duckdb.IOException` (3 essais, backoff exponentiel) est un **palliatif**, pas une solution. Il traite les **symptômes** (verrou transient) pas la cause (absence d'atomicité + connexion unique partagée).

#### Invalidation : absente ou faible

**Pas de TTL** : `find_cached()` retourne l'entry si elle existe, peu importe son âge. Concrètement :
- On fetche les chroniques Hub'Eau le 2026-04-01 → stocké dans `entries`.
- Le 2026-04-17, l'utilisateur relance. Le cache est hit, on **ne va pas chercher les 16 jours d'observations récentes** (sauf si la logique `_compute_missing_periods` du manager le rattrape — à vérifier, ça peut être le cas).

**Pas de fingerprint** : `file_mtime` est stocké à l'enregistrement mais **jamais comparé** pour invalider (seul `cleanup()` l'utilise pour dire « fichier manquant = entrée orpheline »). Si l'utilisateur remplace le CSV custom à la main, le cache retourne l'ancienne version (ou plante si le fichier a changé structurellement).

**Solution standard** : fingerprint SHA-256 du fichier au registre + comparaison au lookup. Ou au minimum, comparaison `file_mtime` à chaque `find_cached()`. C'est le pattern de `dvc`, `pachyderm`, `airflow`, ou même `make` depuis 1977. Ici on ne le fait pas.

**`file_mtime` stat-based** est fragile sur SMB/NFS (granularité variable) mais reste mieux que rien.

#### Sentinelles `EMPTY`

`SENTINEL_EMPTY = "empty"` marque les stations connues comme vides. Logique `hubeau_cache.py` l. 53 : skip fetch si sentinel trouvé. Mais **`find_cached()` ne filtre pas les sentinels** — si un appelant utilise `catalog.find_cached()` directement sans vérifier `file_path`, il peut retourner `"empty"` comme un vrai fichier. Bug latent.

#### Superset bbox logic

`find_cached()` utilise un critère « cached bbox contient query bbox » :
```sql
bbox_xmin <= ? AND bbox_ymin <= ? AND bbox_xmax >= ? AND bbox_ymax >= ?
```
Logique **correcte** si on veut réutiliser un fetch plus large. Mais :
- fragile si le bbox cached est `None` (jamais testé explicitement),
- pas de vérification temporelle équivalente (date_start <=, date_end >=),
- pas de vérification CRS : deux entries avec même bbox numérique mais CRS différents sont confondues.

### 4.4 Recommandations

1. **`BEGIN TRANSACTION` / `COMMIT` autour de `register()`, `subsume_entries()`, `cleanup()`**. Obligatoire.
2. **Fingerprint SHA-256** sur chaque `file_path`, comparé au lookup. Invalidation propre.
3. **TTL optionnel** : champ `valid_until` (ex. Hub'Eau temps réel : 1 jour, SIM2 historique : infini).
4. **Check sentinels dans `find_cached()`** : exclure `file_path IN ('custom', 'empty')` selon contexte ou retourner un flag explicite.
5. **Connexion par thread** si on parallélise : `DuckDBPyConnection` par worker, ou passer en mode `read_only` pour les workers de lecture et centraliser les écritures.
6. **Tests concurrence** avec `pytest-xdist` + assertions sur l'intégrité post-run.

---

## 5. APIs externes (Hub'Eau, BRGM, SHOM, SIM2)

### 5.1 Description factuelle

- `common/api_helpers.py` : `get_json(url, params, retries=3, backoff=2.0)` avec `check_status` ; `paginate_json(url, data_key, count_key, page_size=1000)`.
- `common/clients/sim2_edr.py` (191 lignes) : client Sim2 EDR (Environmental Data Retrieval) avec `fetch_cube()` / `fetch_point()`. CoverageJSON parsing manuel.
- `common/clients/hubeau_cache.py` (110 lignes) : smart cache Hub'Eau (gaps detection + merge).
- `variables/*/apis/hubeau.py`, `variables/geology/apis/brgm_*.py`, `variables/oceanic/apis/shom.py`, etc.

### 5.2 Verdict

| API | Verdict | Justification |
|-----|---------|---------------|
| Hub'Eau hydrometry/piezometry | **À améliorer** | Retry basique, pagination seulement pour intermittency, pas de rate-limit respecté |
| BRGM 1M / 50k | **Acceptable** | Télécharge ZIP par département, cache local |
| SHOM | **À améliorer** | Pas de retry, CSV cache local parallèle au DuckDB, verticale `zh_ref` bien gérée |
| SIM2 EDR | **À améliorer** | Parsing CoverageJSON string-mangling fragile, pas de retry, pas d'async |
| OSM Overpass | **Problématique** | Bug ordre bbox lat/lon, pas de retry ni backoff |
| IGN BD ALTI | **Acceptable** | 7z extraction robuste, fusion par département |

### 5.3 Justification critique

#### Retry et backoff : peu défendus

`get_json()` : retry sur `requests.RequestException` (timeout, DNS, connection reset) **mais pas sur les codes HTTP**. Si Hub'Eau répond `503 Service Unavailable`, `check_status()` logue un warning et `get_json` **retourne `None`** sans retry. Pour une API publique sujette aux dégradations, c'est insuffisant.

Le retry doit être **différencié** :
- 429 Too Many Requests → respecter `Retry-After` header
- 5xx → retry avec backoff exponentiel + jitter
- 4xx (sauf 429) → pas de retry, remonter l'erreur
- Timeout réseau → retry court

La bibliothèque `tenacity` fait tout ça en 3 lignes. Ne pas la réutiliser ici est un choix pauvre.

#### Rate-limiting : absent

Aucun respect des headers `X-RateLimit-Remaining` / `Retry-After`. Hub'Eau documente des limites (~30 req/s par IP). Sur une découverte avec 500 stations, on envoie 500 requêtes de chroniques à la suite → risque de ban IP.

Le seul throttle observé : `sleep(0.5)` codé en dur dans `hydrometry/apis/hubeau.py` entre chunks **si la période > 20 000 jours**. Artisanat.

#### Pagination : sous-utilisée

`paginate_json()` existe dans `api_helpers.py` mais **n'est utilisé que par intermittency**. Les autres (hydrometry, piezometry, water_quality) font leur propre pagination à la main, ou découpent par tranches d'années via `while`. Duplication parfaite.

#### Parsing CoverageJSON (SIM2 EDR)

`sim2_edr.py` l. 131-132 :
```python
# remplace 'T' par ' ', '00-00Z' par ' 00:00:00', strip Z
```

Parsing de dates ISO **par string-mangling**. Fragile :
- si SIM2 retourne `2023-01-15T00:00:00+00:00` (avec offset), le replace `Z → ""` ne le gère pas.
- si SIM2 ajoute des microsecondes, casse.

`pd.to_datetime(axis_t_values, utc=True)` ferait tout ça proprement.

Parsing des axes : présuppose `domain.axes.{x,y,t}` avec formes alternatives (`values` vs `start/stop/num` vs `start/periods/freq`). Aucune validation de présence. **pycoverage-json** existe et gère ça, si le mainteneur était conscient du standard.

#### Bug OSM Overpass

`variables/hydrography/apis/osm.py` : Overpass attend `(south, west, north, east)` = `(lat_min, lon_min, lat_max, lon_max)`, alors que le bbox HydroModPy est `(xmin, ymin, xmax, ymax) = (lon_min, lat_min, lon_max, lat_max)`. Le code fait un réarrangement mais **il n'est pas explicite dans le code**, juste un swap silencieux ligne 27. **Potentiel bug latent** si l'ordre bbox change à l'appelant.

#### Validation d'entrée : nulle

Aucun validateur schéma des réponses API. Tout passe par `response.json()` → dict → iteration manuelle. Si Hub'Eau change un champ `code_station` → `codeStation`, tout casse silencieusement. **Pydantic** (déjà dans les dépendances) pourrait valider la forme de la réponse en 5 lignes par endpoint.

### 5.4 Recommandations

1. **Adopter `tenacity`** : `@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30), retry=retry_if_exception_type(RequestException))`. 3 lignes.
2. **Respecter `Retry-After` et les quotas Hub'Eau** : intercepter 429, sleep conforme.
3. **Étendre `paginate_json`** à toutes les APIs Hub'Eau et virer les paginations manuelles dans chaque `apis/hubeau.py`.
4. **Valider les réponses API via Pydantic** : `HubeauStationSchema(BaseModel)`, `pd.DataFrame.parse_obj(response.json())`. Plantage explicite et tôt.
5. **`pd.to_datetime(utc=True)`** au lieu de string-mangling pour SIM2 EDR.
6. **Documenter le swap bbox OSM** avec un commentaire et un test unitaire.

---

## 6. Formats d'entrée (custom)

### 6.1 Description factuelle

Format « custom » propriétaire :
- **LOC file** : `{variable}_custom_LOC.{csv|xlsx|parquet|geojson|gpkg|shp|tif}` — positions des stations/grilles.
- **Chronicle file** : `{variable}_custom_{id}_{YYYYMMDD}_{YYYYMMDD}_{FREQ}.csv` — séries temporelles.
- Parsing par regex : `io_helpers.py:parse_chronicle_filename` et `parse_loc_filename`.
- Pour grilles : NetCDF / GeoTIFF monofichier (`custom_grid_loader.py`).

### 6.2 Verdict

| Aspect | Verdict |
|--------|---------|
| Conventions de nommage | **Non-standard** (totalement propriétaire) |
| Documentation formelle du schéma | **Problématique** (aucune) |
| Support GeoJSON / GeoPackage | **Acceptable** pour LOC vectoriel, **absent** pour chroniques |
| Support Parquet | **Acceptable** (read/write existent) |
| Support WaterML / OGC SensorThings | **Absent** |

### 6.3 Justification critique

Le schéma custom est **non documenté formellement** : pas de JSON-schema, pas de Pandera DataFrameSchema, pas de docstring exhaustive. On le reconstruit en lisant `io_helpers.py` et `custom_point_loader.py`. Pour un package qui veut être utilisé par des hydrogéologues, **c'est un obstacle majeur à l'adoption**.

#### Pourquoi pas les standards du domaine ?

- **WaterML 2.0** (OGC standard) : format XML/JSON de référence pour les séries temporelles hydrologiques. Toute infrastructure sérieuse (USGS NWIS, BGS, BRGM ADES, Hub'Eau en partie) produit du WaterML. Ne pas le supporter en entrée oblige l'utilisateur à réécrire en format maison.
- **OGC SensorThings** : API JSON moderne pour capteurs temps réel. Structure `Thing → Location → Datastream → Observations`. Adaptée aux piézomètres télémétriques.
- **CF-NetCDF** pour grilles : standard de fait en géosciences. Les chroniques stationnelles peuvent aussi être en NetCDF avec `featureType = "timeSeries"` (conformément CF).
- **GeoParquet** : binaire, rapide, portable, aligné sur Apache Arrow. Bien supporté par `geopandas >= 0.14`.

Le package supporte `parquet` pour LOC (cf. `write_parquet/read_parquet` dans `io_helpers.py`) mais pas pour les chroniques. C'est incohérent.

#### Format LOC : convention de colonnes implicite

`read_locations_csv()` attend `col_id`, `col_x`, `col_y`, `col_crs`, `default_crs` — tous configurables. Flexibilité appréciable mais **pas documentation formelle**. Un Pandera schema :

```python
LocationSchema = DataFrameSchema({
    "id": Column(str, unique=True),
    "x": Column(float, checks=Check.in_range(-180, 180) | ...),
    "y": Column(float, ...),
    "crs": Column(str, Check.str_matches(r"^EPSG:\d+$")),
})
```

…serait la norme. Ici on a 50 lignes de code impératif pour valider ce que 10 lignes déclaratives feraient.

#### Regex filename : fragile

```
(?P<type>[A-Za-z0-9]+)_(?P<source>[A-Za-z0-9]+)_(?P<id>.+?)_(?P<start>\d{8})_(?P<end>\d{8})_(?P<freq>[A-Za-z0-9]+)\.(?P<ext>\w+)$
```

Problèmes :
- `id` peut contenir `_` (greedy non-greedy) → parsing ambigu si `id = "bss_42"`.
- Date au format `YYYYMMDD` sans séparateur → peu lisible, collision possible avec identifiants numériques.
- `safe_file_token()` remplace non-alphanumérique par `_` → collision potentielle (stations `"BSS-01"` et `"BSS_01"` produisent le même token).

#### Expansion de constantes

`custom_point_loader.py` a une feature « constant expansion » : 1 ligne dans la chronique → répétée pour toute la période projet. **Utile pour les valeurs fixes (ex. hauteur océan calée)**, mais qui transforme 1 observation en 10 000 → mémoire + qualité trompeuse (100 % complet alors qu'une seule mesure).

### 6.4 Recommandations

1. **Définir un Pandera DataFrameSchema** pour LOC et chroniques, testable et documentant.
2. **Supporter WaterML 2.0 en lecture** : `owslib.waterml.v20` ou parseur simple. Interopérabilité directe avec Hub'Eau téléchargement en WaterML.
3. **Supporter GeoJSON / GeoParquet nativement** pour stations (déjà possible via `read_locations_vector` mais à documenter).
4. **CF-NetCDF pour grilles custom** : c'est déjà le cas via `custom_grid_loader`. Bon. Ajouter une validation CF (`cfchecker` ou `cf_xarray.cf_attrs`).
5. **Marquer les valeurs `is_constant=True`** dans le `quality_report` pour ne pas tromper l'utilisateur sur la complétude.

---

## 7. Formats de sortie

### 7.1 Description factuelle

- `common/export.py:export_records()` : 3 fichiers par appel :
  - `{prefix}_{id}_chronicle.csv` (datetime, value)
  - `{prefix}_metadata.csv` (index station)
  - `{prefix}_toc.csv` (table des matières)
- Grilles : `.nc` via `xarray.to_netcdf()` (BaseFieldManager).
- Hydrographie : `.shp` + `.tif` (rasterio / geopandas).

### 7.2 Verdict

| Format | Verdict |
|--------|---------|
| CSV chroniques | **Non-standard** — pas de métadonnées embarquées |
| CSV metadata | **Non-standard** |
| NetCDF grilles | **Acceptable** — utilise `xarray.to_netcdf()` donc hérite de CF si les attrs sont bons |
| Shapefile hydrographie | **Non-standard** (ESRI legacy) |
| Pas de WaterML 2.0 / SensorThings | **Problématique** |
| Pas de GeoPackage | **À améliorer** |

### 7.3 Justification critique

#### CSV maison pour chroniques

Le format sortie `csv_chronicle` est du CSV nu à 2 colonnes sans :
- métadonnées unit / CRS / source incluses en ligne d'en-tête,
- no-data encoding documenté,
- conformité avec un standard (OGC CSV-on-the-Web, CKAN, ODM2, etc.).

C'est **reproductible, mais totalement isolé** : personne d'autre ne lira ces CSV sans lire la doc HydroModPy. Pour un package scientifique, c'est une barrière inutile à la reproductibilité.

**Alternatives standard** :
- **CF-NetCDF feature-timeSeries** : un seul `.nc` qui contient stations + coords + chroniques + unités + CRS. Lecture universelle. C'est ce que fait `CDMS2` d'UCAR.
- **WaterML 2.0 JSON** : standard OGC, DCAT compatible.
- **Parquet + metadata.json** : rapide, typé, portable.

#### Shapefile

`hydrography` écrit du `.shp` (ESRI Legacy) pour les streams clippés. Shapefile a des limitations connues :
- longueur nom de champ ≤ 10 caractères,
- ASCII seulement (échappe les caractères diacritiques français — « Vézère » devient « Vzre »),
- encoding CRS dans un `.prj` séparé non toujours préservé.

**GeoPackage** (`.gpkg`) est le standard moderne OGC depuis 2014. Déjà utilisé en entrée (géologie). Incohérent que la sortie soit en shapefile.

#### NetCDF grilles : dépend des attrs

`BaseFieldManager._persist_field_records()` écrit `ds.to_netcdf(nc_path)`. Si le `xr.Dataset` a les bonnes `attrs["units"]`, `attrs["standard_name"]`, `attrs["long_name"]` + variables `time/x/y` avec `units`, le fichier est CF-compliant.

Vérification rapide : dans `variables/precipitation/apis/sim2.py`, le `Dataset` retourné est renommé mais **sans attrs CF explicitement positionnés** — seulement `source_unit` via `custom_grid_loader`. Pas de `standard_name` (ex. `precipitation_amount`), pas de `long_name`, pas de `institution`, pas de `Conventions = "CF-1.10"`. Donc **NetCDF oui, CF partiel**.

Un `cf_xarray.coerce_to_cf()` ou un post-processing global mettrait tout le monde à niveau.

#### Exports absents

- Pas d'export Parquet pour chroniques (écrit pour LOC seulement).
- Pas d'export vers un format de partage pluri-utilisateurs (Zarr cloud-native, STAC Catalog).
- Pas d'export WaterML / SensorThings (mais c'est rare en output, OK).

### 7.4 Recommandations

1. **Exporter chroniques en CF-NetCDF timeSeries-feature** via `xarray.Dataset` avec `featureType="timeSeries"`. Réduit 500 CSV à 1 NetCDF universellement lisible.
2. **Remplacer `.shp` par `.gpkg`** pour hydrographie. Deux lignes de code.
3. **Ajouter attrs CF systématiques** sur tous les `xr.Dataset` produits par les `apis/sim2.py` : `standard_name`, `units`, `long_name`, `grid_mapping`, `Conventions`. Template commun dans `common/cf_helpers.py`.
4. **Option `--format parquet`** sur `hmp export`. Gratuit avec `df.to_parquet`.
5. **Documenter les formats d'export** dans un `data-format-spec.md`.

---

## 8. Gestion des CRS

### 8.1 Description factuelle

- `StationLocation.crs: str` et `FieldRecord.crs: str` = chaînes libres (`"EPSG:4326"`, `"EPSG:2154"`).
- `unit_helpers`, `geo_helpers` : reprojections via `pyproj` / `rasterio` / `geopandas` — optionnelles.
- Defaults :
  - Hub'Eau → EPSG:4326 stocké.
  - DEM / géologie / climatiques → EPSG:2154 assumé (avec fallback silencieux).
  - `load_mask_geometry_wgs84` vs `load_mask_geometry` : deux variantes.

### 8.2 Verdict

| Aspect | Verdict |
|--------|---------|
| CRS comme `str` | **À améliorer** (devrait être `pyproj.CRS`) |
| Fallback silencieux vers EPSG:2154 | **Problématique** |
| Reprojection automatique raster (géologie) | **À améliorer** |
| Duplication `load_mask_geometry` / `..._wgs84` | **À améliorer** |
| Validation format EPSG au niveau config | **Problématique** (aucune) |

### 8.3 Justification critique

#### CRS en `str` : ticket ouvert à l'ambiguïté

`"EPSG:2154"` fonctionne. `"epsg:2154"` aussi (selon pyproj). `"2154"` parfois. `"IGNF:LAMB93"` aussi. Comparaisons `==` sur strings vont planter en silence.

**Ce que fait la communauté scientifique** :
- `geopandas.GeoDataFrame.crs` est un `pyproj.CRS` typé.
- `rioxarray.rio.crs` idem.
- `cartopy.crs.CRS` idem.

Tous normalisent à l'objet dès l'entrée. Ici on reste en string jusqu'au site d'utilisation, ce qui multiplie les points de défaillance.

#### Fallbacks silencieux EPSG:2154

Repéré dans plusieurs endroits :

- `variables/dem/custom.py:99` : si fichier ASC sans CRS, assume EPSG:2154 sans avertir.
- `variables/dem/custom.py:167` : NetCDF `ds.attrs.get("crs", "EPSG:2154")`.
- `variables/geology/io.py` : rasterization assume CRS du raster support, pas d'assertion.
- `common/custom_grid_loader.py:_extract_bbox_and_crs()` : heuristique « si bounds ≤ 180/90 → EPSG:4326, sinon local » — potentiellement faux pour Lambert 93 en zone alpine (x ≈ 900 000, pas d'ambiguïté) mais dangereux pour coords normalisées ou zones polaires.

**Une grille MNT non-Lambert (UTM, WebMercator) reprojetée en silence est un bug latent** : l'utilisateur pense calculer un bassin versant sur UTM, HydroModPy l'interprète en Lambert 93, les résultats sont garbage.

**Règle** : si CRS absent, **raise ValueError**. Jamais de fallback silencieux sur des données spatiales. C'est la règle d'or en géomatique.

#### Duplication `load_mask_geometry` vs `_wgs84`

`geo_helpers.py` définit deux fonctions presque identiques, une qui retourne la géométrie dans son CRS natif, l'autre reprojetée en WGS84. Le deuxième appelle le premier + reprojection. Maintenable en factorisant : `load_mask_geometry(path, target_crs="EPSG:4326")`.

#### Validation config

`DataManagersConfig.project_crs: str | None` : pas de validateur. `"EPSG:abc"` serait accepté à la config et planterait à la première utilisation. Un `@field_validator` qui fait `pyproj.CRS.from_user_input(v)` coûte 3 lignes et attrape tout.

### 8.4 Recommandations

1. **Typer tous les CRS avec `pyproj.CRS`** dans contracts et configs (+ validateur Pydantic).
2. **Interdire les fallbacks silencieux** : `raise ValueError("CRS manquant sur {path}. Spécifier explicitement via config.")` dans `custom.py`, `custom_grid_loader.py`, `io.py`.
3. **Fusionner `load_mask_geometry(_wgs84)?`** en un seul `load_mask_geometry(path, target_crs=None)`.
4. **Tests** : régressions sur raster UTM, Lambert conique, WebMercator. Au minimum un test par projection connue.

---

## 9. Duplications, dead code, over/under-engineering

### 9.1 Duplications majeures

| Module(s) | Duplication | Lignes | Priorité |
|-----------|------------|--------|----------|
| `hydrometry/discovery.py` ↔ `piezometry/discovery.py` | 13 méthodes identiques (haversine, mask_centroid, normalize_api_date, fallback radius, etc.) | ~900 lignes / 1080 | **Critique** |
| `hydrometry/apis/hubeau.py` ↔ `piezometry/apis/hubeau.py` | `fetch()`, `_station_period_overlaps`, `_discover_*_in_bbox` | ~500 lignes / 627 | **Critique** |
| `variables/{etp,humidity,radiation,soil_moisture,temperature,wind}/apis/sim2.py` | Même pattern `Sim2EDRClient(...).fetch_cube(parameters=[SIM2_PARAM])` répété 7× | ~500 lignes | **Critique** |
| `variables/{etp,humidity,radiation,soil_moisture,temperature,wind}/manager.py` | Managers tous strictement identiques modulo `VARIABLE_NAME`/`INTERNAL_UNIT`/`SIM2_PARAM` | ~200 lignes | **Critique** |
| `DataStore.load_*()` × 13 | 13 méthodes `load_hydrometry`, `load_piezometry`, etc. 100 % formatées pareil | ~200 lignes | **Majeur** |
| `BaseVariableManager._resolve_bbox` ↔ `BaseFieldManager._resolve_bbox` | Logique identique sauf reprojection WGS84 | ~50 lignes | **Majeur** |
| `common/clients/hubeau_cache.py` merge logic | Répétée implicitement dans certains managers | ~50 lignes | Mineur |

**Une refactorisation soignée éliminerait entre 1 500 et 2 000 lignes de code** (~15-20 % du package `data/`).

#### Détails hydrometry ↔ piezometry

Les seules différences *réelles* :
- URL de base (`hydrometrie/v2` vs `niveaux_nappes/v1`)
- Nom des champs API (`code_station` vs `code_bss`, `longitude_station` vs `x`, etc.)
- Unités par défaut (m³/s vs m)
- Chunking par années (piezo) vs par périodes (hydro)

Cela se résout avec **une classe parent `HubeauStationManager`** + deux sous-classes minimales qui surchargent uniquement les mappings API. Voire une config table :

```python
HUBEAU_HYDRO = HubeauEndpointSpec(
    base_url="https://hubeau.../hydrometrie/v2",
    station_code_field="code_station",
    unit_in="L/s",
    unit_out="m3/s",
    ...
)
HUBEAU_PIEZO = HubeauEndpointSpec(...)

class HubeauStationManager(BaseVariableManager):
    ENDPOINT: ClassVar[HubeauEndpointSpec]
```

#### Détails SIM2 climatiques

7 adaptateurs `variables/{var}/apis/sim2.py` qui font tous :

```python
def fetch(config, bbox, project_period, ...):
    client = Sim2EDRClient(bbox=bbox, crs="EPSG:2154", date_range=..., output_format="CoverageJSON")
    cov = client.fetch_cube(parameters=[SIM2_PARAMETER])
    ds = Sim2EDRClient.coverage_json_to_dataset(cov)
    return [FieldRecord(variable=..., source="sim2", unit=..., data=ds[[SIM2_PARAMETER]].rename(...), bbox=bbox, crs="EPSG:2154", ..., frequency="D")]
```

Factorisation évidente :

```python
# common/clients/sim2_fetcher.py
def fetch_sim2_field(variable: str, sim2_parameter: str, unit: str, bbox, project_period) -> list[FieldRecord]:
    ...

# variables/etp/apis/sim2.py
def fetch(config, bbox, project_period, **_):
    return fetch_sim2_field("etp", "ETP_Q", "mm/day", bbox, project_period)
```

De 81 lignes × 7 fichiers = 567 lignes, on passe à ~30 lignes total.

### 9.2 Dead code

| Fichier | Quoi | Action |
|---------|------|--------|
| `data/climatic/climatic.py` (619 l) | `DeprecationWarning` explicite, remplacé par managers variable-spécifiques | **Supprimer** |
| `data/climatic/sim2.py` (933 l) | Ancien SIM2 par CSV data.gouv.fr | **Supprimer** (remplacé par `Sim2EDRClient`) |
| `data/climatic/sim2_API.py` (283 l) | Wrapper encore utilisé ? Duplique `Sim2EDRClient` | **Vérifier et supprimer** |
| `data/climatic/driasclimat.py`, `driaseau.py`, `safransurfex.py` | À auditer isolément | **Vérifier usages** |
| `hydrometry/discovery.py:83` | `fallback_search_radius_km` paramètre inutilisé | **Supprimer** |
| `piezometry/discovery.py` | Offset lon incorrect (`buffer_deg = radius_m / 111_000`) — diverge d'hydrometry (bug géographique latitude-dépendant) | **Corriger** |
| `data/subbasin/__init__.py` | Module vide ? | **Vérifier** |

**Au total 1 800+ lignes de code climatique legacy probablement supprimables**.

### 9.3 Over-engineering

- **`data_managers.py`** (35 lignes) : wrapper trivial d'une `list[str]`. `DataManagers.from_config()` / `from_plan()` → classe purement cérémoniale. Devrait disparaître au profit d'un usage direct de `DataLoadPlan`.
- **`runtime_loader.py`** (893 lignes) : God class qui orchestre tout. `_LOADER_DISPATCH` dict + méthode par variable → méthode générique + registry serait plus propre.
- **`DataStore`** (228 lignes) : 13 méthodes `load_<variable>()` copier-collées. Une seule `load(variable: str, config)` suffit.
- **`_CatalogEntry` dataclass-like** (`catalog_duckdb.py:68-82`) : fake-SQLAlchemy pour compat. Si plus personne n'utilise l'ancienne interface → supprimer.

### 9.4 Under-engineering

- **Pas de tests de race conditions** sur DuckDB.
- **Pas de validation schéma** sur les DataFrames post-lecture (Pandera).
- **Pas de logs structurés** (logging avec `extra={}`), juste `print` ou `log_manager` minimaliste.
- **Pas de versioning du schéma DuckDB** (table `_schema_version`). Si demain vous ajoutez une colonne à `entries`, les caches existants sont incompatibles et le package va crasher.
- **Pas d'async I/O** : `ThreadPoolExecutor` max 4 workers pour du I/O réseau, là où `asyncio.gather` ferait mieux. Acceptable pour un outil CLI, sous-optimal pour un serveur.

---

## 10. Tests excessifs ou manquants

Audit visuel rapide (non exhaustif, pas de lecture de `tests/` demandée dans la tâche) — à vérifier :

- `data/variables/*/examples/run_examples.py` (hydrometry, piezometry, water_quality) : **examples exécutables dans le package source**. Hors CI normalement. Si ces scripts sont joués par `pytest`, ils ralentissent beaucoup (appels API réels). Recommandation : les déplacer dans `docs/examples/` et les exécuter hors de CI.
- `data/variables/geology/cases/`, `intermittency/cases/`, `oceanic/cases/` : cases de validation isolés. Potentiellement doublonnés avec `tests/validation/`. Vérifier.
- Tests de contrats : les dataclasses `PointRecord` / `FieldRecord` sont simples mais `__post_init__` de `PointRecord` fait de la coercion. Tests de bordure attendus (df vide, datetime invalide, value=NaN only).

**Recommandation** : lister les tests touchant `data/` (fichier séparé à l'audit tests) et fusionner/élaguer.

---

## 11. Tableau récapitulatif par type de donnée

| Variable | Config Pydantic | Manager | Source API | Format entrée custom | Format sortie | Standards d'interopérabilité | Verdict |
|----------|-----------------|---------|-----------|----------------------|---------------|------------------------------|---------|
| **Hydrometry** | `HydrometryConfig` | `HydrometryManager(BaseVariableManager)` | Hub'Eau `/hydrometrie/v2` | CSV LOC + CSV chronicles | CSV chronicle + metadata.csv | **Non-standard** (CSV maison, pas WaterML) | **À améliorer** |
| **Piezometry** | `PiezometryConfig` | `PiezometryManager` | Hub'Eau `/niveaux_nappes/v1` | idem | idem | idem, de plus NGF implicite | **À améliorer** |
| **Water Quality** | `WaterQualityConfig` | `WaterQualityManager` | Hub'Eau `/qualite_rivieres/v2` + `/qualite_nappes/v1` | CSV + colonne `parameter` | CSV | Non-standard | **À améliorer** |
| **Intermittency (ONDE)** | `IntermittencyConfig` | `IntermittencyManager` | Hub'Eau `/ecoulement/v1` | CSV + code ordinal 1-5 | CSV | Non-standard (codes ONDE nationaux non mappés à SDM) | **À améliorer** |
| **Oceanic** | `OceanicConfig` | `OceanicManager(BaseFieldManager)` | SHOM (REFMAR + PREVIMER) | CSV + NetCDF + GeoTIFF | NetCDF + CSV | **Acceptable** (NetCDF si CF attrs posés) | **Acceptable** |
| **DEM** | `DemConfig` | `DemManager(BaseFieldManager)` | IGN BD ALTI 25m (département `.7z`) | TIF / ASC / NC | GeoTIFF | **Acceptable** (GeoTIFF standard) | **Acceptable** |
| **Geology** | `GeologyConfig` | `GeologyManager(BaseFieldManager)` | BRGM 1M + 50k (par département) | SHP / GPKG / GeoJSON / TIF / CSV points → Voronoi | GeoPackage + TIF encoded int32 | **Acceptable** (GeoPackage standard, mais code 0=nodata non CF-compliant) | **Acceptable** |
| **Hydrography** | `HydrographyConfig` | `HydrographyManager(BaseFieldManager)` | BD TOPAGE (Sandre WFS) + EU-Hydro (EEA REST) + OSM Overpass | SHP / GPKG / GeoJSON / TIF | **Shapefile** (legacy) + TIF | **Non-standard** sortie (shapefile obsolète) + **bug** OSM bbox | **À améliorer** |
| **Precipitation** | `PrecipitationConfig` | `PrecipitationManager(BaseFieldManager)` | SIM2 EDR (`PRELIQ_Q`, `PRENEI_Q`) | NetCDF / GeoTIFF | NetCDF | **Acceptable** si attrs CF | **Acceptable** |
| **ETP** | `EtpConfig` | `EtpManager(BaseFieldManager)` | SIM2 EDR (`ETP_Q`) | idem | NetCDF | **Acceptable** | **Acceptable** |
| **Temperature** | `TemperatureConfig` | `TemperatureManager(BaseFieldManager)` | SIM2 EDR (`T_Q`) | idem | NetCDF | **Acceptable** (conversion °K/°C gérée) | **Acceptable** |
| **Humidity** | `HumidityConfig` | `HumidityManager(BaseFieldManager)` | SIM2 EDR (`HU_Q`) | idem | NetCDF | Acceptable | Acceptable |
| **Wind** | `WindConfig` | `WindManager(BaseFieldManager)` | SIM2 EDR (`FF_Q`) | idem | NetCDF | Acceptable | Acceptable |
| **Radiation** | `RadiationConfig` | `RadiationManager(BaseFieldManager)` | SIM2 EDR (`DLI_Q`, `SSI_Q`) | idem | NetCDF | Acceptable | Acceptable |
| **Soil moisture** | `SoilMoistureConfig` | `SoilMoistureManager(BaseFieldManager)` | SIM2 EDR (`SWI_Q`) | idem | NetCDF | Acceptable | Acceptable |
| **Runoff** | `RunoffConfig` | `RunoffManager(BaseFieldManager)` | SIM2 EDR (`RUNC_Q`) | idem | NetCDF | Acceptable | Acceptable |
| **Recharge** | `RechargeConfig` | `RechargeManager(BaseFieldManager)` | SIM2 EDR (`DRAINC_Q`) + **synthetic** | idem + série synthétique | NetCDF | Acceptable | Acceptable |

**Verdicts agrégés** :
- **À améliorer** : Hydrometry, Piezometry, Water Quality, Intermittency, Hydrography (5 variables / 17)
- **Acceptable** : DEM, Geology, Oceanic, les 8 climatiques SIM2 (12 variables / 17)
- **Conforme aux standards** : aucune.

---

## 12. Recommandations prioritaires

Classées par retour sur investissement (ROI) décroissant :

### Priorité 1 — Corrections de fond, ROI élevé

1. **Transactions DuckDB** autour de `register()`, `subsume_entries()`, `cleanup()`. Une journée de travail, supprime toute une classe de bugs.
2. **Refactor Hydrometry ↔ Piezometry** : classe parent `HubeauStationManager` + endpoint-spec. Économie 900+ lignes.
3. **Factorisation SIM2 climatique** : un seul `fetch_sim2_field()` partagé. Économie 500+ lignes.
4. **Interdire CRS fallback silencieux** : `raise ValueError` sur CRS manquant. Évite des bugs géospatiaux fourbes.
5. **Purge `data/climatic/*.py` legacy** après vérification d'usage. Économie 1 800+ lignes.

### Priorité 2 — Renforcement du filet de sécurité

6. **Pandera schemas** sur `PointRecord.data`, LOC files, réponses Hub'Eau. Pandera est déjà compatible Pandas.
7. **Fingerprint SHA-256** dans `entries.fingerprint`. Invalidation cache correcte.
8. **Retry HTTP différencié** via `tenacity` (+ respect `Retry-After`).
9. **Migrer Hydrography vers GeoPackage** en sortie. Ligne triviale.
10. **Schéma versioning DuckDB** (`_schema_version` table). Obligatoire avant tout changement schéma.

### Priorité 3 — Interopérabilité / standards

11. **Export CF-NetCDF timeSeries-feature** pour chroniques. Remplace les CSV multiples.
12. **Remplacer `PointRecord` / `FieldRecord` par `pd.Series[DatetimeIndex]` / `xr.DataArray`** avec `attrs` CF. Lourd mais définitivement l'orientation correcte.
13. **Typer CRS en `pyproj.CRS`** partout (contracts + configs).
14. **Support WaterML 2.0 en entrée** (lecteur simple via `owslib`).

### Priorité 4 — Hygiène

15. **Logs structurés** sur inférences planner et cache hits/miss.
16. **Sortir `examples/run_examples.py`** du package source.
17. **Split `runtime_loader.py`** en modules plus petits.
18. **Supprimer `DataStore.load_<var>()` × 13** → `DataStore.load(variable, config)`.

---

## 13. Notes finales

Le package `data/` est **le plus mature et le plus vaste** du projet (à vue d'œil), couvrant toute la donnée hydrogéologique française utile à la modélisation MODFLOW. L'effort pour avoir factorisé Hub'Eau, SHOM, SIM2, BRGM et IGN dans un modèle unique est louable.

Mais la **dette technique s'accumule** :
- duplication par copier-coller plutôt que factorisation,
- contrats maison au lieu de s'appuyer sur l'écosystème scientifique Python,
- absence de standards d'interopérabilité en sortie,
- cache DuckDB sans les garde-fous élémentaires (transactions, fingerprint, TTL),
- bugs géomatiques latents (CRS fallback, OSM bbox, offset lon piézo).

**Ce package peut être réduit de 20 % en lignes sans perdre une fonctionnalité**, en gagnant la robustesse et l'interopérabilité standard. Un sprint dédié y suffirait probablement.

*Audit réalisé le 2026-04-17 par un auditeur senior data engineering / hydrogéologie opérationnelle.*
