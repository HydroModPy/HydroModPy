# Audit critique — Package `hydromodpy/data/`

Auditeur : expert Data Engineering & Hydrogéologie (Hub'Eau, ADES, BRGM, SIM2, SHOM).
Base auditée : `dev-database` @ `74b62878` après merge `dev-refact` (2026-04-17).
Périmètre : `hydromodpy/data/` (18 144 lignes Python, 170 modules, 17 types de variables).
Référentiel : CF-conventions 1.11, OGC SensorThings API v1.1, WaterML 2.0, INSPIRE, Frictionless Data, WMO GRDC.

---

## 0. Vue d'ensemble et verdict global

Le package `data/` est le pivot entrée de HydroModPy : il orchestre la récupération, la mise en cache et la normalisation de 17 variables hydrogéologiques/climatiques issues d'APIs françaises (Hub'Eau, BRGM, SHOM, IGN, Météo-France SIM2). Il a subi une refonte structurelle récente (contracts typés, catalog DuckDB, planner d'inférence) mais cohabite avec une couche héritée (`data/climatic/*`, gestionnaires DEM/Géologie non migrés) qui crée un anti-pattern de duplication et un flou de responsabilités.

**Note globale : 5,3/10 — « Acceptable en usage interne, non conforme aux standards d'interchange. »**

| Axe | Note /10 | Commentaire |
|---|---|---|
| Design orienté contrat | 6 | LoadResult/PointRecord/FieldRecord cohérents mais ré-inventent la roue (xarray/pandas déjà standard). |
| Conformité CF/OGC | 3 | Aucun attribut CF. Format CSV maison. Pas de WaterML/SensorThings. |
| Robustesse réseau | 3 | Pas de rate-limit 429, pas de timeout urllib, `resp.json()` non protégé, exceptions avalées. |
| Robustesse concurrence DuckDB | 4 | Pas de `BEGIN/COMMIT` explicite. Pas de `schema_version`. Retry sur IOException uniquement. |
| Gestion CRS | 5 | WGS84 hardcodé ; reprojections partielles dans DEM/Géologie avec logique dupliquée. |
| Unités et précision | 4 | Système maison (pas de pint), `float64` partout y compris pour des codes géologiques discrets. |
| Cache / invalidation | 5 | Invalidation sur mtime (fragile). Clé cache opaque (pas de SHA-256). Sentinelles `_EMPTY` pertinentes. |
| Testabilité | 5 | Dépendance forte à `WorkflowContext` dans `runtime_loader.py`. Peu de mocks des APIs. |
| Hygiène code (dup/dead) | 4 | `climatic.py` déprécié mais encore présent ; double registry (store + runtime_loader). |
| Cohérence pattern manager | 5 | Deux hiérarchies en parallèle, DEM/Géologie/Hydrographie hors hiérarchie. |

Les sections suivantes détaillent chaque axe avec verdict et recommandations. Le **§ 9** fournit le tableau récapitulatif par variable.

---

## 1. Pattern `BaseVariableManager` — évaluation critique

### 1.1 Description

`hydromodpy/data/common/base_manager.py` (492 lignes) définit une ABC `BaseVariableManager` qui expose :

- `load() -> LoadResult` : template method orchestrant le cycle `fetch_from_source → warn_outside_extent → register_records`.
- `_fetch_from_source(source_cfg)` : méthode abstraite, seule extension attendue.
- Méthodes concrètes pour cache partiel (`_compute_missing_periods`, `_merge_into_record`), persistance API (`_persist_api_records`, `_cleanup_old_api_file`), sentinelles (`_is_empty_sentinel`), LOC files (`_upsert_api_loc`, `_load_cached_location`), reporting (`get_completeness_report`, `export`).

Parallèlement, il existe `BaseFieldManager` dans `common/base_field_manager.py` pour les grilles climatiques.

### 1.2 Verdict : **à améliorer (rigidité sur un mauvais axe)**

- **Ce qui est bien** : Template method explicite, séparation cache/fetch/register propre, cycle de vie documenté, gestion fine des sentinelles `SENTINEL_EMPTY` / `SENTINEL_CUSTOM` (astucieux pour éviter de re-fetcher des stations vides — bonne pratique de cache hydrométrique).
- **Ce qui est rigide** : La classe orchestre simultanément I/O réseau, I/O fichier, validation spatiale, catalogage, reporting et merge temporel. C'est un **God Object** ABC. Six responsabilités SRP/SOLID dans une seule classe de 492 lignes. Le test unitaire d'une sous-classe impose de mocker `catalog`, `data_dir`, `project_extent`, `project_period` + un `config.sources`.
- **Ce qui est non-standard** : Le pattern attendu dans l'écosystème Python scientifique est soit (a) **Intake** (`intake.DataSource` → `.to_dask()`), soit (b) **Pangeo-Forge** (`FilePattern` + `recipe`), soit (c) simple `extract / transform / load` fonctionnel. Ici on a une POO « Spring-like » qui n'apporte pas plus que des fonctions pures.
- **DEM, Géologie, Hydrographie** n'héritent **pas** de `BaseVariableManager` ni de `BaseFieldManager` : `DemManager` (201 L), `GeologyManager` (264 L), `HydrographyManager` (320 L) ré-implémentent leur propre pipeline. Résultat : 785 lignes hors du pattern, dont ~150 lignes de `_resolve_bbox / _resolve_bbox_2154` dupliquées.
- **Cycle de vie implicite** : aucun état explicite (« created → configured → loading → loaded → cached »), pas d'assert qu'on n'appelle pas `load()` deux fois, pas de `close()`/context manager. Comparer à `intake.DataSource.discover/read/to_dask/close`.

### 1.3 Recommandations

| Action | Effort | Gain |
|---|---|---|
| Extraire `BaseVariableManager` en 3 classes (`BaseManagerIO`, `BaseManagerCache`, `BaseManagerPersistence`) ou, mieux, en **fonctions pures** + un unique `Manager` dataclass stateless | M | -40 % LOC |
| Unifier DEM/Géologie/Hydrographie dans `BaseSpatialManager` héritant de la même racine que `BaseFieldManager` | L | Élimine 150 lignes dupliquées |
| Ajouter un enum `ManagerState` et des `assert` pour empêcher les ré-appels non voulus | XS | Robustesse |
| Envisager adoption d'**Intake** pour exposer publiquement les datasets (`catalog.yaml` → `open_hydrometry_hubeau`) | XL | Interopérabilité écosystème Pangeo |

---

## 2. Contrats `LoadResult`, `PointRecord`, `FieldRecord`, `StationLocation`

### 2.1 `PointRecord` (contracts/timeseries.py, 90 L)

```python
@dataclass
class PointRecord:
    station_id: str
    variable: str
    source: str
    unit: str
    frequency: str
    data: pd.DataFrame   # colonnes requises ["datetime", "value"]
    date_start, date_end: datetime
    location: StationLocation | None
    ...
```

**Verdict : non-standard, à ré-architecturer.**

- **Problème majeur** : `data: pd.DataFrame` avec colonnes plates `[datetime, value]` alors que **l'objet naturel pour une chronique univariée est `pandas.Series` avec `DatetimeIndex`**. On reproduit manuellement ce qu'un `Series` offre gratuitement : indexation temporelle, resample, rolling, tz-awareness. Cela se voit dans `filter_by_period` qui fait `(data["datetime"] >= Timestamp(start))` au lieu d'un simple `series.loc[start:end]` (slicing naturel d'un DatetimeIndex).
- **Redondance avec les métadonnées** : `unit`, `frequency`, `date_start`, `date_end` dupliquent ce que **CF-NetCDF** encode dans les attributs xarray (`units`, `calendar`, `standard_name`). Une `pandas.Series.attrs` ou une `xarray.DataArray` avec attrs CF feraient le même travail de façon standard.
- **`date_start`/`date_end` dérivables** de `data["datetime"].min/max` → stockage redondant qui peut devenir incohérent après un `filter_by_period` (on recalcule).
- **`compute_completeness` dans `__post_init__`** : effet de bord silencieux, recalcul à chaque instanciation (y compris lors de `filter_by_period` → O(n) inutile). À déplacer dans un `@cached_property`.
- **`quality: Optional[dict]`** non typé (signature permissive). Devrait être `QualityStats` dataclass frozen.
- **`data.to_csv(filepath)`** déclenché côté manager → `pd.to_csv` par défaut écrit en UTF-8 mais sans fuseau horaire des timestamps : **perte d'information** si stations métropolitaines vs DROM.

