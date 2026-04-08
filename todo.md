# Audit Architectural — HydroModPy v0.3.5

**Date :** 2026-04-07
**Branche :** `dev-database`
**Périmètre :** 670 fichiers `.py` (package principal) · 233 fichiers de tests · 23 fichiers launchers · `hydromodpy_annex/`

---

### Directives de refactoring

> **REGLE 1 — Pas de backward compatibility.**
> Tout code passerelle, façade de compatibilité, migration legacy, alias deprecated, ou ré-export "pour ne pas casser" doit être **supprimé**, pas maintenu. On veut uniquement le vrai code. Casser l'existant est acceptable — on est sur une branche de restructuration.

> **REGLE 2 — `solver/modflow6/` : ne pas toucher.**
> Le module Modflow6 (1 500 lignes, God class) est constaté mais n'est pas prioritaire. Il fonctionne. Le refactoring de ce module est reporté à une phase ultérieure.

> **REGLE 3 — Supprimer tout code de migration SQLite→DuckDB.**
> Le code de migration automatique depuis l'ancien catalog SQLite (`catalog.db`) vers DuckDB n'a plus de raison d'être. Supprimer la migration et le code de détection legacy dans `catalog_duckdb.py`. Seul le schéma DuckDB natif doit rester.

> **REGLE 4 — Claude ne fait aucun commit.**
> Les commits sont exclusivement réalisés par l'utilisateur. Claude ne doit jamais exécuter `git commit`, `git push`, ou toute commande git qui modifie l'historique, sauf demande explicite contraire.

---

## 1. Vue d'ensemble architecturale

### Diagnostic

L'architecture émergente est un **pipeline en couches (layered pipeline)** avec orchestration TOML-driven et des traces de pattern hexagonal (ports/adapters) dans la couche simulation. Six couches logiques se dégagent :

```
┌──────────────────────────────────────────────────────────┐
│  CLI / Launchers         (launchers/, __main__.py)       │  Orchestration
├──────────────────────────────────────────────────────────┤
│  Simulation              (simulation/)                   │  Planning + Execution
│    Planning → Runner → Adapters → Results Extractors     │
├──────────────────────────────────────────────────────────┤
│  Process                 (process/)                      │  Domaine métier
│    Flow, Transport, Hydrology                            │
├──────────────────────────────────────────────────────────┤
│  Solver                  (solver/)                       │  Intégration FloPy
│    Modflow6, ModflowNWT, Boussinesq                     │
├──────────────────────────────────────────────────────────┤
│  Spatial                 (spatial/)                      │  Domaine géographique
│    Geographic, Domain, Field, Mesh                       │
├──────────────────────────────────────────────────────────┤
│  Data + Results          (data/, results/)               │  I/O & Persistance
│    Catalog DuckDB, Managers, ResultStore (DuckDB+Zarr)   │
├──────────────────────────────────────────────────────────┤
│  Core                    (core/)                         │  Infrastructure
│    Config, State, Workspace, Units, Time, Backends       │
└──────────────────────────────────────────────────────────┘
```

**Flux de données principal :**

```
TOML → HydroModPyConfig (Pydantic) → SimulationPlan (frozen)
  → SimulationRunner → SolverAdapter.execute(RunContext)
  → Solver.pre/process/post → ResultStore (DuckDB + Zarr v3)
```

