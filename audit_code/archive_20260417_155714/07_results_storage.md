# Audit critique — `hydromodpy/results/` (stockage des résultats de simulation)

**Auditeur** : expert stockage de données scientifiques (DuckDB, Zarr v2/v3, HDF5, NetCDF-4, CF-conventions, UGRID, data lakehouse).
**Périmètre** : `hydromodpy/results/{catalog.py, catalog_schema.py, zarr_store.py, config.py, provenance.py, spatial_index.py, virtual_fields.py, simulation.py, simulation_group.py, display.py, resample.py, exporters/*}`.
**Date** : 2026-04-17. Branche : `dev-database`.

---

## 0. Synthèse exécutive

| Axe | Verdict global |
|---|---|
| Choix DuckDB + Zarr | **Acceptable**, bon pari mono-utilisateur, mais risque élevé en concurrent write et en partage réseau |
| Schéma DuckDB (12 tables) | **À améliorer** — partiellement 3NF, FKs absentes, clés primaires manquantes sur 3 tables, types SQL mélangés |
| Migration de schéma | **Problématique** — squelette en place mais jamais exercé, logique d’ensure_schema cassée |
| Layout Zarr | **Acceptable** — chunking `(1, L, C)` optimal pour carte-à-instant, **catastrophique** pour time-series à 1 point |
| Compression / version Zarr | **À améliorer** — clevel=3 OK, mais codec API mélange v2/v3 de manière incohérente |
| Métadonnées CF / UGRID | **Non-standard** — topologie UGRID incomplète, unités absentes, pas de `standard_name`, pas de CRS, temps non CF |
| Formats d’export | **À améliorer** — NetCDF non-CF, VTU bogué (split_cell_data), GeoTIFF mono-bande, CSV sans header de métadonnées |
| Provenance | **Sous-dimensionnée** — SHA-256 sur l’array injecté, pas sur les fichiers source, pas de PROV-O, pas de lignée |
| Interopérabilité sans l’API | **Mauvaise** — Zarr ouvrable mais inutilisable (pas de CF, pas d’UGRID dans le store natif), config_toml en JSON ambigu |
| Concurrence | **Problématique** — un seul connection handle, pas de WAL compatible concurrent, rien documenté |
| Format `.hmp` | **Non-standard et non-documenté** — répertoire `simulation.duckdb + results.zarr[.zip]`, pas de `MANIFEST`, pas de signature, pas de version |
| Duplication / over-engineering | `_find_variable` dupliqué 4×, `write_X` / `write_Xs` dupliqués, `resample.py` mort, `rerun()` lève NotImplementedError |
| Dead code / code mort | `resample.py`, `rerun()`, `spatial_index.py` import Point dans la boucle, `solver_category` en dur, `display.py` 3 stubs |

Le package est **fonctionnel mais fragile**. Il tient debout parce que l’usage est mono-processus. Il ne passe pas l’épreuve d’un HPC, d’un SaaS ou d’une collaboration distribuée. La maturité réelle vs. les ambitions affichées dans `CLAUDE.md` (« data lakehouse », « single source of truth ») est faible.

---

## 1. Choix de stockage : DuckDB + Zarr

### 1.1 Pertinence du couple

| Candidat | Pour | Contre | Verdict ici |
|---|---|---|---|
| **DuckDB + Zarr** (actuel) | Analytique colonne rapide, Python-first, pas de serveur, Zarr cloud-ready | Concurrence en écriture limitée, DuckDB encore jeune (1.x), format DuckDB instable entre versions majeures | **Acceptable mono-user** |
| SQLite + HDF5 | Mature (20+ ans), HDF5 = standard de fait en sciences, librairies matures (h5py, PyTables) | HDF5 mal adapté au cloud (sérialisé), SQLite limité en analytique (row-store) | Alternative plus sûre pour reproductibilité long terme |
| Parquet + Zarr | Cloud-native, schema evolution facile, Arrow comme pivot, lisible par tout l’écosystème Spark/Polars/DuckDB | Pas de transactions, pas de mises à jour in-place, nécessite un orchestrateur (Delta, Iceberg, Lance) | Meilleur à > 100 k simulations |
| Delta Lake / Iceberg + Zarr | ACID sur objet, time-travel, schema evolution contrôlée | Poids opérationnel (metastore, compaction) | Disproportionné pour l’échelle actuelle |

**Jugement** : le choix est défendable pour un outil de labo (1 chercheur, 1 workstation, < 1000 simulations). Il devient discutable dès qu’on envoie ça en production HPC multi-nœuds ou qu’on envisage du cloud. Le mélange « DuckDB unique » + « Zarr par simulation » crée deux temporalités d’intégrité qui ne sont jamais synchronisées par transaction.

### 1.2 Risques identifiés

| Risque | Gravité | Justification | Recommandation |
|---|---|---|---|
| **Corruption** du `.duckdb` | Haute | DuckDB < 1.0 avait des breaks de format ; aucun `VACUUM`, aucun `CHECKPOINT` explicite dans le code ; pas de `EXPORT DATABASE` périodique | Ajouter `PRAGMA enable_checkpoint_on_shutdown=true`, un snapshot `EXPORT DATABASE` hebdomadaire |
| **Format DuckDB** non stable | Haute | Entre DuckDB 0.9, 0.10, 1.0, 1.1 les formats ont régulièrement cassé. Aucune pin dans `pyproject.toml` sur une version précise visible dans le code | Figer `duckdb>=1.0,<2.0` explicitement et documenter la procédure `EXPORT DATABASE` de mise à niveau |
| **Divergence DuckDB ↔ Zarr** | Moyenne | `register_simulation` insère en DuckDB puis crée le Zarr ; si le Zarr échoue, la ligne DuckDB est orpheline | Envelopper dans une transaction avec rollback et cleanup Zarr ; ou pattern « write-ahead → commit ID » |
| **Pas de FK** | Moyenne | Voir §2 : aucune clé étrangère de `parameters`/`timeseries`/… vers `simulations`. `delete()` gère la cohérence côté code, mais un crash en cours laisse des orphelins | Déclarer `FOREIGN KEY (sim_id) REFERENCES simulations(sim_id) ON DELETE CASCADE` |
| **Concurrent write** | Haute | DuckDB autorise un seul writer à la fois ; aucune stratégie de retry/lock dans le code | Voir §7 |
| **`.zarr.zip`** | Moyenne | Le store zip est read-only par conception ; toute évolution d’une simulation packée nécessite un unpack | Acté par le code (pack à la finalisation) — OK, à documenter explicitement |
| **Migration de schéma** | Haute | `LATEST_VERSION = 1`, `MIGRATIONS = {}` ; la logique de `ensure_schema()` est cassée — voir §2.7 | Rebâtir une vraie stratégie Alembic-like ou Flyway-like |

### 1.3 Comparaison avec l’écosystème