### 2.2 `FieldRecord` (contracts/spatial_field.py, 51 L)

```python
@dataclass
class FieldRecord:
    variable: str
    source: str
    unit: str
    data: Union[xr.Dataset, Path]
    bbox: tuple
    crs: str
    date_start/end, frequency
```

**Verdict : acceptable mais sous-typé.**

- Le champ `data` en `Union[xr.Dataset, Path]` est **un anti-pattern de typage** : toutes les branches appelantes doivent faire `isinstance(self.data, Path)`. La propriété `dataset` résout le chargement lazy (bonne idée, similaire à `dask.delayed`) mais **mute `self.data`** (`self.data = ds`) → la dataclass n'est pas immutable, et on casse l'invariant d'origine.
- `bbox: tuple` → devrait être `tuple[float, float, float, float]` typé, voire un `shapely.box` ou un `rasterio.coords.BoundingBox`. Aucun contrôle d'ordre `(xmin, ymin, xmax, ymax)`.
- `crs: str` → string libre (`"EPSG:4326"`, `"EPSG:2154"`), pas de `pyproj.CRS`. Un typo `"EPSG:4325"` passe silencieusement.
- **Il devrait s'agir directement d'une `xarray.DataArray`** (variable unique) ou `Dataset` (multi-var) décorée CF-compliant. Le wrapper `FieldRecord` n'ajoute rien qu'xarray ne fasse déjà : les attributs CRS sont stockables dans `ds.rio.crs` (rioxarray) ou dans `ds.attrs["Conventions"] = "CF-1.11"`.

### 2.3 `LoadResult` (contracts/load_result.py, 40 L)

Container `points + fields + warnings`. **Verdict : utile mais surfacique.** La liste `warnings: list[str]` (stringly-typed) devrait être une liste de `ValidationWarning` avec `code`, `severity`, `variable`, `station_id`. Sinon la consommation programmatique est impossible — on parse des chaînes.

### 2.4 `StationLocation` (contracts/location.py, 19 L)

```python
@dataclass(frozen=True)
class StationLocation:
    id, x, y, crs, metadata
```

**Verdict : minimaliste, non-standard.**