**Carte des dépendances réelles (sens du flux d'import) :**

```
core ← spatial ← process
             ↖         ↘
              solver ←──┘
                ↑
          simulation (adapters, planning, runner)
                ↑
           launchers (orchestration top-level)

data ←→ results (persistance DuckDB + Zarr)
  ↕         ↕
core       core
```

**Points clés :**

- `core/` ne dépend de rien — fondation correcte.
- `process/` ne dépend PAS de `spatial/` ni de `solver/` — excellente isolation.
- `solver/` dépend de `spatial/` et `process/` — attendu et one-way.
- `simulation/adapters/` fait le pont Process ↔ Solver via un Protocol `SolverAdapter`.
- `launchers/` dépend de tout — attendu pour l'orchestration, mais contient trop de logique domaine.
- Pas de dépendances circulaires détectées grâce au lazy loading et aux guards `TYPE_CHECKING`.
- Règle one-way `hydromodpy_annex/ → hydromodpy/` respectée (vérifié par grep).

### Problèmes critiques 🔴

**`HydroModPyLauncher` est un God Object**
- Fichier : `launchers/process_simulation/launcher.py` — 777 lignes, 50+ méthodes
- Mélange orchestration, logique domaine (spatial supports, data inference, mesh resolution), et gestion d'état
- Point de couplage le plus fort du projet : importe 20+ modules domaine (lignes 54-90)
- Les méthodes `_run_setup()` (52 lignes), `_build_domain_spatial_supports()` (40 lignes) et `run()` (60 lignes) contiennent de la logique métier qui devrait être déléguée

**`Modflow6` est un God Class** *(constaté mais PAS prioritaire — ne pas toucher pour le moment)*
- Fichier : `solver/modflow6/modflow6.py` — 1 500 lignes, 57 méthodes
- Gère preprocessing, assemblage de grille, discrétisation, propriétés, stress-periods, et post-processing dans une seule classe
- 15+ variables d'instance, constructeur avec 6+ paramètres (dont filesystem paths, détection plateforme)
- 38 raise/except — gestion d'erreur dispersée
- **DECISION :** Ce module fonctionne et n'est pas sur le chemin critique de la restructuration actuelle. Le refactoring de Modflow6 est reporté — on ne casse pas ce qui marche.

### Problèmes importants 🟠

- **`core/tools/toolbox.py`** (1 146 lignes) — Module utilitaire fourre-tout : raster I/O, statistiques hydrologiques, utilitaires de date, visualisation, gestion de dossiers. Importe 15+ bibliothèques au top-level (matplotlib, rasterio, geopandas, xarray, pyproj, etc.). Violation massive du SRP.
- **`HydroModPyConfig`** (`core/config/hydromodpy_config.py`) — Agrège 12 sections de config mais les loaders sont inconsistants : certains délèguent (`FlowConfig.from_toml_section()`), d'autres font la validation inline.
- **`flow_to_modflow_adapter.py`** (`solver/modflow_nwt/modflow/`, 1 377 lignes) — Fichier massif. Rôle clair (pont Process→MODFLOW) mais devrait être découpé par type de BC.

### Améliorations souhaitables 🟡

- `launchers/` est un package distribué au même niveau que `hydromodpy/` dans le repository mais inclus dans le même wheel via `[tool.setuptools.packages.find]`. Devrait être un sous-package de `hydromodpy` ou un package séparé.
- `Solver` ABC (`solver/prototype/solver.py`) trop minimaliste : 3 méthodes abstraites seulement (`pre_processing`, `processing`, `post_processing`). Manque `get_results()`, `cleanup()`, `validate_config()`.

### Points positifs 🟢

- **Séparation Process/Solver exemplaire** — `Flow` n'importe jamais de solver, l'adapter fait le pont.
- **Frozen dataclasses** pour tous les contrats : `ProcessRun`, `SimulationPlan`, `RunContext`, `RunExecutionResult`, `HydroMesh`, `SolverMesh`, `GridReference` — empêchent les mutations accidentelles.
- **Pattern Adapter** via `SolverAdapter` Protocol + registry (`simulation/adapters/registry.py`) — extensible, propre, permet l'ajout de solveurs sans modifier le core.
- **State management 3-scope** (`SetupContext`, `LoadedDataContext`, `ExecutionRegistry`) — séparation claire des préoccupations.
- **Pas de dépendances circulaires** — lazy loading + `TYPE_CHECKING` partout.

---

## 2. Qualité du code Python

### Diagnostic

La codebase présente une **dualité nette** : les modules récents (post-2024) sont de haute qualité (type hints complets, Pydantic, frozen dataclasses), tandis que les modules legacy (toolbox, visualization, certains solvers) sont en style Python 2/3 hybride avec peu de typing.

**Couverture type hints par couche :**

| Couche | Couverture | Style |
|--------|-----------|-------|
| `core/config/`, `core/units/` | 90-100% | Moderne (`\|` unions, `Annotated`) |
| `results/`, `simulation/` | 85-95% | Moderne |
| `process/`, `spatial/` (core) | 80-90% | Moderne (`Generic[T]`, `TYPE_CHECKING`) |
| `data/contracts/`, `data/planner.py` | 90%+ | Moderne |
| `solver/modflow6/`, `solver/boussinesq/` | 70-80% | Bon, dataclasses typés |
| `core/tools/toolbox.py` | <10% | Legacy, quasi-absent |
| `analysis/display/visualization_*.py` | <15% | Legacy |
| `core/tools/log_manager.py` | 0% | Legacy |

### Problèmes critiques 🔴

**Code mort dans `hydromodpy/__init__.py` lignes 191-198**

Un `return` à la ligne 191 de `_ensure_proj_db_layout()` rend les lignes 193-198 **inaccessibles**. Le message d'avertissement PROJ ne sera jamais affiché :

```python
# Ligne 191
return   # ← sort de la fonction ici

# Lignes 193-198 — DEAD CODE, jamais exécuté
_bootstrap_logger.warning(
    "PROJ database layout is older than expected (need >= %s). "
    "Update pyproj in the active environment (pip install -U pyproj) "
    "and avoid mixing system PROJ installs.",
    min_minor,
)
```

**`toolbox.load_to_xarray()` — fonction de ~183 lignes**
- `core/tools/toolbox.py`, lignes ~302-484
- Impossible à tester unitairement, trop de branches conditionnelles imbriquées

### Problèmes importants 🟠

**60 `except:` nus à travers le package**
- `analysis/display/visualization_results.py` : 53 occurrences — chaque rendu de figure wrappé dans un `try/except:` nu qui avale TOUTES les exceptions (y compris `KeyboardInterrupt`, `SystemExit`)
- `analysis/display/visualization_watershed.py` : 6 occurrences — même pattern
- `data/climatic/driasclimat.py` : 9 occurrences — au niveau module
- `data/climatic/driaseau.py` : 5 occurrences
- `solver/modflow_nwt/modpath/modpath.py` : 4 occurrences

**318 appels `print()` éparpillés dans 52 fichiers**
- Devrait être 0 en production, tout devrait passer par `logging`
- Concentrés dans : examples, test cases, modules legacy de visualisation

**`LogManager` — singleton mutable global**
- `core/tools/log_manager.py` (294 lignes) — initialisé au chargement du package (ligne 243 de `__init__.py`)
- 0 type hints sur la classe entière
- Pattern singleton complique les tests (pas d'injection de dépendances)

**Magic values et effets de bord globaux**
- `toolbox.py` ligne 29 : `xr.set_options(keep_attrs=True)` — modifie la configuration globale xarray à l'import du module
- Détection de plateforme par strings `"win"/"mac"/"linux"` dans les solvers au lieu d'enums
- `_mf6_safe_name()` : longueur max 16 caractères hardcodée, fallback SHA1

### Améliorations souhaitables 🟡

- Les façades de compatibilité (`modeling/`, aliases backward dans `Workspace`, etc.) doivent être **supprimées purement et simplement** (cf. Règle 1), pas décorées avec `@deprecated`
- Conventions legacy : `#%% LIBRAIRIES` (notation Spyder/MATLAB) dans les anciens fichiers
- Pas d'exceptions domain-spécifiques — tout est `ValueError`, `RuntimeError`, `TypeError` génériques. Une hiérarchie `HydroModPyError → ConfigError, SolverError, DataError` aiderait le diagnostic.
- `_validate_cross_section_constraints()` dans `HydroModPyConfig` (lignes 154-157) est **vide** — validateur déclaré mais jamais implémenté

### Points positifs 🟢

- **Usage exemplaire de `Generic[T]`** : `ProcessSpatial[TInitialConditions]` lie Flow → FlowInitialConditions avec type-safety
- **Protocols bien utilisés** : `SolverAdapter`, `SpatialSupportProvider`, `WhiteboxBackend`, `OutputAdapter` — duck typing intentionnel et documenté
- **Builder pattern immutable** : `HydroMesh.with_cell_data()`, `Surface` — excellent
- **Pydantic `ConfigDict(extra="forbid")`** systématique — empêche les typos TOML
- **`ParamLevel`** (`core/config/param_level.py`) : design élégant avec `Annotated[Type, ParamLevel("user")]` pour la visibilité progressive des paramètres
- **Système d'unités** (`core/units/`) : conversion canonique SI cohérente (m, m/s, secondes, W/m²) avec fallback gracieux sans Pint

---

## 3. Dépendances et écosystème

### Diagnostic

**Build system :** setuptools classique (PEP 518 via `pyproject.toml`). Pas de hatchling/flit/pdm.

**41 dépendances déclarées** dans `dependencies`, dont **9 inutilisées ou mal placées**.

### Problèmes critiques 🔴

**9 dépendances fantômes ou mal placées (vérifiées par grep exhaustif des imports) :**

| Dépendance | Imports trouvés | Verdict |
|-----------|----------------|---------|
| `selenium` | 0 | **Supprimer** — aucun usage |
| `ipykernel` | 0 | **Supprimer** — aucun usage |
| `ipython` | 0 (1 commentaire dans `folder_root.py`) | **Supprimer** |
| `pyside6` | 0 | **Supprimer** — aucun usage |
| `spyder-kernels` | 0 (1 commentaire) | **Supprimer** |
| `pyshp` | 0 | **Supprimer** — shapely couvre les besoins |
| `dask` | 0 | **Supprimer** — aucun usage |
| `blosc2` | 0 | **Supprimer** — zarr utilise son propre codec |
| `pytest`, `pytest-xdist` | Tests uniquement | **Déplacer** vers `[optional-dependencies] test` |

**Impact :** ces dépendances alourdissent l'installation (~200+ Mo avec PySide6 seul), créent des conflits potentiels (PySide6 ↔ Qt system), et `pytest` en runtime est une erreur de packaging.

### Problèmes importants 🟠

**Pas de version pinning sur la majorité des dépendances**
- Seuls `numpy>=2.0`, `pydantic>=2.0`, `zarr>=3.0`, `setuptools>=65.0` ont des contraintes
- `flopy`, `gmsh`, `rasterio`, `geopandas` sans version minimum → breakages probables à toute mise à jour majeure

**`pyvista` doublon** : présent dans `dependencies` ET dans `[optional-dependencies] viewer3d`
- Le code utilise un pattern `require_pyvista()` avec late import → confirme que ça devrait être purement optionnel

**Dépendances lourdes à usage marginal :**

| Dépendance | Nb imports | Usage | Recommandation |
|-----------|-----------|-------|----------------|
| `plotly` | 1 | Animations (fallback gracieux) | Optionnel → groupe `viz` |
| `ultraplot` | 1 | Subplots (fallback `plt.subplots`) | Optionnel → groupe `viz` |
| `vedo` | 2 | 3D viz (gestion optionnelle) | Optionnel → groupe `viewer3d` |
| `contextily` | 2 | Fond de carte dans display | Optionnel → groupe `viz` |
| `imageio` | 2 | Génération GIF | Optionnel → groupe `viz` |
| `scikit-learn` | ~5 | Calibration (GP) | Garder mais documenter |

### Améliorations souhaitables 🟡

Restructuration des groupes optionnels recommandée :

```toml
[project.optional-dependencies]
test = ["pytest", "pytest-xdist", "pytest-timeout"]
viz = ["plotly", "ultraplot", "vedo", "contextily", "imageio"]
viewer3d = ["pyvista"]
ide = ["spyder>=6.0", "jupyterlab>=4.0", "ipykernel"]
docs = [...]  # déjà existant
```

Le build system `setuptools` fonctionne mais `hatchling` simplifierait la maintenance (suppression du `MANIFEST.in`, auto-detection packages).

### Points positifs 🟢

- **Core scientifique justifié** : numpy (196 imports), pandas (67), rasterio (35), geopandas (41), flopy (6), scipy — chacun massivement utilisé
- `numpy>=2.0` montre une volonté de rester sur le stack moderne
- Lazy import dans `__init__.py` atténue le temps de chargement malgré le nombre de dépendances
- Le fichier `uv.lock` (873 Ko) est présent — lock file pour reproductibilité

---

## 4. Base de données — Structure et usage

### Diagnostic

**Deux moteurs DuckDB indépendants :**

1. **Data Catalog** (`data/registry/catalog_duckdb.py`) — registre des fichiers de données téléchargés/custom. Stocké dans `catalog.duckdb` au niveau workspace (partagé entre projets).
2. **Results Store** (`results/store.py` + `results/schema.py`) — résultats de simulation. `project.duckdb` par projet + Zarr v3 pour champs spatiaux (`project_results.zarr`).

**Schéma Results Store (7 tables projet + 1 table registre workspace) :**

```sql
-- Table principale
simulations (
    sim_id UUID PRIMARY KEY,
    name VARCHAR, created_at TIMESTAMP DEFAULT now(),
    config_toml JSON,           -- config TOML complète sérialisée
    solver VARCHAR,
    n_cells INTEGER, n_layers INTEGER, n_timesteps INTEGER,
    cell_types VARCHAR[],       -- array DuckDB natif
    bbox DOUBLE[4],             -- array DuckDB natif
    zarr_group VARCHAR,
    status VARCHAR,
    duration_s DOUBLE,
    tags VARCHAR[],
    calibration_params JSON     -- paramètres optimaux post-calibration
);

-- Séries temporelles normalisées (v1, migrées depuis arrays v0)
timeseries (
    sim_id UUID REFERENCES simulations(sim_id),
    station_id VARCHAR NOT NULL,
    variable VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    value DOUBLE,               -- ⚠️ nullable
    unit VARCHAR
);
-- INDEX ix_ts_lookup ON (sim_id, station_id, variable, timestamp)

-- Bilans hydriques par zone
budgets (sim_id UUID, timestep INTEGER, zone_id INTEGER, component VARCHAR,
         flux_in DOUBLE, flux_out DOUBLE, unit VARCHAR);

-- Métriques de performance
metrics (sim_id UUID, station_id VARCHAR, metric_name VARCHAR, value DOUBLE);

-- Points d'observation ↔ cellules du maillage
observation_points (sim_id UUID, station_id VARCHAR, x DOUBLE, y DOUBLE,
                    cell_id INTEGER, layer INTEGER DEFAULT 0, variable VARCHAR);

-- Bilan de masse global
mass_balance_summary (sim_id UUID, timestep INTEGER, total_in DOUBLE, total_out DOUBLE,
                      storage_in DOUBLE, storage_out DOUBLE, percent_error DOUBLE);

-- Provenance des données d'entrée (traçabilité scientifique)
input_provenance (sim_id UUID, variable VARCHAR, source_type VARCHAR, source_ref VARCHAR,
                  period_start DATE, period_end DATE,
                  checksum VARCHAR,     -- SHA-256
                  n_records INTEGER,
                  stats JSON);          -- {mean, min, max, std}

-- Registre workspace (cross-projet)
simulation_registry (
    sim_id UUID PRIMARY KEY,
    project VARCHAR NOT NULL, project_path TEXT NOT NULL,
    best_nse DOUBLE, best_kge DOUBLE, best_rmse DOUBLE,
    forcing_sources VARCHAR[], config_hash VARCHAR,
    -- + 15 colonnes de métadonnées
);
```

**Schéma Data Catalog :**

```sql
entries (
    id INTEGER PRIMARY KEY,
    variable VARCHAR, source VARCHAR, station_id VARCHAR,
    bbox_xmin DOUBLE, bbox_ymin DOUBLE, bbox_xmax DOUBLE, bbox_ymax DOUBLE,
    crs VARCHAR,
    date_start VARCHAR, date_end VARCHAR,   -- ISO strings
    frequency VARCHAR, unit VARCHAR, source_unit VARCHAR,
    file_path VARCHAR,
    file_mtime DOUBLE,
    created_at TIMESTAMP,
    is_custom INTEGER,          -- 0/1 (pas BOOLEAN)
    fetch_metadata JSON
);
-- INDEX ix_entries_var_src_station (variable, source, station_id)
-- INDEX ix_entries_bbox (bbox_*)

api_coverage (id INTEGER, variable VARCHAR, source VARCHAR, country VARCHAR,
              description VARCHAR, bbox_* DOUBLE);
```

**Layout Zarr v3 :**

```
project_results.zarr/
├── {sim_id}/
│   ├── mesh/
│   │   ├── vertices           (n_nodes, 2|3)  float64
│   │   ├── face_node_connectivity  (n_cells, max_vpf)  int32
│   │   └── z_interfaces      (n_layers+1,)  float64
│   ├── {variable}             (n_timesteps, n_cells)      BLOSC-ZSTD clevel=3
│   ├── derived/{variable}     (n_timesteps, n_cells)
│   ├── budget/{flux}          (n_timesteps, n_cells)
│   └── pathlines/
```

Chunking : `(1, n_cells)` pour 2D, `(1, n_layers, n_cells)` pour 3D. Fill value : NaN.

**Accès SQL :** 100% requêtes paramétrisées avec `?` — vérifié dans `catalog_duckdb.py` et `store.py`. Aucun string formatting.

**Gestion des connexions :**

| Composant | Context manager | `close()` explicite | Retry |
|-----------|:-:|:-:|:-:|
| `ResultStore` | oui (`__enter__`/`__exit__`) | oui | oui (3×, backoff) |
| `DataCatalogDuckDB` | **non** | oui | oui (3×, backoff) |

### Problèmes critiques 🔴

**Supprimer tout le code de migration SQLite→DuckDB** *(cf. Règle 3)*
- `data/registry/catalog_duckdb.py` lignes ~101-176 : auto-migration depuis `catalog.db` SQLite → à supprimer intégralement
- `results/schema.py` `_migrate_v0_to_v1()` lignes 187-229 : migration array→normalized timeseries. Si le schéma v1 est le schéma cible, supprimer le code de migration et ne garder que le DDL v1 natif.
- Tout code de détection/fallback legacy (`catalog.db`, `_CatalogEntry` legacy compat) → supprimer
- Le schéma DuckDB natif est la seule source de vérité.

### Problèmes importants 🟠

**`DataCatalogDuckDB` sans context manager**
- `data/registry/catalog_duckdb.py` — si une exception survient entre l'ouverture et `.close()`, la connexion fuit
- `ResultStore` a résolu ce problème avec `__enter__`/`__exit__` — le catalog devrait suivre le même pattern

**`timeseries.value` nullable sans contrainte NOT NULL**
- `results/schema.py` ligne 52 : `value DOUBLE` sans `NOT NULL`
- NaN et NULL coexistent potentiellement → sémantique ambiguë dans les agrégations (`SUM`, `AVG`)

**`is_custom` stocké en INTEGER (0/1) au lieu de BOOLEAN**
- `data/registry/catalog_duckdb.py` — DuckDB supporte nativement BOOLEAN

**Type hint incorrect**
- `results/schema.py` ligne 232 : `_MIGRATIONS: dict[int, callable]` — `callable` minuscule n'est pas un type valide, devrait être `Callable`

### Améliorations souhaitables 🟡

- `timeseries` manque d'une clé primaire composite — les doublons ne sont détectés que par logique applicative
- `config_toml` en JSON dans `simulations` peut devenir très volumineux et n'est pas queryable efficacement — considérer un stockage séparé
- Les dates du catalog (`date_start`, `date_end`) sont des `VARCHAR` ISO au lieu de `DATE` natif DuckDB — perdent les avantages d'indexation temporelle

### Points positifs 🟢

- **SQL 100% paramétrisé** — aucune injection SQL possible
- **Retry avec backoff exponentiel** sur `duckdb.IOException` (3 tentatives, 0.1/0.2/0.4s) — gère la concurrence fichier
- **Deletion transactionnelle** (`delete_simulation()`) : `begin()`/`commit()`/`rollback()` explicite sur 7 tables
- **Schema versioning** avec migration automatique (`_ensure_schema()`) — permet l'évolution sans casser les bases existantes
- **Provenance tracking** avec SHA-256 checksums + stats (mean, min, max, std) — essentiel pour la reproductibilité scientifique
- **Zarr v3 + BLOSC-ZSTD** : compromis performance/stockage approprié pour les séries spatio-temporelles
- ~~Auto-migration SQLite→DuckDB pour le legacy catalog~~ — **A SUPPRIMER** (voir directive ci-dessous)
- **Sentinel pattern** (`SENTINEL_CUSTOM`, `SENTINEL_EMPTY`) : marque les entrées custom/vides sans les détruire lors du cleanup

---

## 5. Interfaces et API interne

### Diagnostic

L'API publique est structurée via `hydromodpy/__init__.py` avec lazy loading intelligent.

**Surface publique (`__all__`, 22 noms) :**
- 9 modules : `analysis`, `core`, `data`, `modeling`, `process`, `simulation`, `solver`, `spatial`, `watershed`
- 13 classes lazy-loaded : `Geographic`, `Workspace`, `Modflow`, `HydroModPyConfig`, `Hydrometry`, `Piezometry`, etc.
- `log_manager` et `__version__`

**Mécanisme lazy :** `__getattr__()` avec deux dictionnaires (`_MODULE_EXPORTS`, `_LAZY_IMPORTS`) et cache dans `globals()`.

**Protocol/ABC utilisés :**

| Interface | Fichier | Type | Méthodes |
|-----------|---------|------|----------|
| `SolverAdapter` | `simulation/adapters/base.py` | Protocol | `execute(RunContext) → RunExecutionResult` |
| `OutputAdapter` | `simulation/results/extractors/base.py` | Protocol | `extract()`, `derive()`, `cleanup_solver_files()` |
| `WhiteboxBackend` | `core/backends/` | Protocol | 10+ méthodes DEM (fill, breach, d8, clip...) |
| `SpatialSupportProvider` | `spatial/` | Protocol | `ClassVar` + méthodes builder |
| `ProcessSpatial[T]` | `process/prototype/process_spatial.py` | ABC Generic | `build_initial_conditions()`, `set_boundary_conditions()` |
| `Solver` | `solver/prototype/solver.py` | ABC | `pre_processing()`, `processing()`, `post_processing()` |
| `AbstractCalibrationCase` | `analysis/calibration/core/case_interface.py` | ABC | Plugin interface pour cas de calibration |
| `BaseVariableManager` | `data/common/base_manager.py` | ABC | `load() → LoadResult`, fetch, persist, register |

**Data Contracts :**
- `PointRecord` (`data/contracts/timeseries.py`) — séries temporelles avec validation post-init
- `FieldRecord` (`data/contracts/spatial_field.py`) — champs spatiaux (xarray ou Path lazy)
- `LoadResult` (`data/contracts/load_result.py`) — conteneur manager → consommateur
- `StationLocation` (`data/contracts/location.py`) — frozen dataclass immutable

### Problèmes importants 🟠

- **`modeling` dans `_MODULE_EXPORTS`** : façade de compatibilité qui n'a pas lieu d'être. **A supprimer** de `_MODULE_EXPORTS` et de `__all__` (cf. Règle 1).
- **Noms dupliqués module/classe** dans `_LAZY_IMPORTS` : `Hydrometry` pointe vers `data.variables.hydrometry.hydrometry` — fragile à refactorer.
- **`SolverAdapter` Protocol trop minimaliste** (27 lignes) : seulement `process_type`, `solver_name`, et `execute()`. Les implémentations ajoutent ad hoc `get_results()`, `cleanup()`, etc. — la surface contractuelle devrait être élargie.

### Améliorations souhaitables 🟡

- Data contracts (`PointRecord`, `FieldRecord`, `LoadResult`) non exposés dans `__all__` — un utilisateur avancé doit fouiller dans `data.contracts`
- `Workspace` lazy import pointe vers le module `hydromodpy.core.workspace` et dépend de `__getattr__` pour résoudre l'attribut classe — fragile

### Points positifs 🟢

- **Lazy loading** avec cache — temps d'import minimal
- **Progressive disclosure** : `import hydromodpy as hmp` puis `hmp.Geographic`, `hmp.Workspace` — API intuitive
- **Pydantic `extra="forbid"`** partout — les typos TOML sont détectées immédiatement
- **`ParamLevel`** avec `Annotated[Type, ParamLevel("user")]` — génération de templates TOML par profil (user/dev/expert)
- **`CalibrationParameter`** : validation de plages, conversion vector/dict, support bornes — API calibration propre

---

## 6. Gestion des configurations

### Diagnostic

**Flux de configuration :**

```
config.toml → load_toml_with_base_config()
  → merge_toml_payloads() (héritage récursif)
  → HydroModPyConfig.from_toml(path)
  → validation Pydantic section par section
  → objets runtime (Flow, Domain, etc.)
```

**Features :**
- `base_config` récursif : un TOML peut hériter d'un autre avec override (détection de cycles incluse)
- Conversion d'unités automatique dans les configs (conductivité hydraulique → m/s canonical)
- `_repair_path_like_basic_strings()` : auto-fix des backslashes Windows dans les chemins TOML
- 12 sections de configuration mappées 1:1 vers des modèles Pydantic

**Variables d'environnement :**

| Variable | Usage |
|----------|-------|
| `HYDROMODPY_NO_DISPLAY=1` | Mode headless (skip plots interactifs) |
| `HYDROMODPY_NO_SAVE=1` | Désactive la sauvegarde des figures |
| `HYDROMODPY_TEST_SCRATCH_ROOT` | Override répertoire scratch des tests |
| `HYDROMODPY_PROJECT_ROOT` | Override résolution workspace dans les tests |
| `HYDROMODPY_COVERAGE=1` | Active la collecte de couverture en régression |
| `PROJ_DATA` / `PROJ_LIB` | Chemin base de données pyproj (auto-résolu) |

### Problèmes importants 🟠

- **`_validate_cross_section_constraints()` est vide** — `core/config/hydromodpy_config.py` lignes 154-157. Validateur déclaré mais non implémenté → des configurations incohérentes entre sections passent la validation.
- **`_repair_path_like_basic_strings()`** — heuristique regex qui corrige les backslashes Windows. Peut transformer des valeurs légitimes contenant des backslashes.

### Améliorations souhaitables 🟡

- Les variables d'environnement ne sont pas centralisées — chaque module les lit via `os.environ.get()`. Un objet `EnvironmentSettings` (Pydantic Settings) centraliserait la logique.
- Loaders inconsistants dans `HydroModPyConfig.from_toml()` : `_load_flow_section()` délègue à `FlowConfig.from_toml_section()`, mais `_load_solver_section()` fait la validation inline. Devrait être uniformisé.

### Points positifs 🟢

- **TOML 1:1 Pydantic** : chaque section correspond exactement à un modèle Pydantic
- **`base_config` récursif** avec détection de cycles — factorisation des configurations partagées
- **Système d'unités** (`core/units/`) : 7 modules (length, time, hydraulic_conductivity, volumetric_flow, hydraulic_conductance, radiation, scalar) — conversions canoniques SI cohérentes, degradation gracieuse sans Pint
- **`DataManagersPlanner`** : inférence automatique des types de données depuis le contexte config (ex: `"stream"` dans `flow.active_bc` → charge automatiquement l'hydrographie)
- **`ResolvedSimulationTimeWindow`** : design soigné avec bornes inclusives pour l'utilisateur et half-open en interne, stress-periods en secondes pour l'export solver

---

## 7. Gestion des erreurs et robustesse

### Diagnostic

**Statistiques cross-package :**

| Pattern | Occurrences | Fichiers |
|---------|:-----------:|:--------:|
| `except:` nus | 60 | ~15 |
| `except Exception` | 273 | ~75 |
| `print()` | 318 | 52 |
| `logging.getLogger()` | 29 | 29 |

### Problèmes critiques 🔴

**53 `except:` nus dans `visualization_results.py`** (928 lignes)
- `analysis/display/visualization_results.py` — chaque tentative de rendu de figure wrappée dans un `try/except:` nu
- Avale silencieusement TOUTES les exceptions y compris `KeyboardInterrupt` et `SystemExit`
- Un fichier corrompu, un crash matplotlib, ou un Ctrl+C sont ignorés

**`except:` dans les modules data climatiques**
- `data/climatic/driasclimat.py` : 9 occurrences
- `data/climatic/driaseau.py` : 5 occurrences
- Module-level dans certains cas (erreurs d'import avalées silencieusement)

### Problèmes importants 🟠

- **Pas de hiérarchie d'exceptions custom** — tout est `ValueError`/`RuntimeError`/`TypeError` génériques. L'appelant ne peut pas distinguer une erreur de config d'une erreur solver d'une erreur I/O. Recommandation :
  ```python
  class HydroModPyError(Exception): ...
  class ConfigError(HydroModPyError): ...
  class SolverError(HydroModPyError): ...
  class DataError(HydroModPyError): ...
  class MeshError(HydroModPyError): ...
  ```

- **Validation scientifique insuffisante** — peu de vérification de plages physiques (conductivité hydraulique négative, épaisseur aquifère nulle, recharge > précipitation). Les erreurs remontent comme des NaN ou des divergences solver au lieu d'être détectées en amont.

- **Logging hybride** — 29 modules utilisent `logging.getLogger(__name__)` correctement, mais 52 fichiers utilisent encore `print()`. Le `LogManager` singleton expose des modes (dev/verbose/quiet) mais n'est pas utilisé par tous les modules.

### Points positifs 🟢

- **Validation Pydantic en entrée de pipeline** : erreurs de config détectées tôt avec messages clairs
- **Retry avec backoff** sur les opérations DuckDB
- **Fail-fast dans `SimulationRunner`** : dépendance manquante → `ValueError` immédiat avec contexte
- **Diagnostics path** : les adapters solver fournissent le chemin fichiers de diagnostic en cas d'échec
- **Auto-export résilient** (`simulation/results/post_run.py`) : chaque format d'export wrappé individuellement — l'échec VTU n'empêche pas CSV
- **Provenance verification** : `verify_fingerprint()` permet de détecter les corruptions de données

---

## 8. Testabilité

### Diagnostic

**Structure des tests :**

```
tests/                              (233 fichiers total)
├── conftest.py                     (root: scratch dir, markers, update_goldens)
├── unit/                           (181 fichiers)
│   ├── geographic/ (14)
│   ├── data_managers/ (21)
│   ├── simulation/ (17)
│   ├── launchers/ (11)
│   ├── calibration/ (5)
│   ├── mesh/ (7)
│   ├── display/ (5)
│   ├── solver/ (6)
│   ├── field/ (5)
│   ├── units/ (5)
│   ├── postprocess/ (5)
│   ├── process/ (4)
│   └── ... (config, backends, tools, domain, hydrology, annex)
├── regression/                     (9 fichiers, 2 tiers)
│   ├── fast/ (4)
│   ├── extensive/ (5)
│   └── reference/golden_references/  (fichiers JSON de référence)
└── validation/                     (20 fichiers)
    ├── analytical/steady/
    ├── analytical/transient/
    └── helpers/
```

**Marqueurs pytest actifs :**

| Marqueur | Occurrences | Usage |
|----------|:-----------:|-------|
| `fast` | 78 | Tests rapides |
| `slow` | 20 | Tests longs |
| `validation` | 20 | Benchmarks scientifiques |
| `analytical` | 20 | Comparaison à solution analytique |
| `steady` | 11 | Régime permanent |
| `regression` | 9 | Non-régression |
| `extensive` | 5 | Validation approfondie |
| `nwt` / `mf6` | variable | Tests par solveur |

**Golden reference system** (`tests/regression/golden_utils.py`, 918 lignes) : comparaison par statistiques (mean, p50, p95, sum, shape) avec tolérances configurables (`rel=1e-4`, `abs=1e-6`), pas de comparaison bit-à-bit.

### Problèmes critiques 🔴

**Coverage ciblée sur 3 modules seulement (sur 12+)**

```toml
# pyproject.toml [tool.coverage.run]
source = [
    "hydromodpy.spatial.geographic",
    "hydromodpy.core.tools",
    "hydromodpy.analysis.display",
]
```

Modules **exclus** du coverage : `core/config/`, `core/state/`, `core/units/`, `process/`, `data/`, `results/`, `simulation/`, `solver/`, `spatial/domain/`, `spatial/field/`, `spatial/mesh/`. Des régressions dans ces modules passent sous le radar du CI.

### Problèmes importants 🟠

- **`LogManager` singleton** : initialisé au chargement du package, pas d'injection de dépendances. Les tests ne peuvent pas substituer ou isoler le logger.

- **`toolbox.py` non-testable unitairement** : 30+ fonctions importent matplotlib, rasterio, geopandas au top-level module. Tester une seule fonction force le chargement de toute la stack scientifique.

- **`Modflow6` (1 500 lignes)** : constructeur à 6+ paramètres dont des filesystem paths et détection plateforme. Pas d'injection → tests unitaires impossibles sans monkeypatching lourd. *(Constaté mais reporté — cf. Règle 2)*

- **Ratio régression/unitaire déséquilibré** : 9 fichiers de régression vs 181 unitaires (5%). Les tests d'intégration end-to-end qui vérifient le pipeline complet sont sous-représentés.

- **Pas de `pytest-timeout`** configuré — un solver qui hang bloque indéfiniment le CI.

### Améliorations souhaitables 🟡

- Étendre `[tool.coverage.run] source` à tous les packages principaux
- Ajouter `pytest-timeout` avec un timeout global raisonnable (ex: 300s pour les tests slow, 30s pour les fast)
- Promouvoir 10-15 tests d'intégration du tier unitaire vers le tier régression
- Activer `pytest-xdist` dans le CI (listé en dépendance mais non utilisé dans `addopts`)

### Points positifs 🟢

- **Golden references statistiques** plutôt que comparaison exacte — robuste aux variations d'arrondi cross-plateforme
- **Marqueurs bien disciplinés** : filtrage fin possible par solveur, régime, tier
- **Architecture adapter** structurellement testable : `SolverAdapter` Protocol + `RunContext` dataclass
- **`WhiteboxBackend` Protocol** : les opérations DEM sont mockables sans installer whitebox
- **Data contracts** (`PointRecord`, `FieldRecord`) : structures typées facilitent les assertions
- **Scratch directory configurable** avec auto-cleanup — pas de pollution du filesystem
- **Auto-assignment des marqueurs** regression tier (fast/extensive) par localisation dans `conftest.py`

---

## Synthèse stratégique

### Classement des problèmes par priorité

| # | Problème | Section | Impact | Effort |
|:-:|----------|:-------:|:------:|:------:|
| 1 | 9 dépendances fantômes dans `pyproject.toml` | §3 | Bloat install, conflits | Trivial |
| 2 | Code mort `__init__.py:191-198` (bug PROJ) | §2 | Bug silencieux | Trivial |
| 3 | `pytest` dans dependencies runtime | §3 | Packaging incorrect | Trivial |
| 4 | 60 `except:` nus (surtout `visualization_results.py`) | §7 | Exceptions avalées | Faible |
| 5 | Coverage ciblée 3/12+ packages | §8 | Régressions invisibles | Faible |
| 6 | `DataCatalogDuckDB` sans context manager | §4 | Fuite connexion | Faible |
| 7 | `_validate_cross_section_constraints()` vide | §6 | Configs incohérentes | Faible |
| 8 | `toolbox.py` monolithique (1 146 lignes) | §2 | Maintenance, testabilité | Moyen |
| 9 | Pas d'exceptions domain-spécifiques | §7 | Diagnostic difficile | Moyen |
| 10 | `HydroModPyLauncher` God class (777 lignes) | §1 | Maintenabilité | Élevé |
| 11 | ~~`Modflow6` God class (1 500 lignes, 57 méthodes)~~ | §1 | ~~Testabilité~~ | **Reporté** |
| 12 | Logging hybride (29 `logging` vs 318 `print`) | §7 | Observabilité | Moyen |

### Feuille de route de refactoring

#### Phase 1 — Quick wins (1-2 jours, risque nul)

- [ ] Supprimer les 9 dépendances inutilisées de `pyproject.toml` (`selenium`, `ipykernel`, `ipython`, `pyside6`, `spyder-kernels`, `pyshp`, `dask`, `blosc2`, et déplacer `pytest`/`pytest-xdist` vers `[optional-dependencies] test`)
- [ ] Corriger le code mort dans `__init__.py:191` (déplacer le `return` après le warning, ou restructurer le flow)
- [ ] Étendre `[tool.coverage.run] source` à tous les packages principaux
- [ ] Ajouter `pytest-timeout` au CI
- [ ] Corriger `_MIGRATIONS: dict[int, callable]` → `dict[int, Callable]` dans `schema.py:232`
- [ ] Ajouter `__enter__`/`__exit__` à `DataCatalogDuckDB`
- [ ] Supprimer la façade `modeling` de `_MODULE_EXPORTS` et `__all__` dans `__init__.py`
- [ ] Supprimer le code de migration SQLite→DuckDB dans `catalog_duckdb.py` (lignes ~101-176) et `schema.py` (`_migrate_v0_to_v1`)
- [ ] Supprimer les aliases backward compat dans `Workspace` (`catch_folder`, `data_path`, etc.)

**Risques :** Quasi-nuls. Le nettoyage des dépendances pourrait révéler des imports dynamiques non détectés — vérifier avec `pip install -e . && hmp test unit` après. La suppression du code legacy casse volontairement la compat backward (cf. Règle 1).

#### Phase 2 — Hygiène du code (1-2 semaines, risque faible)

- [ ] Remplacer les 60 `except:` nus par `except Exception as e:` avec logging approprié — priorité sur `visualization_results.py` (53 occurrences)
- [ ] Convertir les 318 `print()` en `logging.info()` / `logging.debug()` dans les modules non-example
- [ ] Éclater `toolbox.py` (1 146 lignes) en modules ciblés :
  - `core/tools/raster_io.py` — fonctions raster (clip_tif, mask_by_dem, load_to_numpy, load_to_xarray)
  - `core/tools/statistics.py` — métriques hydrologiques (rmse, nse, kge, mare, efficiency_criteria)
  - `core/tools/filesystem.py` — gestion de dossiers (create_folder, etc.)
  - `core/tools/geospatial.py` — transformations de coordonnées (basin_area, etc.)
  - Supprimer `toolbox.py` une fois les imports mis à jour (pas de façade de ré-export, cf. Règle 1)
- [ ] Créer une hiérarchie d'exceptions : `HydroModPyError` → `ConfigError`, `SolverError`, `DataError`, `MeshError`
- [ ] Implémenter `_validate_cross_section_constraints()` dans `HydroModPyConfig`
- [ ] Supprimer les modules façade deprecated à la racine du package (`modeling/`, et tout alias de compat identifié)

**Risques :** Le split de `toolbox.py` et la suppression des façades cassent les imports existants. C'est voulu (cf. Règle 1). Mettre à jour tous les `from hydromodpy.core.tools.toolbox import X` vers les nouveaux modules.

#### Phase 3 — Refactoring structural (2-4 semaines, risque modéré)

- [ ] Décomposer `HydroModPyLauncher` (777 lignes) en phases :
  - `SetupPhase` — workspace, geographic, domain, flow/transport creation
  - `DataPhase` — data plan inference + loading
  - `MeshPhase` — mesh generation ou chargement externe
  - `ExecutionPhase` — simulation plan + runner invocation
  - Le launcher devient un orchestrateur mince qui compose les phases
- ~~Décomposer `Modflow6`~~ — **Reporté** (cf. Règle 2 : ne pas toucher `solver/modflow6/`)
- [ ] Uniformiser les loaders de `HydroModPyConfig.from_toml()` — toutes les sections devraient utiliser le pattern `SectionConfig.from_toml_section()`
- [ ] Enrichir `Solver` ABC avec `validate_config()`, `get_results()`, `cleanup()`
- [ ] Enrichir `SolverAdapter` Protocol avec `validate(ctx)` et `cleanup(ctx)`

**Risques :** La décomposition du launcher peut casser les tests de régression. Stratégie : exécuter `hmp test regression --fast -j auto` et `hmp test regression --extensive` après chaque étape. Les golden references statistiques devraient rester stables si seule l'architecture interne change.

#### Phase 4 — Modernisation profonde (1-2 mois, risque élevé)

- [ ] Ajouter type hints complets aux modules legacy (`toolbox.py`, `log_manager.py`, `visualization_*.py`)
- [ ] Migrer `LogManager` singleton → logging standard Python avec configuration lazy (supprime l'état global mutable)
- [ ] Structurer les groupes optionnels de dépendances (`viz`, `viewer3d`, `test`) avec late imports conditionnels
- [ ] Ajouter validation de plages physiques dans les configs Pydantic (conductivité > 0, épaisseur > 0, etc.)
- [ ] Considérer la migration du build system vers `hatchling` (suppression `MANIFEST.in`, auto-detection)
- [ ] Centraliser les variables d'environnement dans un objet Pydantic Settings

**Risques :** Les changements de type hints et de logging peuvent avoir des effets cascade. Le changement de build system nécessite une validation complète de l'installation. Recommandation : faire la migration sur une branche dédiée avec CI complet.

### Architecture cible recommandée

```
hydromodpy/
├── __init__.py                     (lazy loading, __all__, version)
├── exceptions.py                   (HydroModPyError hierarchy)
│
├── core/                           (← dépend de RIEN)
│   ├── config/                     (Pydantic models, TOML loader, ParamLevel)
│   ├── state/                      (LauncherRunState, contexts)
│   ├── workspace/                  (paths, folders)
│   ├── units/                      (SI conversions)
│   ├── time/                       (time windows, stress periods)
│   ├── backends/                   (Whitebox Protocol)
│   ├── logging.py                  (logging config, PAS singleton)
│   └── tools/                      (raster_io, statistics, filesystem, geospatial)
│
├── spatial/                        (← core)
│   ├── geographic/
│   ├── domain/
│   ├── field/
│   └── mesh/
│
├── process/                        (← core, PAS spatial ni solver)
│   ├── prototype/
│   ├── flow/
│   ├── transport/
│   └── hydrology/
│
├── data/                           (← core)
│   ├── contracts/                  (PointRecord, FieldRecord, LoadResult)
│   ├── registry/                   (DataCatalogDuckDB)
│   ├── common/                     (BaseVariableManager, BaseFieldManager)
│   ├── variables/                  (managers par type)
│   └── planner.py                  (DataManagersPlanner)
│
├── solver/                         (← core, spatial, process)
│   ├── prototype/
│   ├── modflow6/                   (tel quel — ne pas toucher pour le moment)
│   ├── modflow_nwt/
│   ├── boussinesq/
│   └── modflow_common/
│
├── simulation/                     (← core, solver.compatibility)
│   ├── planning/                   (SimulationPlan, SimulationPlanner)
│   ├── execution/                  (SimulationRunner)
│   ├── adapters/                   (SolverAdapter Protocol + registry + impls)
│   └── results/                    (OutputAdapter, extractors, post_run)
│
├── results/                        (← core)
│   ├── store.py                    (ResultStore: DuckDB + Zarr)
│   ├── schema.py                   (DDL + migrations)
│   ├── exporters/                  (NetCDF, CSV, VTU, GeoTIFF, Shapefile)
│   └── provenance.py              (SHA-256 fingerprints)
│
├── analysis/                       (← tout sauf simulation)
│   ├── calibration/
│   ├── display/
│   └── postprocess/
│
└── launchers/                      (← tout, orchestrateur mince)
    ├── process_simulation/
    │   ├── launcher.py             (compose SetupPhase+DataPhase+MeshPhase+ExecutionPhase)
    │   ├── setup_phase.py
    │   ├── data_phase.py
    │   ├── mesh_phase.py
    │   └── execution_phase.py
    ├── data_overview/
    └── mesh_catchment/
```

**Règles de dépendance :**
- `core/` → rien (fondation)
- `spatial/` → `core/`
- `process/` → `core/` uniquement (JAMAIS spatial, JAMAIS solver)
- `data/` → `core/`
- `results/` → `core/`
- `solver/` → `core/`, `spatial/`, `process/`
- `simulation/` → `core/`, `solver/` (via registry/compatibility)
- `analysis/` → `core/`, `spatial/`, `data/`, `results/`
- `launchers/` → tout (mais orchestrateur mince, pas de logique domaine)