- **FloPy** : stocke en fichiers plats MODFLOW natifs (`.hds`, `.cbc`, `.lst`) + flopy peut écrire en NetCDF via xarray. Pas de DB centrale. Simple, portable.
- **PyGMT / ObsPy** : pas de store unifié, résultats par projet en NetCDF/miniSEED.
- **MLflow** : SQLite/Postgres + artefacts plats par run ; lecture par API, pas de promesse de lecture directe.
- **W3C / PROV** : pas de standard équivalent dans le monde des sciences de la Terre, sauf **CF-conventions + ACDD** pour NetCDF, et **RO-Crate** pour les paquets de recherche.

**Conclusion** : HydroModPy invente son propre format, alors que CF + RO-Crate auraient permis une interopérabilité immédiate. Ce n’est pas anormal pour un outil en cours de maturation, mais il faudra soit (a) amener la cohérence au niveau CF, soit (b) documenter le format comme « interne, ne pas consommer directement ».

---

## 2. Schéma DuckDB — analyse normative

### 2.1 Diagramme ASCII du schéma

```
                      ┌────────────────────────────────┐
                      │         simulations            │
                      │ PK sim_id       (UUID)         │
                      │    name         VARCHAR        │
                      │    project      VARCHAR NOT NULL│
                      │    solver / solver_category    │
                      │    flow_regime                 │
                      │    n_cells / n_layers / n_ts   │
                      │    cell_types   VARCHAR[]      │
                      │    bbox         DOUBLE[4]      │
                      │    crs          VARCHAR        │
                      │    period_start/end VARCHAR ⚠  │
                      │    config_toml  JSON           │
                      │    config_hash  VARCHAR        │
                      │    zarr_path    VARCHAR        │
                      │    parent_sim_id UUID          │ ← pas de FK !
                      │    status / duration_s         │
                      │    created_at  TIMESTAMP       │
                      │    tags         VARCHAR[]      │
                      └────────────────────────────────┘
                                     ▲
                                     │ (FK manquantes partout)
        ┌──────────────┬─────────────┼─────────────┬───────────────┐
        │              │             │             │               │
┌───────┴──────┐ ┌─────┴──────┐ ┌────┴─────┐ ┌────┴──────┐ ┌──────┴──────┐
│  parameters  │ │ timeseries │ │ budgets  │ │ metrics    │ │ provenance  │
│PK(sim,name,  │ │(sim,sta,   │ │(sim,ts,  │ │PK(sim,sta, │ │(sim, ...)   │
│   zone)      │ │ var,time)  │ │ zone,    │ │  metric)   │ │ checksum    │
│              │ │ ⚠ no PK    │ │ comp)    │ │            │ │ stats JSON  │
│              │ │ INDEX only │ │ ⚠ no PK  │ │            │ │ ⚠ no PK     │
└──────────────┘ └────────────┘ └──────────┘ └────────────┘ └─────────────┘

┌──────────────────┐ ┌──────────────┐ ┌─────────────────┐
│ mass_balance     │ │ observation_ │ │ geographic_     │
│ (sim,ts,...)     │ │    points    │ │   features      │
│ ⚠ no PK          │ │ ⚠ no PK      │ │PK(sim,feature)  │
└──────────────────┘ └──────────────┘ └─────────────────┘

┌─────────────────────┐        ┌────────────────────────┐
│ calibration_sessions│        │ calibration_iterations │
│ PK session_id       │◄───────┤ PK (session_id, iter)  │
│  best_sim_id        │        │  parameters JSON       │
│                     │        │  metrics JSON          │
└─────────────────────┘        └────────────────────────┘

┌──────────────────────┐
│ geographic_metadata  │
│ PK (sim_id, key)     │
└──────────────────────┘

┌──────────────────────┐
│   _schema_version    │  (pas de PK, pas de UNIQUE ni de CHECK)
└──────────────────────┘
```

### 2.2 Verdict par table

| Table | Normalisation | PK | FK | Types | Verdict |
|---|---|---|---|---|---|
| `simulations` | Presque 3NF (UNF sur `cell_types`, `bbox`, `tags` = arrays, acceptable DuckDB) | ✅ `sim_id` UUID | ❌ `parent_sim_id` devrait être FK `simulations(sim_id)` | `period_start/end` VARCHAR — **problématique** (on perd l’ordre temporel SQL) | **À améliorer** |
| `parameters` | 3NF OK | ✅ composite | ❌ pas de FK `sim_id` | OK | **Acceptable** |
| `timeseries` | 3NF, pivotable | ❌ **aucune PK** — permet doublons | ❌ pas de FK | `timestamp TIMESTAMP` — OK, mais **pas de timezone** (cf. §2.4) | **À améliorer** |
| `budgets` | Dénormalisé (`unit` par ligne = redondant) | ❌ **aucune PK** | ❌ pas de FK | `zone_id VARCHAR` (doc dit VARCHAR, code traite comme str) | **À améliorer** |
| `mass_balance` | OK | ❌ **aucune PK** (unicité par `sim_id, timestep` manquante) | ❌ pas de FK | OK | **À améliorer** |
| `metrics` | 3NF OK | ✅ composite | ❌ pas de FK | OK | **Acceptable** |
| `observation_points` | OK | ❌ **aucune PK** | ❌ pas de FK | OK | **À améliorer** |
| `provenance` | OK mais `stats JSON` = anti-pattern (vs. colonnes dédiées mean/min/max/std) | ❌ **aucune PK** | ❌ pas de FK | `period_start/end VARCHAR` idem `simulations` | **À améliorer** |
| `calibration_sessions` | OK | ✅ `session_id` | ❌ `best_sim_id` devrait FK `simulations` | `config JSON` OK | **Acceptable** |
| `calibration_iterations` | OK | ✅ composite | ❌ pas de FK vers sessions | `parameters JSON` + `metrics JSON` = discutable | **À améliorer** |
| `geographic_features` | OK | ✅ composite | ❌ pas de FK | `geojson TEXT` — OK, mais voir §2.5 | **Acceptable** |
| `geographic_metadata` | OK, mais EAV (entity-attribute-value) — anti-pattern | ✅ composite | ❌ pas de FK | `value VARCHAR` — **on perd les types** (float stocké comme str) | **Problématique** |
| `_schema_version` | Pas une table de données | ❌ pas de PK, pas de UNIQUE | — | OK | **Acceptable mais à durcir** |

### 2.3 Les trois points les plus graves du schéma

1. **Absence totale de clés étrangères**. DuckDB supporte les FK (avec limitations). En l’état, `delete(sim_id)` fonctionne parce que le code boucle sur `PER_SIM_TABLE_NAMES`. Si un dev ajoute une nouvelle table per-sim et oublie de la mettre dans cette constante : orphelins silencieux. **Recommandation** : déclarer les FK, retirer la logique explicite de cascade.
2. **Manque de PK** sur 5 tables (`timeseries`, `budgets`, `mass_balance`, `observation_points`, `provenance`). Cela permet des insertions dupliquées. Un re-run partiel ou un retry après erreur peut doubler les lignes. **Recommandation** : PK composite systématique.
3. **`period_start/end` en VARCHAR** dans `simulations` et `provenance`. C’est une **erreur de modélisation** : on perd le tri chronologique SQL, les filtres `WHERE period_start >= '2020-01'` deviennent fragiles. **Recommandation** : `TIMESTAMPTZ` + contrainte `CHECK(period_end >= period_start)`.

