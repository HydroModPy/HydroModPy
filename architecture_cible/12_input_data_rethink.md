# Refonte de la couche de données d'entrée — HydroModPy

**Document** : `architecture_cible/12_input_data_rethink.md`
**Date** : 2026-04-18
**Auteur** : Expert Data Pipelines & Géosciences (Hub'Eau, ADES, BRGM, Météo-France SIM2, SHOM, data.gouv, STAC, intake, fsspec, DVC)
**Portée** : repenser **intégralement** la logique de gestion des données d'entrée (APIs + fichiers custom + cache + catalogue + provenance + reproductibilité).
**Statut attendu** : conception *ex nihilo*, indépendante du code existant, directement implémentable.

> **Légende des tags** : `[NOUVEAU]` n'existe pas · `[RENOMME]` existe sous un autre nom · `[REFACTORE]` existe mais doit changer · `[CONSERVE]` existe et est bien.

---

## OVERRIDES (décisions post-review)

Les décisions ci-dessous **prévalent** sur toute mention contraire dans la suite du document.

### 1. API SIM2 via INRAE — PRÉSERVÉE

- Le client SIM2 actuel (`hydromodpy/data/climatic/sim2_API.py`) pointe vers un **hébergement INRAE public** qui **redistribue Météo-France** avec des formats améliorés (NetCDF CF natif, pas de rate limit, pas de clé obligatoire). Testé, fonctionne bien.
- **NE PAS** migrer vers `meteo.data.gouv.fr/api/v1/edr/collections/sim2/` — cela casserait un flow qui marche déjà pour un gain théorique.
- Action P04 : **refacto cosmétique uniquement** → déplacer le fichier vers `hydromodpy/data/common/clients/sim2_inrae.py`. **Aucun changement d'endpoint, aucun changement de format.**
- Les sections 2.1 / 2.2 qui détaillent la migration vers l'EDR data.gouv sont **annulées**.

### 2. Données utilisateur custom — drag-and-drop AVANT CLI

**Flow principal** (déjà amorcé dans `hydromodpy/data/scaffold.py`) :

```
~/hydromodpy/                              ← workspace
├── hydrometry_custom/                     ← scaffoldé à `hmp init`
│   ├── locations.csv                      ← header: id,x,y,crs,unit
│   ├── README.md                          ← format expliqué
│   └── chronicles/
│       ├── P01.csv                        ← header: datetime,value
│       └── P02.csv
├── piezometry_custom/
├── precipitation_custom/
├── recharge_custom/
└── ...
```

**Auto-scan mtime-based** au `hmp run` :
- `hydromodpy/data/auto_scan.py` (NOUVEAU en P04) détecte les fichiers **nouveaux ou modifiés** (mtime > `indexed_at` dans `data/cache.duckdb`).
- Validation schéma automatique, conversion format pivot invisible.
- Enregistrement avec `provider="custom"` dans le cache DuckDB.

**Coexistence avec CLI** :
- `hmp data add FILE` reste disponible pour les **power users** (contrôle fin, metadata explicite).
- `hmp data check [--variable X]` valide sans ingérer.
- `hmp data list` liste les artefacts indexés.
- **Mais le flow standard ne l'exige pas** : l'utilisateur drop ses fichiers dans `{variable}_custom/` et lance `hmp run`, point.

### 3. Formats utilisateur acceptés

| Type | Formats utilisateur acceptés | Format pivot interne (invisible) |
|---|---|---|
| Stations / points | CSV (header `id,x,y,crs,unit`), SHP, GeoJSON | GeoParquet |
| Chroniques | CSV (header `datetime,value`) | Parquet |
| Rasters | GeoTIFF, ASC (Esri grid) | GeoTIFF COG |
| Géométries vectorielles | SHP, GeoJSON, GPKG | GeoParquet |

**Principe** : l'utilisateur n'est **jamais exposé** à Parquet/GeoParquet. Des adapters convertissent en amont du cache.

### Conséquences dans le reste du document

- Section 2 (Couche API-first) : l'entrée SIM2 pointe vers INRAE, pas data.gouv.
- Section 3 (Couche fichiers locaux) / Section 4 (hmp data) : le drag-and-drop est le flow **primaire**, les commandes CLI sont **secondaires**.

---

## Table des matières

0. [Diagnostic synthétique de l'existant](#0-diagnostic-synthétique)
1. [Architecture cible — choix du paradigme](#1-architecture-cible--choix-du-paradigme)
2. [Couche API-first — détail exhaustif](#2-couche-api-first)
3. [Couche fichiers locaux — structure et registre](#3-couche-fichiers-locaux)
4. [Donnée custom utilisateur — expérience `hmp data`](#4-données-custom-utilisateur)
5. [Base de données d'entrée — DuckDB vs manifests](#5-base-de-données-dentrée)
6. [Reproductibilité — lockfile et provenance](#6-reproductibilité)
7. [Modèle d'objets Python — squelette complet](#7-modèle-dobjets-python)
8. [Migration depuis l'existant](#8-migration-depuis-lexistant)
9. [Conclusion](#9-conclusion)

---

## 0. Diagnostic synthétique

Audit source (`audit_code/03_data_layer.md`) : note globale **5,3/10**. Les trois maux dominants :

1. **Organisation par dossiers implicite** : l'utilisateur doit savoir qu'un CSV `hydrometry_custom_LOC.csv` doit vivre dans `data/hydrometry/` avec un suffixe `_LOC` précis. Convention orale, aucune validation à l'ingestion.
2. **Cache DuckDB minimaliste** : deux tables (`entries`, `api_coverage`), `date_start/end` stockées en `VARCHAR`, pas de SHA-256, invalidation par `mtime` (fragile), aucun `BEGIN/COMMIT` explicite (corruption possible en batch).
3. **Réseau fragile** : `urllib.request.urlretrieve()` sans timeout (BRGM, IGN), aucun handling HTTP 429 Hub'Eau, `resp.json()` non protégé, **pas de validation Pydantic des payloads** API.

La section qui suit propose un remplacement intégral. Elle ne cherche pas à patcher — elle redessine.

---

## 1. Architecture cible — choix du paradigme

### 1.1 Les trois options envisageables

| Critère | **A — Tout API** | **B — Fichiers + registre** | **C — Hybride API-first + fallback fichiers** |
|---|---|---|---|
| Barrière d'entrée utilisateur | Nulle (juste une `bbox`) | Forte (il faut préparer les fichiers) | Faible (start avec API, enrichi avec ses propres fichiers) |
| Fonctionne offline | ❌ sans cache | ✅ | ✅ via cache chaud |
| Données custom (DEM local, piézos internes) | Impossible sans passer à B | ✅ natif | ✅ natif |
| Gouvernance (labo, certification) | Faible (dépendance externe) | Forte (on maîtrise la source) | Forte (provenance tracée) |
| Reproductibilité à 2 ans | Fragile (APIs évoluent) | Forte (si data versionnée) | Forte (lockfile + archive snapshots) |
| Complexité d'implémentation | Moyenne (APIs à durcir) | Moyenne (validateurs + registre) | **Haute** (union des deux) |
| Robustesse réseau (batch national, CI) | Critique (rate-limit, 429) | Nulle (hors-ligne) | Mitigée (cache absorbe les 429) |
| Multi-utilisateurs / HPC | Réservable (cache partagé) | Naturel (NFS) | Naturel |
| Alignement écosystème Python sciences | `intake`, `fsspec` | Frictionless, STAC | Pangeo (catalog intake + fsspec) |
| Dette de migration | Faible | Moyenne | Moyenne-haute |

### 1.2 Recommandation : option **C — Hybride API-first avec cache local intelligent et enregistrement fichiers custom**

**Justification :**

1. **HydroModPy sert deux publics opposés** : l'utilisateur institutionnel (BRGM, INRAE) qui part *de zéro* sur un bassin et veut tout fetcher, et l'hydrogéologue local qui a *déjà ses propres piézos* et sa propre géologie de forage. Une architecture mono-source ignore la moitié du public.
2. **La donnée hydro française est déjà exposée en APIs nationales** (Hub'Eau, ADES via Hub'Eau, BRGM InfoTerre, Météo-France SIM2 EDR, SHOM Refmar, IGN Géoservices). Ne pas en profiter, c'est réinventer un scraping.
3. **Mais aucune API ne couvre tout** : un DEM de forage, une carte géologique interne de labo, une piézo « maison » non déclarée en ADES existent. Ces cas justifient un second chemin d'ingestion.
4. **Le cache local DOIT exister de toute façon** (audits Hub'Eau : ~1 000 req/jour sans clé). Autant en faire la *seule source de vérité runtime* : **runtime → cache local → fetch API si manquant**. C'est le pattern DVC, Poetry, npm.
5. **Un fichier custom déposé par l'utilisateur est juste une ligne de cache avec `provider='custom'`**. Unification totale du modèle — un seul `SimulationInputCatalog` à maintenir, pas deux pipelines distincts.

**Principe directeur** : *« L'utilisateur interagit toujours avec le même objet — un catalog d'entrées du workspace. Que la ligne vienne d'Hub'Eau, d'un fichier qu'il a déposé, ou d'un export qu'on lui a transmis, l'interface est la même. »*

### 1.3 Schéma d'architecture cible

```
 ┌────────────────────────────────────────────────────────────────────┐
 │                 CONFIG TOML (hmp run config.toml)                  │
 │  [data]  types = ["dem","hydrometry","piezometry","recharge",…]    │
 │         inference_mode = "strict"                                  │
 │  [data.hydrometry]   source = "hubeau"   |   source = "custom"     │
 └────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
 ┌────────────────────────────────────────────────────────────────────┐
 │                    DataPlanner  (pure, deterministic)              │
 │   résout  (types explicites ∪ types inférés)  +  sélection source  │
 └────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
 ┌────────────────────────────────────────────────────────────────────┐
 │                     InputCatalog  (DuckDB)                         │
 │      GET    key=(var,provider,bbox,period) →  hit/miss             │
 │      PUT    nouveau artefact enregistré (SHA-256 + provenance)     │
 └──────┬────────────────────────────────────────────────┬────────────┘
        │ cache MISS                                      │ cache HIT
        ▼                                                 │
 ┌────────────────────────────┐                           │
 │     DataSource.fetch()     │                           │
 │  (hubeau | brgm | sim2 |   │                           │
 │   shom   | ign    | ocsge) │                           │
 │   via  HTTPClient durci    │                           │
 └────────────────────────────┘                           │
        │                                                 │
        ▼                                                 │
 ┌────────────────────────────┐                           │
 │  Validation contractuelle  │                           │
 │   (pandera / Pydantic)     │                           │
 └────────────────────────────┘                           │
        │                                                 │
        ▼                                                 ▼
 ┌────────────────────────────────────────────────────────────────────┐
 │    Normalisation vers format pivot (Parquet / GeoParquet / Zarr)   │
 │    écriture fichier + insertion DuckDB (artifacts + provenance)    │
 └────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
 ┌────────────────────────────────────────────────────────────────────┐
 │   LoadResult  →  consommé par SimulationPlanner / SolverAdapter    │
 └────────────────────────────────────────────────────────────────────┘
```

### 1.4 Comparaison aux outils de référence

| Projet | Ce qu'il fait bien | Ce qu'on reprend ici | Ce qu'on NE reprend PAS |
|---|---|---|---|
| **intake** (Pangeo) | Catalog YAML + `DataSource.to_dask()` | Le concept `DataSource` comme Protocol | Pas de YAML exposé à l'utilisateur final, trop bureaucratique |
| **fsspec** | Abstraction filesystems (local/S3/GCS/HTTP) | `fsspec.AbstractFileSystem` comme couche d'accès | — |
| **DVC** | Lockfile par fichier + remotes | **`hydromodpy.lock`** pour la provenance | Pas de remote DVC natif ; on garde `.hmp` pour la portabilité |
| **STAC 1.0** | Catalog d'items raster | Inspiration pour les métadonnées géospatiales | Pas de STAC JSON files, DuckDB est plus pratique |
| **Frictionless Data** | `datapackage.json` + `tableschema.json` | **Sidecar JSON pour fichiers custom** | Pas l'outil `frictionless validate` (on utilise pandera) |
| **Poetry / npm / Cargo** | `pyproject.toml` + `poetry.lock` | **Séparation sources déclaratives / lockfile résolu** | — |
| **OGC SensorThings v1.1** | Modèle `Thing/Location/Observation` | Modèle logique station + observations | Pas l'API REST, pas JSON-LD |
| **THREDDS / OPeNDAP** | Serveur NetCDF distribué | — | Hors périmètre (on n'héberge pas) |
| **PROJ + pyproj** | Gestion CRS industrielle | `pyproj.CRS` pour tout ce qui est spatial | — |
| **MODFLOW input** | Texte fixe, bien documenté | Principe : *chaque fichier est autoportant* | Pas de format texte maison |
| **SWAT** | Fichiers texte structurés | — | Pattern obsolète, trop rigide |
| **MIKE SHE (DHI)** | Base propriétaire `.she` | — | Anti-pattern (vendor lock-in) |

### 1.5 Conséquence architecturale immédiate

Le dossier `hydromodpy/data/` est **restructuré** comme suit `[REFACTORE]` :

```
hydromodpy/data/
├── __init__.py                       # expose catalog(), DataPlanner, load()
├── planner.py                        # [REFACTORE] DataPlanner (sans God class)
├── loader.py                         # [RENOMME depuis runtime_loader.py, fonction pure]
├── cache.py                          # [NOUVEAU] InputCatalog (DuckDB)
├── lockfile.py                       # [NOUVEAU] hydromodpy.lock (YAML)
├── contracts/
│   ├── point_record.py               # [REFACTORE] pd.Series + Station
│   ├── field_record.py               # [REFACTORE] xr.Dataset only, plus de Union[Path,Dataset]
│   ├── station.py                    # [NOUVEAU] shapely.Point + pyproj.CRS
│   └── load_result.py                # [CONSERVE]
├── schemas/                          # [NOUVEAU] pandera + Pydantic contrats
│   ├── timeseries.py
│   ├── stations.py
│   ├── raster_dem.py
│   ├── raster_geology.py
│   └── field_cf.py
├── sources/                          # [RENOMME depuis variables/*/apis/]
│   ├── base.py                       # DataSource Protocol
│   ├── registry.py                   # @register_source decorator
│   ├── hubeau/                       # 4 classes : Hydrometry, Piezometry, WaterQuality, Intermittency
│   ├── brgm/                         # Geology50k, Geology1M
│   ├── shom/                         # Oceanic (Refmar)
│   ├── ign/                          # BDAlti (DEM)
│   ├── meteofrance/                  # SIM2Client (unique, 9 variables)
│   └── custom/                       # CustomFileSource (parquet/csv/tif/nc user-provided)
├── common/
│   ├── http_client.py                # [NOUVEAU] wrapper Session+Retry+timeout unique
│   ├── geo_helpers.py                # [REFACTORE] CRS LRU + reprojection unique
│   ├── units.py                      # [CONSERVE] unit_helpers.py renommé
│   └── quality.py                    # [NOUVEAU] codes qualité + completeness
└── cli/
    ├── data_add.py                   # [NOUVEAU] `hmp data add`
    ├── data_list.py                  # [NOUVEAU] `hmp data list`
    ├── data_export.py                # [NOUVEAU] `hmp data export`
    └── data_prune.py                 # [NOUVEAU] `hmp data prune`
```

**Supprimés `[K]`** : `data/climatic/*` (2 700 L), `data/common/base_manager.py` (492 L), `data/common/base_field_manager.py`, `data/store.py`, `data/subbasin/`, `data/geology/` legacy, `data/hydrometry/` legacy, `data/piezometry/` legacy, `data/oceanic/` legacy. Soit **~4 500 lignes de moins**.

---

## 2. Couche API-first

### 2.1 Tableau exhaustif des APIs source

| Variable cible | API / Source | Endpoint | Format natif | Périodicité max | Rate-limit | Auth | Période couverte |
|---|---|---|---|---|---|---|---|
| `hydrometry` (débits) | **Hub'Eau Hydrométrie v2** | `https://hubeau.eaufrance.fr/api/v2/hydrometrie/` | JSON | horaire / 6 min | ~1 000 req/jour (sans clé) / 10 k (clé) | Clé optionnelle | 1968 – aujourd'hui |
| `piezometry` (niveaux) | **Hub'Eau Nappes (ADES)** | `/api/v1/niveaux_nappes/chroniques` | JSON | journalier / sub-horaire | idem | idem | 1900 – aujourd'hui |
| `water_quality` (physico-chimie) | **Hub'Eau Qualité Nappes (Naïades)** | `/api/v2/qualite_nappes/` | JSON | ponctuel (prélèvements) | idem | idem | 1970 – aujourd'hui |
| `intermittency` (assèchement) | **Hub'Eau ONDE** | `/api/v1/ecoulement/` | JSON | mensuel été | idem | idem | 2012 – aujourd'hui |
| `hydrography` (cours d'eau) | **IGN BDTopage** (via data.gouv) | Téléchargement ZIP GPKG | GeoPackage | statique | — | — | — |
| `hydrography` (OSM) | **Overpass API** | `https://overpass-api.de/api/interpreter` | JSON/XML | 25 000 objets/requête | IP-based | — | — |
| `hydrography` (EU-Hydro) | **Copernicus EU-Hydro** | S3 public | GPKG/SHP | statique | — | — | — |
| `dem` | **IGN BD ALTI 25 m** | Géoservices WMS/WFS ou téléchargement par dalle | GeoTIFF / ASC | statique | — | — | — |
| `dem` (CosmWorld) | **Copernicus DEM GLO-30** | S3 public | COG | statique | — | — | — |
| `geology` (1/1M) | **BRGM InfoTerre WMS** | `https://infoterre.brgm.fr/formulaires/telechargement-cartes.htm` | SHP/GPKG | statique | — | — | — |
| `geology` (1/50k) | **BRGM Géologie 1/50 000** | Téléchargement par feuille | SHP | statique | — | — | — |
| `geology` (BDLisa) | **BRGM BDLisa (nappes)** | WMS/WFS | GPKG | statique | — | — | — |
| `oceanic` (marégraphes) | **SHOM Refmar** | `https://data.shom.fr/data/seismometre/*` et `refmar.shom.fr` | CSV/JSON | 10 min | ~1 req/s | — | 1846 (Brest) – aujourd'hui |
| `recharge`, `etp`, `precipitation`, `temperature`, `humidity`, `wind`, `radiation`, `soil_moisture`, `runoff` | **SIM2 via hébergement INRAE** (préservé — voir OVERRIDES) | Endpoint INRAE existant (ne **pas** migrer vers `meteo.data.gouv.fr`) | NetCDF / CSV reformaté | journalier | pas de rate limit | aucune clé | 1958 – J-5 |
| `administrative` (communes, dépts) | **IGN ADMIN-EXPRESS** | `https://geoservices.ign.fr/adminexpress` | SHP/GPKG | statique | — | — | — |
| `landcover` (OCS) | **IGN OCS GE** | Téléchargement par département | SHP | statique | — | — | — |
| `soils` (carte mondiale) | **SoilGrids 250 m (ISRIC)** | WCS/WMS | GeoTIFF COG | statique | ~50 req/min | — | — |

**Nouvelle règle** : **aucune source n'est hardcodée dans un manager**. Chaque source est une classe décorée qui s'enregistre dans un registre.

### 2.2 Cache local — *où, combien de temps, invalidation, offline*

#### 2.2.1 Emplacement

```
~/hydromodpy/                                    # HYDROMODPY_WORKSPACE, configurable
├── data/
│   ├── cache.duckdb                             # [CONSERVE] le catalog DuckDB (schéma ci-dessous)
│   ├── blobs/                                   # [NOUVEAU] tous les artefacts physiques
│   │   ├── hydrometry/
│   │   │   └── hubeau/
│   │   │       └── K1234001/
│   │   │           └── 20100101_20251231_P1D.parquet
│   │   ├── piezometry/hubeau/BSS002GNSS/…
│   │   ├── dem/ign/bdalti25/L93_xy_resXXX.tif
│   │   ├── geology/brgm_1m/L93_xy.geoparquet
│   │   └── recharge/sim2/2010_2025.zarr/        # Zarr chunks compressé
│   ├── stations.geoparquet                      # [NOUVEAU] collection globale des stations
│   └── providers/                               # [NOUVEAU] snapshots api-level (doc pour audit)
│       └── hubeau_coverage_2026-04-18.json
└── hydromodpy.lock                              # [NOUVEAU] lockfile (voir §6)
```

**Partage** : `HYDROMODPY_WORKSPACE` est typiquement sur un NFS labo → cache chaud mutualisé entre utilisateurs.

#### 2.2.2 Durée de rétention (TTL par type)

| Type de donnée | TTL cache | Justification |
|---|---|---|
| Chronique hydro/piézo Hub'Eau | **7 jours** (data < J-7) ; **∞** (data > J-30) | Hub'Eau « stabilise » ses données à J-30. Cache des données récentes doit être court (révisions fréquentes). |
| Météo SIM2 temps réel | **J+5** (réanalyses finales après 5 jours) | Météo-France publie sur J+1 l'estimation provisoire, stabilise à J+5. |
| DEM, BD ALTI | **365 jours** | Publications annuelles ou moins. |
| Géologie BRGM | **730 jours** (2 ans) | Publications quinquennales. |
| Stations (localisations) | **90 jours** | Créations/désactivations occasionnelles. |
| Marégraphes SHOM | **24 heures** | Corrections fréquentes sur 30 jours glissants. |

Implémentation : colonne `ttl_days` dans `provenance` + `fetched_at` → expiration calculée à `GET`.

#### 2.2.3 Invalidation

**Trois mécanismes, dans l'ordre de priorité :**

1. **SHA-256 changé** (le fichier local ne correspond plus au hash enregistré) → invalide.
2. **`fetched_at + ttl < now`** → invalide (stale).
3. **`--force-refresh`** CLI → invalide manuellement.

**Mtime n'est jamais utilisé.** Audit `03_data_layer.md` § 4.3 : fragile sur NFS, résolution seconde variable selon FS.

#### 2.2.4 Mode offline

```bash
hmp run config.toml --offline       # fail sur cache miss, ne tente aucun HTTP
hmp run config.toml --offline-warn  # warn sur cache miss, génère NaN
```

Mode `offline` configurable par variable dans le TOML :

```toml
[data.hydrometry]
source = "hubeau"
offline = true            # si cache miss → exception DataCacheMiss explicite
```

#### 2.2.5 Rate limiting et résilience réseau

**Un seul wrapper HTTP**, `hydromodpy/data/common/http_client.py` `[NOUVEAU]` :

```python
# hydromodpy/data/common/http_client.py
from dataclasses import dataclass
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

@dataclass(frozen=True, slots=True)
class HTTPClient:
    base_url: str
    timeout: tuple[float, float] = (10.0, 60.0)   # (connect, read)
    user_agent: str = "HydroModPy/1.0 (+https://github.com/…)"
    api_key: str | None = None
    rps_budget: float = 1.0                        # requêtes / seconde max
    _session: requests.Session = None              # init dans __post_init__

    def __post_init__(self):
        sess = requests.Session()
        retry = Retry(
            total=6,
            backoff_factor=1.0,                    # délais 1,2,4,8,16,32 s
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,       # honorer Retry-After: HubEau
        )
        sess.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4))
        sess.headers.update({"User-Agent": self.user_agent})
        if self.api_key:
            sess.headers["X-API-Key"] = self.api_key
        object.__setattr__(self, "_session", sess)

    def get_json(self, path: str, params: dict | None = None) -> Any:
        self._throttle()
        r = self._session.get(f"{self.base_url}/{path}", params=params,
                              timeout=self.timeout)
        r.raise_for_status()
        try:
            return r.json()
        except ValueError as e:
            raise UpstreamResponseError(
                f"Non-JSON response from {r.url} [{r.status_code}]: "
                f"{r.text[:200]!r}") from e

    def stream_download(self, path: str, dest: Path, *, expected_sha256: str | None):
        self._throttle()
        with self._session.get(f"{self.base_url}/{path}", stream=True,
                                timeout=self.timeout) as r:
            r.raise_for_status()
            hasher = hashlib.sha256()
            with dest.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    fh.write(chunk); hasher.update(chunk)
        sha = hasher.hexdigest()
        if expected_sha256 and sha != expected_sha256:
            dest.unlink(missing_ok=True)
            raise ChecksumError(f"SHA256 mismatch: got {sha}, want {expected_sha256}")
        return sha
```

- **Timeout systématique** `(connect=10s, read=60s)`.
- **Backoff exponentiel** 1-2-4-8-16-32 s, jusqu'à 6 retries, status-forcelist `[408, 429, 5xx]`.
- **Retry-After header respecté** (Hub'Eau l'envoie).
- **Token bucket** côté client (`rps_budget=1.0` par défaut, 0.2 pour Overpass).
- **JSON safe** (exception typée, jamais de `json.JSONDecodeError` qui remonte).
- **SHA-256 calculé en streaming** lors du download — validé si la source le publie (BRGM publie des `.md5`).

Toutes les sources héritent de ce client. **Zéro `urllib.request.urlretrieve`** dans le code.

#### 2.2.6 Validation des payloads API (Pydantic)

Chaque endpoint Hub'Eau a un `RootModel` dans `sources/hubeau/schemas.py` `[NOUVEAU]` :

```python
# hydromodpy/data/sources/hubeau/schemas.py
from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
from typing import Annotated

class HubEauStation(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code_station: str
    libelle_station: str | None = None
    longitude_station: Annotated[float, Field(ge=-180, le=180)]
    latitude_station: Annotated[float, Field(ge=-90, le=90)]
    date_ouverture_station: datetime | None = None
    date_fermeture_station: datetime | None = None
    altitude_station: float | None = None
    code_commune_station: str | None = None

    @field_validator("code_station")
    @classmethod
    def _strip(cls, v): return v.strip().upper()

class HubEauObservation(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    date_obs: datetime
    resultat_obs: float | None
    code_qualification: int | None

class HubEauStationPage(BaseModel):
    count: int
    next: str | None = None
    previous: str | None = None
    data: list[HubEauStation]
```

Utilisation :

```python
page = HubEauStationPage.model_validate(resp_json)
# → lève ValidationError structurée si Hub'Eau renvoie champ manquant
```

### 2.3 Données qui N'EXISTENT PAS en API

Exemples concrets : géologie de forage interne BRGM (non publique), piézomètres privés non déclarés ADES, DEM LIDAR départemental non IGN, mesures de laboratoire, essais de pompage propriétaires.

**Solution unifiée :** elles sont traitées *exactement* comme n'importe quelle entrée cachée, avec `provider='custom'`. Voir § 4.

---

## 3. Couche fichiers locaux — quand et comment

### 3.1 Rôle

Les fichiers locaux ont **deux rôles uniquement** :

1. **Cache des APIs** : écrits par le cache manager, l'utilisateur ne les manipule pas.
2. **Données custom** : déposées par l'utilisateur via `hmp data add` (voir § 4).

**L'utilisateur n'est JAMAIS censé organiser manuellement les fichiers dans `~/hydromodpy/data/`.** Toute action passe par CLI ou API Python. Le dossier `blobs/` est structuré par le système, pas par l'humain.

### 3.2 Structure de répertoires prescrite

```
~/hydromodpy/data/blobs/
├── <variable>/
│   └── <provider>/
│       ├── <station_id>/                        # timeseries : subdivisé par station
│       │   └── <date_start>_<date_end>_<freq>.parquet
│       └── <spatial_key>/                       # grilles/rasters : subdivisé par bbox
│           └── <period>.{nc,zarr,tif,geoparquet}
```

**Convention over configuration** : le path est un détail d'implémentation, **généré par le `InputCatalog`**, pas tapé par l'utilisateur.

### 3.3 Format pivot par type de géométrie

| Type d'entrée | Format pivot imposé | Lecteur standard | CRS écrit dans le fichier |
|---|---|---|---|
| DEM (raster continu) | **COG GeoTIFF Float32** | `rioxarray.open_rasterio` | oui (tags GeoTIFF) |
| Géologie raster catégoriel | **COG GeoTIFF UInt16** + sidecar `*_attributes.parquet` | `rioxarray` + `geopandas` | oui |
| Géologie vectorielle | **GeoParquet** (polygones) | `geopandas.read_parquet` | oui (metadata GeoParquet) |
| Hydrographie | **GeoParquet** (lines/polygons) | `geopandas.read_parquet` | oui |
| Stations de mesure | **GeoParquet** (points) | `geopandas.read_parquet` | oui |
| Chronique ponctuelle | **Parquet + sidecar metadata** | `pandas.read_parquet` | — (pas spatial) |
| Grille climatique 2D+T | **CF-NetCDF 1.11** ou **Zarr v3** | `xarray.open_dataset` | oui (`grid_mapping`) |

**Éliminés** : tous les CSV propriétaires, les ASC, les SHP (au profit de GeoPackage/GeoParquet), les NC maison non-CF.

### 3.4 Registre/catalogue : DuckDB avec vues matérialisées

Pas de STAC JSON sidecar, pas de YAML intake. Le registre **est** le DuckDB (schéma détaillé § 5). Les raisons :

- **Requêtes spatiales RTREE natives** (DuckDB `spatial` extension depuis 0.10).
- **Jointures SQL** entre artefacts et provenance sans parser de fichiers.
- **Atomicité transactionnelle** via `BEGIN/COMMIT`.
- **Export portable** : `DuckDB → .hmp` trivial (EXPORT DATABASE).

Une **vue JSON read-only** est néanmoins générée pour les outils externes qui n'ont pas DuckDB :

```bash
hmp data list --format json > workspace_catalog.json
# ↓
# [{"artifact_id":"…","variable":"piezometry","provider":"hubeau",
#   "station_id":"BSS002…","path":"…/blobs/piezometry/…","sha256":"…","fetched_at":"…"}]
```

### 3.5 Validation automatique à l'ingestion

Chaque `PUT` cache passe par **un pipeline de validation en 4 étapes** :

1. **Format** : `FormatValidator.check(path)` — vérifie que le fichier est bien un COG/GeoParquet/CF-NetCDF/Parquet selon ce qui est attendu.
2. **Schéma** : `pandera.DataFrameSchema.validate(df, lazy=True)` ou Pydantic `*Contract.from_path(path)`.
3. **Spatial** : bbox extraite intersecte `project_extent` (warn) ; CRS `pyproj.CRS.from_user_input()` valide.
4. **Intégrité** : SHA-256 calculé et stocké ; taille != 0.

Toute violation lève `DataContractViolation` `[NOUVEAU]` avec rapport structuré :

```python
class DataContractViolation(Exception):
    def __init__(self, path: Path, contract: str, errors: list[ValidationError]):
        self.path, self.contract, self.errors = path, contract, errors
```

Persistées dans la table DuckDB `validation_reports` pour audit (§ 5.2).

---

## 4. Données custom utilisateur — expérience `hmp data`

### 4.1 Principe d'UX

L'utilisateur ne connaît que **trois commandes** :

```bash
hmp data add my_wells.csv --type piezometry --crs EPSG:2154
hmp data list [--variable piezometry] [--provider custom]
hmp data remove <artifact_id>
```

Il **ne crée jamais de dossier**. Il **ne crée jamais de fichier LOC**. Il **ne renomme jamais** `hydrometry_custom_LOC.csv`. Le système gère tout.

### 4.2 `hmp data add` — flux détaillé

```bash
$ hmp data add ./my_piezo_network.csv --type piezometry --crs EPSG:2154
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Detecting format : CSV with ';' separator
 Detecting schema : 42 rows, columns = [id, x, y, z_m, datetime, head_m]
 Inferred data type : piezometry
   → stations    : 7 unique ids      [P01, P02, P03, P04, P05, P06, P07]
   → observations : 42 rows × 6 columns
   → time range  : 2018-03-01 → 2024-12-15
   → frequency   : P1D (daily, 98% complete)
 Validating schema against TimeSeriesSchema… ✓
 Validating CRS EPSG:2154 (RGF93 / Lambert-93)… ✓
 Validating spatial extent…
   → 7/7 stations inside project_extent (~Rennes basin) ✓
 Normalising to pivot format (Parquet + GeoParquet)…
 Writing to ~/hydromodpy/data/blobs/piezometry/custom/<sha>/…
 Registering 1 artifact, 7 stations, 42 observations in catalog.duckdb
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ✓ Added : piezometry/custom/<artifact_id>
   SHA-256  : 3f2a9e…c01
   Use      : [data.piezometry]  source = "custom"  in config.toml
```

Toutes les étapes sont **visibles, pas silencieuses**. L'utilisateur voit ce qui a été détecté (et peut corriger avec des flags s'il n'est pas d'accord).

### 4.3 Formats d'entrée acceptés

**Format tabulaire simple (CSV / Excel / Parquet / Feather)** — le plus courant :

**Piezometry / Hydrometry / Water Quality / Intermittency / Oceanic (chronique + stations inline)**

| Colonne | Obligatoire | Type | Contraintes |
|---|---|---|---|
| `id` | ✅ | string | alphanumérique, 3-32 car. |
| `x`, `y` | ✅ | float | coords dans le CRS donné en CLI |
| `z_m` | ❌ | float | altitude, sinon NULL |
| `station_name` | ❌ | string | libellé |
| `datetime` | ✅ | ISO-8601 string | UTC par défaut, tz-aware accepté |
| `<var>_<unit>` | ✅ | float | p.ex. `head_m`, `discharge_m3_s`, `no3_mg_L` |
| `qflag` | ❌ | string | `valid` / `raw` / `reconstructed` / `missing` |

**Exemple minimal** `my_piezo_network.csv` (3 lignes) :

```csv
id;x;y;datetime;head_m;qflag
P01;350123.4;6789012.1;2020-01-01;12.35;valid
P01;350123.4;6789012.1;2020-01-02;12.36;valid
P02;350234.5;6789234.2;2020-01-01;9.87;valid
```

Le chargeur **éclate** ce fichier en :

- `stations.geoparquet` → 2 lignes (P01, P02)
- `piezometry/custom/<sha>/P01.parquet` et `/P02.parquet` → chroniques par station

**Format grille (NetCDF / Zarr / COG)** — déjà conforme :

```bash
hmp data add recharge_2020_2024.nc --type recharge
# → validation CF, écriture dans blobs/recharge/custom/<sha>/2020-01-01_2024-12-31_P1D.nc
```

**Format raster vecteur (GeoPackage / GeoParquet / SHP legacy)** — géologie, hydrographie :

```bash
hmp data add my_geology.gpkg --type geology --layer lithology
# → ouvre la couche 'lithology', vérifie géométries, normalise en GeoParquet
```

### 4.4 CLI spécifiée

```
hmp data add FILE [OPTIONS]
    --type TEXT                 Variable cible (piezometry, hydrometry, dem, geology, recharge…)
                                Si absent : inférence depuis nom de colonne/fichier (confirmation interactive)
    --crs TEXT                  CRS explicite (EPSG:XXXX ou WKT). Requis pour CSV ; lu depuis le
                                fichier pour GeoPackage/GeoParquet/GeoTIFF/NetCDF.
    --provider TEXT             [default: custom] nom de provenance logique (ex : "labo_rennes")
    --unit TEXT                 Override unité (sinon inférée du nom de colonne ou sidecar)
    --frequency TEXT            ISO-8601 duration (P1D, PT1H). Inférée si possible.
    --station-id TEXT           Pour fichier unique à 1 station sans colonne id.
    --replace                   Si artefact (var, provider, station, period) existe : remplacer
    --dry-run                   Affiche ce qui SERAIT fait, n'écrit rien
    --format FMT                Force format (csv, parquet, nc, zarr, tif, gpkg). Sinon détecté.

hmp data list [OPTIONS]
    --variable TEXT             Filtre
    --provider TEXT             Filtre
    --station-id TEXT           Filtre
    --since DATE                Fetched after DATE
    --format [table|json|csv]   [default: table]
    --expired                   Seulement les artefacts stale (fetched_at + ttl < now)

hmp data remove ARTIFACT_ID [--keep-file]
    ARTIFACT_ID                 UUID ou préfixe unique (min 8 car.)
    --keep-file                 Supprime de DuckDB mais garde le blob sur disque

hmp data prune [--older-than DAYS] [--dry-run]
    Purge les artefacts expirés et les blobs orphelins

hmp data export ARTIFACT_ID --to PATH
    Copie un artefact cached + son sidecar metadata dans un dossier partageable

hmp data import ARCHIVE.tar.zst
    Import inverse de ci-dessus ; ré-insère dans DuckDB avec validation SHA-256

hmp data check [--fix]
    Vérifie cohérence DuckDB ↔ filesystem (orphans, SHA mismatch)
```

### 4.5 Feedback immédiat — exemple d'erreur

```bash
$ hmp data add my_bad_data.csv --type piezometry --crs EPSG:2154
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Detecting format : CSV
 Validating schema against TimeSeriesSchema…
 ✗ SchemaError : 3 issues found

   column 'datetime' : not parseable as timestamp (3 rows)
       row 5 : "31/02/2020"              ← 31 février n'existe pas
       row 12: "2020-13-01"              ← mois 13 invalide
       row 18: ""

   column 'head_m' : contains negative values (2 rows)
       row 22: -999.0                    ← sentinelle ? utiliser NULL ou qflag="missing"
       row 23: -1.5

   column 'id' : duplicate station_id with different coordinates
       station P01 appears with (350123, 6789012) AND (350150, 6789030)

 To fix :
   1. Replace "31/02/2020" with a valid date or leave empty
   2. Mark -999 as NULL or use --sentinel -999 to auto-convert
   3. Decide which (x,y) is canonical for P01

 No artifact added. Run again after fixes, or use --force to ingest with warnings.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

La validation pandera `lazy=True` collecte **toutes** les erreurs avant d'échouer, contrairement au comportement actuel qui s'arrête à la première.

### 4.6 API Python équivalente

Pour les hydrogéologues qui travaillent en Jupyter, l'UX doit être symétrique :

```python
import hydromodpy as hmp

ws = hmp.open("~/hydromodpy")
art = ws.data.add(
    "./my_piezo_network.csv",
    variable="piezometry",
    crs="EPSG:2154",
    provider="labo_rennes",
)
print(art.artifact_id, art.sha256, art.path)

# Liste
ws.data.list(variable="piezometry").to_pandas()

# Récupération pour simulation
rec = ws.data.load(variable="piezometry", provider="labo_rennes",
                   extent=my_bbox, period=("2018-01-01", "2024-12-31"))
rec.points[0].values.plot()
```

---

## 5. Base de données d'entrée — DuckDB vs manifests

### 5.1 Verdict : **DuckDB est le bon choix, mais avec un schéma sérieux**

**Options évaluées** :

| Option | Pour | Contre | Décision |
|---|---|---|---|
| **DuckDB unique** (avec 7 tables) | Jointures SQL, transactions, RTREE spatial, portable, embarqué | Un seul fichier → risque corruption ; pas de lock NFS fiable | ✅ **Retenu** |
| **Fichiers JSON par artefact** (STAC-like) | Lisible, git-friendly, no dépendance | Pas de jointures, scan O(n) chaque requête | ❌ |
| **SQLite** | Plus répandu que DuckDB | Pas de RTREE natif, colonnes JSON limitées, lent sur analytics | ❌ |
| **Postgres + PostGIS** | Industriel | Trop lourd pour workspace local d'un hydrogéologue | ❌ |
| **intake catalog YAML** | Standard Pangeo | YAML verbeux, pas de transactions, pas de RTREE | ❌ |
| **DVC** | Versioning + remotes | Orienté fichiers Git, pas de requêtes relationnelles | Complément optionnel |

**Argumentation** : DuckDB résout en un seul outil les besoins *requêtes analytiques* (trouver les stations dans un bbox actif en 2020), *transactions* (insertion atomique), *embarqué* (pas de serveur à installer), *portable* (fichier unique). C'est l'équivalent moderne de SQLite pour la data science.

**Mais le schéma actuel (`entries` + `api_coverage`) est insuffisant.** Il faut le refondre.

### 5.2 Schéma DuckDB cible `[REFACTORE]`

```sql
-- workspace/data/cache.duckdb
CREATE SCHEMA IF NOT EXISTS cache;
SET schema 'cache';

-- Table de versionnement du schéma (migration)
CREATE TABLE IF NOT EXISTS _schema_version (
    version       INTEGER PRIMARY KEY,
    applied_at    TIMESTAMP NOT NULL DEFAULT current_timestamp,
    description   VARCHAR,
    hydromodpy_pkg_version VARCHAR
);

-- 1) artifacts : un fichier physique par ligne
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id   UUID       PRIMARY KEY DEFAULT uuid(),
    variable      VARCHAR    NOT NULL,                            -- piezometry, dem…
    provider      VARCHAR    NOT NULL,                            -- hubeau, brgm_50k, custom
    station_id    VARCHAR    NULL,                                -- NULL pour les grilles
    bbox_xmin     DOUBLE     NULL,
    bbox_ymin     DOUBLE     NULL,
    bbox_xmax     DOUBLE     NULL,
    bbox_ymax     DOUBLE     NULL,
    crs_wkt       VARCHAR    NOT NULL,                            -- WKT2, jamais str EPSG libre
    date_start    TIMESTAMP  NULL,                                -- TIMESTAMP, pas VARCHAR
    date_end      TIMESTAMP  NULL,
    frequency     VARCHAR    NULL,                                -- ISO-8601 duration (P1D, PT1H)
    unit          VARCHAR    NOT NULL,                            -- CF unit canonique
    format        ENUM('parquet', 'geoparquet', 'netcdf', 'zarr',
                        'geotiff_cog')     NOT NULL,
    path          VARCHAR    NULL,                                -- relatif à workspace/data/blobs
    status        ENUM('cached', 'empty', 'failed', 'custom')
                             NOT NULL DEFAULT 'cached',
    size_bytes    BIGINT     NULL,
    sha256        VARCHAR    NULL,                                -- 64 hex chars
    created_at    TIMESTAMP  NOT NULL DEFAULT current_timestamp,
    CHECK (status != 'cached' OR (path IS NOT NULL AND sha256 IS NOT NULL))
);

-- Contraintes d'intégrité manquantes au schéma actuel
CREATE UNIQUE INDEX ux_artifacts_key
    ON artifacts(variable, provider, COALESCE(station_id, ''),
                 COALESCE(date_start, TIMESTAMP '1900-01-01'),
                 COALESCE(date_end, TIMESTAMP '2200-01-01'));
CREATE INDEX ix_artifacts_bbox
    ON artifacts USING RTREE(bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax);

-- 2) provenance : lineage complet de chaque artefact
CREATE TABLE IF NOT EXISTS provenance (
    artifact_id       UUID        PRIMARY KEY REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
    source_type       ENUM('http_api', 'custom_file', 'derived') NOT NULL,
    source_url        VARCHAR     NULL,                     -- URL complète de la requête
    source_file       VARCHAR     NULL,                     -- path original si custom
    http_status       INTEGER     NULL,
    http_etag         VARCHAR     NULL,
    request_hash      VARCHAR     NULL,                     -- SHA des params (pour déduplication)
    fetched_at        TIMESTAMP   NOT NULL,
    ttl_days          INTEGER     NOT NULL DEFAULT 30,
    loader_name       VARCHAR     NOT NULL,                 -- HubEauHydrometrySource
    loader_version    VARCHAR     NOT NULL,                 -- git sha ou semver
    pandas_version    VARCHAR     NULL,                     -- traçabilité biblios
    extras            JSON        NULL                      -- pagination, token hash, …
);

-- 3) stations : tableau relationnel distinct pour requêtes cross-variables
CREATE TABLE IF NOT EXISTS stations (
    station_id        VARCHAR NOT NULL,
    provider          VARCHAR NOT NULL,
    variable          VARCHAR NOT NULL,
    station_name      VARCHAR NULL,
    x                 DOUBLE  NOT NULL,
    y                 DOUBLE  NOT NULL,
    z_m               DOUBLE  NULL,
    crs_wkt           VARCHAR NOT NULL,
    active_from       TIMESTAMP NULL,
    active_to         TIMESTAMP NULL,
    metadata          JSON    NULL,
    first_seen_at     TIMESTAMP NOT NULL DEFAULT current_timestamp,
    last_seen_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (station_id, provider, variable)
);

-- 4) coverage : cache de couverture temporelle pour calcul manquant par station
CREATE TABLE IF NOT EXISTS coverage (
    variable          VARCHAR NOT NULL,
    provider          VARCHAR NOT NULL,
    station_id        VARCHAR NOT NULL,
    frequency         VARCHAR NOT NULL,
    period_start      TIMESTAMP NOT NULL,
    period_end        TIMESTAMP NOT NULL,
    row_count         INTEGER NOT NULL,
    completeness_pct  DOUBLE NOT NULL,
    artifact_id       UUID REFERENCES artifacts(artifact_id),
    PRIMARY KEY (variable, provider, station_id, frequency, period_start)
);

-- 5) failures : pour éviter les retry agressifs
CREATE TABLE IF NOT EXISTS failures (
    variable          VARCHAR,
    provider          VARCHAR,
    station_id        VARCHAR,
    period_start      TIMESTAMP NULL,
    period_end        TIMESTAMP NULL,
    error_type        VARCHAR,         -- http_404, empty_response, schema_violation
    error_message     VARCHAR,
    failed_at         TIMESTAMP NOT NULL,
    retry_after       TIMESTAMP NOT NULL,
    fail_count        INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (variable, provider, station_id,
                 COALESCE(period_start, TIMESTAMP '1900-01-01'))
);

-- 6) validation_reports : audit pandera/CF
CREATE TABLE IF NOT EXISTS validation_reports (
    artifact_id       UUID REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
    validated_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    schema_name       VARCHAR NOT NULL,
    schema_version    VARCHAR NOT NULL,
    passed            BOOLEAN NOT NULL,
    errors_json       JSON    NULL,
    PRIMARY KEY (artifact_id, schema_name, validated_at)
);

-- 7) inference_rules : traçabilité des règles d'inférence appliquées
CREATE TABLE IF NOT EXISTS inference_audit (
    sim_run_id        VARCHAR NOT NULL,
    variable          VARCHAR NOT NULL,
    was_explicit      BOOLEAN NOT NULL,
    inferred_from     VARCHAR,               -- 'domain.zone_ids' / 'flow.active_bc'
    planned_at        TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (sim_run_id, variable)
);
```

### 5.3 Requêtes canoniques

```sql
-- Trouver tous les artefacts pour un bassin (~10 ms sur 10k artefacts avec RTREE)
SELECT a.*, p.fetched_at, p.loader_name
FROM artifacts a JOIN provenance p USING (artifact_id)
WHERE bbox_xmin >= 100000 AND bbox_xmax <= 200000
  AND bbox_ymin >= 6000000 AND bbox_ymax <= 6100000
  AND a.status = 'cached';

-- Stations piézo actives en 2020
SELECT station_id, station_name, x, y
FROM stations
WHERE variable = 'piezometry' AND provider = 'hubeau'
  AND active_from <= '2020-01-01'
  AND (active_to IS NULL OR active_to >= '2020-12-31');

-- Artefacts stale à purger
SELECT a.artifact_id, a.path
FROM artifacts a JOIN provenance p USING (artifact_id)
WHERE p.fetched_at + INTERVAL (p.ttl_days) DAY < current_timestamp
  AND a.status = 'cached';

-- Lignage complet d'une simulation (join cache ↔ simulation)
ATTACH 'data/cache.duckdb' AS cache_db (READ_ONLY);
SELECT sim.sim_id, a.variable, a.provider, a.sha256, pr.fetched_at
FROM simulations sim
JOIN provenance sp USING (sim_id)                  -- table côté catalog simulation
JOIN cache_db.cache.artifacts a USING (sha256)
JOIN cache_db.cache.provenance pr USING (artifact_id);
```

### 5.4 Risques de corruption / désynchronisation / migration

| Risque | Mitigation |
|---|---|
| **Corruption multi-processus** | `with conn.begin():` sur toutes les écritures. Documenter que chaque worker HPC a son DuckDB puis merge. |
| **Désynchronisation DuckDB ↔ filesystem** | Commande `hmp data check` qui scanne les deux et rapporte orphans/SHA mismatch. Cron hebdo recommandé sur NFS. |
| **Migration de schéma** | `_schema_version` + `MIGRATIONS: list[tuple[int, str, str]]` dans `data/cache_migrations.py`. Auto-appliqué à l'ouverture. |
| **Perte du DuckDB** | Lockfile `hydromodpy.lock` (YAML) contient SHA-256 + URL + loader_version de chaque artefact : reconstruction possible. |
| **Lock NFS** | Documenter `HYDROMODPY_WORKSPACE=/local/fast_disk` pour usage HPC intensif ; le NFS reste pour les blobs (read-heavy). |

### 5.5 Ce que font les autres projets

| Projet | Choix de stockage d'entrée | Analyse |
|---|---|---|
| **SWAT+** | Fichiers texte structurés (input.std, hru.hru) | Fragile, zéro validation runtime, mais lisible |
| **MODFLOW 6** | Fichiers texte à format fixe (.dis, .npf, .sto) | Auto-portables, pas d'état global, mais pas de catalog |
| **MIKE SHE (DHI)** | Base propriétaire .she | Vendor lock-in, non partageable |
| **GSFLOW (USGS)** | Fichiers texte + contrôle PRMS | Similaire MODFLOW |
| **CWatM (IIASA)** | NetCDF + INI files | CF-compliant, bonne pratique |
| **ParFlow** | PFB (propriétaire) + YAML | Convertisseurs multiples nécessaires |
| **Delft3D** | Fichiers texte + MDU + NetCDF sortie | Acceptable mais touffu |

**Leçon** : aucun outil de modélisation n'a de catalog d'entrées moderne. HydroModPy peut se différencier sur ce point en étant le premier à exposer `hmp data list` SQL-queryable. C'est un **axe concurrentiel réel**.

---

## 6. Reproductibilité — lockfile et provenance

### 6.1 Problème à résoudre

Scénario : un utilisateur exécute `hmp run config.toml` le 2026-04-18. Deux ans plus tard, il exécute le même TOML le 2028-04-18. **Doit-il retrouver exactement les mêmes résultats ?**

Aujourd'hui : **non**. Hub'Eau aura révisé des données, SIM2 aura mis à jour sa réanalyse, BRGM aura publié une v2 de la carte géologique. L'utilisateur obtient un résultat **différent et silencieusement**.

Cible : **oui, via un lockfile + archive de snapshots**.

### 6.2 `hydromodpy.lock` `[NOUVEAU]`

Similaire à `poetry.lock` : fichier YAML co-géré avec `config.toml`, décrit exhaustivement les artefacts utilisés.

```yaml
# ~/hydromodpy/projects/canut/hydromodpy.lock
# AUTO-GÉNÉRÉ — ne pas éditer à la main
version: 1
hydromodpy_pkg: "1.4.2"
generated_at: "2026-04-18T09:31:02Z"
config_sha256: "e2c3a1…"                  # SHA du config.toml à la génération

artifacts:
  - variable: hydrometry
    provider: hubeau
    station_id: K1234001
    period: ["2010-01-01", "2025-12-31"]
    frequency: P1D
    format: parquet
    path: blobs/hydrometry/hubeau/K1234001/20100101_20251231_P1D.parquet
    sha256: "3f2a9e…c01"
    bytes: 412034
    fetched_at: "2026-04-17T14:12:03Z"
    source_url: "https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr?code_entite_hydro=K1234001&date_debut_obs=2010-01-01&date_fin_obs=2025-12-31&size=20000"
    loader: { name: HubEauHydrometrySource, version: "1.4.2" }

  - variable: piezometry
    provider: hubeau
    station_id: BSS002GNSS
    period: ["2018-06-01", "2024-03-15"]
    sha256: "7a1b4f…"
    …

  - variable: dem
    provider: ign
    spatial_key: L93_bbox_350000_6780000_400000_6820000_res25
    sha256: "c4d8e2…"
    …

  - variable: recharge
    provider: sim2
    period: ["2015-01-01", "2024-12-31"]
    format: netcdf
    sha256: "9f3a2b…"
    …

  - variable: piezometry
    provider: custom
    station_id: P01
    sha256: "2b5c9d…"
    source_file: "./my_piezo_network.csv"           # provenance : fichier custom
    source_file_sha256: "1e4f7a…"                   # SHA du fichier source (pas transformé)
```

### 6.3 Workflow lockfile

```bash
# 1) Première exécution : génère hydromodpy.lock
hmp run config.toml
# → si pas de .lock : fetch tout, écrit le .lock, exécute

# 2) Re-exécution stricte : honore le .lock
hmp run config.toml --frozen
# → échoue si un artefact listé dans .lock est absent du cache / SHA mismatch
# → idéal pour CI, revue scientifique, reproduction à 2 ans

# 3) Mise à jour ciblée
hmp lock update --variable recharge
# → ne refetche que la recharge, réécrit .lock

# 4) Archivage long terme
hmp lock archive --to snapshots/canut_2026-04-18.hmp
# → empaquète le .lock + TOUS les blobs référencés dans .hmp (tar.zst)
# → rejouable à 10 ans en extrayant le .hmp

hmp lock restore snapshots/canut_2026-04-18.hmp
# → remet en place le cache + réactive le .lock
```

### 6.4 Versioning / hash / timestamp / provenance

**Règle triple clé de reproductibilité** : chaque artefact porte `(sha256, fetched_at, loader_version)`.

| Niveau | Granularité | Rôle |
|---|---|---|
| **sha256 du contenu** | par artefact | détecte toute mutation bit-à-bit |
| **source_url + request_hash** | par fetch HTTP | permet de rejouer exactement la même requête |
| **loader_version** | par source class (git sha ou semver) | détecte un changement de parsing/normalisation |
| **ttl_days** | par artefact | règle la fraîcheur acceptable sans refetch |
| **fetched_at** | par artefact | ancre temporelle |
| **config_sha256** | par run | détecte une modification de la config |
| **hydromodpy_pkg version** | par lockfile | signale un saut majeur |

### 6.5 Scénarios de validation

**Scénario A — "Même config, même .lock, 3 mois plus tard"**

```
$ hmp run config.toml --frozen
 Loading hydromodpy.lock (v1, 2026-04-18)
 Checking 24 artifacts against cache…
   ✓ hydrometry/hubeau/K1234001 — SHA match
   ✓ piezometry/hubeau/BSS002GNSS — SHA match
   ⋮
 All artifacts verified. Running simulation…
 → Identical output (deterministic solver)
```

**Scénario B — Hub'Eau a révisé 4 stations entre temps**

```
$ hmp run config.toml                          # sans --frozen
 Cache HIT on 22/24 artifacts (TTL not expired)
 Cache STALE on 2 artifacts :
   - hydrometry/hubeau/K1234001  (fetched 97 days ago, TTL=7 days for recent data)
   - piezometry/hubeau/BSS002GNSS (fetched 95 days ago)
 Refetching…
 → 2 artifacts updated, hydromodpy.lock rewritten
 → Running simulation with fresh data
```

**Scénario C — Publication article ESSD, besoin de rejeu à 5 ans**

```
$ hmp lock archive --to canut_ESSD_submission.hmp
 Packaging 24 artifacts + lock + config + LICENSE (EPL-2.0)
 Size : 412 MB compressed (zstd -6)
 → canut_ESSD_submission.hmp ready for DOI upload (Zenodo)

$ # 5 ans plus tard, reviewer reproduit :
$ hmp lock restore canut_ESSD_submission.hmp --to ~/review_canut/
$ cd ~/review_canut/
$ hmp run config.toml --frozen
 → Identical results
```

### 6.6 Limites assumées

- Si une URL source devient **404** à 5 ans, on ne peut pas la refetcher. Le `.hmp` archive **les blobs**, pas seulement les URLs. Utilisateur averti.
- Si la version du **solveur MODFLOW** change, les résultats peuvent différer à epsilon près. Le `.lock` n'inclut pas le SHA de l'exécutable — c'est hors périmètre *data*, à documenter dans le `.hmp` manifest global (déjà prévu dans `architecture_cible/04_storage_ideal.md`).
- La **plateforme** (BLAS, threads) influence les 6e décimales. Les goldens statistiques l'absorbent (`architecture_cible/09_tests_ideaux.md`).

---

## 7. Modèle d'objets Python — squelette complet

### 7.1 Point d'entrée public

```python
# hydromodpy/data/__init__.py   [REFACTORE]
from hydromodpy.data.cache import InputCatalog
from hydromodpy.data.loader import load
from hydromodpy.data.planner import DataPlanner
from hydromodpy.data.lockfile import LockFile
from hydromodpy.data.contracts import LoadResult, PointRecord, FieldRecord, Station

__all__ = [
    "InputCatalog", "load", "DataPlanner", "LockFile",
    "LoadResult", "PointRecord", "FieldRecord", "Station",
]
```

### 7.2 `InputCatalog` (le cœur)

```python
# hydromodpy/data/cache.py   [NOUVEAU]
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Any
import duckdb, hashlib, uuid, json

import pandas as pd, xarray as xr, geopandas as gpd
from pyproj import CRS
from shapely.geometry import box as sbox

from hydromodpy.data.lockfile import LockFile
from hydromodpy.data.common.hashing import sha256_of_file


@dataclass(frozen=True, slots=True)
class CacheKey:
    variable: str
    provider: str
    station_id: str | None
    period: tuple[pd.Timestamp, pd.Timestamp] | None
    bbox_wkt: str | None                       # WKT du polygone d'emprise

    @property
    def request_hash(self) -> str:
        payload = json.dumps(
            {k: getattr(self, k) for k in self.__slots__},
            default=str, sort_keys=True,
        ).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class CacheHit:
    artifact_id: uuid.UUID
    path: Path
    sha256: str
    fetched_at: datetime
    format: Literal["parquet","geoparquet","netcdf","zarr","geotiff_cog"]
    provenance: dict[str, Any]


class InputCatalog:
    """DuckDB-backed cache registry and provenance store."""

    def __init__(self, duckdb_path: Path, blobs_dir: Path):
        self._db_path  = Path(duckdb_path)
        self._blobs    = Path(blobs_dir)
        self._blobs.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._migrate()

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def _migrate(self) -> None:
        from hydromodpy.data.cache_migrations import MIGRATIONS
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM _schema_version"
        ).fetchone()[0]
        for version, desc, sql in MIGRATIONS:
            if version <= cur: continue
            with self._conn.begin():
                self._conn.execute(sql)
                self._conn.execute(
                    "INSERT INTO _schema_version(version, description, "
                    "hydromodpy_pkg_version) VALUES (?, ?, ?)",
                    [version, desc, _pkg_version()]
                )

    def close(self) -> None: self._conn.close()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    # ------------------------------------------------------------------
    # API principale
    # ------------------------------------------------------------------
    def get(self, key: CacheKey, *, ttl_days: int = 30,
            force_refresh: bool = False) -> CacheHit | None:
        if force_refresh: return None
        row = self._conn.execute(
            """
            SELECT a.artifact_id, a.path, a.sha256, a.format,
                   p.fetched_at, p.ttl_days, p.source_url, p.loader_name
            FROM artifacts a JOIN provenance p USING (artifact_id)
            WHERE a.variable = ? AND a.provider = ?
              AND COALESCE(a.station_id,'') = COALESCE(?,'')
              AND a.status = 'cached'
            ORDER BY p.fetched_at DESC LIMIT 1
            """,
            [key.variable, key.provider, key.station_id]
        ).fetchone()
        if row is None: return None
        aid, path_rel, sha, fmt, fetched, ttl, url, loader = row
        full = self._blobs / path_rel
        if not full.exists():
            return None
        actual = sha256_of_file(full)
        if actual != sha:
            return None                              # cache corrompu
        if (datetime.now(tz=timezone.utc) - fetched) > timedelta(days=ttl):
            return None                              # stale
        return CacheHit(
            artifact_id=aid, path=full, sha256=sha,
            fetched_at=fetched, format=fmt,
            provenance={"source_url": url, "loader_name": loader},
        )

    def put(self, key: CacheKey, *,
            payload: pd.DataFrame | xr.Dataset | gpd.GeoDataFrame | Path,
            unit: str, frequency: str | None, crs: CRS,
            source_type: Literal["http_api","custom_file","derived"],
            source_url: str | None, source_file: Path | None,
            loader_name: str, loader_version: str,
            format: Literal["parquet","geoparquet","netcdf","zarr","geotiff_cog"],
            ttl_days: int = 30,
            extras: dict | None = None) -> CacheHit:
        rel_path = self._allocate_path(key, format)
        full = self._blobs / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)

        # 1. Écriture fichier selon format
        self._write_payload(payload, full, format, unit=unit, crs=crs)
        sha = sha256_of_file(full)
        size = full.stat().st_size

        aid = uuid.uuid4()
        bbox = self._compute_bbox(payload, crs)
        date_start, date_end = self._compute_period(payload)

        with self._conn.begin():                    # transaction explicite
            self._conn.execute(
                """INSERT INTO artifacts(artifact_id, variable, provider,
                    station_id, bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax,
                    crs_wkt, date_start, date_end, frequency, unit, format,
                    path, status, size_bytes, sha256)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [str(aid), key.variable, key.provider, key.station_id,
                 *(bbox or [None]*4), crs.to_wkt(),
                 date_start, date_end, frequency, unit, format,
                 str(rel_path), "custom" if source_type=="custom_file" else "cached",
                 size, sha]
            )
            self._conn.execute(
                """INSERT INTO provenance(artifact_id, source_type, source_url,
                    source_file, request_hash, fetched_at, ttl_days,
                    loader_name, loader_version, pandas_version, extras)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [str(aid), source_type, source_url,
                 str(source_file) if source_file else None,
                 key.request_hash, datetime.now(tz=timezone.utc),
                 ttl_days, loader_name, loader_version,
                 pd.__version__, json.dumps(extras or {})]
            )
            self._record_stations(payload, key, crs)

        return CacheHit(artifact_id=aid, path=full, sha256=sha,
                        fetched_at=datetime.now(tz=timezone.utc),
                        format=format,
                        provenance={"source_url": source_url,
                                    "loader_name": loader_name})

    # ------------------------------------------------------------------
    # Helpers (stubs)
    # ------------------------------------------------------------------
    def _allocate_path(self, key, fmt) -> Path: ...
    def _write_payload(self, payload, path, fmt, *, unit, crs) -> None: ...
    def _compute_bbox(self, payload, crs) -> tuple[float,float,float,float] | None: ...
    def _compute_period(self, payload) -> tuple[pd.Timestamp|None, pd.Timestamp|None]: ...
    def _record_stations(self, payload, key, crs) -> None: ...

    # ------------------------------------------------------------------
    # Introspection pour CLI / lockfile
    # ------------------------------------------------------------------
    def list(self, *, variable: str|None=None, provider: str|None=None,
             expired: bool=False) -> pd.DataFrame:
        sql = """
          SELECT a.artifact_id, a.variable, a.provider, a.station_id,
                 a.path, a.sha256, a.size_bytes, a.date_start, a.date_end,
                 p.fetched_at, p.ttl_days, p.loader_name
          FROM artifacts a JOIN provenance p USING (artifact_id)
          WHERE 1=1
        """
        args = []
        if variable: sql += " AND a.variable = ?"; args.append(variable)
        if provider: sql += " AND a.provider = ?"; args.append(provider)
        if expired:
            sql += " AND p.fetched_at + INTERVAL (p.ttl_days) DAY < current_timestamp"
        return self._conn.execute(sql, args).df()

    def to_lockfile(self) -> LockFile: ...
    def prune_expired(self, dry_run: bool=False) -> list[uuid.UUID]: ...
    def check_integrity(self) -> list[dict]: ...
```

### 7.3 `DataSource` Protocol + registre

```python
# hydromodpy/data/sources/base.py   [NOUVEAU, remplace base_manager.py]
from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from pyproj import CRS
from shapely.geometry import base as shp
import pandas as pd

@dataclass(frozen=True, slots=True)
class Extent:
    geometry: shp.BaseGeometry
    crs: CRS

@dataclass(frozen=True, slots=True)
class Period:
    start: pd.Timestamp                # tz-aware UTC
    end: pd.Timestamp

@runtime_checkable
class DataSource(Protocol):
    """One-method protocol. A source loads data for one (variable, provider) pair."""
    name: str
    variable: str
    version: str                        # loader_version

    def fetch(self, extent: Extent, period: Period | None,
              cache: "InputCatalog", **kwargs) -> "LoadResult": ...
```

```python
# hydromodpy/data/sources/registry.py   [NOUVEAU]
from typing import Callable

_SOURCES: dict[tuple[str, str], type] = {}

def register_source(variable: str, name: str):
    def _decorator(cls):
        key = (variable, name)
        if key in _SOURCES:
            raise ValueError(f"Duplicate source registered: {key}")
        _SOURCES[key] = cls
        return cls
    return _decorator

def get_source(variable: str, name: str) -> type:
    try: return _SOURCES[(variable, name)]
    except KeyError:
        avail = sorted(n for v, n in _SOURCES if v == variable)
        raise KeyError(f"No source '{name}' for variable '{variable}'. "
                       f"Available: {avail}")
```

### 7.4 Exemple : source Hub'Eau piézométrie

```python
# hydromodpy/data/sources/hubeau/piezometry.py   [RENOMME depuis variables/piezometry/apis/hubeau.py]
from hydromodpy.data.sources.base import DataSource, Extent, Period
from hydromodpy.data.sources.registry import register_source
from hydromodpy.data.common.http_client import HTTPClient
from hydromodpy.data.cache import CacheKey
from hydromodpy.data.schemas import TimeSeriesSchema
from hydromodpy.data.contracts import LoadResult, PointRecord, Station
from .schemas import HubEauStationPage, HubEauObservationPage

@register_source(variable="piezometry", name="hubeau")
class HubEauPiezometrySource:
    name    = "hubeau"
    variable = "piezometry"
    version = "1.4.2"

    http = HTTPClient(
        base_url="https://hubeau.eaufrance.fr/api/v1/niveaux_nappes",
        timeout=(10.0, 60.0),
        rps_budget=1.0,
    )

    def fetch(self, extent, period, cache, **kw) -> LoadResult:
        stations = self._list_stations_in_extent(extent)
        points = []
        for station in stations:
            key = CacheKey(
                variable="piezometry", provider="hubeau",
                station_id=station.id,
                period=(period.start, period.end) if period else None,
                bbox_wkt=None,
            )
            hit = cache.get(key, ttl_days=7)
            if hit:
                values = pd.read_parquet(hit.path)
            else:
                df = self._fetch_chronicle(station.id, period)
                TimeSeriesSchema.validate(df, lazy=True)
                hit = cache.put(
                    key, payload=df, unit="m_NGF69", frequency="P1D",
                    crs=station.crs,
                    source_type="http_api",
                    source_url=self._chronicle_url(station.id, period),
                    source_file=None,
                    loader_name=type(self).__name__,
                    loader_version=self.version,
                    format="parquet",
                    ttl_days=7,
                )
                values = df
            points.append(PointRecord(
                station=station, values=values["value"], source=self.name,
                unit="m_NGF69", frequency="P1D", sha256=hit.sha256,
            ))
        return LoadResult(points=points)

    def _list_stations_in_extent(self, extent) -> list[Station]: ...
    def _fetch_chronicle(self, sid, period) -> pd.DataFrame: ...
    def _chronicle_url(self, sid, period) -> str: ...
```

### 7.5 Exemple : source custom (fichier utilisateur)

```python
# hydromodpy/data/sources/custom/tabular.py   [NOUVEAU]
from hydromodpy.data.sources.base import DataSource
from hydromodpy.data.sources.registry import register_source

@register_source(variable="piezometry", name="custom")
class CustomPiezometrySource:
    """Active quand config.data.piezometry.source = 'custom'.
    Se contente de relayer un artefact déjà ingéré via hmp data add.
    """
    name = "custom"; variable = "piezometry"; version = "1.4.2"

    def fetch(self, extent, period, cache, **kw) -> LoadResult:
        df_artifacts = cache.list(variable="piezometry", provider="custom")
        if df_artifacts.empty:
            raise DataSourceEmpty(
                "No custom piezometry artifact found. "
                "Run `hmp data add <file> --type piezometry` first."
            )
        points = []
        for row in df_artifacts.itertuples():
            values = pd.read_parquet(row.path)
            station = self._station_from_stations_table(row.station_id)
            points.append(PointRecord(station=station, values=values["value"],
                source="custom", unit=row.unit, frequency=row.frequency,
                sha256=row.sha256))
        return LoadResult(points=points)
```

### 7.6 Fonction `load()` pure

```python
# hydromodpy/data/loader.py   [RENOMME+REFACTORE depuis runtime_loader.py]
from hydromodpy.data.sources.registry import get_source
from hydromodpy.data.cache import InputCatalog
from hydromodpy.data.contracts import LoadResult

def load(variable: str, provider: str, *,
         extent, period, catalog: InputCatalog, **kw) -> LoadResult:
    """Functional entry point. No God class, trivially testable."""
    src_cls = get_source(variable, provider)
    return src_cls().fetch(extent, period, catalog, **kw)
```

### 7.7 CLI `hmp data add`

```python
# hydromodpy/data/cli/data_add.py   [NOUVEAU]
import click, pandas as pd, geopandas as gpd, rioxarray
from pyproj import CRS
from hydromodpy.data.cache import InputCatalog, CacheKey
from hydromodpy.data.schemas import TimeSeriesSchema, StationCollectionSchema
from hydromodpy.data.ingest import detect_format, normalize_to_pivot

@click.command("add")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--type", "variable", required=True,
              type=click.Choice(SUPPORTED_VARIABLES))
@click.option("--crs", help="EPSG:XXXX or WKT. Required for CSV.")
@click.option("--provider", default="custom")
@click.option("--unit", help="Override unit from column name.")
@click.option("--frequency", help="ISO-8601 (P1D, PT1H)")
@click.option("--replace", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--force", is_flag=True,
              help="Ingest despite warnings (NOT errors)")
def add(file, variable, crs, provider, unit, frequency,
        replace, dry_run, force):
    click.echo(f" Detecting format : ...")
    fmt = detect_format(file)

    click.echo(" Reading & validating…")
    df_or_ds = read_and_validate(file, variable=variable, crs=crs, format=fmt)

    click.echo(" Normalising to pivot format…")
    pivot = normalize_to_pivot(df_or_ds, variable=variable, fmt=fmt)

    if dry_run:
        click.echo(" [dry-run] would add :"); return

    with InputCatalog(WORKSPACE/"data"/"cache.duckdb",
                      WORKSPACE/"data"/"blobs") as cat:
        crs_obj = CRS.from_user_input(crs) if crs else pivot.infer_crs()
        for sub_key, sub_payload in pivot.split_by_station():
            key = CacheKey(variable=variable, provider=provider,
                           station_id=sub_key.station_id,
                           period=sub_key.period, bbox_wkt=None)
            cat.put(key, payload=sub_payload, unit=unit or sub_key.unit,
                    frequency=frequency or sub_key.frequency,
                    crs=crs_obj, source_type="custom_file",
                    source_url=None, source_file=file,
                    loader_name="CustomTabularLoader", loader_version=VERSION,
                    format=sub_key.pivot_format, ttl_days=3650)      # TTL long
    click.echo(" ✓ Added")
```

### 7.8 `DataPlanner` simplifié

```python
# hydromodpy/data/planner.py   [REFACTORE]
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True, slots=True)
class DataRequest:
    variable: str
    provider: str
    explicit: bool               # dans le TOML ?
    inferred_from: str | None    # 'domain.zone_ids' / 'flow.active_bc' / None

_INFERENCE_RULES: list[Callable[["HydroModPyConfig"], list[DataRequest]]] = []

def register_inference_rule(fn):
    _INFERENCE_RULES.append(fn); return fn

@register_inference_rule
def _geology_rule(cfg) -> list[DataRequest]:
    if "geology" in cfg.domain.zone_ids:
        return [DataRequest("geology", "brgm_1m", explicit=False,
                            inferred_from="domain.zone_ids")]
    return []

@register_inference_rule
def _stream_rule(cfg) -> list[DataRequest]:
    if "stream" in cfg.flow.active_bc:
        return [DataRequest("hydrography", "bdtopage", explicit=False,
                            inferred_from="flow.active_bc")]
    return []

@register_inference_rule
def _ocean_rule(cfg) -> list[DataRequest]:
    if "ocean" in cfg.flow.active_bc:
        return [DataRequest("oceanic", "shom", explicit=False,
                            inferred_from="flow.active_bc")]
    return []


class DataPlanner:
    def __init__(self, mode: str = "warn"): self.mode = mode

    def plan(self, cfg) -> list[DataRequest]:
        explicit = [DataRequest(v.variable, v.source, explicit=True,
                                inferred_from=None) for v in cfg.data.variables]
        inferred = []
        for rule in _INFERENCE_RULES:
            inferred.extend(rule(cfg))
        merged = self._merge(explicit, inferred)
        if self.mode == "strict":
            self._enforce_strict(merged, cfg)
        return merged
```

---

## 8. Migration depuis l'existant

### 8.1 Tableau de correspondance global

| Artefact actuel | Statut | Cible |
|---|---|---|
| `data/common/base_manager.py` (492 L) | `[K]` | Remplacé par `data/sources/base.py` Protocol (~40 L) |
| `data/common/base_field_manager.py` | `[K]` | Même Protocol |
| `data/runtime_loader.py` | `[RENOMME+REFACTORE]` | `data/loader.py` (fonction `load()` pure) |
| `data/store.py` | `[RENOMME]` | `data/sources/registry.py` |
| `data/planner.py` | `[REFACTORE]` | Règles via décorateur `@register_inference_rule` |
| `data/registry/catalog_duckdb.py` | `[REFACTORE]` | `data/cache.py::InputCatalog` (7 tables, transactions, SHA-256) |
| `data/variables/*/apis/hubeau.py` | `[RENOMME]` | `data/sources/hubeau/<var>.py` |
| `data/variables/*/apis/sim2.py` (9×) | `[K]` | Consolidé en `data/sources/meteofrance/sim2.py` (1 client paramétré) |
| `data/climatic/climatic.py` (618 L) | `[K]` | Supprimé |
| `data/climatic/sim2.py` (932 L) | `[K]` | Supprimé |
| `data/climatic/drias*.py`, `safransurfex.py` | `[K]` | Archivés hors runtime (`archive/legacy/`) |
| `data/geology/*`, `data/hydrometry/*`, `data/piezometry/*`, `data/oceanic/*`, `data/subbasin/*` (dossiers legacy au niveau racine) | `[K]` | Absorbés dans `data/sources/` |
| `data/contracts/timeseries.py::PointRecord` (90 L) | `[REFACTORE]` | `data/contracts/point_record.py` : `values: pd.Series`, `station: Station` |
| `data/contracts/spatial_field.py::FieldRecord` | `[REFACTORE]` | `data/contracts/field_record.py` : `dataset: xr.Dataset` uniquement |
| `data/contracts/location.py::StationLocation` | `[REFACTORE]` | `data/contracts/station.py` : `point: shapely.Point`, `crs: pyproj.CRS` |
| `data/scaffold.py` — `hmp init` dépose `hydrometry_custom_LOC.csv` | `[REFACTORE]` | `hmp init` crée seulement `data/cache.duckdb`, `blobs/`, `projects/` |
| Sentinelles `SENTINEL_EMPTY` / `SENTINEL_CUSTOM` | `[K]` | Remplacées par colonne `status ENUM('cached','empty','custom','failed')` |
| `DataManagers`, `DataManagersRuntimeLoader` | `[K]` | Inlinés dans `loader.load()` |
| Format CSV station `*_LOC.csv` | `[K]` | GeoParquet + DuckDB `stations` |

### 8.2 Ordre des sprints

Cohérent avec `architecture_cible/03_data_contracts.md` (déjà écrit), étendu pour l'API-first + lockfile :

| Sprint | Durée | Contenu | Bloquant levé |
|---|---|---|---|
| **S1** | 1 sem | `http_client.HTTPClient` (backoff/timeout/retry/sha-stream) ; purge `urllib.request.urlretrieve` | Bug réseau P0 (audit) |
| **S2** | 2 sem | `InputCatalog` DuckDB 7 tables + migrations + transactions explicites + SHA-256 | Corruption multi-processus |
| **S3** | 2 sem | `schemas/` (pandera + Pydantic) + contrats `point_record` / `field_record` / `station` refactorés | Validation payloads |
| **S4** | 3 sem | Migration sources : hubeau × 4 (hydro/piézo/wq/onde) → `sources/hubeau/*` avec `DataSource` Protocol | Pattern manager unifié |
| **S5** | 2 sem | Consolidation SIM2 (9 → 1) ; SHOM ; BRGM 1M/50k ; IGN BDAlti | Purge legacy |
| **S6** | 2 sem | CLI `hmp data add/list/remove/prune/check/export/import` | UX custom data |
| **S7** | 1 sem | `LockFile` + `hmp lock update/archive/restore` + flag `--frozen` | Reproductibilité |
| **S8** | 1 sem | Suppression `climatic/`, `subbasin/`, legacy dossiers variables racine | Hygiène |

**Total : ~14 semaines d'un senior Data Engineering. Dette supprimée : ~4 500 lignes. Gain d'UX : massif sur le custom data.**

### 8.3 Script de migration pour les workspaces existants

```python
# hydromodpy/data/migrate_v1_to_v2.py   [NOUVEAU, one-shot]
def migrate(workspace_root: Path) -> None:
    old_db = workspace_root / "data" / "cache.duckdb"
    new_db = workspace_root / "data" / "cache_v2.duckdb"
    blobs_dst = workspace_root / "data" / "blobs"
    blobs_dst.mkdir(parents=True, exist_ok=True)

    old = duckdb.connect(str(old_db), read_only=True)
    rows = old.execute("SELECT * FROM entries").fetchall()

    with InputCatalog(new_db, blobs_dst) as cat:
        for row in rows:
            # 1) déplacer le fichier sous blobs/ structuré
            # 2) calculer SHA-256 (manquant dans v1)
            # 3) insérer dans artifacts + provenance (forge source_url=None,
            #    source_type='http_api' ou 'custom_file' selon is_custom)
            ...
    # Backup de l'ancien
    old_db.rename(workspace_root/"data"/"cache_v1.backup.duckdb")
    new_db.rename(old_db)
```

---

## 9. Conclusion

### 9.1 Invariants du design

Trois règles qui résument tout :

1. **Un seul point d'ingestion — `InputCatalog.put()`** — qu'on fetche une API ou qu'un utilisateur dépose un fichier, le chemin est identique. Provenance, SHA-256, validation, format pivot : mêmes étapes.
2. **Trois clés de reproductibilité — `(sha256, fetched_at, loader_version)`** — stockées dans `provenance`, exportées dans `hydromodpy.lock`, archivables en `.hmp`. Permet un rejeu à 5 ans avec preuve.
3. **Zéro format propriétaire, zéro convention implicite** — le format pivot est imposé par type de géométrie (COG, GeoParquet, CF-NetCDF, Parquet). L'utilisateur ne range jamais de fichiers à la main ; le système le fait pour lui via `hmp data add`.

### 9.2 Ce qu'on élimine

- **~4 500 lignes** de code legacy (`climatic/`, `base_manager.py`, dossiers racine variables).
- **5 anti-patterns** : `urllib.request.urlretrieve` sans timeout, `resp.json()` nu, `SENTINEL_CUSTOM` stringly-typed, invalidation par `mtime`, sentinelles dans un champ `path NOT NULL`.
- **2 formats maison** : CSV `*_LOC.csv` et CSV chronique `_YYYYMMDD_YYYYMMDD_D.csv`.
- **2 registres en doublon** : `store.py` + `runtime_loader.py`.

### 9.3 Ce qu'on gagne

- **UX dramatiquement simplifiée** : `hmp data add my_wells.csv --type piezometry` remplace l'apprentissage de la convention de dossiers et du format CSV `_LOC`.
- **Reproductibilité de niveau publication scientifique** : `.lock` + `.hmp` permettent de soumettre à ESSD/HESS avec un artefact rejouable.
- **Robustesse réseau industrielle** : `HTTPClient` unique avec backoff 429, timeout, validation Pydantic des payloads Hub'Eau.
- **Requêtes SQL puissantes** sur le catalog d'entrée : *« quelles stations piézo custom ont plus de 5 ans de couverture dans le bassin X ? »* en une requête, aujourd'hui impossible.
- **Mutualisation multi-utilisateurs HPC** : un seul `~/hydromodpy/data/` partagé via NFS ; cache chaud réutilisé.
- **Alignement écosystème Pangeo / OGC** : `xr.open_zarr()`, `gpd.read_parquet()`, pandera, CF-1.11. Zéro adapter à écrire pour un chercheur externe.

### 9.4 Compromis assumés

- **DuckDB est un fichier unique** : sur NFS, pas de lock multi-processus fiable. Mitigé en recommandant `HYDROMODPY_WORKSPACE=/scratch/local` pour l'écriture HPC, NFS pour les blobs en lecture.
- **Le lockfile est optionnel** : si l'utilisateur ne l'ingère pas dans `git`, il ne reprodurira rien. On ne peut pas forcer, on peut seulement fournir un warning à la première exécution.
- **Une API qui disparaît à 5 ans ne peut pas être refetchée** : d'où l'importance du `.hmp` archive qui contient les blobs, pas seulement les URLs.
- **Un utilisateur qui modifie manuellement un fichier dans `blobs/`** cassera le SHA-256. Détecté et rapporté par `hmp data check`, jamais masqué.

### 9.5 Positionnement final

Cette architecture n'est **pas plus complexe** que l'existant — elle est **mieux structurée**. Elle s'aligne sur des standards externes (CF, GeoParquet, OGC) plutôt que d'en inventer. Elle donne à HydroModPy ce qu'aucun autre outil de modélisation hydrogéologique n'offre aujourd'hui : un **catalog d'entrées SQL-queryable avec lockfile et provenance signée**.

Pour l'hydrogéologue, c'est *« je dépose mon CSV, le système s'occupe du reste »*.
Pour le chercheur en IA, c'est *« un `read_parquet` suffit »*.
Pour le reviewer ESSD à 2 ans, c'est *« j'extrais le `.hmp` et `--frozen`, ça tourne »*.

Trois publics, une architecture.