- **Standard attendu** : OGC SensorThings API expose `Thing/Location` avec `@iot.id`, `encodingType="application/vnd.geo+json"`, `location: GeoJSON`. Ici on a un `(x, y, crs)` plat.
- Pourquoi pas `shapely.Point` ? `shapely` garantit la validité géométrique et s'intègre avec GeoPandas.
- `metadata: dict` non typé → tous les champs hydrométriques (altitude, département, nom, date d'activité) terminent dans un dict hétérogène. À typer ou à sortir.

### 2.5 Précision flottante

- Partout `float` (= `float64`). Aucune distinction.
- **Recommandation hydro** : float64 pertinent pour débits m³/s (précision 0,001), hauteurs piézométriques (mm). **`float32` suffisant** pour grilles SAFRAN/SIM2 (résolution 8 km, incertitude de reanalyse > 1 % déjà). Codes géologiques : `int32` ou `category` (pandas). Actuellement `astype(float)` sur codes géologiques → **gaspillage mémoire × 2 à 8 selon dtype natif**.

### 2.6 Tableau récapitulatif contrats

| Contrat | LOC | Standard équivalent | Verdict | Recommandation |
|---|---|---|---|---|
| `PointRecord` | 90 | `pandas.Series` + `attrs` CF ; WaterML | **non-standard** | Remplacer `data: DataFrame` par `values: pd.Series(DatetimeIndex)` |
| `FieldRecord` | 51 | `xarray.DataArray/Dataset` CF-compliant | **à améliorer** | Passer en `xr.Dataset` direct, lazy via `open_dataset(chunks={})` |
| `LoadResult` | 40 | n/a | **acceptable** | Typer les warnings |
| `StationLocation` | 19 | OGC SensorThings `Location` | **non-standard** | Utiliser `shapely.Point` + `pyproj.CRS` |
| `QualityStats` (implicite) | - | ISO 19157 (data quality) | **inexistant** | Ajouter dataclass frozen |

---

## 3. Inférence des données (`DataManagersPlanner`)

### 3.1 Fonctionnement

`planner.py` (157 L) produit un `DataLoadPlan` (dataclass frozen) à partir de `DataManagersConfig`. Trois règles d'inférence codées en dur dans `build()` :

1. `"geology"` ∈ `domain.zone_ids` → activation `geology`
2. `"stream"` ∈ `flow.active_bc` → activation `hydrography`
3. `"ocean"` ∈ `flow.active_bc` → activation `oceanic`

Deux modes :
- **`warn`** (défaut) : inférence silencieuse, manager chargé avec config par défaut si section TOML absente.
- **`strict`** : si type inféré sans section `[data.<type>]` explicite → `ValueError` (sauf `geology` qui auto-default).

### 3.2 Verdict : **fragile, trop centralisé, non extensible**

- **Règles hardcodées** : trois `if` dans `build()`. Ajouter un 4ᵉ couplage (p. ex. `precipitation` requise si `flow.forcing = "recharge_from_precipitation"`) = modifier `planner.py`. Anti-ouverture/fermeture (OCP).
- **`_domain_requests_geology` est un wrapper vide** (ligne 116-117). Dead code.
- **Le rapport de raison (`reasons_by_type`)** est généré mais jamais consulté au runtime loader pour décider des actions. Intention louable (transparence) mais non exploitée.
- **Le mode `strict` est une guillotine** : échec `ValueError` au planning, alors qu'un utilisateur pourrait vouloir un avertissement explicite avec suggestion (« voulez-vous ajouter `[data.hydrography] source = "bdtopage"` ? »). Pas de `DataInferenceWarning` typée.
- **Que se passe-t-il si l'inférence se trompe ?** Rien de détectable : l'utilisateur obtient un manager chargé avec config par défaut. Pas de garde-fou (ex : vérifier que le CRS du watershed recoupe la couverture géographique de la source par défaut).
- **Logique d'inférence scattered** : `planner` décide de l'activation, mais `runtime_loader._is_required_data_type` ré-évalue avec `inference_mode` pour décider si l'erreur est fatale. Deux endroits à maintenir.

### 3.3 Recommandations

| Action | Effort | Gain |
|---|---|---|
| Extraire les règles en `DataInferenceRule` typées, enregistrées via un registry décorateur (`@register_rule`) | S | Extensibilité |
| Marquer chaque type `required|optional|inferred` dans le `DataLoadPlan`, supprimer `_is_required_data_type` côté loader | S | Cohérence |
| Introduire `DataInferenceError` et `DataInferenceWarning` typées (pas des `ValueError`/`warnings.warn`) | S | UX |
| Supprimer `_domain_requests_geology` (wrapper mort) | XS | -2 lignes |

---

## 4. Cache DuckDB (`registry/catalog_duckdb.py`)

### 4.1 Schéma

Deux tables uniquement (`entries`, `api_coverage`) :

```sql
entries(id PK, variable, source, station_id, bbox_*, crs, date_start VARCHAR, date_end VARCHAR,
        frequency, unit, source_unit, file_path TEXT, file_mtime DOUBLE, created_at TIMESTAMP,
        is_custom INTEGER, fetch_metadata JSON);
ix_entries_var_src_station(variable, source, station_id)
ix_entries_bbox(bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax)
```

### 4.2 Problèmes de normalisation

- **`date_start / date_end` stockés en `VARCHAR`** → pas de comparaison SQL temporelle native (`WHERE date_start <= '2020-06-01'` fonctionne lexicographiquement parce qu'on a de la chance avec ISO-8601, mais c'est un antipattern). **À passer en `DATE` ou `TIMESTAMP` DuckDB.**
- **`is_custom INTEGER DEFAULT 0`** → DuckDB expose `BOOLEAN` natif. Entier fragile.
- **Pas de contrainte `UNIQUE` sur (variable, source, station_id)** → on dédouble si `register` est appelé sans le lookup préalable. La logique de lookup est côté Python (lignes 144-150), pas côté schéma.
- **`file_path TEXT NOT NULL`** mais peut valoir `SENTINEL_CUSTOM` ou `SENTINEL_EMPTY` (chaînes magiques). **À modéliser** : colonne `status ENUM('cached', 'empty', 'custom')` + colonne `file_path` nullable.
- **Pas de table `provenance`** alors que l'architecture cible (CLAUDE.md § Storage) mentionne « provenance — input data fingerprints (SHA-256 + stats) ». Le catalog d'entrée n'a pas de SHA-256 — il est dans le catalog de simulation en aval seulement. **Chaînon manquant pour traçabilité amont.**

### 4.3 Risques de corruption et concurrence

- **Aucun `BEGIN TRANSACTION`/`COMMIT` explicite** dans `register()`, `invalidate()`, `cleanup()`. DuckDB fait du **auto-commit** par défaut, mais l'enchaînement `SELECT ... WHERE ...` + `UPDATE`/`INSERT` (lignes 144-199) n'est **pas atomique** → race condition si deux processus écrivent (batch multi-bassins).
- **Retry sur `duckdb.IOException`** (lignes 200-207) avec backoff exponentiel — bien. Mais le catch-all `except Exception: logger.warning(...); return -1` **avale silencieusement toutes les erreurs** y compris les contraintes, les disk-full, etc.
- **Pas de `schema_version`** (contrairement au catalog de simulation amont). Si on fait évoluer le schéma, les anciens workspaces ne sauront pas migrer automatiquement. **Régression** par rapport au SimulationCatalog qui gère `_schema_version`.
- **DuckDB fichier unique = pas de lock multi-processus fiable** sur NFS/Ceph. En batch régional (plusieurs workers écrivant `cache.duckdb`), risque d'erreur `Could not set lock on file`. Peu documenté.
- **Invalidation par `mtime`** (base_manager.py:401-408) : test `abs(current_mtime - entry.file_mtime) > 1.0`. Fragile si le système de fichiers arrondit à la seconde (ext4 : ns, APFS : ns, ext3 : s). Un remplacement de fichier identique change le mtime → invalidation prématurée. **Un SHA-256 serait plus robuste** (coût négligeable pour CSVs < 10 Mo).

### 4.4 Lookup `find_cached` (lignes 212-249)

- Retourne **un seul résultat** (`LIMIT 1` implicite). Si deux entrées couvrent partiellement la requête (p. ex. 2010-2015 et 2016-2020 séparées), **on ne peut pas merger**. Le cache « smart » de `base_manager._compute_missing_periods` suppose une couverture contiguë **par station** → OK pour Hub'Eau station-par-station, **KO pour grilles climatiques** multi-chunks.

### 4.5 Recommandations

| Action | Effort | Gain |
|---|---|---|
| Typer `date_start/date_end` en `DATE` ou `TIMESTAMP` | S | Requêtes temporelles correctes |
| Ajouter `UNIQUE(variable, source, station_id)` côté schéma | S | Intégrité |
| Wrapper les écritures critiques en `conn.begin()/commit()` avec rollback sur exception | M | Cohérence multi-processus |
| Ajouter `schema_version` + mécanisme de migration | M | Évolutivité |
| Calculer SHA-256 en complément de mtime pour invalidation | S | Robustesse |
| Supprimer les sentinelles stringly-typed (`SENTINEL_EMPTY`/`SENTINEL_CUSTOM`) au profit d'une colonne `status` | M | Lisibilité |

**Verdict global catalog : acceptable (fonctionne en mono-processus), problématique en multi-processus et non-migratable.**

---

## 5. APIs externes (Hub'Eau, BRGM, SHOM, IGN, SIM2)

### 5.1 Hub'Eau (hydrométrie, piézométrie, qualité eau, intermittence/ONDE)

Fichiers : `variables/{hydrometry,piezometry,water_quality,intermittency}/apis/hubeau.py`, `common/clients/hubeau_cache.py`, `common/api_helpers.py`.

**Défauts critiques :**

1. **Aucune gestion HTTP 429 (Too Many Requests)** — Hub'Eau limite à ~1 000 req/jour sans clé. `api_helpers.check_status()` log un warning mais retourne `False` ; `get_json()` continue à `resp.json()` → crash si corps HTML d'erreur. **P0.**
2. **Pagination incomplète** — `paginate_json()` utilise `page` + `size` ; Hub'Eau v2 expose aussi `cursor` + `next`. Si Hub'Eau change le mode par défaut (ils l'ont fait pour `ONDE`), silencieusement on perd des stations au-delà de la page 1.
3. **Paramètre `size=20000`** hardcodé pour contourner la pagination → fragile si Hub'Eau abaisse la limite (ils ont déjà capé à 10 000 pour piézo).
4. **Aucun backoff exponentiel** — 3 retries à intervalle fixe `BACKOFF_FACTOR=2.0`.
5. **`resp.json()` non protégé** — `sim2_edr.py:73, 99`, `shom.py:120, 160, 187`. Si l'API renvoie une page d'erreur HTML (portail tombé, captcha), crash `json.JSONDecodeError` non attrapé.
6. **Aucune validation de schéma** sur les réponses. `row.get("code_station")` → `None` accepté silencieusement. Un changement de nom (`code_station` → `station_code`) passerait en silence. **Pydantic `TypeAdapter` ou `pydantic.RootModel`** résoudrait en ~30 lignes.
7. **CRS hardcodé WGS84** (hydrometry:223, piezometry:247). Si Hub'Eau bascule un jour à L-93 pour une station (cas déjà rencontré sur ADES), pas de détection.
8. **Duplications** : `_fetch_station_location` quasi-identique dans hydrometry/piezometry/water_quality (3×). `_check_period_overlap` : 2×. À factoriser dans `common/clients/hubeau.py`.

### 5.2 BRGM (géologie 50k et 1M)

Fichiers : `variables/geology/apis/brgm_{50k,1m}.py`.

**Défauts critiques :**

1. **`urllib.request.urlretrieve()` sans `timeout`** (brgm_50k:75, brgm_1m:205). **Le serveur BRGM peut mettre des minutes à répondre** pour une carte 1M → processus bloqué indéfiniment. **P0.**
2. **`except Exception: logger.warning(); return`** → silence total, aucune trace du type d'erreur.
3. **Pas de validation de l'archive ZIP** téléchargée (pas de vérification taille, SHA-256, ou header magique). Un 404 renvoyant une page HTML peut être persisté comme `.zip` et tout casser à l'`unzip`.
4. **Reprojection manuelle L-93 → WGS84** dupliquée entre `brgm_50k` et `brgm_1m` et avec `DemManager._resolve_bbox_2154`. Factoriser dans `geo_helpers.py` (qui existe déjà et ferait le job).

### 5.3 SHOM (océanique / marégraphes)

Fichier : `variables/oceanic/apis/shom.py`.

**Points positifs :** `requests.Session()` + `raise_for_status()` (4xx/5xx levés). Timeout 60 s sur les requêtes.

**Défauts :**

1. `response.json()` sans try/except (lignes 120, 160, 187).
2. **Fenêtres 31 jours hardcodées** (`interval="60"`) pour contourner la limite API → si SHOM change (ils ont historiquement capé à 7 jours pendant une panne), re-casser.
3. `_try_load_cached` avale `pd.errors.EmptyDataError` + toute `Exception` → silence si cache corrompu.
4. Aucun handling des trous de données (marégraphes tombent régulièrement). L'API SHOM renvoie 204 No Content dans ce cas → non géré.

### 5.4 IGN BD ALTI (DEM)

Fichier : `variables/dem/apis/ign_bdalti.py`.

**Défauts :**

1. **`urllib.request.urlretrieve()` sans timeout** (ligne 205). Idem BRGM.
2. Extraction 7z dépend de `7z` système puis fallback `py7zr` → mais pas de vérification d'intégrité du ZIP (checksum IGN disponible sur leur site, non exploité).
3. **Re-mosaïquage** des dalles en mémoire (`rasterio.merge.merge`) : pas de mention de chunk, risque OOM sur grande emprise (ex : département du Var).
4. Logique de `_resolve_bbox` dupliquée avec `GeologyManager._resolve_bbox_2154` et `DemManager._resolve_bbox`.

### 5.5 Météo-France SIM2 (climatique)

Fichiers : `common/clients/sim2_edr.py`, `common/clients/sim2_variables.py`, plus **9 wrappers** `variables/*/apis/sim2.py` (25-30 lignes chacun, quasi-identiques).

**Verdict : duplication massive + dépendance legacy.**

- Les 9 wrappers délèguent à `climatic.sim2.Sim2` (932 lignes, voir § 7).
- **La migration dev-refact → dev-database n'a pas terminé la consolidation SIM2.** Le merge a ramené `climatic/` qui aurait dû être purgé. À rationaliser.
- Aucun handling de la déprecation annoncée par Météo-France du endpoint SIM2 en 2026 (voir FAQ Climatheque).

### 5.6 Tableau récap API clients

| Source | Fichier | LOC | Timeout | Retry/backoff | 429 | JSON safe | Validation schéma | Verdict |
|---|---|---|---|---|---|---|---|---|
| Hub'Eau hydrométrie | `variables/hydrometry/apis/hubeau.py` | 308 | 60 s | 3 × fixe | ❌ | ❌ | ❌ | **problématique** |
| Hub'Eau piézométrie | `variables/piezometry/apis/hubeau.py` | 317 | 60 s | 3 × fixe | ❌ | ❌ | ❌ | **problématique** |
| Hub'Eau qualité | `variables/water_quality/apis/hubeau.py` | 283 | 60 s | 3 × fixe | ❌ | ❌ | ❌ | **problématique** |
| Hub'Eau ONDE | `variables/intermittency/apis/hubeau.py` | ~250 | 60 s | 3 × fixe | ❌ | ❌ | ❌ | **problématique** |
| BRGM 50k | `variables/geology/apis/brgm_50k.py` | 183 | ❌ | ❌ | - | - | ❌ | **problématique** |
| BRGM 1M | `variables/geology/apis/brgm_1m.py` | 120 | ❌ | ❌ | - | - | ❌ | **problématique** |
| SHOM | `variables/oceanic/apis/shom.py` | 243 | 60 s | ❌ | ❌ | ❌ | ❌ | **à améliorer** |
| IGN BD ALTI | `variables/dem/apis/ign_bdalti.py` | 314 | ❌ | ❌ | - | - | ❌ | **problématique** |
| SIM2 EDR | `common/clients/sim2_edr.py` | ~250 | ? | ? | ❌ | ❌ | ❌ | **à améliorer** |

### 5.7 Recommandations transverses APIs

1. **Créer `common/api_helpers.HTTPClient`** wrapper unique avec :
   - `requests.Session` + `HTTPAdapter(max_retries=Retry(status_forcelist=[429,500,502,503,504], backoff_factor=1.0, allowed_methods=["GET"]))`.
   - Timeout systématique (`connect=10, read=60`).
   - Try/except JSON avec log structuré.
   - Migration de tous les clients vers ce wrapper.
2. **Ajouter validation Pydantic des réponses** (1 `RootModel` par endpoint Hub'Eau).
3. **Interdire `urllib.request.urlretrieve`** (remplacer par `requests.get(stream=True, timeout=...)` + `shutil.copyfileobj`).
4. **Factoriser les 9 wrappers SIM2** en un seul `SIM2Client` paramétré par variable.
5. **Ajouter SHA-256 sur les archives téléchargées** (BRGM ZIP, IGN 7z) + comparaison avec la valeur attendue quand l'API fournit un checksum.

---

## 6. Formats d'entrée (CSV custom et autres)

### 6.1 CSV stations LOC (`*_LOC.csv`)

Exemple observé : `examples/data/hydrometry/hydrometry_hubeau_LOC.csv`

```
id, x, y, crs, station_name, x_l93, y_l93, city, department, altitude, start_date
```

**Verdict : format propriétaire, non interopérable.**

- Pas de **GeoJSON** (standard OGC pour collections de points), pas de **GeoPackage** (standard OGC pour persistance SIG).
- Pas de **Frictionless `datapackage.json`** (schéma explicite pour CSV scientifique).
- Pas de **WaterML 2.0 `MonitoringPoint`** (standard OGC/WMO pour stations hydro).
- Pas de **OGC SensorThings `Thing + Location`** (standard IoT hydro pour capteurs temps réel).
- Doubles coordonnées `(x, y, crs)` + `(x_l93, y_l93)` : **redondance volontaire mais dangereuse** → si on met à jour une paire sans l'autre, désynchro silencieuse. Convention attendue : coordonnées uniques + CRS explicite.
- `start_date` sans `end_date` : incohérent avec la chronique elle-même.
- **Pas de schéma formel** : les colonnes supplémentaires varient par variable (hydrométrie a `altitude`, piézométrie a `codesise`, qualité eau a `nom_org_producteur`). Le lecteur `custom_point_loader.py` accepte tout ce qui est parseable.

### 6.2 CSV chroniques (`{variable}_{source}_{id}_{dates}_{freq}.csv`)

Format minimal `datetime, value`. Aucune colonne de qualité (`quality_code`), aucune colonne d'origine (`origine: validé, brut, reconstitué`), aucune unité dans le fichier (uniquement dans le nom de fichier et le catalog).

**Verdict : minimaliste acceptable pour debug interne, inadapté pour partage scientifique.**

Comparaison :
- **GRDC** : `YYYY-MM-DD;hh:mm;Value;Flag` + header 30 lignes (station, origine, unité, période).
- **WaterML 2.0** : XML structuré avec `TimeValuePair` + `qualifier` + `censoredReason`.
- **CSV-W (W3C)** : CSV + JSON-LD sidecar documentant chaque colonne.

### 6.3 CSV grilles (`recharge_hubeau_*.csv`, etc.)

Pour les variables climatiques, cohabitent `.csv` et `.nc`. Le `.csv` aplatit une grille 2D+T en `[x, y, datetime, value]` → explosion volumétrique (× 4 vs NetCDF). **À supprimer au profit exclusif de NetCDF CF-1.11 + Parquet pour les séries.**

### 6.4 Recommandations

| Format actuel | Remplacer par | Effort |
|---|---|---|
| `*_LOC.csv` | `*_LOC.geojson` ou `stations.gpkg` (couche SIG unique) | S |
| `{var}_{src}_{id}_{dates}_{freq}.csv` | Parquet avec colonnes `[datetime, value, quality_flag, source_code]` | M |
| Grilles CSV (climatic) | NetCDF CF-1.11 uniquement (déjà présent en `.nc`, supprimer les doublons CSV) | S |
| Stations | Complément sidecar `stations.json` schema Frictionless | M |

### 6.5 Verdict d'interopérabilité

- **Lecture par QGIS** : non (CSV LOC avec doubles coords non reconnu automatiquement).
- **Lecture par `geopandas.read_file`** : non (il faut passer par `pd.read_csv` + conversion).
- **Partage avec partenaire externe (INRAE, BRGM)** : nécessite un README manuel pour documenter les colonnes.

**C'est un format interne HydroModPy, pas un format d'échange.** À assumer comme tel, ou à standardiser.

---

## 7. Formats de sortie

### 7.1 Chroniques

Export via `data/common/export.py::export_records` → CSV uniquement.

Verdict : **non interopérable.**
- Pas d'export WaterML 2.0.
- Pas d'export NetCDF CF pour les chroniques (pourtant `xarray.Dataset` supporte `station_id` comme dimension via Discrete Sampling Geometries de CF).

### 7.2 Champs

Export : conservation du `FieldRecord.data` (xarray) sous forme `.nc` si déjà fourni, sinon raster `.tif` pour DEM. Pas de conversion systématique vers CF.

**Contrôle CF** : aucun `cf-checker` ou `cfchecks` dans `pyproject.toml`. Les NetCDF SIM2 passent probablement CF par héritage Météo-France, mais les NetCDF produits en interne (ex : recharge synthétique) ne sont pas validés.

### 7.3 Recommandations

| Action | Effort | Gain |
|---|---|---|
| Ajouter `export_waterml2.py` pour chroniques (via `pandas` → XML) | M | Partage scientifique |
| Ajouter attributs CF à tous les NetCDF produits (`units`, `standard_name`, `Conventions="CF-1.11"`) | S | Validation cf-checker |
| Remplacer l'export CSV chronique par Parquet + sidecar metadata | S | Volumes × 10, typage |

---

## 8. Gestion des CRS

### 8.1 État des lieux

- `StationLocation.crs: str` libre.
- `FieldRecord.crs: str` libre.
- `DemManager._resolve_bbox` / `_resolve_bbox_2154` : deux méthodes qui reprojettent à la main via `pyproj.Transformer`. Dupliqué dans `GeologyManager`.
- `data/common/geo_helpers.py` offre `load_mask_geometry_wgs84` et `filter_locations_by_geometry` → bonne factorisation partielle.
- `project_extent` passé aux managers : CRS implicite (en L-93 d'après le projet type, mais non vérifié).
- **Hub'Eau requiert WGS84** pour les bbox → reprojection imposée dans `base_manager._resolve_bbox`. OK.

### 8.2 Problèmes

1. **Mélange libre/contrainte** : les APIs Hub'Eau exigent WGS84 mais le projet tourne en L-93. Les bbox sont reprojetées à chaque appel, sans cache, sans validation. **Une erreur de CRS dans `config.project_crs` → reprojection silencieuse sur mauvais système.**
2. **Pas de validation `pyproj.CRS.from_user_input(crs)`** à l'entrée du config. Un typo `"EPSG:2145"` (au lieu de 2154) ne lève rien.
3. **Doubles coordonnées `(x, y)` + `(x_l93, y_l93)` dans les LOC** : source de désynchronisation (§ 6.1).
4. **Aucune convention claire** : certaines sorties sont en L-93 (rasters DEM), d'autres en WGS84 (LOC Hub'Eau). Un utilisateur qui superpose les deux dans QGIS sans reprojection a des décalages de 100 km.
5. **`xarray` Datasets sans `rio.crs`** : le CRS est stocké dans `FieldRecord.crs` (attribut dataclass) mais **pas injecté dans `ds.attrs` ou `ds.rio.crs`** → un `.to_netcdf()` perd l'info.

### 8.3 Recommandations

| Action | Effort | Gain |
|---|---|---|
| Valider `project_crs` au chargement du config (`pyproj.CRS.from_user_input`) | XS | Prévention bug |
| Typer `StationLocation.crs` et `FieldRecord.crs` comme `pyproj.CRS` (pas `str`) | S | Robustesse |
| Centraliser toutes les reprojections dans `common/geo_helpers.py` avec cache LRU | S | -150 lignes dupliquées |
| Injecter systématiquement le CRS dans `xr.Dataset.rio.crs` avant sérialisation NetCDF | XS | Persistance CF |
| Imposer une seule paire de coordonnées dans les LOC + CRS explicite | S | Cohérence |

**Verdict CRS : acceptable en usage contrôlé, fragile dès qu'on sort du duo L-93/WGS84.**

---

## 9. Tableau récapitulatif par variable

**Légende verdict** : ✅ conforme / 🟡 acceptable / 🔶 à améliorer / ❌ problématique / 🗑️ legacy à supprimer

| # | Variable | Config Pydantic | Manager (L) | Héritage | Sources API | Format entrée | Format sortie interne | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | `dem` | `DEMConfig` | 201 | **aucun** ❌ | `ign_bdalti`, custom | ASC/TIF/NC | GeoTIFF | 🔶 hors-pattern |
| 2 | `geology` | `GeologyConfig` | 264 | **aucun** ❌ | `brgm_1m`, `brgm_50k`, custom | SHP/GPKG/TIF/CSV | GeoPackage | 🔶 hors-pattern |
| 3 | `hydrography` | `HydrographyConfig` | 320 | **aucun** ❌ | `osm`, `bdtopage`, `euhydro`, custom | SHP/GeoJSON | SHP + raster | 🔶 pipeline maison |
| 4 | `hydrometry` | `HydrometryConfig` | 38 | `BaseVariableManager` ✅ | Hub'Eau, custom | CSV LOC+chr | `PointRecord` | 🟡 OK mais deps fragiles |
| 5 | `intermittency` | `IntermittencyConfig` | 41 | `BaseVariableManager` ✅ | Hub'Eau (ONDE), custom | CSV | `PointRecord` | 🟡 OK |
| 6 | `piezometry` | `PiezometryConfig` | 41 | `BaseVariableManager` ✅ | Hub'Eau (ADES), custom | CSV | `PointRecord` | 🟡 OK |
| 7 | `water_quality` | `WaterQualityConfig` | 41 | `BaseVariableManager` ✅ | Hub'Eau (Naïades), custom | CSV | `PointRecord` | 🟡 OK |
| 8 | `oceanic` | `OceanicConfig` | 84 | `BaseFieldManager` ✅ | SHOM, `constant`, custom | CSV/NC | `FieldRecord`+`PointRecord` | 🟡 OK |
| 9 | `recharge` | `RechargeConfig` | 34 | `BaseFieldManager` ✅ | SIM2, `synthetic`, custom | NC/CSV | `FieldRecord` | 🟡 OK |
| 10 | `runoff` | `RunoffConfig` | 27 | `BaseFieldManager` ✅ | SIM2, custom | NC/CSV | `FieldRecord` | 🟡 OK |
| 11 | `etp` | `EtpConfig` | 27 | `BaseFieldManager` ✅ | SIM2, custom | NC/CSV | `FieldRecord` | 🟡 OK |
| 12 | `precipitation` | `PrecipitationConfig` | 31 | `BaseFieldManager` ✅ | SIM2 (2 comp.), custom | NC/CSV | `FieldRecord` | 🟡 OK |
| 13 | `temperature` | `TemperatureConfig` | 27 | `BaseFieldManager` ✅ | SIM2, custom | NC/CSV | `FieldRecord` | 🟡 OK |
| 14 | `humidity` | `HumidityConfig` | 27 | `BaseFieldManager` ✅ | SIM2, custom | NC/CSV | `FieldRecord` | 🟡 OK |
| 15 | `wind` | `WindConfig` | 27 | `BaseFieldManager` ✅ | SIM2, custom | NC/CSV | `FieldRecord` | 🟡 OK |
| 16 | `radiation` | `RadiationConfig` | 31 | `BaseFieldManager` ✅ | SIM2 (2 comp.), custom | NC/CSV | `FieldRecord` | 🟡 OK |
| 17 | `soil_moisture` | `SoilMoistureConfig` | 27 | `BaseFieldManager` ✅ | SIM2, custom | NC/CSV | `FieldRecord` | 🟡 OK |

---

## 10. Duplication, dead code, over-engineering

### 10.1 Code dupliqué identifié

| # | Localisation | Lignes estimées | Action |
|---|---|---|---|
| 1 | `DemManager._resolve_bbox` + `GeologyManager._resolve_bbox_2154` + `brgm_50k` reprojection | ~150 | Factoriser dans `common/geo_helpers.py` |
| 2 | `_fetch_station_location` dans hydrometry/piezometry/water_quality | 3 × ~30 = 90 | Factoriser dans `common/clients/hubeau.py` |
| 3 | 9 wrappers `variables/*/apis/sim2.py` | 9 × ~25 = 225 | Un seul `SIM2Client` paramétré |
| 4 | Dispatch `if source == "custom" elif source == "hubeau"` dans 4 managers point | 4 × ~15 = 60 | Registry pattern ou dict lookup |
| 5 | Registry managers dans `store.py` (97-115) ET `runtime_loader.py` (65-83, 618-647) | ~80 | Registry unique exporté |
| 6 | `check_period_overlap` hydrometry/piezometry | 2 × ~20 = 40 | Factoriser |
| **Total** | | **~645 lignes** | **~3,5 % du package** |

### 10.2 Dead code / legacy

| Fichier | Lignes | Statut | Action |
|---|---|---|---|
| `data/climatic/climatic.py` | 618 | Déprécié (warning explicite ligne 40) | 🗑️ **Supprimer** |
| `data/climatic/sim2.py` | 932 | Encore utilisé par 9 wrappers | 🔶 Consolider ou déprécier |
| `data/climatic/sim2_API.py` | 282 | Helper de `sim2.py` | 🗑️ Supprimer avec sim2.py |
| `data/climatic/driasclimat.py` | 365 | Référencé uniquement dans `watershed.py` (legacy) | 🗑️ À archiver |
| `data/climatic/driaseau.py` | 274 | Idem | 🗑️ À archiver |
| `data/climatic/safransurfex.py` | 206 | Idem | 🗑️ À archiver |
| `planner._domain_requests_geology` | 2 | Wrapper vide | 🗑️ Supprimer |
| `DataManagers` (data_managers.py) | 34 | Container trivial (2 static ctor) | 🔶 Inliner |
| `LoadResult.all_records` (backward-compat) | 3 | Commentaire « backward compatibility » | 🔶 Vérifier si utilisé, sinon retirer |

**Total supprimable sans friction : ~2 700 lignes (environ 15 % du package).**

### 10.3 Over-engineering

- `DataLoadPlan.reasons_by_type` : généré mais jamais lu au runtime → overhead pour rien. À soit exploiter (log informatif), soit supprimer.
- `SourceConfigProtocol` (base_manager.py:27-32) : `Protocol` avec 3 attributs alors qu'une seule hiérarchie de `SourceConfig` l'implémente. Abstraction prématurée.
- `_CatalogEntry` avec `__slots__` manuel (catalog_duckdb.py:68-82) alors qu'un dataclass frozen ferait la même chose en 5 lignes.

### 10.4 Under-engineering

- Aucun `schema_version` dans le catalog DuckDB amont.
- Aucun export WaterML 2.0 / CF-NetCDF.
- Aucune validation Pydantic des réponses Hub'Eau.
- Aucun SHA-256 de traçabilité amont.

---

## 11. Optimisations potentielles

| Cible | Problème | Amélioration | Gain |
|---|---|---|---|
| `PointRecord.__post_init__` | Recalcule `compute_completeness` à chaque instanciation, y compris après `filter_by_period` | `@cached_property` | -O(n) par filtrage |
| `_upsert_api_loc` (base_manager.py:301-322) | Relecture du CSV + réécriture complète à chaque station → O(n²) | Buffer en mémoire, flush en fin de `load()` | 10-100× sur gros bassins |
| Téléchargements BRGM/IGN | Synchrones, un par un | `asyncio` ou `concurrent.futures` (déjà dispo côté runtime_loader, à étendre) | 3-4× sur multi-sources |
| Grilles SIM2 float64 | Gaspillage mémoire | float32 en option config | -50 % mémoire |
| `for _, row in df.iterrows()` (base_manager.py:311-312) | Antipattern Pandas | `df.to_dict(orient="records")` ou `df.apply` | 5-10× |
| `LOC CSV round-trip` | Parsing + reformat à chaque `_upsert` | Fichier Parquet ou SQLite | 10× |
| Invalidation mtime vs SHA-256 | mtime fragile | SHA-256 sur CSV < 10 Mo | Fiabilité |

---

## 12. Tests (vue rapide)

Non demandé explicitement mais relevé au passage dans `tests/unit/data_managers/` :
- Bonne couverture Hub'Eau water_quality (fichier `test_loaders_api_wq_integration.py` modifié au merge).
- Mais : peu de tests sur le **catalog DuckDB en écriture concurrente**. Aucun test `pytest-xdist` qui vérifie qu'un `register()` parallèle n'écrase pas une autre entrée.
- Aucun test de `DataManagersPlanner.build()` en mode `strict` avec toutes les combinaisons inférentielles (les règles hardcodées ne sont couvertes que partiellement).

---

## 13. Synthèse et feuille de route

### 13.1 Risques majeurs (P0)

1. **`urllib.request.urlretrieve` sans timeout** (BRGM 50k/1M, IGN BD ALTI) → risque blocage indéfini.
2. **Aucun handling HTTP 429 côté Hub'Eau** → crashes en usage intensif (batch régional).
3. **`resp.json()` non protégé** dans SIM2, SHOM, IGN → crashes sur pannes API.
4. **DuckDB sans `BEGIN/COMMIT` explicite** → corruption possible en multi-processus.
5. **Catalog sans `schema_version`** → impossibilité de migration future.

### 13.2 Risques intermédiaires (P1)

6. **Format CSV stations propriétaire** → non partageable sans documentation manuelle.
7. **DEM / Géologie / Hydrographie hors `BaseVariableManager`** → duplication ~150 lignes.
8. **Duplication registry managers** (store.py vs runtime_loader.py).
9. **Exceptions avalées partout** (bare `except Exception:` dans BRGM, catalog, caching).
10. **CRS stringly-typed** sans validation `pyproj.CRS`.

### 13.3 Hygiène (P2)

11. **~2 700 lignes dead code** (`climatic/`, wrappers triviaux).
12. **Over-engineering** (`SourceConfigProtocol`, `reasons_by_type` non exploité).
13. **`PointRecord.data: DataFrame`** devrait être `pd.Series` avec `DatetimeIndex`.
14. **`float64` partout** (économie `float32` sur grilles climatiques).

### 13.4 Feuille de route suggérée (3 sprints)

**Sprint 1 — Robustesse réseau (P0)**
- Créer `common/http_client.HTTPClient` avec retry/backoff/timeout.
- Migrer tous les clients API.
- Supprimer tous les `urllib.request.urlretrieve`.
- Protéger tous les `resp.json()`.

**Sprint 2 — Hygiène & legacy (P1)**
- Supprimer `climatic/climatic.py`, archiver `drias*.py` / `safransurfex.py`.
- Consolider SIM2 (1 client unique).
- Factoriser registry managers.
- Unifier DEM/Géologie sous `BaseSpatialManager`.
- Ajouter `schema_version` au catalog DuckDB.

**Sprint 3 — Interopérabilité (P2)**
- Typer contrats (`PointRecord.data → Series`, `FieldRecord.data → DataArray`).
- Ajouter export WaterML 2.0 et CF-NetCDF.
- Validation Pydantic des réponses Hub'Eau.
- CRS via `pyproj.CRS` partout.
- Format GeoPackage pour stations (en complément de LOC.csv).

**Effort total estimé : 3-4 sprints d'un développeur senior. ROI attendu : -30 % LOC, +fiabilité CI, conformité partielle CF/OGC, portabilité accrue.**

---

## 14. Conclusion

Le package `data/` est le **maillon le plus hétérogène** de HydroModPy. Il combine :

- une **couche moderne** (contracts typés, catalog DuckDB, planner d'inférence) récemment introduite — design honnête mais non-standard ;
- une **couche legacy** (`climatic/`, `DemManager`, `GeologyManager`) non encore migrée qui dilue la cohérence ;
- une **couche réseau** fragile (pas de rate-limit, pas de timeout urllib, schémas non validés) qui représente le plus gros risque en production.

L'architecture est fonctionnelle pour de la modélisation ponctuelle sur un bassin maîtrisé ; elle **ne tiendra pas** un usage en batch national, en CI continue contre des APIs vivantes, ou un partage scientifique soumis à revue (ESSD, HESS).

Les contrats `PointRecord`/`FieldRecord` devraient s'aligner sur `pandas.Series`/`xarray.DataArray` CF-compliant plutôt que réinventer la roue. Le catalog DuckDB doit être durci (transactions, migrations, SHA-256). Les APIs externes nécessitent un wrapper HTTP industriel unique (backoff, timeout, validation). Enfin, le format CSV propriétaire doit être assumé comme format interne ou remplacé par des standards (GeoPackage, Parquet, CF-NetCDF, WaterML).

**Priorité absolue : Sprint 1 (robustesse réseau). Les autres tâches peuvent attendre, mais les bugs réseau actuels sont des time-bombs.**