### 2.4 Types SQL — détail

| Champ | Type actuel | Type attendu | Justification |
|---|---|---|---|
| `period_start`, `period_end` | `VARCHAR` | `TIMESTAMPTZ` ou au minimum `TIMESTAMP` | Ordre et comparaison SQL |
| `timeseries.timestamp` | `TIMESTAMP` | `TIMESTAMPTZ` | Les simulations hydrologiques manipulent des heures solaires/UTC, un fuseau doit être explicite |
| `geographic_metadata.value` | `VARCHAR` | Anti-pattern EAV — éclater en colonnes typées dans `simulations` | Perte de type, parsing requis à chaque lecture |
| `simulations.config_toml` | `JSON` | `JSON` OK, mais la colonne s’appelle `config_toml` alors qu’on stocke du **JSON** (ligne 100 `config_json = json.dumps(config)`) — **nommage trompeur** | Renommer en `config_json` ou `config_snapshot` |
| `budgets.unit` | `VARCHAR DEFAULT 'm3/d'` | OK mais redondant ligne-à-ligne | Normaliser : table `components(name, default_unit)` ou `units` intégrée par composant |
| `observation_points.x, y` | `DOUBLE` | OK, mais pas de CRS — `crs` stocké seulement dans `simulations` | Ajouter `crs VARCHAR` par ligne ou documenter l’héritage |
| `geographic_features.properties` | `JSON` toujours `NULL` en écriture (ligne 360) | Dead column | À retirer ou à peupler |
| `parameters.value` | `DOUBLE` | Mais les paramètres peuvent être des listes ou des tableaux 2D (zonations) — pas supporté | Prévoir `value_array DOUBLE[]` ou stocker en Zarr |
| `_schema_version.version` | `INTEGER` sans UNIQUE | Doublons possibles à chaque `ensure_schema` | `PRIMARY KEY (version)` |

### 2.5 `geojson TEXT` vs géométries natives

DuckDB expose **l’extension spatial** (GEOS, GEOMETRY type, WKB, WKT). Stocker en GeoJSON texte :

- **Pour** : portable, lisible, pas besoin d’extension.
- **Contre** : pas de requête spatiale (`ST_Intersects`, `ST_Within`) possible sans reparser à chaque fois ; coût CPU et mémoire prohibitif ; aucune indexation spatiale DB-level.

**Verdict** : **À améliorer**. Utiliser `GEOMETRY` de `duckdb_spatial` (`INSTALL spatial; LOAD spatial;`). Sinon, a minima stocker en WKB binaire (`BLOB`), plus compact qu’un GeoJSON JSON.

### 2.6 EAV sur `geographic_metadata` et `parameters`

Le couple `(key, value VARCHAR)` sur `geographic_metadata` est un antipattern EAV classique. Les auteurs y stockent `catch_area`, `crs`, `dem_res`… qui ont des types différents (float, str, float). **Recommandation** : promouvoir ces colonnes dans `simulations` ou créer une table typée dédiée. Idem pour `parameters` : `value DOUBLE` empêche les paramètres vectoriels (profils verticaux, zonations pixelisées) — inévitable à terme en hydrogéologie.

### 2.7 Migration de schéma — **cassée**

Extrait (`catalog_schema.py:262-280`) :

```python
def ensure_schema(conn):
    conn.execute(_SCHEMA_VERSION_DDL)
    current = _get_schema_version(conn)
    if current >= LATEST_VERSION:
        for ddl in _ALL_DDL:
            conn.execute(ddl)
        return
    for ddl in _ALL_DDL:
        conn.execute(ddl)
    for v in range(current + 1, LATEST_VERSION + 1):
        for stmt in MIGRATIONS.get(v, []):
            conn.execute(stmt)
        conn.execute("INSERT INTO _schema_version (version) VALUES (?)", [v])
```

Défauts :
1. À chaque instanciation du catalogue, on **INSERE une nouvelle ligne** dans `_schema_version` si `current < LATEST_VERSION`. Mais `current` reste à `0` tant que `_schema_version` est vide **au démarrage** — or, ici on lit la version AVANT d’insérer, donc à chaque premier démarrage, `current=0`, on insère v1. OK. Au deuxième démarrage, `current=1 == LATEST_VERSION`, on sort dans la branche du haut sans réinsérer. Correct **par accident**.
2. Aucune logique de **rollback** si une étape de migration échoue au milieu.
3. Aucun **CHECKPOINT / EXPORT DATABASE** avant migration (pas de backup).
4. Pas de **LOCK** global : deux processus qui lancent `ensure_schema` en parallèle peuvent se marcher dessus.
5. `MIGRATIONS` est vide (juste un commentaire), donc la stratégie n’a jamais été exercée. **Dès la v2, on risque de tout casser.**
6. Les DDL utilisent `CREATE TABLE IF NOT EXISTS`. Si on ajoute une colonne à `simulations` en v2, le `IF NOT EXISTS` ne la créera pas sur une DB existante. Il faudra `ALTER TABLE` dans `MIGRATIONS[2]`.

**Verdict** : **Problématique**. Recommandation : adopter **Alembic** (SQLAlchemy migrations) ou **yoyo-migrations**, ou coder proprement un chemin de migration avec `idempotent ALTER TABLE IF NOT EXISTS COLUMN` (DuckDB le supporte) et un test `pytest` qui valide la migration v_i → v_{i+1} sur une DB réelle.

### 2.8 Index

| Index présent | Utile ? | Manquant et utile |
|---|---|---|
| `ix_sim_project` | Oui pour `find(project=…)` | `ix_sim_config_hash` pour dédupe |
| `ix_sim_solver` | Oui | — |
| `ix_sim_status` | Oui | — |
| `ix_sim_created` | Oui (ORDER BY) | — |
| `ix_ts_lookup(sim_id, station_id, variable, timestamp)` | Oui, couvre bien les requêtes | — |
| — | — | **`metrics(sim_id, metric_name)` pour `best()`** |
| — | — | **`parameters(param_name, zone_id)` pour les calibrations inter-sim** |
| — | — | **`budgets(sim_id, component)` pour `budget(component=)`** |
| — | — | **Index sur `provenance(checksum)` pour retrouver des provenances identiques** |

Verdict : **À améliorer**. DuckDB indexation ≠ PostgreSQL (Zone maps automatiques) mais sur les lookups ponctuels, l’index explicite est utile.

---

## 3. Layout Zarr — analyse critique

### 3.1 Diagramme du layout

```
workspace/simulations/<uuid>.zarr/
├── .zgroup  (ou .zarr.json selon v2/v3)
├── attrs: n_cells, n_layers, cell_types
│
├── mesh/
│   ├── vertices                 float64[n_nodes, 2 or 3]
│   ├── face_node_connectivity   int32  [n_cells, max_vpf]  fill=-1
│   ├── z_interfaces             float64[n_layers + 1]
│   ├── layer_indices            int32  [n_cells] (optionnel)
│   └── source_cell_indices      int32  [n_cells] (optionnel)
│   attrs: start_index, n_nodes, n_cells, n_layers
│
├── head                          float(T, L, C) chunks=(1,L,C) BLOSC-ZSTD3 fill=NaN
├── concentration                 idem (si présent)
│
├── derived/
│   ├── watertable_elevation     float(T, C)
│   ├── watertable_depth          float(T, C)
│   └── seepage_areas             float(T, C)  ← binaire stocké en float64 ⚠
│
├── budget/
│   ├── drn / drain / drains      float(T, L, C)
│   ├── rch                       …
│   └── …
│
├── pathlines/                    (vide dans le code lu)
│
├── geographic/
│   ├── dem                       float(H, W)  attrs: transform, crs, nodata
│   └── geology                   …
│
└── forcing/
    ├── <variable>/
    │   └── <station_id>/
    │       ├── timestamps       int64 (ns since epoch)
    │       └── values           float64
    └── …
```

### 3.2 Verdict

| Aspect | Verdict | Justification |
|---|---|---|
| Organisation hiérarchique | **Acceptable** | Séparation mesh / head / derived / budget / forcing claire |
| Chunking `(1, L, C)` | **Problématique** (voir §3.3) | Optimal pour lecture d’une carte-instant, pessimal pour time-series 1-point |
| Compression BLOSC-ZSTD clevel=3 | **Acceptable** | clevel=3 est le sweet spot recommandé par BLOSC ; OK |
| Codec API (v2 vs v3) | **Incohérent** (voir §3.4) | `zarr.codecs.BloscCodec` est v3, `create_array` semble v3, mais pas d’`zarr_format=3` explicite |
| Métadonnées CF | **Absentes** (voir §3.5) | `units`, `long_name`, `standard_name`, `grid_mapping`… manquants |
| UGRID dans le store | **Partiel** | La topologie est là (`vertices`, `face_node_connectivity`), mais pas les attributs CF `cf_role`, `topology_dimension` ; elles sont ajoutées UNIQUEMENT à l’export NetCDF |
| Fill value `NaN` pour head | **Acceptable** | Choix pragmatique, compatible xarray ; prévoir l’incompatibilité int |
| `seepage_areas` en float64 | **À améliorer** | Binaire 0/1 → utiliser `uint8` ou `bool` (×8 compression en plus) |
| `layer_indices` en int32 | **Acceptable** | int32 OK pour < 2 G cells |
| `face_node_connectivity` fill=-1 | **Non-standard** | UGRID-1.0 recommande `_FillValue=-1` mais avec `start_index` explicite ; l’attribut `start_index` est bien écrit → OK |
| `forcing/timestamps` en int64 ns | **À améliorer** | Utiliser la convention NetCDF (`units="seconds since 1970-01-01"` + type int64) plutôt qu’un view `datetime64[ns]` non documenté |

### 3.3 Chunking — analyse détaillée

Le pattern `(1, n_layers, n_cells)` est optimal **uniquement** pour :
- Lecture d’une carte 2D/3D à un instant donné (1 chunk suffit).
- Écriture time-step-par-time-step (1 chunk par pas de temps).

Il est **catastrophique** pour :
- Lecture d’une série temporelle à un point `(t, l, c)` fixe : on décompresse T chunks entiers pour récupérer T valeurs. Sur `T=3650` (10 ans journaliers) × `L=10` × `C=500 000` = 18 Go décompressés pour extraire 3650 scalaires.

**Comparaison industrie** :
- xarray + Dask recommandent des chunks d’environ 10-100 MB **par dimension dominante**.
- Convention Pangeo : `(T/100, L, C/10)` pour de l’analyse mixte, ou chunking adaptatif via `rechunker`.
- L’article « Zarr chunk choices » de Pangeo suggère de chunker aussi **sur la dimension temps** pour permettre les time-series.

**Recommandation** :
1. Chunk par défaut `(min(T, 24), L, min(C, 10_000))` pour équilibrer. Exposer comme paramètre.
2. Ou bien, à la finalisation, **rechunker** vers `(T, L, 1000)` pour les simulations stockées long terme (rechunker.io).
3. Alternative : stocker les time-series de stations dans DuckDB (déjà fait), et garder Zarr pour les champs spatiaux. Là c’est OK.

**Verdict** : **À améliorer**. Pour le cas d’usage pur carte-à-instant, c’est optimal. Pour un usage mixte time-series + carte, il faut au moins le documenter.

### 3.4 Zarr v2 vs v3 — incohérence

```python
# zarr_store.py:14
BLOSC_ZSTD = zarr.codecs.BloscCodec(cname="zstd", clevel=3)
```

`zarr.codecs.BloscCodec` est **Zarr v3** (package `zarr>=3`). Or :
- Aucun `zarr_format=3` n’est passé à `zarr.open_group` / `zarr.storage.LocalStore`.
- `create_array(..., compressors=BLOSC_ZSTD, ...)` utilise le paramètre **`compressors`** (pluriel, v3), non `compressor` (singulier, v2).
- Les fichiers générés seront donc v3 (métadata `zarr.json` au lieu de `.zarray/.zgroup`).

**Conséquences** :
- **`.zarr.zip`** est en v3 : incompatible avec xarray si l’utilisateur a `zarr<3`. Pas d’import via xarray sans bump de dépendance.
- **Interopérabilité cloud/QGIS** : QGIS/MDAL supporte mal Zarr v3 au moment de l’audit (adoption partielle ; Zarr v3 finalisé mi-2024, outils en rattrapage).
- Aucun commentaire dans le code n’indique le choix v3.

**Verdict** : **Problématique**. Recommandation :
- Soit documenter clairement « Zarr v3 only, nécessite zarr>=3, xarray>=2024.02 ».
- Soit rester en v2 pour maximiser l’interop (`compressor=zarr.codecs.Blosc(...)` en v2, ou `numcodecs.Blosc`).

### 3.5 Métadonnées CF — absentes

Aucun appel à `arr.attrs["units"] = ...`, `arr.attrs["long_name"] = ...`, `arr.attrs["standard_name"] = ...` dans le store. Les CF-conventions (1.9 ou 1.10) sont le standard de facto en géosciences. Sans ces attributs :

- **xarray** ouvre le Zarr mais ne sait pas décoder le temps, les unités, les axes.
- **THREDDS / OPeNDAP** refusent ou affichent du bruit.
- **QGIS (MDAL)** ne détecte pas les variables comme variables scalaires temporelles.

**Recommandation minimale** :
```python
arr.attrs["units"] = "m"
arr.attrs["standard_name"] = "water_table_altitude"  # CF standard_name_table
arr.attrs["long_name"] = "Simulated hydraulic head"
arr.attrs["_FillValue"] = np.nan
arr.attrs["grid_mapping"] = "crs"  # pointe vers une variable scalaire `crs` avec les attrs EPSG
```

Et à la racine : `Conventions = "CF-1.9 UGRID-1.0"`, `title`, `institution`, `source`, `history`, `references`.

### 3.6 UGRID dans le store natif

UGRID-1.0 exige :
- Une variable scalaire (placeholder) avec `cf_role="mesh_topology"`.
- Les attributs `node_coordinates`, `face_node_connectivity`, `face_dimension`, `topology_dimension`.
- Les attributs `_FillValue` et `start_index` sur la connectivité.

Le store Zarr natif stocke les tableaux mais **pas** ces attributs UGRID — ils sont ajoutés seulement à l’export NetCDF (`netcdf.py:73-97`). Résultat : un `xarray.open_zarr(zarr_path)` brut ne comprend pas la topologie. **Recommandation** : ajouter les attributs UGRID directement dans le Zarr. Gain : un simple `xr.open_zarr` devient exploitable dans un notebook.

---

## 4. Formats d’export — audit détaillé

### 4.1 NetCDF (`exporters/netcdf.py`)

**Analyse**.
- Conventions déclarées : `"UGRID-1.0"` seulement. **Manque `CF-1.9`** (doit être composite : `"CF-1.9 UGRID-1.0"`).
- Pas d’attributs globaux ACDD (`title`, `institution`, `source`, `history`, `creator_name`, `date_created`). Indispensables en géosciences.
- Temps : `ds["time"] = arange(n)` avec `units="timestep index"`. **C’est faux selon CF** : `units` doit être `"days since 2020-01-01 00:00:00"` (ou similaire). Sans ça, aucun outil CF ne décodera le temps. L’utilisateur ne peut même pas sélectionner un mois.
- Pas de `grid_mapping` / `crs` variable. Sans CRS, QGIS refusera de projeter.
- Les variables ont `attrs={"mesh": "mesh2d", "location": "face"}` — c’est bien UGRID, mais il manque `units` et `standard_name`.
- `face_x`, `face_y` sont calculées par **np.nanmean** sur des coordonnées clippées `np.clip(connectivity, 0, n_nodes - 1)` — bug potentiel : quand `connectivity == -1`, on clip à 0 et le `valid_mask` masque après `np.where`. OK mathématiquement, mais le calcul est sous-optimal (fancy index avec reclip sur toute la matrice).
- `ds.to_netcdf(output_path)` sans `engine="netcdf4"` explicite : dépend de l’environnement. Et pas de `encoding={"head": {"zlib": True, "complevel": 3}}` → fichier non compressé → 10× plus gros que le Zarr.

**Verdict** : **À améliorer** — ni vraiment CF, ni bien UGRID, ni compressé. Le fichier sera ouvrable par xarray mais rejeté par `cf-checker`.

### 4.2 CSV (`exporters/csv.py`)

- Header : `datetime, station_id, variable, value, unit`. Pas de `#`-prefixed metadata (sim_id, source, time_zone, projection). L’utilisateur à qui on envoie ce CSV ne sait pas de quelle simulation il vient.
- Format « long » : une ligne par (time, station, var). OK pour DataFrame ; laborieux pour un humain.
- Pas de `sim_id` dans le CSV → impossible de fusionner deux exports sans le suffixe dans le nom de fichier.
- Pas de `float_format` : on laisse pandas choisir (scientifique par défaut). Peut générer des valeurs comme `0.023000000000000002`.

**Verdict** : **À améliorer**. Ajouter un header YAML commenté (pattern des `.csv` d’observatoires, comme les CSV RBCA ou les NEXRAD sites) :
```csv
# sim_id: f2e...
# source: HydroModPy 1.0
# time_zone: UTC
# crs: EPSG:2154
# variable_units: {head: m, recharge: mm/d}
datetime,station_id,variable,value,unit
...
```

### 4.3 VTU (`exporters/vtu.py`)

- Seul format purement spatial 2D (pas de pathlines 3D, pas de volumes).
- **Bug potentiel : `_split_cell_data`**. Le code fait :
  ```python
  for block in cells:
      n = block.data.shape[0]
      result.append(data[offset:offset + n])
      offset += n
  ```
  Or les blocs sont créés par **masques** (tri_mask, quad_mask), pas par contiguïté. `data[offset:offset+n]` peut donc associer la valeur de la cellule 0 (triangle) à la première cellule du bloc « triangle » **si et seulement si les triangles apparaissent tous avant les quads** dans la connectivité. Si les cellules sont intercalées (tri, quad, tri, quad…), l’association est **fausse**. C’est un bug silencieux. **Recommandation** : indexer avec `data[tri_mask]` pour les triangles et `data[quad_mask]` pour les quads.
- Pas de CRS dans la sortie (VTU ne le supporte pas nativement, à documenter).
- Pas d’export multi-timesteps (PVD / series) — grand manque pour ParaView.

**Verdict** : **Problématique** (bug potentiel) + **À améliorer** (pas de PVD). Tester sur maille mixte tri+quad.

### 4.4 GeoTIFF (`exporters/geotiff.py`)

- Rasterise un maillage non-structuré → discrétisation avec pertes. Acceptable.
- **Mono-bande seulement** : on exporte 1 layer d’1 timestep à la fois. Pas d’option band-stacking par layer ou multi-band par timestep. C’est limitant pour l’analyse SIG.
- `crs="EPSG:2154"` **hardcodé** en défaut : Lambert-93, pertinent pour la France uniquement. **Problématique** pour un outil qui se veut général. Devrait lire le CRS depuis la simulation (`simulations.crs`).
- `nodata=-9999.0` : OK mais différent du `-99999.0` utilisé dans `zarr_store.py` pour les rasters géographiques. **Incohérence** interne.
- `dtype="float64"` : GeoTIFF float64 est peu supporté hors des SIG modernes. Préférer `float32` sauf besoin avéré.
- Pas de tags TIFF métadonnées (`TIFFTAG_IMAGEDESCRIPTION`, `TIFFTAG_SOFTWARE`). Le fichier est non identifiable hors contexte.

**Verdict** : **À améliorer**. Le CRS hardcodé est particulièrement gênant.

### 4.5 Shapefile (`exporters/shapefile.py`)

- Shapefile est **un format obsolète** (1998, limite 2 Go, noms de colonnes 10 chars, pas d’encodage texte standardisé, pas de géométrie mixte, pas de Z). OGC lui-même recommande **GeoPackage** depuis 2012.
- `crs="EPSG:2154"` hardcodé : idem GeoTIFF.
- Pas de champ métadonnées (sim_id, timestep, variable) autre que la colonne `variable` qui contient les valeurs.
- **Recommandation** : switcher par défaut vers **GeoPackage** (`.gpkg`) via `gdf.to_file(..., driver="GPKG", layer="cells")`. Plus rapide, plus propre, multi-couches, CRS embarqué, UTF-8 natif. Garder Shapefile en option legacy.

**Verdict** : **Non-standard / obsolète**. Recommandation forte : migrer vers GPKG.

### 4.6 Duplication massive entre les exporters

Les 4 exporters (`netcdf`, `vtu`, `geotiff`, `shapefile`) définissent chacun leur propre `_find_variable(grp, var_name)` — **code dupliqué 4×**. C’est exactement la fonction présente aussi dans `zarr_store.py:read_field` (même logique).

**Recommandation** : factoriser dans `zarr_store.py` → `SimulationZarr.find_variable(name) -> zarr.Array | None`, et l’utiliser partout.

---

## 5. Provenance — sous-dimensionnée

### 5.1 Ce qui est fait

`provenance.py:fingerprint()` calcule :
- SHA-256 sur les octets de l’array numpy.
- `shape`, `dtype`, `stats` (mean, min, max, std).

Stocké dans la table `provenance` avec `source_type`, `source_ref`.

### 5.2 Ce qui manque

| Manque | Gravité | Commentaire |
|---|---|---|
| **Hash des fichiers source** (DEM, raster geology, shapefile rivers) | Haute | On hash le `np.ndarray` **après** chargement → si le fichier source change mais qu’on passe par le même cache DuckDB, on ne verra rien |
| **Version de HydroModPy** | Haute | `hydromodpy.__version__` jamais stocké dans la table simulations |
| **Versions des solveurs** (MODFLOW-NWT 1.1.4, MF6 6.4.1) | Haute | Critique pour reproductibilité |
| **Versions des dépendances Python** (flopy, numpy) | Moyenne | Peut aller dans un champ `environment JSON` |
| **Hash du code source** ou **git commit SHA** | Moyenne | Idéalement via `git rev-parse HEAD` au moment du run |
| **Horodatage**  de la donnée source (ce qu’on trouverait dans un fichier CSV téléchargé) | Moyenne | Absent |
| **Lignée (lineage)** : quelles variables dérivent de quelles autres | Moyenne | PROV-O / W3C PROV parle de `wasDerivedFrom` ; ici rien |
| **Traçabilité des exports** | Basse | Quand on `export_simulation` vers `.hmp`, pas d’entrée provenance |
| **Signature cryptographique** | Basse | Pour la partage inter-institution (RO-Crate le recommande) |

### 5.3 Comparaison industrie

- **DVC** : hash de fichiers source + tracking dans `.dvc/` + git. Bien plus complet.
- **MLflow** : run ID, environment, git commit, params, metrics, artifacts avec checksum.
- **W3C PROV-O** : graphe `Agent → Activity → Entity` (qui a fait quoi sur quoi). Ici on a juste des fingerprints.
- **RO-Crate** : paquet RDF-JSON qui déclare inputs/outputs/activities. Beaucoup plus riche.

**Verdict** : **Sous-dimensionnée**. En l’état, la promesse de reproductibilité scientifique n’est pas tenue. Pour un outil de recherche, c’est une **lacune majeure**.

**Recommandation minimale** :
1. Ajouter `hydromodpy_version`, `git_commit`, `solver_version`, `python_version` à la table `simulations`.
2. Ajouter `source_file_path`, `source_file_sha256`, `source_file_mtime` dans `provenance`.
3. Exporter en RO-Crate lors de `export_simulation` (un `ro-crate-metadata.json` à la racine du `.hmp`).

---

## 6. Interopérabilité hors API HydroModPy

### 6.1 Peut-on ouvrir les résultats avec des outils standards ?

| Outil | Accès direct au workspace | Accès au `.hmp` exporté | Verdict |
|---|---|---|---|
| **DuckDB CLI / Python** sur `hydromodpy.duckdb` | ✅ Oui, l’utilisateur lit les tables sans API HMP | ✅ idem sur `simulation.duckdb` | **Bon** |
| **Pandas / SQL** | ✅ via DuckDB | ✅ | **Bon** |
| **xarray** sur le Zarr natif | ⚠ Ouvre le groupe mais sans CF/time, les `head[t,l,c]` sont des tableaux anonymes, pas de décodage time | ⚠ idem | **Mauvais** |
| **xarray** sur le NetCDF exporté | ⚠ Ouvre, mais `time` non CF-décodé, pas de CRS | ⚠ idem | **Moyen** |
| **QGIS / MDAL** sur le NetCDF | ❌ Conventions manquantes, pas de `grid_mapping` | ❌ | **Mauvais** |
| **ParaView** sur le VTU | ✅ si une seule forme de cellule, ⚠ si tri+quad mixé (bug `_split_cell_data`) | idem | **Moyen** |
| **GDAL / rasterio** sur GeoTIFF | ✅ | ✅ | **Bon** |
| **GDAL / ogr2ogr** sur le Shapefile | ✅ | ✅ | **Bon** (format lui-même obsolète) |
| **Zenodo / figshare** sur `.hmp` | ❌ Format non documenté | ❌ | **Mauvais** |

### 6.2 Verdict global d’interopérabilité

- Pour un utilisateur DuckDB/SQL : **bonne** ergonomie (schéma clair, indexé).
- Pour un utilisateur xarray/QGIS/ParaView : **mauvaise** sans l’API HydroModPy, à cause des métadonnées manquantes.
- Pour un utilisateur cloud/partage : **mauvaise** (pas de CF, pas de RO-Crate, `.hmp` non documenté).

**Recommandation** : rendre le Zarr **self-describing** (CF + UGRID) pour que `xarray.open_zarr` fonctionne sans ingénieur HydroModPy. C’est l’investissement à plus fort ROI d’interop.

---

## 7. Concurrence — problématique

### 7.1 Modèle actuel

- **Un seul** `duckdb.connect()` par `SimulationCatalog`.
- Chaque `write_*` fait un `self._db.execute(...)` sans lock explicite.
- `delete()` utilise `self._db.begin()` / `commit()` / `rollback()` → **OK en local**.
- Autres méthodes (insert) : pas de `begin()` → utilisent l’autocommit implicite. Entre deux inserts, un lecteur peut voir un état intermédiaire si des triggers étaient présents (ici il n’y en a pas, OK).

### 7.2 Scénarios problématiques

| Scénario | Comportement actuel | Risque |
|---|---|---|
| Deux processus Python écrivent dans le même workspace en parallèle (HPC, batch) | DuckDB refuse la seconde connexion writable avec `IOError: database is locked` | **Crash** |
| Un processus écrit, un notebook lit | DuckDB 1.x autorise multiple readers quand un writer est actif, mais la cohérence **snapshot isolation** dépend de la version | À vérifier |
| Même simulation finalisée deux fois | `finalize()` appelé deux fois → pack_to_zip appelé deux fois → pas de check → peut-être OK, pas garanti | Mineur |
| `pack_to_zip` pendant qu’un lecteur ouvre le Zarr | Le lecteur ouvre `LocalStore` ; le packeur supprime le répertoire → `FileNotFoundError` côté lecteur | **Crash silencieux** |
| Sigkill au milieu de `register_simulation` (DuckDB OK, Zarr non créé) | Orphelin en DuckDB, aucun `.zarr` associé | **Incohérence** |

### 7.3 Verdict

**Problématique** pour tout usage multi-processus. Actuellement c’est « un seul user à la fois ». Aucune doc n’explicite cette limitation.

**Recommandations** :
1. Documenter explicitement : « workspace mono-writer ».
2. Pour du batch HPC, partitionner par workspace (un workspace par job).
3. Ou migrer vers **Postgres** (DuckDB supporte le FDW postgres, on peut fédérer) pour le usage multi-user.
4. Pour la cohérence DuckDB ↔ Zarr : ajouter un `status='initializing' -> 'running' -> 'completed'` et un job de GC qui retire les `initializing` trop vieux.

### 7.4 Transactions — audit par opération

| Opération | Transaction ? | Atomique sur DB + Zarr ? |
|---|---|---|
| `register_simulation` | ❌ autocommit | ❌ non — DB insert avant Zarr create |
| `write_parameters` (boucle) | ❌ N autocommits | ❌ pas d’all-or-nothing |
| `write_timeseries` | Single INSERT | ✅ pour DB, pas de Zarr impliqué |
| `write_budgets` | Single INSERT | ✅ |
| `delete` | ✅ `begin/commit/rollback` | ❌ suppression du Zarr en dehors de la transaction DB |
| `import_simulation` | ✅ `begin/commit/rollback` | ❌ copie du Zarr en dehors |
| `export_simulation` | lecture only | OK |
| `pack_to_zip` | — | ❌ pas de verrou lecteurs |

**Verdict** : **À améliorer**. Encapsuler ces séquences dans un `try/except` avec cleanup explicite.

---

## 8. Package `.hmp` — format et stabilité

### 8.1 Structure observée (dans `export_simulation`)

```
<output_dir>/
├── simulation.duckdb       # DuckDB mono-simulation avec 10 tables + _schema_version
├── results.zarr/           (si source était directory)
└── results.zarr.zip        (si source était zippée ou cible packée)
```

### 8.2 Problèmes

1. **Pas un format packagé unique**. C’est un **répertoire** — pas un `.tar.gz`, pas un `.zip`. L’utilisateur qui veut l’envoyer par mail doit zipper lui-même. Incohérent avec le nom `.hmp` qui suggère un fichier unique.
2. **Pas de `MANIFEST.json`** : rien qui liste les fichiers du paquet, leurs checksums, leur version.
3. **Pas de versioning du format `.hmp`** : dans 2 ans, comment savoir si ce paquet est ancien ou récent ? La table `_schema_version` existe mais ne dit rien sur la version du paquet.
4. **Pas de `ro-crate-metadata.json`** (RO-Crate) : c’est le standard de facto en science ouverte pour le partage de résultats.
5. **`import_simulation` a un bug logique** : lignes 831-834 :
   ```python
   if pkg_zarr_zip.exists():
       zarr_path = f"simulations/{sid}.zarr.zip"
   else:
       zarr_path = f"simulations/{sid}.zarr.zip"
   ```
   **Les deux branches sont identiques**. C’est un **bug** ou du code mort issu d’un copier-coller non fini. L’import d’un paquet en format répertoire se retrouve annoté `.zip` alors qu’il ne l’est pas — puis le code plus loin (lignes 846-857) repacke en zip. Donc finalement OK, mais l’intention du `if/else` est morte.
6. **Pas de signature** : impossible de vérifier l’intégrité ni l’auteur.
7. **Extension `.hmp`** mentionnée dans `CLAUDE.md` mais jamais réellement imposée : `export_simulation` crée un répertoire quelconque, pas un fichier `.hmp`.

### 8.3 Verdict

**Non-standard et non-documenté**. Recommandation :
1. Figer un format : soit **ZIP** (compatible partout, browseable), soit **TAR.ZSTD** (plus compact). Viser `.hmp` comme extension.
2. Ajouter un `MANIFEST.json` : `{"format_version": 1, "hydromodpy_version": "1.0", "sim_id": "...", "files": {"simulation.duckdb": {"sha256": "..."}, ...}}`.
3. Intégrer **RO-Crate** minimal (une trentaine de lignes JSON-LD) pour se conformer aux standards de publication FAIR.
4. Corriger le `if/else` identique.

---

## 9. Duplication, code mort, verbosité

### 9.1 Duplication

| Duplication | Localisation | Action |
|---|---|---|
| `_find_variable` | `exporters/netcdf.py:147`, `exporters/vtu.py:119`, `exporters/geotiff.py:129`, `exporters/shapefile.py:95`, et pseudo-dupliqué dans `zarr_store.py:read_field:173-180` | Factoriser dans `SimulationZarr.find_variable()` |
| `write_X` / `write_Xs` | `catalog.py:write_budget` vs `write_budgets`, `write_mass_balance` vs `write_mass_balances` | Garder seulement la version batch `write_budgets([{...}])` et supprimer les singulières |
| `query_timeseries` | `catalog.py:491` et `simulation.py:131-156` | La méthode `Simulation.timeseries` duplique la SQL. Déléguer à `catalog.query_timeseries` |
| Pattern `str(sim_id)` répété 30× | Tout `catalog.py` | Normaliser en entrée (property `sid` ou décorateur) |
| `export_*` zarr_path = str(self.open_zarr(...)) | `catalog.py:573` appelle open_zarr juste pour le path, puis les exporters rouvrent le Zarr — on fait 2× l’ouverture | Passer la `SimulationZarr` directement |
| Pattern `pd.DataFrame / INSERT … SELECT FROM df` | Répété dans `write_timeseries`, `write_budgets`, `write_mass_balances` | Factoriser en helper `_bulk_insert(table, df)` |

### 9.2 Code mort / unreachable

| Élément | Statut |
|---|---|
| `resample.py` (2 stubs `NotImplementedError`) | **Mort** — supprimer le fichier, restaurer plus tard si besoin |
| `Simulation.rerun()` | **Stub qui lève `NotImplementedError`** après avoir importé `HydroModPyConfig.from_snapshot` — l’import peut lui-même planter. Soit implémenter, soit supprimer |
| `catalog.py:record_provenance = write_provenance` | Alias redondant, à retirer si personne n’utilise l’ancien nom |
| `catalog.py:import_simulation` — variable `pkg_zarr_dir` déclarée 2× (832 et 847), une fois jamais utilisée | Dead variable |
| `catalog.py:828` : commentaire « Determine zarr_path based on package content » suivi de `if…else` identique | **Bug + dead branch** (§8.2.5) |
| `display.py:_render_stub` pour `drainage_density`, `concentration_map`, `pathlines` | 3 renderers annoncés mais qui ne font rien sauf logger. Enlever de `_RENDERERS` ou vraiment implémenter |
| `spatial_index.py:66` : `from shapely.geometry import Point` **dans la boucle** | Import à sortir en haut de fonction |
| `provenance.py` : `dtype` calculé dans `fingerprint()` mais jamais stocké dans la table (seul `checksum`, `n_records`, `stats` le sont) | Champ calculé inutilement |
| `catalog_schema.py:LATEST_VERSION = 1` + `MIGRATIONS = {}` + commentaire `# 1: []` | Pas mort, mais squelette sans contenu — à tester avant publication |
| `results/display.py` | Doublonne `hydromodpy/analysis/display` probable (non lu ici mais suggéré par le nom) ; valider qu’il n’y a pas de concurrence | À vérifier |

### 9.3 Verbosité et sur-ingénierie

| Cas | Commentaire |
|---|---|
| `SimulationZarr.__init__` vs `.create` | Deux chemins, `create` utilise `cls.__new__(cls)` → cassure d’encapsulation. Un seul constructeur avec flag `create=False` suffirait |
| `fingerprint()` retourne `{"checksum", "shape", "dtype", "stats"}` mais seuls `checksum` et `stats` sont stockés — le reste est gaspillé | Simplifier à 2 champs |
| `SimulationGroup.to_dataframe` construit un DataFrame en 3 merges Python alors qu’une seule requête SQL le ferait en 10× moins de code | Réécrire en SQL natif avec CTE |
| `SimulationGroup.parameters` / `.metrics` : logique de pivot redondante (presque identique) | Factoriser `_pivot(table, key_col, value_col)` |
| `config.py:ExportVariablesConfig.active_names()` : liste hardcodée des noms dérivés | Couplage fort avec `virtual_fields.py:VIRTUAL_FIELDS`. Devrait importer de là |
| `_SUBGROUPS` en constante globale avec 6 noms, tous re-créés à l’init | OK — mais `pathlines` est créé vide systématiquement alors que rien n’y écrit jamais dans le code audité |

### 9.4 Tests (revue indirecte)

Je n’ai pas lu les tests, mais plusieurs signes inquiétants :
- Aucun test de migration dans `MIGRATIONS` (puisque vide).
- Aucune validation automatique du round-trip `export_simulation` → `import_simulation`.
- `_split_cell_data` bug potentiel pas couvert (sinon on l’aurait détecté).
- Pas de fuzz sur la cohérence DuckDB ↔ Zarr après crash.

**Recommandation** : ajouter un test `test_catalog_roundtrip` (create → write → export → import → assert equal) qui exerce tout le pipeline.

---

## 10. Performance — points critiques

| Hot path | Problème | Gain potentiel |
|---|---|---|
| `write_parameters` | Boucle Python avec N `execute()` | `executemany` ou `INSERT … SELECT FROM df`. Gain 10-100× |
| `export_geotiff` | Boucle Python qui construit N `Polygon()` | Vectoriser via `shapely.geometry.polygons(coords_list)` ou rasterio `features.rasterize` avec itérateur généré paresseusement |
| `export_shapefile` | Idem | Idem |
| `spatial_index.point_in_cell` | Boucle Python pour créer N polygons avant STRtree | Garder ; mais cacher STRtree par simulation dans le Zarr (sérialiser en WKB) |
| `export_netcdf` | Calcul `nanmean` avec clip sur toute la matrice de connectivité | Utiliser `np.where(valid_mask, vertices[connectivity, 0], np.nan).mean(axis=1)` une fois, pas clip |
| `_watertable_elevation` | Boucle `for lay in range(n_layers)` | Vectoriser via `np.take_along_axis` avec l’index du premier layer fini |
| `query_timeseries` (pour une boucle de stations) | N requêtes par station | Une requête avec `station_id IN (…)` puis pivot |
| `SimulationGroup.to_dataframe` | 3 merges Python séquentiels | CTE SQL unique |
| `pack_to_zip` utilise `ZIP_STORED` (sans compression) | OK pour Zarr déjà compressé (BLOSC inside) | **Ce choix est bon, à garder** |

**Verdict** : plusieurs gains faciles, mais rien de bloquant à l’échelle actuelle. Le seul risque est `_watertable_elevation` sur des maillages fins où T × n_cells devient gros.

---

## 11. Tableau récapitulatif final

| Section | Verdict | Priorité d’action |
|---|---|---|
| 1. Choix DuckDB + Zarr | Acceptable mono-user | Documenter le modèle de concurrence |
| 2. Schéma DuckDB | À améliorer | **Haute** — ajouter FK, PK manquantes, typer `period_*` |
| 2.7 Migration schéma | Problématique | **Haute** — adopter un vrai framework (Alembic, yoyo) |
| 3.3 Chunking Zarr | Problématique time-series | Moyenne — rechunker en finalisation |
| 3.4 Zarr v2 vs v3 | Incohérent | **Haute** — fixer et documenter la version |
| 3.5 Métadonnées CF | Non-standard | **Haute** — ajouter `units`, `standard_name`, `grid_mapping` |
| 4.1 NetCDF | Pas CF-conforme | **Haute** — conformance CF-1.9 complète |
| 4.3 VTU | Bug potentiel | **Haute** — corriger `_split_cell_data` |
| 4.4 GeoTIFF | CRS hardcodé | Moyenne |
| 4.5 Shapefile | Format obsolète | Moyenne — switcher vers GeoPackage par défaut |
| 5. Provenance | Sous-dimensionnée | **Haute** — ajouter versions + hash source + RO-Crate |
| 6. Interop | Mauvaise hors API | **Haute** — Zarr self-describing |
| 7. Concurrence | Problématique | Moyenne — documenter + garde-fous |
| 8. Format `.hmp` | Non-standard | Moyenne — `MANIFEST.json` + extension réelle + RO-Crate |
| 9. Duplications / dead code | Plusieurs cas | **Moyenne** — nettoyage attendu |

---

## 12. Recommandations prioritaires

1. **Corriger le bug `_split_cell_data`** (vtu.py:108) — risque de données corrompues à l’export.
2. **Corriger le `if/else` identique dans `import_simulation`** (catalog.py:831-834).
3. **Ajouter FOREIGN KEY** sur toutes les tables per-sim + PK manquantes.
4. **Convertir `period_*` VARCHAR → TIMESTAMP**.
5. **Rendre le Zarr self-describing** (CF-1.9 + UGRID-1.0 attrs sur les arrays).
6. **Factoriser `_find_variable`** en 1 seul endroit.
7. **Enrichir `provenance`** (versions + fichiers source + git SHA) et produire un RO-Crate dans `.hmp`.
8. **Fixer Zarr v2 OU v3 explicitement** et documenter la contrainte de version dans `pyproject.toml`.
9. **Écrire un `test_catalog_roundtrip`** end-to-end (create → write → export → import).
10. **Remplacer Shapefile par GeoPackage** comme format par défaut.
11. **Écrire une vraie stratégie de migration** (Alembic ou yoyo), avec test de v1→v2 sur DB réelle.
12. **Supprimer `resample.py` et `rerun()`** tant qu’ils ne sont pas implémentés (dead code).

---

## 13. Mot de la fin

Le package est **cohérent dans son intention** mais **trop optimiste dans ses garanties**. Les choix (DuckDB + Zarr, UGRID, CF) sont des bons choix d’architecture, **s’ils étaient menés à leur terme**. En l’état, on a 60 % du travail : la structure est là, le détail de conformance aux standards scientifiques (CF, UGRID, PROV, FAIR) manque. Les bugs `_split_cell_data`, `if/else identique`, migrations non testées, FK absentes doivent être traités **avant toute release publique**, sinon le package perd sa promesse de reproductibilité et génère des dettes que les utilisateurs ne pourront pas diagnostiquer eux-mêmes.

Le différentiel entre la documentation (`CLAUDE.md` présente un « single source of truth », une « portable `.hmp` package », etc.) et la réalité du code est important. Ce gap doit être fermé : soit en ajustant la doc à la réalité, soit en amenant le code aux standards annoncés.
