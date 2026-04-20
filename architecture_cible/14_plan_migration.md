# Plan de migration HydroModPy — architecture cible

**Statut :** Plan exécutable · **Cible :** migration intégrale 01→13 · **Branche base :** `dev-refact_v2`
**Périmètre :** 13 phases indépendantes, exécutées par un **unique script** `run_migration.sh` à la racine du repo.

Ce document consolide les 13 documents d'architecture cible (`architecture_cible/01..13`) et les 11 rapports d'audit (`audit_code/01..11`) en une séquence opérationnelle de migration.

---

## OVERRIDES (décisions post-review)

### Un seul script `run_migration.sh` à la racine

- **Remplace** les anciens `run_migration_Pxx.sh` individuels mentionnés plus bas.
- Orchestre **les 13 phases** avec :
  - gestion des **rate limits Claude** (attente jusqu'au reset, max 6h)
  - **reprise après crash / déconnexion** (état persistant dans `migration/phases/*.done`)
  - **commits atomiques** au format `[Pxx] - <few english words>` (sans `Co-Authored-By`)
  - **zéro push**, **zéro changement de branche**, garde-fous automatiques
  - utilisation de **sous-agents Claude** (Agent/Explore) pour paralléliser la recherche
- Lancement : `tmux new-session -s migration './run_migration.sh'`.
- Reprise : `./run_migration.sh --resume` (ou simplement le relancer — idempotent).
- Statut : `./run_migration.sh --status`.

### Phases retirées du scope initial

- **Migration DB** : supprimée (clean slate, voir `04_storage_ideal.md` OVERRIDES).
- **PEST++ adapter** : retiré (voir `07_calibration.md` OVERRIDES, reporté post-P13).
- **FastAPI serveur** : retiré (voir `11_frontend_ready.md` OVERRIDES, hors scope).

### Ordre canonique des phases (appliqué par le script)

| # | Phase | Objectif (synthèse) |
|---|---|---|
| **P01** | Foundations | Cleanup legacy + glossaire + migration docs |
| **P02** | Storage | DuckDB schema clean + Zarr + **geographic fingerprint cache** |
| **P03** | Config | Pydantic + **pydantic-pint** + JSON Schema + annotations riches |
| **P04** | Data layer | Scaffold drag-and-drop + auto-scan mtime + **Météo-France SIM2 préservé** |
| **P05** | Spatial/Delineation | whitebox → **spatial/delineation/** multi-backend + synthetic |
| **P06** | Solvers | Protocol SolverAdapter + `modflow_common/` mutualisé |
| **P07** | Pipeline | Orchestration unifiée + **checkpointing** + resume après crash |
| **P08** | Post-process | Figures solver-agnostiques + métriques + derived |
| **P09** | Calibration | **Optuna** principal + **lightweight mode** + TOML simplifié |
| **P10** | API + CLI | `import hydromodpy as hmp` + CLI `hmp` sous-commandes |
| **P11** | Frontend hooks | JSON Schema export + partial validator (**pas de FastAPI**) |
| **P12** | Tests | Suite compacte + maintenable |
| **P13** | Cleanup | Code mort + renommages + docs finales |

### Conséquences dans le reste du document

- Toute table de phases avec un ordre différent : **considérer celle des OVERRIDES comme canonique**.
- Toute proposition de scripts `run_migration_Pxx.sh` séparés : fusionnée dans le `run_migration.sh` unique.

---

**Plan historique détaillé conservé ci-dessous à titre de référence.**

Chaque phase est autonome, testable isolément, rollback-safe via git branch, et équipée d'un prompt Claude Code prêt à copier-coller.

Légende statuts par fichier/classe :
- **[N]** NOUVEAU — n'existe pas aujourd'hui
- **[R]** RENOMMÉ — existe sous un autre nom
- **[F]** REFACTORÉ — existe, signature ou structure à changer
- **[C]** CONSERVÉ — existe et reste en l'état
- **[K]** SUPPRIMÉ — code mort ou remplacé

---

## 1. Vue d'ensemble — 13 phases

| # | Phase | Objectif | Prérequis | Heures | Risque | Parallélisable avec |
|---|---|---|---|---|---|---|
| **P01** | Fondations | Exceptions typées, `field_registry`, `canonical_json`, renommages P0 | — | 24 | faible | — |
| **P02** | Storage | DuckDB 16 tables + Zarr v3 UGRID + migrations + `.hmp` | P01 | 36 | moyen | — |
| **P03** | Config Pydantic | `HydroModelBase`, `UiMeta`, `Profile`, `PartialModel`, JSON Schema | P01 | 32 | moyen | (P02 en parallèle) |
| **P04** | Data input | `HTTPClient`, `InputCatalog`, sources, `hmp data`, lockfile | P01, P02, P03 | 60 | fort | P05 |
| **P05** | Solveurs | `SolverPlugin/Runner/Extractor`, registry unifié, 3 plugins builtin | P01, P02, P03 | 48 | fort | P04 |
| **P06** | Pipeline | 15 steps immutables, checkpoint, fingerprint, `BatchRunner` | P01–P05 | 40 | moyen | — |
| **P07** | Post-traitement | `results/derived`, `results/metrics`, display UGRID solver-agnostique | P01, P02, P05, P06 | 36 | moyen | P08 |
| **P08** | API Python | `hmp.*` top-level, `Simulation`/`SimulationView`/`SimulationGroup`, `_repr_html_` | P01–P06 | 28 | faible | P07 |
| **P09** | CLI | `_cli/` éclaté, argcomplete, wizard, messages Levenshtein | P01, P03, P08 | 24 | faible | P07, P10 |
| **P10** | Export ALL | Arborescence sous-dossiers, CF-1.11, GeoPackage, WaterML | P01, P02, P07, P08 | 20 | faible | P09, P11 |
| **P11** | Tests | Pyramide 4 niveaux, `TOLERANCES.md`, 20 tests critiques, CI 4 profils | transverse | 48 | moyen | P10 |
| **P12** | API REST | `hydromodpy/api/` FastAPI, Arrow IPC, WS/SSE, tests parité | P03, P08, P09 | 40 | faible | P11, P13 |
| **P13** | Nettoyage | Suppression legacy (~9600 LOC), renommages finaux, docs | tout | 16 | faible | — |

**Total :** 452 heures Claude Code (~11 semaines ETP · ~6 semaines avec parallélisation).

---

## 2. Diagramme de Gantt ASCII

```
Semaine :           1       2       3       4       5       6       7       8       9      10      11
                    |-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
P01 Fondations      ###
P02 Storage             #####
P03 Config              #####
P04 Data input                  ##########
P05 Solveurs                    ########
P06 Pipeline                              ######
P07 Post-traitement                              #####
P08 API Python                                   ####
P09 CLI                                              ###
P10 Export ALL                                          ###
P11 Tests                 ################################   (transverse)
P12 API REST                                                   ######
P13 Nettoyage                                                         ##

Chemin critique : P01 → P02/P03 → P04/P05 → P06 → P07/P08 → P10 → P13
Parallélisme :    P02||P03 ; P04||P05 ; P07||P08 ; P09||P10||P11 ; P12||P13
```

---

## 3. Stratégie de rollback

**Pattern git :** une branche par phase, mergée dans `dev-database` après validation.

```
dev-database  (base)
├── migration/P01-foundations
├── migration/P02-storage          ← créée depuis P01 mergée
├── migration/P03-config           ← créée depuis P01 mergée (parallèle P02)
├── migration/P04-data             ← créée depuis P02+P03 mergées
├── migration/P05-solver           ← créée depuis P02+P03 mergées (parallèle P04)
├── migration/P06-pipeline         ← créée depuis P04+P05 mergées
├── migration/P07-postprocess      ← depuis P06
├── migration/P08-api              ← depuis P06 (parallèle P07)
├── migration/P09-cli              ← depuis P08
├── migration/P10-export           ← depuis P07+P08
├── migration/P11-tests            ← créée dès P01, rebased en continu
├── migration/P12-rest             ← depuis P08+P09
└── migration/P13-cleanup          ← depuis toutes les autres
```

**Règles :**
1. **Commit atomiques** par sous-étape (créer classe, migrer 1 fichier, supprimer ancien). Messages `[PXX] <action>`.
2. **Jamais de `--force-push`** sur `dev-database` ni `master`.
3. **Tag de safety** avant merge : `git tag -a pre-PXX-merge -m "..."`.
4. **Rollback phase :** `git checkout dev-database && git branch -D migration/PXX-<name>` (branche non mergée) ou `git revert <merge-sha> -m 1` (post-merge).
5. **Tag de milestone** après chaque merge validé : `vMigration-PXX-complete`.
6. **Critère de merge :** tous les tests critiques de la phase passent + aucune régression unit/regression existante.

---

## 4. Métriques de progrès

| Catégorie | Métrique | Baseline (avant P01) | Cible (après P13) | Commande |
|---|---|---|---|---|
| **Tests** | Fichiers tests | 283 | ~115 | `find tests -name "test_*.py" \| wc -l` |
| **Tests** | LOC tests | ~48 000 | ~18 000 | `cloc tests/ --include-lang=Python` |
| **Tests** | Durée `unit/` série | ~10 min | ≤45 s | `pytest tests/unit/ --duration` |
| **Tests** | Durée CI `pr` | ~30 min | ≤5 min | Workflow `ci.yml` |
| **Code** | LOC `hydromodpy/` | ~72 000 | ~52 000 | `cloc hydromodpy/` |
| **Code** | Fichiers >800 L | 14 | 0 | `find hydromodpy -name "*.py" \| xargs wc -l \| awk '$1>800'` |
| **Code** | Profondeur max import | 6 | 4 | `tests/unit/test_import_dag.py` |
| **Couverture** | Unit | ~55 % | ≥80 % | `pytest --cov=hydromodpy --cov-report=term` |
| **Couverture** | Branch | — | ≥70 % | `pytest --cov-branch` |
| **API** | Symboles top-level | 17 | 22 | `python -c "import hydromodpy; print(len(hydromodpy.__all__))"` |
| **API** | Endpoints REST | 0 | ~50 | `GET /openapi.json` |
| **Schema** | Version DuckDB | 1 | 3 | `SELECT version FROM _schema_version` |
| **Schema** | Tables DuckDB | 12 | 16 | `SHOW TABLES` |
| **Schema** | Tables sans PK | 5 | 0 | `tests/unit/test_duckdb_integrity.py` |
| **Perf** | Lazy import `hmp` | 870 ms | <50 ms | `python -X importtime -c "import hydromodpy"` |
| **Perf** | `validate-field` p95 | — | <50 ms | `tests/api/test_validate_field.py` |
| **Reproductibilité** | `sim_id` stable | non | oui | `tests/validation/test_reproducibility.py` |
| **Conformité** | CF-1.11 | non | oui | `cfchecks <file>.nc` |
| **Conformité** | UGRID-1.0 | non | oui | `xugrid.open_dataset` |

---

## 5. Instructions communes à tous les prompts

**Conventions injectées dans chaque prompt via `$COMMON`:**
- Écrire en français technique.
- Toujours lire `CLAUDE.md` à la racine avant de commencer.
- Ne jamais commiter avec `--no-verify`, `--no-gpg-sign`.
- Créer une branche `migration/PXX-<slug>` depuis `dev-database` avant d'écrire.
- Faire des commits atomiques `[PXX] <action>` en anglais.
- Lancer `pytest tests/unit/ -x -q` après chaque commit significatif.
- En cas d'échec de test existant : corriger la cause, ne jamais désactiver.
- En cas d'ambiguïté entre deux docs `architecture_cible/*.md`, `13_coherence_globale.md` tranche.
- Tester en mode headless : `HYDROMODPY_NO_DISPLAY=1 HYDROMODPY_NO_SAVE=1`.
- Ne pas modifier `pyproject.toml` sans justification explicite dans le commit.
- Rapporter à la fin : LOC ajoutées, LOC supprimées, tests ajoutés, tests cassés.

---

## 6. Phase P01 — Fondations

**Objectif :** poser les primitives sur lesquelles toutes les autres phases s'appuient — hiérarchie d'exceptions typées, registre des champs canoniques (`FieldDescriptor`), fonction `canonical_json()` pour reproductibilité, et renommages P0 (tranchage `13_coherence_globale.md`).

**Prérequis :** aucun · **Risque :** faible · **Heures :** 24 · **Parallélisable avec :** (aucune — prérequis universel)

### 6.1 Fichiers à créer / modifier / supprimer

#### Exceptions — `hydromodpy/core/exceptions.py` [F]
Refondre le fichier existant (30 L, squelette) en hiérarchie complète (~180 L). Racine : `HydroModPyError(Exception)` avec attribut `error_code: str = "HMPY.E000"`.

```python
# hydromodpy/core/exceptions.py
class HydroModPyError(Exception):
    error_code: ClassVar[str] = "HMPY.E000"
    def __init__(self, msg: str, *, context: dict | None = None) -> None: ...

# Config (E0xx)
class ConfigError(HydroModPyError): error_code = "HMPY.E001"
class PhysicalBoundsError(ConfigError): error_code = "HMPY.E002"
class ImplicitInferenceError(ConfigError): error_code = "HMPY.E003"
class SchemaVersionTooNewError(ConfigError): error_code = "HMPY.E004"
class UnitAliasConflict(ConfigError): error_code = "HMPY.E005"
class MissingForcingError(ConfigError): error_code = "HMPY.E006"

# Data (E1xx)
class DataError(HydroModPyError): error_code = "HMPY.E100"
class DataContractViolation(DataError): error_code = "HMPY.E101"
class DataLoadError(DataError): error_code = "HMPY.E102"
class NetworkError(DataError): error_code = "HMPY.E103"
class CacheCorruptionError(DataError): error_code = "HMPY.E104"

# Mesh/Spatial (E2xx)
class MeshError(HydroModPyError): error_code = "HMPY.E200"
class IncompatibleMeshError(MeshError): error_code = "HMPY.E201"

# Solver (E3xx) — base avec context (sim_id, run_id)
class SolverError(HydroModPyError):
    error_code = "HMPY.E300"
    def __init__(self, msg, *, sim_id: str | None = None, run_id: str | None = None, **kw): ...
class SolverDivergedError(SolverError): error_code = "HMPY.E301"
class SolverTimeoutError(SolverError): error_code = "HMPY.E302"
class SolverBinaryError(SolverError): error_code = "HMPY.E303"
class SolverMassBalanceError(SolverError): error_code = "HMPY.E304"
class SolverInputError(SolverError): error_code = "HMPY.E305"
class SolverEnvironmentError(SolverError): error_code = "HMPY.E306"
class IncompatibleCapabilitiesError(SolverError): error_code = "HMPY.E307"

# Pipeline (E4xx)
class PipelineError(HydroModPyError): error_code = "HMPY.E400"
class ExtractError(PipelineError): error_code = "HMPY.E401"
class ExportError(PipelineError): error_code = "HMPY.E402"
class DisplayError(PipelineError): error_code = "HMPY.E403"
class WorkspaceLockedError(PipelineError): error_code = "HMPY.E404"
```

Supprimer le fichier `hydromodpy/exceptions.py` racine (30 L, legacy) [K] après re-export temporaire vers `core.exceptions`.

#### Registre des champs canoniques — `hydromodpy/results/field_registry.py` [N]
Module central qui tranche les noms publics (pour display) vs chemins Zarr (pour stockage), unité CF-1.11, shape attendue, producteur (core ou plugin).

```python
# hydromodpy/results/field_registry.py
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True, slots=True)
class FieldDescriptor:
    public_name: str
    zarr_path: str
    cf_standard_name: str
    udunits: str
    shape: Literal["time_layer_face", "time_face", "face", "particles"]
    derived_by: Literal["core", "plugin"] = "core"
    description: str = ""

FIELD_REGISTRY: dict[str, FieldDescriptor] = {
    "head": FieldDescriptor(
        public_name="head", zarr_path="head",
        cf_standard_name="groundwater_level",
        udunits="m", shape="time_layer_face", derived_by="plugin",
        description="Hauteur piézométrique par couche et par face UGRID",
    ),
    "watertable_elevation": FieldDescriptor(
        public_name="watertable_elevation", zarr_path="derived/watertable_elevation",
        cf_standard_name="water_table_altitude", udunits="m",
        shape="time_face", derived_by="core",
        description="Altitude de la nappe = head couche supérieure saturée",
    ),
    "watertable_depth": FieldDescriptor(
        public_name="watertable_depth", zarr_path="derived/watertable_depth",
        cf_standard_name="depth_of_water_table_below_ground_surface",
        udunits="m", shape="time_face", derived_by="core",
    ),
    "seepage_mask": FieldDescriptor(  # scindé ex seepage_areas
        public_name="seepage_mask", zarr_path="derived/seepage_mask",
        cf_standard_name="land_binary_mask", udunits="1",
        shape="time_face", derived_by="core",
        description="Masque binaire 1=nappe affleurante, 0=sinon",
    ),
    "seepage_rate": FieldDescriptor(
        public_name="seepage_rate", zarr_path="derived/seepage_rate",
        cf_standard_name="water_flux_into_sea_water_from_rivers", udunits="m s-1",
        shape="time_face", derived_by="core",
    ),
    "concentration": FieldDescriptor(...),   # transport
    "recharge": FieldDescriptor(...),        # budget source
    "drain_flux": FieldDescriptor(...),      # budget drain
    # ... 18 total (voir doc 13 §3.1)
}

def get_field(name: str) -> FieldDescriptor:
    if name not in FIELD_REGISTRY:
        raise KeyError(f"Champ '{name}' non enregistré. Disponibles : {sorted(FIELD_REGISTRY)}")
    return FIELD_REGISTRY[name]

def list_public_names() -> list[str]: ...
def list_zarr_paths() -> list[str]: ...
```

#### Sérialisation canonique — `hydromodpy/core/io/canonical_json.py` [N]
Fonction pure `canonical_json(obj) -> str` avec `sort_keys=True`, `separators=(",",":")`, float `repr()` déterministe, gestion `Path`/`datetime`/`UUID`. Critique pour `sim_id = uuid5(NAMESPACE, canonical_json(config))`.

```python
# hydromodpy/core/io/canonical_json.py
import json, uuid
from datetime import datetime, date
from pathlib import Path

HYDROMODPY_NAMESPACE = uuid.UUID("8f7b1c9e-3d4a-4e5b-9c8a-1f2d3e4f5a6b")  # figé

def _default(o):
    if isinstance(o, (Path,)): return str(o)
    if isinstance(o, (datetime, date)): return o.isoformat()
    if isinstance(o, uuid.UUID): return str(o)
    if hasattr(o, "model_dump"): return o.model_dump(mode="json")
    raise TypeError(f"Non sérialisable : {type(o)}")

def canonical_json(obj) -> str:
    return json.dumps(obj, default=_default, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)

def sim_id_from_config(cfg_dict: dict) -> str:
    return str(uuid.uuid5(HYDROMODPY_NAMESPACE, canonical_json(cfg_dict)))
```

#### Renommages P0 tranchés par doc 13 [R]
Exécuter les renommages massifs en 1 seul commit par couple (via `git mv` + `grep -rl` pour call sites) :

| Ancien | Nouveau | Emplacement |
|---|---|---|
| `hydromodpy/project.py:Simulation` | `hydromodpy/simulation/api.py:Simulation` | classe façade exécution |
| `hydromodpy/results/simulation.py:Simulation` | idem : `SimulationView` | vue lecture seule catalog |
| `hydromodpy/data/planner.py:DataManagersPlanner` | `DataPlanner` | même fichier |
| `hydromodpy/analysis/calibration/core/parameters.py:ParamSpace` | `ParameterSpace` | — |
| `hydromodpy/simulation/adapters/base.py:SolverAdapter` | `SolverRunner` | Protocol |
| `hydromodpy/spatial/geographic/geographic.py:Geographic` | `CatchmentDelineation` | garder alias `Geographic = CatchmentDelineation` 2 phases |
| `hydromodpy/process/base/sinks_sources.py:SinkSource` | `SourceTerm` | convention PDE |
| `process/` (package) | `physics/` | — **différé à P13** (impact global) |
| `simulation/results/` | `simulation/extraction/` | collision avec `results/` top-level |
| `seepage_areas` (Zarr path + code) | scindé en `seepage_mask` + `seepage_rate` | cohérent avec `FIELD_REGISTRY` |

Laisser **alias de compatibilité** (`SolverAdapter = SolverRunner`, `Geographic = CatchmentDelineation`) marqués `DeprecationWarning` jusqu'à P13.

### 6.2 Tests à écrire

`tests/unit/core/test_exceptions.py` [N] (~40 L) :
- Tous les codes `HMPY.E0xx..E4xx` uniques.
- `SolverError(msg, sim_id="abc").error_code == "HMPY.E300"` et `.context["sim_id"] == "abc"`.
- `isinstance(SolverDivergedError("x"), HydroModPyError)`.

`tests/unit/core/test_canonical_json.py` [N] (~60 L) :
- `canonical_json({"b":1,"a":2}) == '{"a":2,"b":1}'` (sort).
- `canonical_json({"a":1.0}) == '{"a":1.0}'` (repr float stable).
- `sim_id_from_config(cfg) == sim_id_from_config(cfg)` (idempotent).
- Round-trip `Path`, `datetime`, `UUID`.

`tests/unit/results/test_field_registry.py` [N] (~50 L) :
- Aucun collision `public_name` vs `zarr_path`.
- Tous les CF `standard_name` dans un set autorisé (chargé depuis `data/cf-standard-name-table.xml` — vendu).
- `list_public_names()` stable (ordre alphabétique).

`tests/unit/test_renaming_backcompat.py` [N] (~30 L) :
- `from hydromodpy.simulation.adapters.base import SolverAdapter` émet `DeprecationWarning`.
- `SolverAdapter is SolverRunner` True.

### 6.3 Critère de succès

```bash
pytest tests/unit/core/test_exceptions.py \
       tests/unit/core/test_canonical_json.py \
       tests/unit/results/test_field_registry.py \
       tests/unit/test_renaming_backcompat.py -v
# 4 modules, ~20 tests, <2 s, 100 % PASS
pytest tests/unit/ tests/regression/fast/ -q  # aucune régression
```

### 6.4 Prompt Claude Code

```
Tu es un SENIOR PYTHON ENGINEER. Tu exécutes la phase P01 du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : créer migration/P01-foundations depuis dev-database
SPEC : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev/architecture_cible/14_plan_migration.md §6

LECTURE OBLIGATOIRE (dans cet ordre) :
1. CLAUDE.md (conventions projet)
2. architecture_cible/13_coherence_globale.md §3 (renommages canoniques)
3. architecture_cible/13_coherence_globale.md §11 (actions bloquantes P0)
4. audit_code/11_synthese_finale.md §8 (renommages nécessaires)

OBJECTIFS (à exécuter dans l'ordre) :
1. Refondre hydromodpy/core/exceptions.py (hiérarchie complète 42 classes, codes HMPY.E001..E404).
   Supprimer ensuite hydromodpy/exceptions.py après re-export transitoire.
2. Créer hydromodpy/results/field_registry.py avec FieldDescriptor frozen dataclass et
   FIELD_REGISTRY peuplé des 18 champs canoniques (head, watertable_elevation,
   watertable_depth, seepage_mask, seepage_rate, concentration, recharge, drain_flux,
   river_flux, well_flux, ghb_flux, chd_flux, storage_change, dem, geology, pathlines,
   velocity, wtd_flux). Scinder seepage_areas → seepage_mask + seepage_rate partout.
3. Créer hydromodpy/core/io/canonical_json.py avec canonical_json() et
   sim_id_from_config() basé sur uuid5.
4. Renommages P0 (git mv + remplacement call sites avec grep -rln) :
   - Project → Simulation (class dans project.py reste jusqu'à P08)
   - DataManagersPlanner → DataPlanner
   - ParamSpace → ParameterSpace
   - SolverAdapter → SolverRunner (laisser alias DeprecationWarning)
   - Geographic → CatchmentDelineation (alias)
   - SinkSource → SourceTerm
5. Écrire 4 fichiers de tests unitaires (tests/unit/core/test_exceptions.py,
   test_canonical_json.py, tests/unit/results/test_field_registry.py,
   tests/unit/test_renaming_backcompat.py).

CONTRAINTES :
- Tests existants doivent continuer à passer (aucune régression).
- Commits atomiques avec message "[P01] <action>".
- Tester à chaque étape : pytest tests/unit/ -x -q
- Ne PAS renommer process/ → physics/ (différé à P13).
- Ne PAS modifier simulation/results/ → simulation/extraction/ (P05).

RAPPORT FINAL : LOC ajoutées/supprimées, liste des renommages appliqués, nombre
de call sites modifiés par renommage, tests qui passent/échouent.

Écris TOUT en français technique.
```

---

## 7. Phase P02 — Storage (DuckDB 16 tables + Zarr v3 UGRID)

**Objectif :** implémenter le schéma DuckDB cible (16 tables + 4 vues dénormalisées + migrations réversibles), le layout Zarr v3 CF-1.11 + UGRID-1.0, le filelock single-writer, et le package portable `.hmp`.

**Prérequis :** P01 · **Risque :** moyen · **Heures :** 36 · **Parallélisable avec :** P03

### 7.1 Fichiers

#### Nouveau module `hydromodpy/results/catalog/` [F] (éclatement de `catalog.py` monolithe 920 L)

```
hydromodpy/results/
├── catalog/                         [F] était catalog.py monolithe
│   ├── __init__.py                  re-exporte SimulationCatalog
│   ├── catalog.py           [F]    SimulationCatalog classe (≤150 L, lifecycle)
│   ├── writes.py            [N]    write_field, write_timeseries, write_budget
│   ├── queries.py           [N]    find, best, worst, simulation(sim_id), sql()
│   ├── package.py           [N]    export_simulation/.hmp, import_simulation
│   └── migrations.py        [N]    SCHEMA_VERSION=3 + up/down dataclasses
├── schema/                          [F] était catalog_schema.py
│   ├── __init__.py
│   ├── tables.py            [N]    DDL des 16 tables
│   ├── views.py             [N]    DDL des 4 vues (v_simulation_summary, etc.)
│   ├── enums.py             [N]    CHECK ENUM (sim_status, flow_regime, ...)
│   └── indexes.py           [N]    idx_* et RTREE
├── storage/
│   ├── __init__.py
│   ├── zarr_store.py        [R]    depuis zarr_store.py, API + ZipStore finalize()
│   ├── spec.py              [N]    layout formel Zarr v3 (chemins, dtypes, attrs)
│   └── consolidate.py       [N]    finalize() : consolidate metadata + zip
├── locking.py               [N]    WorkspaceLock via filelock sur hydromodpy.duckdb.lock
├── provenance.py            [F]    SHA-256 fichier source (pas tobytes())
└── field_registry.py        [C]    (P01)
```

#### 16 tables DuckDB — `hydromodpy/results/schema/tables.py` [N]

DDL complet (≈350 L). Extraits critiques :

```python
SCHEMA_V3 = {
    "_schema_version": """
        CREATE TABLE IF NOT EXISTS _schema_version (
          version INTEGER PRIMARY KEY,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          description VARCHAR NOT NULL,
          hmp_version VARCHAR NOT NULL
        );
    """,
    "simulations": """
        CREATE TABLE IF NOT EXISTS simulations (
          sim_id UUID PRIMARY KEY,
          parent_sim_id UUID REFERENCES simulations(sim_id) ON DELETE SET NULL,
          project VARCHAR NOT NULL,
          name VARCHAR,
          solver VARCHAR NOT NULL,
          solver_category VARCHAR CHECK (solver_category IN
            ('flow','transport','particles','coupled')),
          status VARCHAR NOT NULL DEFAULT 'pending' CHECK (status IN
            ('pending','running','completed','diverged','timeout',
             'binary_error','input_error','environment_error','interrupted')),
          flow_regime VARCHAR CHECK (flow_regime IN ('steady','transient')),
          mesh_topology VARCHAR CHECK (mesh_topology IN ('dis','disv','disu')),
          period_start TIMESTAMPTZ, period_end TIMESTAMPTZ,
          bbox_min_x DOUBLE, bbox_min_y DOUBLE, bbox_max_x DOUBLE, bbox_max_y DOUBLE,
          crs_wkt VARCHAR, crs_epsg INTEGER,
          config_toml JSON NOT NULL,
          config_hash CHAR(64) NOT NULL,
          mesh_hash CHAR(64) NOT NULL,
          zarr_path VARCHAR NOT NULL,           -- relatif au workspace
          zarr_packed BOOLEAN NOT NULL DEFAULT FALSE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          completed_at TIMESTAMPTZ,
          error_kind VARCHAR, error_message VARCHAR,
          diagnostics_json JSON,
          CHECK (period_end IS NULL OR period_end >= period_start),
          CHECK (bbox_max_x IS NULL OR bbox_max_x >= bbox_min_x)
        );
        CREATE INDEX IF NOT EXISTS idx_sim_project ON simulations(project);
        CREATE INDEX IF NOT EXISTS idx_sim_config_hash ON simulations(config_hash);
    """,
    "runs_environment": """[N]... (git_sha, user_login, hostname, python_version,
        hmp_version, solver_binary_sha, pip_freeze JSON, run_fingerprint CHAR(64),
        step_durations_json JSON)""",
    "parameters": """... PK (sim_id, param_name, zone_id), parameterization ENUM...""",
    "metrics": """... PK (sim_id, station_id, variable, metric_name)... ordre (obs,sim)""",
    "timeseries": """... PK (sim_id, station_id, variable, datetime)...""",
    "budgets": """... component ENUM, PK (sim_id, timestep, zone_id, component)...""",
    "mass_balance": """... PK (sim_id, timestep), percent_error DOUBLE...""",
    "observation_points": """...""",
    "provenance": """... + input_artifact_id UUID (FK cross-DB cache.duckdb)...""",
    "calibration_sessions": """...""",
    "calibration_iterations": """... + sim_id FK + objective_vector DOUBLE[]...""",
    "calibration_iterations_params": """[N] PK (session_id, iteration, param_name)""",
    "geographic_features": """... geometry_kind ENUM, geoparquet_path relatif Zarr...""",
    "geographic_metadata": """... PK (sim_id, key)...""",
    "stations": """[N] PK (station_id, provider, variable), indépendant sims""",
    "tags": """[N] PK (sim_id, tag), remplace simulations.tags VARCHAR[]""",
    "observations": """[N] chroniques observées matérialisées""",
    "sensitivity_sessions": """[N] (différé P07 calibration)""",
    "sensitivity_indices": """[N]""",
    "simulation_cache": """[N] (params_hash PK, sim_id FK)""",
    "steps": """[N] checkpoint ledger (run_id, step_index, step_name, status,
        started_at, completed_at, fingerprint, checkpoint_path)""",
    "api_idempotency": """[N] (différé P12)""",
    "progress_log": """[N] (différé P12)""",
    "api_exports": """[N] (différé P12)""",
}
```

Ajouter les 4 vues dans `schema/views.py` : `v_simulation_summary`, `v_best_per_project` (QUALIFY ROW_NUMBER), `v_params_wide` (PIVOT), `v_metrics_wide`.

#### Migrations réversibles — `hydromodpy/results/catalog/migrations.py` [N]

```python
@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    up: Callable[[duckdb.DuckDBPyConnection], None]
    down: Callable[[duckdb.DuckDBPyConnection], None] | None = None

SCHEMA_VERSION = 3
MIGRATIONS: list[Migration] = [
    Migration(1, "Initial schema (pre-migration, 12 tables)", _noop_up, None),
    Migration(2, "Add PKs to timeseries/budgets/mass_balance/observation_points",
              up=_v1_to_v2_add_pks, down=_v2_to_v1_drop_pks),
    Migration(3, "Add runs_environment/tags/stations/observations + ENUMs",
              up=_v2_to_v3, down=_v3_to_v2),
]

def migrate(conn, target: int = SCHEMA_VERSION) -> None:
    current = conn.execute("SELECT MAX(version) FROM _schema_version").fetchone()[0] or 0
    if current > target:
        raise SchemaVersionTooNewError(
            f"DB en v{current}, binaire en v{target}. Mettre à jour HydroModPy.")
    for m in MIGRATIONS:
        if current < m.version <= target:
            conn.execute("BEGIN")
            try:
                m.up(conn)
                conn.execute("INSERT INTO _schema_version VALUES (?,CURRENT_TIMESTAMP,?,?)",
                             (m.version, m.description, hmp_version()))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
```

#### Layout Zarr v3 — `hydromodpy/results/storage/spec.py` [N]

Document formel du layout (chemins, dtypes, attributs CF/UGRID obligatoires). Fonction de validation `validate_zarr_layout(path) -> list[str]` (erreurs accumulées).

```python
ZARR_LAYOUT_V3 = {
    "root_attrs_required": ["Conventions", "sim_id", "hmp_version", "hmp_git_sha"],
    "root_attrs_conventions": "CF-1.11 UGRID-1.0",
    "groups": {
        "mesh/": {
            "required_vars": ["node_x", "node_y", "face_x", "face_y",
                              "face_node_connectivity", "z_interfaces",
                              "surface_top", "surface_bottom"],
            "mesh_scalar_attrs": {"cf_role": "mesh_topology",
                                  "topology_dimension": 2},
        },
        "time": {"dtype": "int64", "attrs": ["units", "calendar", "standard_name"]},
        "head/": {"chunks": (1, "n_layers", "n_cells"),
                  "compressor": "blosc_zstd_clevel3"},
        "derived/": {"optional_vars": ["watertable_elevation", "watertable_depth",
                                       "seepage_mask", "seepage_rate"]},
        "budget/": {"required_vars": ["recharge"],
                    "optional_vars": ["drain", "river", "well", "chd", "ghb",
                                      "storage"]},
        "geographic/": {"optional_vars": ["dem", "geology"],
                        "optional_files": ["watershed.parquet", "rivers.parquet"]},
        "crs": {"scalar", "attrs": ["grid_mapping_name", "crs_wkt", "epsg_code"]},
    },
}
```

#### Filelock — `hydromodpy/results/locking.py` [N]

```python
from filelock import FileLock, Timeout as LockTimeout
class WorkspaceLock:
    def __init__(self, workspace: Path, *, timeout: float = 2.0):
        self._lock = FileLock(workspace / "hydromodpy.duckdb.lock", timeout=timeout)
    def __enter__(self):
        try: self._lock.acquire()
        except LockTimeout:
            raise WorkspaceLockedError(
                f"Workspace déjà utilisé par un autre processus. "
                f"Lock : {self._lock.lock_file}. Voir hmp doctor.")
        return self
    def __exit__(self, *exc): self._lock.release()
```

#### Package `.hmp` — `hydromodpy/results/catalog/package.py` [N]

`.hmp = tar.zst` niveau 6 contenant `simulation.zarr/` + `catalog_rows.json` + `config.toml` + `manifest.json` + `LICENSE.txt`. Signature :

```python
def export_simulation(catalog, sim_id: str, out_path: Path) -> Path: ...
def import_simulation(catalog, hmp_path: Path, *, into_project: str | None = None) -> str: ...
```

#### À supprimer après migration [K]
- `hydromodpy/results/catalog.py` (monolithe 920 L, remplacé par package).
- `hydromodpy/results/catalog_schema.py` (remplacé par `schema/`).
- `hydromodpy/results/resample.py` (31 L, `NotImplementedError`).

### 7.2 Tests

`tests/unit/results/test_schema_integrity.py` [N] :
- Toutes les tables ont une PK.
- Tous les FK ont `ON DELETE CASCADE` ou `SET NULL` explicite.
- Toutes les colonnes `*_at` sont `TIMESTAMPTZ`.
- Énumérations CHECK couvrent tous les cas vus dans la codebase.

`tests/unit/results/test_migrations.py` [N] :
- Round-trip v1→v2→v3→v2→v1 préserve `COUNT(*)` sur chaque table partagée.
- Fixture `schema_v1.duckdb` fournie dans `tests/fixtures/catalog/`.

`tests/unit/results/test_zarr_spec.py` [N] :
- `validate_zarr_layout()` rejette un Zarr sans `Conventions="CF-1.11 UGRID-1.0"`.
- Chunking par défaut `(1, n_layers, n_cells)`.
- Compresseur BLOSC-ZSTD clevel=3.

`tests/unit/results/test_workspace_lock.py` [N] :
- Double acquisition → `WorkspaceLockedError`.
- Release propre après exception dans `with` block.

`tests/integration/test_hmp_package_roundtrip.py` [N] :
- Export `sim_id` → `.hmp` → import dans workspace vierge → même DuckDB + Zarr byte-identical.

### 7.3 Critère de succès

```bash
pytest tests/unit/results/ -v                           # nouveaux tests PASS
pytest tests/unit/ tests/regression/fast/ -q            # aucune régression
python -c "from hydromodpy.results.catalog import SimulationCatalog; \
           SimulationCatalog('/tmp/wsx').migrate()"      # migration 0→3 sans erreur
```

### 7.4 Prompt Claude Code

```
Tu es un DATA ENGINEER EXPERT DuckDB/Zarr. Tu exécutes la phase P02 du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : créer migration/P02-storage depuis dev-database (après merge de P01)
SPEC : architecture_cible/14_plan_migration.md §7
SPEC COMPLÈTE : architecture_cible/04_storage_ideal.md (lire §2.2 DDL complet, §3.1 Zarr layout, §4 migrations, §5 filelock, §6 .hmp)
TRANCHAGES : architecture_cible/13_coherence_globale.md §3.1 (nommage SimulationCatalog vs SimulationView)

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. hydromodpy/results/catalog.py (actuel, 920 L) — à éclater
3. hydromodpy/results/catalog_schema.py (actuel) — à remplacer
4. hydromodpy/results/zarr_store.py (actuel) — à déplacer sous storage/
5. audit_code/07_results_storage.md (critiques actuelles)

OBJECTIFS :
1. Créer la structure hydromodpy/results/catalog/ (catalog, writes, queries, package, migrations).
2. Créer hydromodpy/results/schema/ (tables.py avec DDL des 16 tables, views.py avec 4 vues,
   enums.py avec CHECK ENUM, indexes.py avec RTREE).
3. Créer hydromodpy/results/storage/ (zarr_store.py déplacé, spec.py layout formel,
   consolidate.py pour ZipStore finalize()).
4. Créer hydromodpy/results/locking.py (WorkspaceLock via filelock).
5. Refondre provenance.py (SHA-256 sur fichier source, pas tobytes()).
6. Implémenter les 3 migrations réversibles v1→v2→v3 avec fixtures fournies.
7. Écrire package.py (.hmp tar.zst) avec export_simulation / import_simulation.
8. Valider le layout Zarr contre spec.py (validate_zarr_layout).
9. Écrire tous les tests (schema_integrity, migrations, zarr_spec, workspace_lock,
   hmp_package_roundtrip).
10. Supprimer hydromodpy/results/catalog.py (monolithe) et catalog_schema.py après
    migration de tous les imports call sites.

CONTRAINTES :
- DuckDB ≥ 0.10 (ON CONFLICT DO UPDATE, QUALIFY, PIVOT, UUID DEFAULT uuid()).
- Extension spatial installée : INSTALL spatial; LOAD spatial; (pour BOX_2D, RTREE).
- Zarr v3 (PAS v2). Import zarr>=3.0.
- Tous chemins zarr_path RELATIFS au workspace dans DuckDB.
- Filelock hydromodpy.duckdb.lock, timeout 2 s.
- Chunking Zarr par défaut (1, n_layers, n_cells).
- Compresseur BLOSC-ZSTD clevel=3.
- Attributs root Zarr obligatoires : Conventions="CF-1.11 UGRID-1.0", sim_id, hmp_version, hmp_git_sha.
- FK ON DELETE CASCADE partout sauf parent_sim_id (SET NULL).
- TIMESTAMPTZ (pas VARCHAR) pour dates.
- Commits atomiques "[P02] <action>".
- Tests existants doivent continuer à passer (pytest tests/unit/ tests/regression/fast/).

RAPPORT FINAL : LOC ajoutées/supprimées, schéma DDL final (table → PK → FK), liste
migrations appliquées, taille .hmp de référence, latence open/close catalog.
```

---

## 8. Phase P03 — Config Pydantic

**Objectif :** Pydantic v2 strict avec `HydroModelBase`, `UiMeta` (frontend-ready), `Profile(IntEnum)`, `PartialHydroModPyConfig` (validation champ-par-champ <50 ms), discriminated unions, `PHYSICAL_BOUNDS`, refonte `HydroModPyConfig.from_toml`.

**Prérequis :** P01 · **Risque :** moyen · **Heures :** 32 · **Parallélisable avec :** P02

### 8.1 Fichiers

#### Base commune — `hydromodpy/core/config/base.py` [N]

```python
from pydantic import BaseModel, ConfigDict
class HydroModelBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        validate_assignment=True,
        str_strip_whitespace=True,
        arbitrary_types_allowed=False,
    )
```

Tous les modèles Pydantic du projet héritent de `HydroModelBase` (migration mécanique via grep+sed).

#### Profile — `hydromodpy/core/config/profile.py` [N]

```python
from enum import IntEnum
class Profile(IntEnum):
    USER = 1
    DEV = 2
    EXPERT = 3
    @classmethod
    def from_str(cls, s: str) -> "Profile": ...
```

Remplace `ParamLevel` (dict/Enum actuel). Comparaison numérique native `Profile.USER < Profile.DEV`.

#### UiMeta (frontend) — `hydromodpy/core/config/ui_meta.py` [N]

```python
from dataclasses import dataclass, asdict
from typing import Literal
WidgetType = Literal["input","textarea","slider","select","multiselect",
                     "checkbox","radio","file","directory","crs","bbox",
                     "coord","datetime"]

@dataclass(frozen=True)
class UiMeta:
    label_fr: str = ""
    label_en: str = ""
    help_fr: str = ""
    help_en: str = ""
    unit: str = ""
    widget: WidgetType = "input"
    placeholder: str = ""
    step: float | None = None
    scale: Literal["linear","log","symlog"] = "linear"
    group: str = ""
    order: int = 0
    profile: Literal["user","dev","expert"] = "user"
    examples: tuple = ()
    readonly: bool = False
    deprecated: bool = False
    def to_schema_extra(self) -> dict:
        return {f"x-{k.replace('_','-')}": v for k, v in asdict(self).items() if v not in ("", None, (), 0, False)}

def ui(**kw) -> dict:
    """Shortcut : Field(json_schema_extra=ui(label_fr=..., unit=..., widget=...))"""
    return {"json_schema_extra": UiMeta(**kw).to_schema_extra()}
```

#### Validation partielle — `hydromodpy/core/config/partial.py` + `partial_builder.py` [N]

```python
# partial.py
from contextvars import ContextVar
from enum import Enum
class ValidationMode(str, Enum):
    STRICT = "strict"
    PARTIAL = "partial"
    SCHEMA = "schema"

_mode: ContextVar[ValidationMode] = ContextVar("_mode", default=ValidationMode.STRICT)

def validation_mode() -> ValidationMode: return _mode.get()

@contextmanager
def partial_validation():
    token = _mode.set(ValidationMode.PARTIAL)
    try: yield
    finally: _mode.reset(token)

# partial_builder.py
def build_partial(model_cls: type[BaseModel]) -> type[BaseModel]:
    """Crée récursivement une version où tous les champs sont Optional."""
    ...

PartialHydroModPyConfig = build_partial(HydroModPyConfig)  # caché au boot
```

#### Bornes physiques — `hydromodpy/core/config/physical_bounds.py` [N]

```python
PHYSICAL_BOUNDS = {
    "K":  (1e-14, 1e2,   "m s-1", "Conductivité hydraulique"),
    "Kh": (1e-14, 1e2,   "m s-1", "Conductivité hydraulique horizontale"),
    "Kv": (1e-15, 1e1,   "m s-1", "Conductivité hydraulique verticale"),
    "Sy": (1e-4,  0.5,   "1",     "Porosité efficace / drainable"),
    "Ss": (1e-8,  1e-2,  "m-1",   "Emmagasinement spécifique"),
    "n":  (1e-3,  0.7,   "1",     "Porosité totale"),
    "n_eff": (1e-4, 0.5, "1",     "Porosité effective"),
    "vka": (1e-3, 1e3,   "1",     "Ratio Kv/Kh (NWT)"),
    "T":  (1e-10, 1e3,   "m2 s-1","Transmissivité"),
    "recharge": (0.0, 1e-5, "m s-1", "Recharge nette"),
}

def validate_physical_value(param: str, value: float, unit: str) -> None:
    if param not in PHYSICAL_BOUNDS: return
    lo, hi, expected_unit, desc = PHYSICAL_BOUNDS[param]
    if not (lo <= value <= hi):
        raise PhysicalBoundsError(
            f"{param}={value} hors bornes [{lo}, {hi}] {expected_unit} ({desc})")
```

#### HydroModPyConfig refactoré — `hydromodpy/core/config/hydromodpy_config.py` [F]

Réduire `from_toml` de 90 à ~20 L (tomlkit + setdefault + `model_validate`). Déplacer toute logique métier dans des validators Pydantic. Valider cross-section :
- `solver.engine ↔ packages.engine` identique.
- `flow_regime=transient ⇒ ic requis`.
- `[calibration] ⇒ flow.param_list non vide`.

Éclater `GeographicConfig` en `StandardGeographicConfig | SyntheticGeographicConfig` discriminé sur `source_mode`.

#### JSON Schema export — `hydromodpy/core/config/schema_export.py` [N]

```python
def export_schema(*, profile: Profile = Profile.USER, out: Path) -> Path:
    schema = HydroModPyConfig.model_json_schema()
    filtered = filter_schema_by_profile(schema, profile)
    filtered["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    filtered["$id"] = f"https://hydromodpy.org/schema/v1.0/{profile.name.lower()}.json"
    out.write_text(json.dumps(filtered, indent=2, ensure_ascii=False))
    return out

def filter_schema_by_profile(schema: dict, active: Profile) -> dict: ...
```

CLI : `hmp config schema --profile user --out schema.json`.

#### Forcing unifié — `hydromodpy/physics/base/forcing.py` [N]

```python
ForcingBase = Annotated[
    Union[ConstantForcing, CsvForcing, SyntheticForcing],
    Field(discriminator="mode")
]
class ConstantForcing(HydroModelBase): mode: Literal["constant"]; value: float; unit: str
class CsvForcing(HydroModelBase):      mode: Literal["csv"];      path: Path;    unit: str
class SyntheticForcing(HydroModelBase):mode: Literal["synthetic"];generator: str;parameters: dict
```

Élimine ~200 L de duplication (recharge, well, drain flux).

#### Timeseries variable factorisé — `hydromodpy/data/variables/common/timeseries.py` [N]

`TimeseriesVariableConfig` parent des 14 variables actuellement dupliquées (etp, humidity, runoff, etc.). Gain ~800 L supprimées en P04.

#### À supprimer [K]
- `hydromodpy/core/config/param_level.py` (ParamLevel Enum/dict) — remplacé par `Profile(IntEnum)` + `UiMeta.profile`.
- `hydromodpy/core/config/streamlit_config.py` — remplacé par `api/schemas/` (P12).

### 8.2 Tests

`tests/unit/core/config/test_hydromodpy_base.py` [N] :
- `HydroModPyConfig(extra_field=1)` → `ValidationError` (`extra="forbid"`).
- `model_dump(by_alias=True)` symétrique `from_toml`.

`tests/unit/core/config/test_profile_ordering.py` [N] :
- `Profile.USER < Profile.DEV < Profile.EXPERT`.

`tests/unit/core/config/test_partial_validation.py` [N] :
- `build_partial(HydroModPyConfig).model_validate({"flow": {"Sy": 0.1}})` passe.
- Latence p95 < 50 ms sur 1000 appels (pytest-benchmark).

`tests/unit/core/config/test_physical_bounds.py` [N] :
- `validate_physical_value("K", 1.5, "m/s")` → `PhysicalBoundsError`.
- Tous les paramètres enregistrés ont unit UDUnits valide.

`tests/unit/core/config/test_toml_roundtrip.py` [N] :
- `from_toml(p).to_toml(p2, profile="expert")` invariant champ-à-champ.

`tests/unit/core/config/test_cross_section_consistency.py` [N] :
- `solver.engine=modflow6` avec `packages.engine=modflow_nwt` → `ConfigError`.
- `flow_regime=transient` sans `[flow.ic]` → `ConfigError`.
- `[calibration]` sans `flow.param_list` → `ConfigError`.

`tests/unit/core/config/test_json_schema_export.py` [N] :
- `hmp config schema --profile user` produit un JSON valide draft 2020-12.
- Champs marqués `profile="expert"` absents du schéma `user`.

### 8.3 Critère de succès

```bash
pytest tests/unit/core/config/ -v
pytest tests/unit/ tests/regression/fast/ -q
hmp config /tmp/test.toml --profile user      # génère template user
hmp config schema --profile user --out /tmp/s.json && jq . /tmp/s.json >/dev/null
python -c "from hydromodpy.core.config.partial_builder import PartialHydroModPyConfig; \
           import time; t=time.perf_counter_ns(); \
           PartialHydroModPyConfig.model_validate({'flow':{'Sy':0.1}}); \
           print(f'{(time.perf_counter_ns()-t)/1e6:.2f} ms')"  # <50 ms
```

### 8.4 Prompt Claude Code

```
Tu es un EXPERT PYDANTIC v2. Tu exécutes la phase P03 du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P03-config depuis dev-database (parallèle à P02)
SPEC : architecture_cible/14_plan_migration.md §8
SPEC DÉTAILLÉE :
 - architecture_cible/02_config_pydantic.md (complet)
 - architecture_cible/11_frontend_ready.md §3 (validation partielle), §4 (UiMeta)
 - architecture_cible/13_coherence_globale.md §3 (nommages), §11.P0 item 1

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. audit_code/02_core_config.md (critiques actuelles)
3. audit_code/10_pydantic_models.md (inventaire ~140 modèles Pydantic)
4. hydromodpy/core/config/hydromodpy_config.py (actuel)
5. hydromodpy/core/config/generate_toml.py (à simplifier)

OBJECTIFS :
1. Créer hydromodpy/core/config/base.py avec HydroModelBase (extra="forbid", ...).
2. Créer profile.py avec Profile(IntEnum) USER/DEV/EXPERT.
3. Créer ui_meta.py avec dataclass UiMeta + helper ui(**kw).
4. Créer partial.py (ValidationMode enum + context manager) + partial_builder.py
   (build_partial fonction récursive).
5. Créer physical_bounds.py avec table PHYSICAL_BOUNDS et validate_physical_value.
6. Créer schema_export.py avec export_schema(profile, out) et filter_schema_by_profile.
7. Créer hydromodpy/physics/base/forcing.py avec Forcing discriminée
   (ConstantForcing | CsvForcing | SyntheticForcing).
8. Créer hydromodpy/data/variables/common/timeseries.py avec TimeseriesVariableConfig.
9. Faire hériter TOUS les modèles Pydantic du projet de HydroModelBase
   (grep -rl "BaseModel" hydromodpy/ + remplacement mécanique). Ajout ConfigDict
   uniforme via base.
10. Refondre HydroModPyConfig.from_toml (90 → ~20 L) : tomlkit + setdefault
    project_root/run_id + model_validate.
11. Ajouter model_validator(mode="after") pour cohérence cross-section
    (solver.engine ↔ packages, flow_regime ↔ ic, calibration ↔ param_list).
12. Éclater GeographicConfig en StandardGeographicConfig | SyntheticGeographicConfig
    discriminée sur source_mode.
13. Ajouter UiMeta (via ui(...)) sur TOUS les Field() publics des configs principales
    (priorité : FlowConfig, GeographicConfig, MeshConfig, RechargeConfig, PeriodConfig).
14. Supprimer param_level.py et streamlit_config.py après migration des call sites.
15. Écrire tous les tests listés (base, profile, partial, bounds, roundtrip,
    cross_section, json_schema).

CONTRAINTES :
- Pydantic v2 strict : pas de Config class, uniquement ConfigDict. Pas de @validator,
  uniquement @field_validator / @model_validator.
- Latence validate-field partielle < 50 ms p95 (pytest-benchmark).
- Tous les Field() critiques ont UiMeta (≥70% des Field publics en P03).
- Round-trip TOML sans perte (test obligatoire).
- tomlkit installé (ajouter au pyproject.toml si absent).
- Ne PAS encore renommer process/ → physics/ (P13). Mais créer physics/base/forcing.py
  qui sera ensuite migré (ok : physics/ coexiste avec process/ jusqu'à P13).
- Commits atomiques "[P03] <action>".

RAPPORT FINAL : LOC ajoutées/supprimées, nombre de modèles migrés vers HydroModelBase,
latence p95 validate-field, taille JSON Schema par profil, tests qui passent/échouent.
```

---

## 9. Phase P04 — Data input (HTTPClient + InputCatalog + sources + CLI + lockfile)

**Objectif :** refondre la couche d'ingestion de données : un seul `HTTPClient` durci, `InputCatalog` DuckDB 7 tables, pattern `DataSource` Protocol, sources consolidées (Hub'Eau×4, SIM2 unique, SHOM/BRGM/IGN), CLI `hmp data add/list/remove/prune/import`, lockfile `hydromodpy.lock` pour reproductibilité.

**Prérequis :** P01, P02, P03 · **Risque :** fort · **Heures :** 60 · **Parallélisable avec :** P05

### 9.1 Fichiers

#### Structure cible `hydromodpy/data/`

```
hydromodpy/data/
├── planner.py                  [F] DataPlanner (sans God class)
├── loader.py                   [R] ex runtime_loader.py — fonction pure load()
├── cache.py                    [N] InputCatalog (7 tables DuckDB)
├── lockfile.py                 [N] hydromodpy.lock roundtrip
├── base.py                     [N] DataSource Protocol + DataSourceRegistry
├── registry.py                 [R] ex store.py — @register_source decorator
├── contracts/
│   ├── station.py              [N] shapely.Point + pyproj.CRS + attrs
│   ├── point_record.py         [F] pd.Series obligatoire (plus Union)
│   ├── field_record.py         [F] xr.Dataset obligatoire
│   ├── load_result.py          [C]
│   └── cache_key.py            [N] CacheKey frozen slots + request_hash
├── schemas/
│   ├── timeseries.py           [N] TimeSeriesSchema (pandera)
│   ├── stations.py             [N] StationCollectionSchema (GeoParquet pandera)
│   ├── raster_dem.py           [N] DEMContract (Pydantic)
│   ├── raster_geology.py       [N] LithologyTableSchema
│   └── field_cf.py             [N] validate_cf_field(ds, variable)
├── common/
│   ├── http_client.py          [N] HTTPClient (retry, backoff, token bucket, SHA-256)
│   ├── geo_helpers.py          [F] + LRU sur pyproj.Transformer
│   ├── units.py                [C]
│   └── quality.py              [N] qualification (qflag) selon standard
├── sources/                    [R] ex variables/*/apis/
│   ├── base.py                 [N] alias DataSource pour compat
│   ├── registry.py             [N] @register_source entry-point aware
│   ├── hubeau/                 [N] (hydrometry, piezometry, waterquality, intermittency)
│   ├── brgm/                   [N] geology50k, geology1m
│   ├── shom/                   [N] oceanic (Refmar)
│   ├── ign/                    [N] bdalti (DEM)
│   ├── meteofrance/
│   │   └── sim2.py             [F] SIM2Client unique (9 variables)
│   └── custom/
│       └── file.py             [N] CustomFileSource (provider='custom')
├── cli/                        [N] toutes les sous-commandes hmp data
│   ├── add.py
│   ├── list.py
│   ├── remove.py
│   ├── prune.py
│   ├── export.py
│   ├── import_.py
│   └── check.py
└── migrate_v1_to_v2.py         [N] script one-shot migration cache legacy

# supprimés ~4500 LOC :
hydromodpy/data/climatic/               [K] 2700 L (climatic, sim2_API, drias*, safransurfex)
hydromodpy/data/common/base_manager.py  [K] 492 L
hydromodpy/data/common/base_field_manager.py [K]
hydromodpy/data/store.py                [K] remplacé par registry.py
hydromodpy/data/scaffold.py             [K] absorbé par workspace init
hydromodpy/data/subbasin/                [K] absorbé par spatial/
hydromodpy/data/variables/hydrometry/apis/ [K] migré vers sources/hubeau/
hydromodpy/data/variables/*/apis/sim2.py [K] 9× consolidé
```

#### HTTPClient — `hydromodpy/data/common/http_client.py` [N]

```python
import httpx
from pydantic_settings import BaseSettings

class HTTPClientSettings(BaseSettings):
    timeout_connect: float = 10.0
    timeout_read: float = 60.0
    max_retries: int = 6
    backoff_factor: float = 1.0
    max_backoff: float = 120.0
    rps_budget: float = 1.0

class HTTPClient:
    def __init__(self, *, name: str, rps_budget: float | None = None): ...
    def get(self, url: str, *, params=None, headers=None, stream=False) -> httpx.Response: ...
    def fetch_with_sha256(self, url: str, dest: Path) -> tuple[Path, str]: ...
    # Retry via tenacity : status_forcelist=[408,429,500,502,503,504]
    # Respect Retry-After header, exponentiel avec jitter.
    # Token bucket interne (rps limité).
    # SHA-256 calculé en streaming pendant le download.
```

#### InputCatalog — `hydromodpy/data/cache.py` [N]

7 tables : `_schema_version`, `artifacts`, `provenance`, `stations`, `coverage`, `failures`, `validation_reports`, `inference_audit`.

API :
```python
class InputCatalog:
    def __init__(self, duckdb_path: Path, data_dir: Path, *, default_ttl_days: int = 30): ...
    def get(self, key: CacheKey, *, ttl_days: int | None = None,
            force_refresh: bool = False) -> CacheHit | None: ...
    def put(self, key: CacheKey, payload: Path, *, unit: str, frequency: str,
            crs: str, source_type: SourceType, source_url: str | None,
            source_file: Path | None, loader_name: str, loader_version: str,
            format: ArtifactFormat, ttl_days: int | None = None,
            extras: dict | None = None) -> CacheHit: ...
    def list(self, *, variable=None, provider=None, ...) -> pd.DataFrame: ...
    def to_lockfile(self, path: Path) -> Path: ...
    def prune_expired(self, *, dry_run: bool = False) -> list[UUID]: ...
    def check_integrity(self, *, fix: bool = False) -> list[str]: ...
```

#### Lockfile — `hydromodpy/data/lockfile.py` [N]

YAML versionné co-géré avec `config.toml`. Contient par artefact `(variable, provider, station_id, period, sha256, fetched_at, source_url, loader_version)`.

CLI :
- `hmp lock update` : snapshot du cache actuel vers `hydromodpy.lock`.
- `hmp lock archive --to snapshots/2026-04-18.hmp` : tar.zst des artefacts référencés.
- `hmp lock restore snapshots/2026-04-18.hmp` : restauration.
- `hmp run --frozen` : utilise exclusivement les artefacts du lockfile, erreur sur miss.

#### DataSource Protocol — `hydromodpy/data/base.py` [N]

```python
from typing import Protocol, runtime_checkable
@runtime_checkable
class DataSource(Protocol):
    name: str
    variable: str
    version: str
    def fetch(self, extent: Extent, period: Period | None,
              cache: InputCatalog, **kwargs) -> LoadResult: ...
```

Registry via decorator `@register_source(variable, name)` + entry-points `"hydromodpy.datasource"`.

#### Schemas pandera — `hydromodpy/data/schemas/timeseries.py` [N]

```python
import pandera as pa
from pandera.typing import Series, Index, DateTime

class TimeSeriesSchema(pa.DataFrameModel):
    class Config:
        strict = "filter"
        coerce = True
    index: Index[DateTime] = pa.Field(unique=True, tz="UTC")  # DatetimeIndex UTC monotone
    value: Series[float] = pa.Field(nullable=True)
    qflag: Series[str] = pa.Field(isin=["good","doubtful","bad","missing"])
    origin: Series[str] = pa.Field(str_length={"min_value": 1})
```

#### CLI `hmp data` — `hydromodpy/data/cli/add.py` [N]

```python
def add(file: Path, *, variable: str, crs: str,
        provider: str, unit: str | None = None, frequency: str | None = None,
        station_id: str | None = None, replace: bool = False,
        dry_run: bool = False, format: str = "auto", force: bool = False) -> None:
    """
    1. Détecter format (csv, parquet, nc, tif, shp, gpkg, gpq)
    2. Lire + valider (pandera lazy=True, accumulate errors)
    3. Normaliser vers format pivot
    4. InputCatalog.put(source_type='custom_file', provider=provider, ...)
    """
```

### 9.2 Tests

`tests/unit/data/test_http_client.py` [N] : retry 429, Retry-After, timeout, SHA-256 streaming.
`tests/unit/data/test_input_catalog.py` [N] : get/put/transactions, invalidation SHA/TTL.
`tests/unit/data/test_lockfile.py` [N] : roundtrip archive→restore→--frozen.
`tests/unit/data/test_data_source_protocol.py` [N] : `isinstance(src, DataSource)` runtime_checkable.
`tests/unit/data/schemas/test_timeseries.py` [N] : rejet index non UTC, colonne manquante.
`tests/unit/data/sources/test_hubeau_hydrometry.py` [N] : VCR.py enregistré (mocké).
`tests/integration/test_data_add_custom_csv.py` [N] : flux complet `hmp data add file.csv`.
`tests/integration/test_cache_concurrence.py` [N] : pytest-xdist, 4 workers, 0 race condition.

### 9.3 Critère de succès

```bash
pytest tests/unit/data/ -v                      # toutes les unités PASS
pytest tests/integration/test_data*.py -v       # intégration PASS
hmp data add examples/piezo_sample.csv --variable piezometry --crs EPSG:2154 --provider labo
hmp data list --variable piezometry             # l'entrée apparaît
hmp lock update                                 # hydromodpy.lock créé
hmp run config.toml --frozen                    # utilise uniquement cache
pytest tests/unit/ tests/regression/fast/ -q    # aucune régression
```

### 9.4 Prompt Claude Code

```
Tu es un DATA ENGINEER SENIOR spécialisé APIs hydrologiques Hub'Eau / Météo-France.
Tu exécutes la phase P04 du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P04-data depuis dev-database (après merge P01, P02, P03)
SPEC : architecture_cible/14_plan_migration.md §9
SPEC DÉTAILLÉE :
 - architecture_cible/12_input_data_rethink.md (complet)
 - architecture_cible/03_data_contracts.md (contrats pandera/Pydantic, format pivot)
 - architecture_cible/13_coherence_globale.md §3.3 (arbitrage [data] vs [observations]+[recharge])

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. audit_code/03_data_layer.md (critiques)
3. hydromodpy/data/common/base_manager.py (492 L, à supprimer)
4. hydromodpy/data/runtime_loader.py (à renommer loader.py)
5. hydromodpy/data/registry/catalog_duckdb.py (à refondre en cache.py)
6. hydromodpy/data/variables/hydrometry/apis/hubeau.py (référence Hub'Eau)

OBJECTIFS (ordre strict) :
1. Créer hydromodpy/data/common/http_client.py avec HTTPClient durci
   (retry, backoff, token bucket, SHA-256 streaming). Dépendance httpx + tenacity.
2. Créer cache.py avec InputCatalog (7 tables : _schema_version, artifacts, provenance,
   stations, coverage, failures, validation_reports, inference_audit).
3. Créer lockfile.py (format YAML versionné).
4. Créer base.py avec DataSource Protocol + registry.py avec @register_source decorator
   (entry-points group "hydromodpy.datasource").
5. Créer schemas/ (timeseries.py pandera, stations.py GeoParquet pandera, raster_dem.py
   Pydantic, raster_geology.py, field_cf.py CF-1.11 validator).
6. Créer contracts/ (station.py shapely+pyproj, point_record.py pd.Series obligatoire,
   field_record.py xr.Dataset, cache_key.py frozen slots).
7. Créer sources/ structure + migrer hubeau×4, brgm, shom, ign, meteofrance/sim2.py
   UNIQUE (consolidation 9 variables).
8. Consolider SIM2 : un seul client qui sait récupérer etp, humidity, runoff,
   soil_moisture, temperature, wind, precipitation, radiation, snow. Supprime 9 fichiers
   existants.
9. Créer custom/file.py (CustomFileSource provider='custom').
10. Créer cli/ (add, list, remove, prune, export, import_, check) — enregistrer sous
    hmp data <verb>.
11. Créer migrate_v1_to_v2.py one-shot.
12. Créer hmp lock verb (update/archive/restore) + flag --frozen dans hmp run.
13. Supprimer (après migration call sites) :
    - hydromodpy/data/climatic/ (2700 L)
    - hydromodpy/data/common/base_manager.py
    - hydromodpy/data/common/base_field_manager.py
    - hydromodpy/data/store.py
    - hydromodpy/data/scaffold.py
    - hydromodpy/data/subbasin/
    - Tous variables/*/apis/sim2.py (9 fichiers)
14. Écrire tests unit + integration listés.

CONTRAINTES :
- Zéro urllib.request.urlretrieve dans le code (grep doit retourner 0 hits).
- Pandera lazy=True partout (accumulate errors).
- Cache invalidation par SHA-256 + TTL, JAMAIS mtime.
- Format pivot imposé par type : COG GeoTIFF Float32 (DEM), GeoParquet (vecteurs),
  CF-NetCDF 1.11 ou Zarr v3 (grille 2D+T), Parquet + sidecar JSON (chronique).
- TOML [data] contrôle cache (source, provider, offline, ttl) ;
  [observations] et [recharge] sections sémantiques séparées (arbitrage doc 13 §3.3).
- Tests VCR.py enregistrés pour Hub'Eau (pas d'appels réseau en CI).
- Commits atomiques "[P04] <action>".

RAPPORT FINAL : LOC ajoutées/supprimées (cible ~-4500 nettes), sources migrées,
tests qui passent/échouent, benchmark InputCatalog.get/put sous 1 ms.
```

---

## 10. Phase P05 — Solveurs (contrats plugin + 3 builtin refaits)

**Objectif :** consolider les 3 registres actuels (`simulation/adapters/_ADAPTERS`, `solver/compatibility`, `results/post_run._ADAPTER_REGISTRY`) en UN `SolverRegistry`, définir les 5 contrats Protocol (`SolverPlugin`, `SolverRunner`, `ResultExtractor`, `SolverConfig`, `ProcessKind`), et migrer NWT/MF6/Boussinesq comme plugins builtin.

**Prérequis :** P01, P02, P03 · **Risque :** fort · **Heures :** 48 · **Parallélisable avec :** P04

### 10.1 Fichiers

#### Contrats — `hydromodpy/solver/contracts/` [N]

```
hydromodpy/solver/contracts/
├── __init__.py              re-exporte SolverPlugin, SolverRunner, ResultExtractor...
├── plugin.py        [N]    SolverCapabilities (frozen) + SolverPlugin Protocol
├── runner.py        [N]    RunContext (frozen) + SolveResult + SolverRunner Protocol
├── extractor.py     [N]    ExtractContext + ResultExtractor Protocol
├── config.py        [R]    depuis solver/base/solver_config.py
├── process_kind.py  [N]    ProcessKind(str, Enum) + ProcessContract + PROCESS_CONTRACTS
└── errors.py        [C]    (re-exporte depuis core/exceptions.py SolverError, ...)
```

#### SolverPlugin — `hydromodpy/solver/contracts/plugin.py`

```python
from dataclasses import dataclass
from typing import Protocol, runtime_checkable, Iterable
from hydromodpy.solver.contracts.process_kind import ProcessKind

@dataclass(frozen=True, slots=True)
class SolverCapabilities:
    process_kinds: frozenset[ProcessKind]
    regimes: frozenset[str]                 # "steady", "transient"
    mesh_types: frozenset[str]              # "dis", "disv", "disu"
    depends_on: frozenset[ProcessKind] = frozenset()
    max_cells: int | None = None
    max_heterogeneity: float | None = None
    supports_dry_cells: bool = False
    supports_unconfined: bool = True
    supports_confined: bool = True
    requires_binary: bool = False
    binary_name: str | None = None
    binary_env_var: str | None = None

@runtime_checkable
class SolverPlugin(Protocol):
    name: str
    version: str
    capabilities: SolverCapabilities
    config_model: type[BaseModel]
    def runner(self, ctx: RunContext) -> SolverRunner: ...
    def extractor(self) -> ResultExtractor: ...
    # méthodes optionnelles détectées par hasattr :
    # validate_environment(), upgrade_config(old, from_version),
    # describe_diagnostics(runner), benchmark_cases() -> list[Path]
```

#### SolverRunner — `hydromodpy/solver/contracts/runner.py`

```python
@dataclass(frozen=True, slots=True)
class RunContext:
    sim_id: str
    run_id: str
    process_kind: ProcessKind
    solver_name: str
    mesh: HydroMesh
    domain: Domain
    fields: FieldParamCollection
    forcings: ForcingsBundle
    initial_conditions: InitialConditions
    time_grid: TimeGrid
    upstream: UpstreamResults         # handles vers sims amont (ex flow→transport)
    scratch_dir: Path
    config: BaseModel                  # instance de plugin.config_model
    overrides: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class SolveResult:
    output_dir: Path
    converged: bool
    iterations: int | None
    wall_time_s: float
    diagnostics: dict
    residual: float | None

@runtime_checkable
class SolverRunner(Protocol):
    ctx: RunContext
    def setup(self) -> None: ...
    def build(self) -> None: ...
    def solve(self) -> SolveResult: ...
    def cleanup(self) -> None: ...
```

#### ProcessKind — `hydromodpy/solver/contracts/process_kind.py`

```python
class ProcessKind(str, Enum):
    FLOW = "flow"
    VARIABLY_SATURATED = "variably_saturated"
    TRANSPORT = "transport"
    REACTIVE_TRANSPORT = "reactive_transport"
    PARTICLES = "particles"
    HEAT = "heat"
    DENSITY = "density"
    SURFACE_WATER = "surface_water"
    RECHARGE = "recharge"

@dataclass(frozen=True, slots=True)
class ProcessContract:
    required_fields: frozenset[str]
    optional_fields: frozenset[str]
    required_timeseries: frozenset[str]
    supported_metrics: frozenset[str]

PROCESS_CONTRACTS: dict[ProcessKind, ProcessContract] = {
    ProcessKind.FLOW: ProcessContract(
        required_fields=frozenset({"head"}),
        optional_fields=frozenset({"drawdown"}),
        required_timeseries=frozenset({"head"}),
        supported_metrics=frozenset({"nse","kge","rmse","pbias"}),
    ),
    ProcessKind.TRANSPORT: ProcessContract(...),
    # etc.
}
```

#### Registre unifié — `hydromodpy/solver/registry/` [F]

```
hydromodpy/solver/registry/
├── __init__.py          re-exporte SolverRegistry
├── registry.py    [N]   SolverRegistry (singleton) avec register/get/_discover
├── discovery.py   [N]   discover_entry_points(registry) via importlib.metadata
└── builtin.py     [N]   register_builtin_plugins(registry) pour NWT/MF6/Boussinesq
```

```python
class SolverRegistry:
    _instance: "SolverRegistry | None" = None

    @classmethod
    def instance(cls) -> "SolverRegistry":
        if cls._instance is None:
            cls._instance = cls()
            register_builtin_plugins(cls._instance)
            discover_entry_points(cls._instance)
        return cls._instance

    def register(self, plugin_cls: type[SolverPlugin]) -> type[SolverPlugin]: ...
    def get(self, name: str) -> SolverPlugin:
        if name not in self._plugins:
            raise KeyError(f"Solveur '{name}' inconnu. Disponibles : {sorted(self._plugins)}")
        return self._plugins[name]
    def list(self) -> list[str]: ...
```

#### Plugins builtin refaits — `hydromodpy/solver/modflow_nwt/`, `modflow6/`, `boussinesq/` [F]

Chaque solveur embarqué devient :
```
solver/<name>/
├── plugin.py         [N]   Plugin class implémentant SolverPlugin Protocol
├── runner.py         [N]   Runner class implémentant SolverRunner (setup/build/solve/cleanup)
├── extractor.py      [N]   Extractor class implémentant ResultExtractor
├── config.py         [N]   Plugin-specific Pydantic config (héritant HydroModelBase)
├── capabilities.py   [N]   SolverCapabilities déclarative
└── internals/              code interne (non exposé hors plugin)
```

#### Extracteurs sentinel-masking — `hydromodpy/solver/<name>/extractor.py` [F]

Le masking -50.0 (bassin côtier tronqué bug audit C13) migré dans chaque extracteur plugin (pas au cœur). Le cœur ne connaît que les `FieldDescriptor` canoniques.

#### DerivedComputerRegistry — `hydromodpy/results/virtual_fields.py` [F]

```python
# Renommé et enrichi (partie du P01 field_registry partage)
_DERIVED: dict[str, DerivedComputer] = {}

def register_derived(name: str):
    def deco(fn: Callable) -> Callable:
        if name in _DERIVED:
            raise ValueError(f"Dérivé '{name}' déjà enregistré.")
        _DERIVED[name] = fn
        return fn
    return deco

@register_derived("watertable_elevation")
def _wt_elevation(sim_zarr, mesh) -> np.ndarray: ...

@register_derived("watertable_depth")
def _wt_depth(sim_zarr, mesh) -> np.ndarray: ...

@register_derived("seepage_mask")
def _seepage_mask(sim_zarr, mesh) -> np.ndarray: ...

@register_derived("seepage_rate")
def _seepage_rate(sim_zarr, mesh) -> np.ndarray: ...
```

#### Fixes bugs physiques bloquants (audit C1-C8) [F]

Ces corrections sont indispensables AVANT tout release. À intégrer dans les extractors des plugins :
- **C1** : `solver/modflow_common/forcing_discretization.py` — `stream → RIV` (pas CHD), `ocean → GHB` (pas CHD).
- **C2** : drain `C = K*A/b` (pas `K*A`).
- **C3** : `spatial/field/core/field_param.py:745-749` — moyenne harmonique (pas arithmétique) pour K aux faces.
- **C4** : `solver/modflow_nwt/mt3dms/mt3dms.py` + `solver/modflow6/modflow6.py` — porosité ≠ Sy pour transport (utiliser `n_eff`).
- **C5** : convention VKA unifiée NWT↔MF6 (Kv en valeur, pas ratio).
- **C6** : `solver/modflow6/modflow6.py:2861` — `bf.HeadFile(...)` ne reçoit plus un `.tif`.
- **C7** : `simulation/results/extractors/derived.py` — `mass_accumulated = cumsum(flux * dt)` (pas `cumsum(flux)`).
- **C8** : `_SENTINEL_THRESHOLD = -50.0` retiré du cœur, migré dans chaque plugin.

#### À supprimer [K]
- `hydromodpy/simulation/adapters/registry.py:_ADAPTERS` (remplacé par `SolverRegistry`).
- `hydromodpy/solver/compatibility.py:PROCESS_SOLVER_REQUIREMENTS` (dict parallèle redondant).
- `hydromodpy/results/post_run.py:_ADAPTER_REGISTRY` (dict parallèle redondant).
- `hydromodpy/solver/base.py:Solver` ABC (fusionné avec `SolverAdapter` → `SolverRunner`).

### 10.2 Tests

`tests/unit/solver/test_plugin_registry.py` [N] : double `register` → `ValueError` ; `get("unknown")` → `KeyError` listant solveurs dispo.
`tests/unit/solver/test_capabilities_matching.py` [N] : plan `TRANSPORT` avec `depends_on=(FLOW,)` sans run FLOW préalable → `IncompatibleCapabilitiesError` au planner.
`tests/unit/solver/test_solver_runner_protocol.py` [N] : `isinstance(nwt_runner, SolverRunner)` True.
`tests/unit/solver/test_typed_errors.py` [N] : divergence simulée → `SolverDivergedError` → `simulations.status='diverged'`.
`tests/unit/solver/test_derived_registry.py` [N] : solveur n'écrivant que `head` produit `watertable_depth`, `seepage_mask`, `seepage_rate`.
`tests/unit/solver/test_bc_mapping.py` [N] : `stream→RIV`, `ocean→GHB`, `drain C=K·A/b` (audit C1-C2).
`tests/unit/solver/test_k_averaging.py` [N] : K aux faces = moyenne harmonique (audit C3).
`tests/unit/solver/test_porosity_transport.py` [N] : transport utilise `n_eff`, pas Sy (audit C4).
`tests/integration/test_solver_check_nwt.py`, `test_solver_check_mf6.py`, `test_solver_check_boussinesq.py` [N] : ~30 tests de conformité plugin par solveur.
CLI `hmp solver check <name>` [N] enregistré.

### 10.3 Critère de succès

```bash
pytest tests/unit/solver/ -v
pytest tests/integration/test_solver_check_*.py -v
hmp solver list                                  # affiche modflow_nwt, modflow6, boussinesq
hmp solver check modflow6                        # 30 tests PASS
hmp solver check boussinesq                      # 30 tests PASS
pytest tests/unit/ tests/regression/fast/ -q     # aucune régression
```

### 10.4 Prompt Claude Code

```
Tu es un EXPERT MODÉLISATION HYDROGÉOLOGIQUE + DESIGN PATTERNS. Tu exécutes la phase P05.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P05-solver depuis dev-database (parallèle P04, après P01/P02/P03)
SPEC : architecture_cible/14_plan_migration.md §10
SPEC DÉTAILLÉE :
 - architecture_cible/05_solver_contracts.md (complet)
 - architecture_cible/13_coherence_globale.md §3.1 (SolverRunner canonique vs SolverAdapter)

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. audit_code/05_process_solver.md (bugs C1-C8 physiques bloquants)
3. audit_code/06_simulation_engine.md (double abstraction Solver+SolverAdapter)
4. hydromodpy/solver/base.py, contracts.py (actuels)
5. hydromodpy/simulation/adapters/ (actuel)
6. hydromodpy/solver/modflow_common/forcing_discretization.py (bugs BC)
7. hydromodpy/spatial/field/core/field_param.py:745-749 (bug K arithmétique)

OBJECTIFS :
1. Créer hydromodpy/solver/contracts/ (plugin.py, runner.py, extractor.py, config.py,
   process_kind.py, errors.py qui re-exporte core/exceptions).
2. Créer hydromodpy/solver/registry/ (registry.py SolverRegistry singleton,
   discovery.py entry-points, builtin.py).
3. Migrer chaque solveur builtin (NWT, MF6, Boussinesq) vers structure
   plugin/runner/extractor/config/capabilities.
4. FIXES BUGS PHYSIQUES (bloquants, audit C1-C8) :
   - C1 : stream → RIV (forcing_discretization.py)
   - C1 : ocean → GHB (pas CHD)
   - C2 : drain C = K*A/b (pas K*A)
   - C3 : K aux faces = moyenne harmonique (field_param.py)
   - C4 : porosité transport = n_eff (pas Sy) — mt3dms.py et modflow6.py
   - C5 : VKA unifiée (valeur Kv, pas ratio)
   - C6 : bf.HeadFile ne reçoit plus .tif (modflow6.py:2861)
   - C7 : mass_accumulated = cumsum(flux*dt) (derived.py)
   - C8 : retirer _SENTINEL_THRESHOLD=-50.0 du cœur, migrer dans plugins
5. Refondre virtual_fields.py en DerivedComputerRegistry avec @register_derived.
6. Supprimer les 3 registres parallèles après migration des call sites :
   - simulation/adapters/registry.py:_ADAPTERS
   - solver/compatibility.py:PROCESS_SOLVER_REQUIREMENTS
   - results/post_run.py:_ADAPTER_REGISTRY
7. Supprimer solver/base.py:Solver ABC (fusionné dans Runner Protocol).
8. Renommer simulation/results/ → simulation/extraction/ (collision avec results/).
9. Enregistrer CLI hmp solver check <name> (~30 tests conformité par plugin).
10. Écrire tous les tests listés + fixtures plugin minimal (mysolver) pour tests plugin tiers.

CONTRAINTES :
- Protocol structurel @runtime_checkable partout (pas d'ABC).
- Signature canonique SolverRunner : setup/build/solve/cleanup (sans paramètres dans solve).
- RunContext et SolveResult FROZEN dataclass slots=True.
- Capacités déclaratives vérifiées au PLANNER (pas au run).
- Erreurs TYPÉES (SolverDivergedError, ...), pas de booléen.
- Chaque plugin expose capabilities.binary_name et binary_env_var si requires_binary.
- hmp solver check benchmark_cases() fournit ≥3 cas analytiques par plugin.
- Commits atomiques "[P05] <action>".
- Fixes bugs C1-C8 en commits séparés avec description du bug physique.

RAPPORT FINAL : LOC ajoutées/supprimées, 3 plugins conformes au Protocol (preuve
isinstance), 8 bugs physiques corrigés (tests validant chaque fix), registres unifiés
(preuve grep zero des 3 anciens).
```

---

## 11. Phase P06 — Pipeline (15 steps + checkpoint + BatchRunner)

**Objectif :** remplacer la triple orchestration (`project.py`, `workflow/pipelines/`, `runners/`) par UN `Pipeline` de 15 steps immutables, reproductibilité contractuelle via `run_fingerprint` / `sim_id = uuid5(...)`, checkpointing opt-in, `BatchRunner` process-level.

**Prérequis :** P01, P02, P03, P04, P05 · **Risque :** moyen · **Heures :** 40 · **Parallélisable avec :** —

### 11.1 Fichiers

#### `hydromodpy/simulation/pipeline/` [N]

```
hydromodpy/simulation/pipeline/
├── __init__.py
├── pipeline.py          [N]   Pipeline orchestrateur
├── step.py              [N]   PipelineStep Protocol[TIn, TOut]
├── state.py             [N]   14 frozen dataclasses (ValidatedState, ..., FinalState)
├── context.py           [N]   StepContext (run_id, logger, resources)
├── resources.py         [N]   ResourceHandle (ExitStack managée)
├── cache.py             [N]   StepCache content-addressable
├── checkpoint.py        [N]   CheckpointStore (pkl.zst + ledger DuckDB `steps`)
├── fingerprint.py       [N]   run_fingerprint = SHA-256 + sim_id = uuid5
├── errors.py            [C]   (re-exporte depuis core/exceptions)
└── steps/
    ├── step_00_validate.py
    ├── step_01_resolve.py
    ├── step_02_load_data.py
    ├── step_03_geographic.py
    ├── step_04_mesh.py
    ├── step_05_domain.py
    ├── step_06_plan.py
    ├── step_07_open_store.py
    ├── step_08_solve.py
    ├── step_09_extract.py
    ├── step_10_derive.py
    ├── step_11_aggregate.py
    ├── step_12_export.py
    ├── step_13_display.py
    └── step_14_finalize.py
```

#### Pipeline — `hydromodpy/simulation/pipeline/pipeline.py`

```python
@dataclass(frozen=True)
class PipelineConfig:
    checkpoint: bool = False
    cache: bool = True
    strict_reproducibility: bool = True
    timeout_s: float | None = None
    retry_policies: dict[str, RetryPolicy] = field(default_factory=dict)

class Pipeline:
    def __init__(self, steps: Sequence[PipelineStep], *, cfg: PipelineConfig): ...

    @classmethod
    def default(cls, cfg: HydroModPyConfig) -> "Pipeline":
        return cls(steps=DEFAULT_STEPS, cfg=PipelineConfig.from_hmp_config(cfg))

    @classmethod
    def from_toml(cls, path: Path) -> "Pipeline":
        return cls.default(HydroModPyConfig.from_toml(path))

    def run(self, initial_state: InputState) -> FinalState:
        with ExitStack() as stack:
            resources = stack.enter_context(self._make_resources())
            state = initial_state
            for i, step in enumerate(self._steps):
                state = self._run_step(step, state, resources, i)
            return state
```

#### Fingerprint & sim_id — `hydromodpy/simulation/pipeline/fingerprint.py`

```python
def run_fingerprint(cfg: HydroModPyConfig, inputs_fp: str,
                    env_lockfile_sha: str, hmp_version: str, hmp_git_sha: str,
                    solver_binary_sha: str, seed: int = 0) -> str:
    payload = canonical_json({
        "config": cfg.model_dump(mode="json"),
        "inputs_fp": inputs_fp,
        "env_lockfile_sha": env_lockfile_sha,
        "hmp": f"{hmp_version}+{hmp_git_sha}",
        "solver_binary_sha": solver_binary_sha,
        "seed": seed,
    })
    return hashlib.sha256(payload.encode()).hexdigest()

def sim_id_from_run(fingerprint: str) -> str:
    return str(uuid.uuid5(HYDROMODPY_NAMESPACE, fingerprint))
```

#### BatchRunner — `hydromodpy/batch/runner.py` [N] (remplace `analysis/batch/batch.py` 1828 L)

```python
class BatchRunner:
    def __init__(self, workspace: Workspace, *, n_workers: int | None = None,
                 backend: Literal["thread","process","dask"] = "process"): ...
    def run(self, configs: Iterable[HydroModPyConfig]) -> BatchResult: ...
    # Fan-out process-level, merge DuckDB via ATTACH...INSERT...DETACH.
```

#### Simulation API mince — `hydromodpy/simulation/api.py` [F] (remplace `project.py` 705 L → ≤150 L)

```python
class Simulation:
    def __init__(self, config: str | Path | HydroModPyConfig, *,
                 headless: bool = False) -> None:
        self._config = HydroModPyConfig.from_toml(config) if isinstance(config, (str, Path)) else config
        self._pipeline = Pipeline.default(self._config)

    @property
    def config(self) -> HydroModPyConfig: return self._config

    @property
    def plan(self) -> SimulationPlan: return self._pipeline.planner(self._config)

    def dry_run(self) -> SimulationPlan: return self.plan

    def run(self, *, name: str | None = None, project: str | None = None,
            tag: list[str] | None = None, **overrides) -> SimulationView:
        final_state = self._pipeline.run(InputState(config=self._config, ...))
        return SimulationView.from_state(final_state)

    def __enter__(self): return self
    def __exit__(self, *exc): self._pipeline.cleanup()
```

#### Logging — `hydromodpy/core/logging/structlog_setup.py` [N]

Configuration structlog JSONL → `workspace/logs/<run_id>.log`, agrégable via DuckDB `read_json_auto()`. `bind_contextvars(run_id=...)`.

#### À supprimer [K]
- `hydromodpy/project.py` (705 L, remplacé par `simulation/api.py`).
- `hydromodpy/workflow/` entier (absorbé dans `simulation/pipeline/`).
- `hydromodpy/simulation/execution/runner.py` (absorbé dans `step_08_solve.py`).
- `hydromodpy/analysis/batch/batch.py` (1828 L, remplacé par `batch/runner.py`).

### 11.2 Tests

`tests/unit/pipeline/test_step_purity.py` [N] : chaque step est pure (`asdict(in) == asdict(in)` après appel).
`tests/unit/pipeline/test_step_fingerprint_deterministic.py` [N] : deux appels → même fp.
`tests/unit/pipeline/test_pipeline_is_linear_dag.py` [N] : exactement 15 steps, `step[i].in_type == step[i-1].out_type`.
`tests/unit/pipeline/test_resume_after_failure.py` [N] : injection d'échec à chaque index 0..14.
`tests/validation/test_reproducibility.py` [N] : même TOML 2× → même fp + Zarr byte-identical.
`tests/validation/test_batch_determinism.py` [N] : 100 sims 1 worker vs 8 workers → résultats identiques.
`tests/unit/pipeline/test_pipeline_overhead.py` [N] : overhead hors solve <5 %.
`tests/unit/pipeline/test_interrupt_cleanup.py` [N] : `KeyboardInterrupt` ferme toutes resources.
`tests/unit/pipeline/test_pickleability.py` [N] : `pickle.dumps(cfg)` sur toutes classes publiques.

### 11.3 Critère de succès

```bash
pytest tests/unit/pipeline/ -v
pytest tests/validation/test_reproducibility.py -v
hmp run configs/demo.toml                     # exécute via Pipeline
hmp run configs/demo.toml --checkpoint        # avec reprise
hmp batch configs/batch.toml -j 4             # batch 4 workers
pytest tests/unit/ tests/regression/fast/ -q
```

### 11.4 Prompt Claude Code

```
Tu es un EXPERT ORCHESTRATION DE WORKFLOWS scientifiques (Prefect/Airflow/Luigi).
Tu exécutes la phase P06 du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P06-pipeline depuis dev-database (après P01-P05)
SPEC : architecture_cible/14_plan_migration.md §11
SPEC DÉTAILLÉE :
 - architecture_cible/06_pipeline_execution.md (complet, 15 steps, checkpoint, fingerprint)
 - architecture_cible/13_coherence_globale.md §3.1 (Simulation canonique), §11 P1 items 6-7

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. audit_code/06_simulation_engine.md (triple orchestration, God class)
3. hydromodpy/project.py (705 L, à supprimer)
4. hydromodpy/workflow/ (absorbé)
5. hydromodpy/simulation/execution/runner.py
6. hydromodpy/analysis/batch/batch.py (1828 L)

OBJECTIFS :
1. Créer hydromodpy/simulation/pipeline/ structure complète avec step.py Protocol.
2. Créer les 14 frozen dataclasses d'état (state.py).
3. Créer les 15 steps dans steps/step_NN_<name>.py (fonctions pures).
4. Créer fingerprint.py (run_fingerprint SHA-256 + sim_id uuid5).
5. Créer checkpoint.py (pkl.zst + table DuckDB `steps` ledger).
6. Créer cache.py (StepCache content-addressable workspace/.hmp/cache/<step_hash>/).
7. Créer resources.py (ResourceHandle ExitStack).
8. Créer pipeline.py avec Pipeline.default(cfg) factory et Pipeline.from_toml(path).
9. Créer simulation/api.py avec classe Simulation mince (≤150 L).
10. Créer batch/runner.py BatchRunner (process pool + merge DuckDB ATTACH/INSERT/DETACH).
11. Créer core/logging/structlog_setup.py (JSONL workspace/logs/<run_id>.log).
12. Supprimer : project.py, workflow/, simulation/execution/runner.py, analysis/batch/batch.py.
13. Migrer tous les call sites : from hydromodpy.project import Simulation
    → from hydromodpy.simulation.api import Simulation.
14. Écrire tous les tests (step_purity, reproducibility, batch_determinism, etc.).

CONTRAINTES :
- Chaque step est PURE : (StepState) → StepState. Frozen dataclass slots=True.
- Reproductibilité contractuelle : run_fingerprint DETERMINISTE via canonical_json.
- sim_id = uuid5(HYDROMODPY_NAMESPACE, run_fingerprint) — stable entre machines.
- Checkpointing opt-in (PipelineConfig.checkpoint=True).
- Dépendances : structlog, zstandard. Ajouter à pyproject.toml si absent.
- Toutes les classes publiques PICKLABLES (pas de Logger/DB connection dans les fields).
- Timeout par step via RetryPolicy (déclaratif dans PipelineConfig).
- Logging structuré structlog JSONL, bind_contextvars(run_id=...).
- Commits atomiques "[P06] <action>".
- Tests anti-régression : pytest tests/unit/ tests/regression/fast/ après chaque étape.

RAPPORT FINAL : LOC ajoutées/supprimées (cible ~-3000 nettes), preuve de
reproductibilité (2× même TOML → même sim_id), overhead pipeline <5%,
temps batch 100 sims 8 workers.
```

---

## 12. Phase P07 — Post-traitement (derived + metrics + display UGRID solver-agnostique)

**Objectif :** 4 packages cloisonnés (`results/derived` écrit lors de l'extraction · `results/metrics` fonctions pures · `results/exporters` refactoré CF-1.11 · `analysis/display` Protocol `Figure` classes). Suppression des ~4700 L de God modules (`suites.py`, `posthoc.py`, `visualization_*.py`).

**Prérequis :** P01, P02, P05, P06 · **Risque :** moyen · **Heures :** 36 · **Parallélisable avec :** P08

### 12.1 Fichiers

#### `hydromodpy/results/derived/` [N] (écrit dans Zarr au step 10 du pipeline)

```
results/derived/
├── flow.py           watertable_elevation, watertable_depth, outflow_drain
├── transport.py      mean_residence_time, breakthrough_curves
├── intermittency.py  drying_frequency, persistence_index
├── reducers.py       temporal reductions (min/max/p50/p95/mean)
└── pathlines.py      travel_time, endpoints, capture_zones
```

#### `hydromodpy/results/metrics/` [N] (fonctions pures, convention `(obs, sim)`)

```
results/metrics/
├── efficiency.py     nse, nse_log, kge_2009, kge_2012, kge_np
├── error.py          rmse, mae, mse
├── correlation.py    pearson, spearman, r_squared
├── signature.py      runoff_ratio, baseflow_index, flashiness_index
└── robust.py         pbias, median_nse
```

Formules exactes : doc 08 §3.3. Toutes fonctions signent `(obs: pd.Series, sim: pd.Series) -> float` ou `-> dict` (KGE). NaN-safe, alignement temporel via `_align(obs, sim)`.

#### `hydromodpy/results/exporters/` [F] (un fichier par format)

```
results/exporters/
├── netcdf.py      CF-1.11 + UGRID-1.0 strict
├── geotiff.py     COG + CRS WKT2 + nodata
├── geopackage.py  remplace Shapefile partout
├── shapefile.py   déprécié (legacy, avertissement)
├── vtu.py         ParaView compatible, fix bug mesh mixte tri/quad (audit C9)
├── csv.py         header standard (Frictionless datapackage sidecar)
└── waterml.py     [N] WaterML 2.0 pour interop WIS/WHOS
```

#### `hydromodpy/analysis/display/` [F]

```
analysis/display/
├── base.py            FigureSpec + Figure Protocol + BaseFigure ABC
├── theme.py           publication, presentation, draft (Theme.context())
├── colormaps.py       viridis, RdBu_r — BANNED={"jet","cool","rainbow","RdYlGn","hsv"}
├── units.py           UnitLabel Unicode (m³/s, mm/mois, µg/L)
├── layout.py          presets AGU/WRR (single_column, double_column, ...)
├── renderer.py        BackendManager.configure(backend="auto")
├── registry.py        @register + get(name) + list_specs() + supports(mesh, figure)
├── geo/               GeoFigureMixin cartopy (ccrs.epsg, scalebar, north arrow)
├── figures/
│   ├── spatial/       (11 cartes UGRID : watertable_map, watertable_depth,
│   │                   seepage_map, recharge_map, concentration_map, dem_map,
│   │                   geology_map, hydrography_map, flux_map, difference_map,
│   │                   watertable_triptych)
│   ├── section/       cross_section, multi_layer_section, quiver
│   ├── timeseries/    (9 : hydrograph, duration_curve, recession_curve,
│   │                    storage_discharge, seasonal_boxplot, autocorr,
│   │                    spectral, residuals, scatter_obs_sim)
│   ├── balance/       water_balance_bar, zonal_budget_stack
│   ├── particles/     pathlines_2d, capture_zones, residence_time_hist
│   ├── hydrochem/     piper, stiff, schoeller
│   ├── calibration/   convergence, pareto, sensitivity_bar
│   ├── comparison/    delta_map, obs_vs_sim_matrix
│   ├── tables/        stats_card
│   ├── animation/     time_evolution_mp4, drying_sequence
│   └── overview/      watershed_id_card
```

Protocol :
```python
@runtime_checkable
class Figure(Protocol):
    spec: FigureSpec
    def render(self, sim: SimulationView, ax: Axes, **opts) -> Axes: ...
    def plot(self, sim: SimulationView, **opts) -> MplFigure: ...  # utilise render
```

Règle d'or : **display ne calcule jamais** (interdit `top - head` ou `* 30*1000`) ; seuls slicing, masquage visuel, lissage visuel autorisés.

#### À supprimer [K] (~4700 L nettes)
- `display/suites.py` (904 L)
- `display/posthoc.py` + `posthoc_orchestration.py` (1244 L)
- `display/orchestration.py` (18 L)
- `display/flow_payloads.py`
- `display/visualization_results.py` (914 L)
- `display/visualization_watershed.py` (469 L)
- `display/adapters.py`
- `display/compare.py`
- `display/transport_plots.py` (fusionné dans `figures/spatial/`)
- `postprocess/timeseries/*_timeseries.py` (écriture CSV → `exporters/csv.py`)
- `postprocess/runner.py`

### 12.2 Tests

`tests/unit/results/metrics/test_nse_reference.py` [N] : MOPEX leaf river NSE = 0.81 (≤1e-6).
`tests/unit/results/metrics/test_kge_hydroeval_parity.py` [N] : `kge_2012` vs hydroeval ≤1e-6.
`tests/unit/results/metrics/test_align_nan_safe.py` [N] : masque NaN commun.
`tests/unit/results/derived/test_derived_registry.py` [N] : watertable_depth = surface_top - head.
`tests/unit/display/test_figure_contract.py` [N] : toutes figures ont `FigureSpec` + `render`.
`tests/unit/display/test_solver_agnostic.py` [N] paramétré sur 3 fixtures (`sim_boussinesq_dis`, `sim_modflownwt_dis`, `sim_modflow6_disv`) × 4 figures spatiales.
`tests/unit/display/test_no_banned_cmap.py` [N] : scan AST pour `cmap="jet"` etc.
`tests/unit/display/test_no_matplotlib_side_effects.py` [N] : `plt.style.use`, `matplotlib.use` interdits au top level.
`tests/unit/display/test_display_never_writes_zarr.py` [N] : grep statique.
`tests/unit/display/test_display_never_computes_derived.py` [N] : pas de `top - head` dans `display/`.
`tests/integration/test_netcdf_cf_ugrid_compliant.py` [N] : `cfchecks` + `xugrid.open_dataset`.

### 12.3 Critère de succès

```bash
pytest tests/unit/results/metrics/ tests/unit/results/derived/ tests/unit/display/ -v
pytest tests/integration/test_netcdf_cf_ugrid_compliant.py -v
python -c "from hydromodpy.analysis.display import get; get('watertable_map')"  # OK
cfchecks /tmp/out.nc                          # 0 warnings CF-1.11
python -c "import xugrid; xugrid.open_dataset('/tmp/out.nc')"  # OK
pytest tests/unit/ tests/regression/fast/ -q  # aucune régression
```

### 12.4 Prompt Claude Code

```
Tu es un EXPERT VISUALISATION SCIENTIFIQUE et POST-TRAITEMENT HYDROGÉOLOGIQUE.
Tu exécutes la phase P07 du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P07-postprocess depuis dev-database (après P06, parallèle P08)
SPEC : architecture_cible/14_plan_migration.md §12
SPEC DÉTAILLÉE :
 - architecture_cible/08_postprocess_display.md (complet)
 - architecture_cible/13_coherence_globale.md §2 (field_registry) §11 P2 item 13

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. audit_code/08_analysis_display.md (critiques)
3. hydromodpy/analysis/display/ (état actuel God modules)
4. hydromodpy/analysis/postprocess/
5. hydromodpy/results/exporters/ (à refactoriser CF-1.11)
6. hydromodpy/results/field_registry.py (créé en P01, guide strict)

OBJECTIFS :
1. Créer results/derived/ (flow, transport, intermittency, reducers, pathlines).
   Ces modules sont appelés au step_10_derive du Pipeline.
2. Créer results/metrics/ (efficiency, error, correlation, signature, robust) —
   fonctions pures, convention (obs, sim), NaN-safe.
3. Refactorer results/exporters/ : un fichier par format. netcdf.py CF-1.11+UGRID-1.0
   strict ; geopackage.py remplace shapefile ; vtu.py fix bug mesh mixte ; waterml.py NEW.
4. Refactoriser analysis/display/ :
   - base.py : FigureSpec + Figure Protocol + BaseFigure ABC
   - theme.py : Theme.context() local (jamais plt.style.use au top level)
   - colormaps.py : BANNED set
   - units.py : UnitLabel Unicode
   - renderer.py : BackendManager.configure(backend="auto") idempotent
   - registry.py : @register + get(name)
   - geo/ : GeoFigureMixin cartopy
   - figures/ : structure en 11 sous-dossiers (spatial/section/timeseries/...)
5. Migrer les figures existantes vers classes BaseFigure (une classe = une figure).
6. Supprimer les 4700 L de God modules (suites.py, posthoc*.py, orchestration*.py,
   visualization_*.py, flow_payloads.py, adapters.py, compare.py, transport_plots.py,
   postprocess/timeseries/*_timeseries.py, postprocess/runner.py).
7. Écrire tests :
   - metrics NSE référence MOPEX (0.81 ± 1e-6)
   - KGE hydroeval parity ≤1e-6
   - display solver-agnostic (3 fixtures × 4 figures)
   - no banned cmap / no mpl side effects / no zarr write / no derived computation
   - NetCDF CF-1.11+UGRID-1.0 compliant (cfchecks + xugrid)

CONTRAINTES :
- Règle d'or : display ne CALCULE jamais. Tout calcul → results/derived/ écrit en Zarr.
- Métriques convention (obs, sim) STRICTE. Corriger tous les call sites.
- matplotlib jamais au top level (pas d'import matplotlib.use, plt.style.use dans __init__).
- Colormaps : viridis par défaut, jamais jet/cool/rainbow/RdYlGn/hsv.
- NetCDF : Conventions="CF-1.11 UGRID-1.0", grid_mapping="crs", UDUnits lowercase.
- pdf.fonttype=42 (publication).
- BackendManager.configure idempotent (HYDROMODPY_NO_DISPLAY=1 → agg).
- Commits atomiques "[P07] <action>".

RAPPORT FINAL : LOC ajoutées/supprimées (cible ~-4700 nettes), nombre de figures
migrées, conformité cfchecks (0 warning), test solver-agnostic couvre DIS/DISV/DISU.
```

---

## 13. Phase P08 — API Python (hmp.* + Simulation + SimulationCatalog + SimulationGroup)

**Objectif :** API publique top-level fluent, 22 symboles, `_repr_html_` partout, lazy imports PEP 562, `py.typed` marker, types stricts (`xr.DataArray`, `pd.Series`, `pd.DataFrame`, `pathlib.Path`).

**Prérequis :** P01, P02, P03, P05, P06 · **Risque :** faible · **Heures :** 28 · **Parallélisable avec :** P07

### 13.1 Fichiers

#### `hydromodpy/__init__.py` [F] (≤80 L vs 319 L actuels)

```python
# hydromodpy/__init__.py
from __future__ import annotations
import importlib
from typing import TYPE_CHECKING

__version__ = "2.0.0"

__all__ = [
    "open", "Workspace", "doctor",
    "HydroModPyConfig",
    "Geographic", "Domain", "HydroMesh",
    "Flow", "Transport",
    "Modflow", "Modflow6", "Modpath7", "Mt3dms", "Boussinesq",
    "Simulation", "SimulationPlan", "SimulationCatalog",
    "SimulationView", "SimulationGroup",
    "compare",
    "__version__",
]

_LAZY = {
    "open": ("hydromodpy.results.catalog", "open"),
    "Workspace": ("hydromodpy.core.workspace", "Workspace"),
    "doctor": ("hydromodpy.core.diagnostics", "doctor"),
    "HydroModPyConfig": ("hydromodpy.core.config.hydromodpy_config", "HydroModPyConfig"),
    "Geographic": ("hydromodpy.spatial.geographic", "CatchmentDelineation"),  # alias
    "Domain": ("hydromodpy.spatial.domain", "Domain"),
    "HydroMesh": ("hydromodpy.spatial.mesh", "HydroMesh"),
    "Flow": ("hydromodpy.physics.flow", "Flow"),
    "Transport": ("hydromodpy.physics.transport", "Transport"),
    "Modflow": ("hydromodpy.solver.modflow_nwt", "Modflow"),
    "Modflow6": ("hydromodpy.solver.modflow6", "Modflow6"),
    "Modpath7": ("hydromodpy.solver.modflow_nwt.modpath", "Modpath7"),
    "Mt3dms": ("hydromodpy.solver.modflow_nwt.mt3dms", "Mt3dms"),
    "Boussinesq": ("hydromodpy.solver.boussinesq", "Boussinesq"),
    "Simulation": ("hydromodpy.simulation.api", "Simulation"),
    "SimulationPlan": ("hydromodpy.simulation.planning", "SimulationPlan"),
    "SimulationCatalog": ("hydromodpy.results.catalog", "SimulationCatalog"),
    "SimulationView": ("hydromodpy.results.simulation", "SimulationView"),
    "SimulationGroup": ("hydromodpy.results.simulation_group", "SimulationGroup"),
    "compare": ("hydromodpy.analysis.comparison", "compare"),
}

def __getattr__(name: str):
    if name in _LAZY:
        module_name, attr = _LAZY[name]
        val = getattr(importlib.import_module(module_name), attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module 'hydromodpy' has no attribute '{name!r}'")

def __dir__(): return sorted(__all__)

if TYPE_CHECKING:
    from hydromodpy.simulation.api import Simulation
    # etc. pour IDE support
```

Suppression des 207 lignes de PROJ_DATA muté à l'import → migré vers `core/io/crs.ensure_proj_data()` appelée paresseusement par `Geographic.__init__`.

#### `hydromodpy/core/diagnostics.py` [N]

```python
def doctor() -> DiagnosticReport:
    """Vérifie l'installation : pyproj, flopy, gmsh, modflow6, modflow-nwt,
    whitebox_workflows, DuckDB, Zarr, libglu1-mesa."""
```

#### `hydromodpy/results/simulation.py` [F]

Devient `SimulationView` (renommé depuis `Simulation`). Classe lecture seule d'un `sim_id` du catalog.

```python
class SimulationView:
    sim_id: str; name: str; project: str; solver: str; status: str
    path: Path; tags: list[str]
    config: HydroModPyConfig; plan: SimulationPlan
    nse: float | None; kge: float | None; rmse: float | None

    def field(self, variable: str, *, timestep: int | slice = -1,
              layer: int | None = None) -> xr.DataArray: ...
    def fields(self, variable: str) -> xr.DataArray: ...         # tous timesteps
    def timeseries(self, variable: str, *, station: str | None = None,
                   scope: Literal["station","basin","outlet"] = "station",
                   period: tuple[datetime, datetime] | None = None) -> pd.Series | pd.DataFrame: ...
    def budget(self, *, zone: str | None = None, component: str | None = None,
               period=None) -> pd.DataFrame: ...
    def plot(self, kind: str, *, save: Path | None = None, show: bool = True,
             ax: Axes | None = None, **kw) -> Axes: ...
    def export(self, fmt: Literal["netcdf","csv","geotiff","vtu","shapefile","gpkg"],
               *, variable: str = "*", path: Path | None = None, **kw) -> Path: ...
    def export_all(self, out_dir: Path) -> Path: ...              # P10
    def to_xarray(self) -> xr.Dataset: ...
    def inspect(self) -> dict: ...
    def __repr__(self) -> str: ...
    def _repr_html_(self) -> str: ...
    def __fspath__(self) -> str: return str(self.path)
```

#### `hydromodpy/results/simulation_group.py` [F]

```python
class SimulationGroup:
    @property
    def simulations(self) -> pd.DataFrame: ...
    def pivot(self, index, columns, values) -> pd.DataFrame: ...
    def to_frame(self, *, params: bool = True, metrics: bool = True,
                 metadata: bool = True) -> pd.DataFrame: ...  # ML-ready
    def filter(self, **criteria) -> "SimulationGroup": ...  # chaînable
    def best(self, metric: str = "nse") -> SimulationView: ...
    def worst(self, metric: str = "nse") -> SimulationView: ...
    def timeseries_matrix(self, variable: str, station: str) -> pd.DataFrame: ...
    def quantile_range(self, variable: str, station: str,
                       *, quantiles: tuple = (0.05, 0.5, 0.95)) -> pd.DataFrame: ...
    def export(self, fmt: str, path: Path) -> list[Path]: ...
    def _repr_html_(self) -> str: ...
```

#### `py.typed` marker — `hydromodpy/py.typed` [N] (fichier vide, PEP 561)

### 13.2 Tests

`tests/unit/test_public_api_symbols.py` [N] : `len(hmp.__all__) == 22`.
`tests/unit/test_lazy_import_perf.py` [N] : `python -X importtime -c "import hydromodpy"` <50 ms.
`tests/unit/results/test_simulation_view.py` [N] : tous les retours typés (xr.DataArray, pd.Series).
`tests/unit/results/test_simulation_group_ml_ready.py` [N] : `group.to_frame()` pour sklearn.
`tests/unit/test_repr_html.py` [N] : snapshot `_repr_html_` sur Simulation, SimulationView, SimulationCatalog, SimulationGroup, HydroMesh, Geographic.
`tests/unit/test_mypy_strict.py` [N] : `mypy --strict hydromodpy/` sur API publique.

### 13.3 Critère de succès

```bash
python -c "import hydromodpy as hmp; print(len(hmp.__all__))"  # 22
python -X importtime -c "import hydromodpy" 2>&1 | tail -1     # <50 ms
pytest tests/unit/test_public_api_*.py -v
mypy --strict hydromodpy/__init__.py                           # pass
pytest tests/unit/ tests/regression/fast/ -q
```

### 13.4 Prompt Claude Code

```
Tu es un EXPERT DESIGN D'API PYTHON scientifique (xarray, pandas, scikit-learn).
Tu exécutes la phase P08 du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P08-api depuis dev-database (parallèle P07, après P06)
SPEC : architecture_cible/14_plan_migration.md §13
SPEC DÉTAILLÉE :
 - architecture_cible/10_ux_cli_api.md (complet)
 - architecture_cible/13_coherence_globale.md §3.1 (nommages canoniques)

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. hydromodpy/__init__.py (319 L actuels, dont 207 L de PROJ_DATA à retirer)
3. hydromodpy/results/simulation.py (classe à renommer SimulationView)
4. hydromodpy/results/simulation_group.py (à enrichir)
5. audit_code/01_architecture_globale.md (API publique critiques)

OBJECTIFS :
1. Refondre __init__.py (≤80 L) : lazy imports via __getattr__ PEP 562 + __all__
   de 22 symboles exacts. Retirer les 207 L de PROJ_DATA.
2. Créer core/diagnostics.py avec doctor() pour hmp doctor.
3. Créer core/io/crs.py avec ensure_proj_data() appelée paresseusement par
   Geographic.__init__ (pas au top level).
4. Refondre results/simulation.py : renommer la classe Simulation en SimulationView.
   Ajouter _repr_html_, __repr__, __fspath__. Types de retour stricts (xr.DataArray,
   pd.Series, pd.DataFrame, pathlib.Path).
5. Enrichir results/simulation_group.py : pivot, to_frame (ML-ready),
   filter chaînable, best/worst, timeseries_matrix, quantile_range, _repr_html_.
6. Ajouter SimulationView.export_all(out_dir) placeholder (implémenté en P10).
7. Ajouter _repr_html_ sur HydroMesh, Geographic, SimulationCatalog, SimulationPlan.
8. Ajouter fichier hydromodpy/py.typed (PEP 561).
9. Tous les call sites `from hydromodpy.project import Simulation` migrés vers
   `from hydromodpy.simulation.api import Simulation`. Tous les `Simulation`
   (anciens simulation.py = view) migrés vers `SimulationView`.
10. Écrire tests listés (public_api_symbols, lazy_import_perf, simulation_view,
    simulation_group_ml_ready, repr_html, mypy_strict).

CONTRAINTES :
- API publique : 22 symboles EXACTS dans __all__.
- Lazy import perf : <50 ms (baseline 870 ms actuelle).
- Types de retour : JAMAIS Any, JAMAIS tuple anonyme. xr.DataArray / pd.Series /
  pd.DataFrame / pathlib.Path.
- _repr_html_ obligatoire sur Simulation, SimulationView, SimulationCatalog,
  SimulationGroup, HydroMesh, Geographic, SimulationPlan.
- mypy --strict doit passer sur hydromodpy/__init__.py et api.py / results/*.py.
- Convention "_catchment" magique → scope="basin" explicite.
- "station" nommée pour scope station, "outlet" pour outlet, "basin" pour agrégat.
- Commits atomiques "[P08] <action>".

RAPPORT FINAL : LOC ajoutées/supprimées, perf import (ms), top-level symbols liste,
tests mypy_strict pass/fail, snapshots _repr_html_ créés.
```

---

## 14. Phase P09 — CLI (hmp éclaté en verbes, argcomplete, wizard, messages Levenshtein)

**Objectif :** `__main__.py` (1223 L) éclaté en `_cli/commands/*`, 13 verbes canoniques + `completion`, `rich`/`questionary`, codes d'erreur `HMPY.Exxx` avec suggestions Levenshtein, exit codes POSIX normalisés.

**Prérequis :** P01, P03, P08 · **Risque :** faible · **Heures :** 24 · **Parallélisable avec :** P07, P10

### 14.1 Fichiers

#### `hydromodpy/_cli/` [N]

```
hydromodpy/_cli/
├── __init__.py
├── main.py            [N]   point d'entrée (argparse racine + dispatch)
├── parser.py          [N]   parse_args + sous-parsers + argcomplete
├── console.py         [N]   rich.console.Console (stdout + stderr)
├── errors.py          [N]   formatage RFC 7807-like pour CLI (code, ligne:col, suggestion)
├── levenshtein.py     [N]   suggest_section(wanted, available) pour typos
└── commands/
    ├── init_cmd.py        hmp init [--path PATH]
    ├── new_cmd.py         hmp new <project> [--workspace PATH]
    ├── config_cmd.py      hmp config template / wizard / check / schema
    ├── run_cmd.py         hmp run <toml> [--override K=V] [--dry-run] [--tag] [--name] [--checkpoint] [--frozen]
    ├── display_cmd.py     hmp display <toml>
    ├── list_cmd.py        hmp list [--project] [--nse] [--format]
    ├── show_cmd.py        hmp show <sim_id>
    ├── inspect_cmd.py     hmp inspect <sim_id>
    ├── export_cmd.py      hmp export <sim_id> --format <fmt>
    ├── import_cmd.py      hmp import <file.hmp>
    ├── compare_cmd.py     hmp compare <A> <B>
    ├── validate_cmd.py    hmp validate <toml>
    ├── delete_cmd.py      hmp delete <sim_id>
    ├── doctor_cmd.py      hmp doctor
    ├── completion_cmd.py  hmp completion bash/zsh/fish
    ├── solver_cmd.py      hmp solver list / check <name>
    ├── data_cmd.py        hmp data add/list/remove/prune/export/import/check (vient de P04)
    ├── lock_cmd.py        hmp lock update/archive/restore (vient de P04)
    └── test_cmd.py        [K] supprimé (réinvention pytest)
```

#### Exit codes POSIX — `hydromodpy/_cli/errors.py`

```python
EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_SOLVER = 4
EXIT_DATA = 5
EXIT_SIGINT = 130

def format_error(err: HydroModPyError, *, verbose: bool = False) -> str:
    """Format RFC 7807-like avec code HMPY.Exxx, localisation fichier:ligne:col,
    cause, suggestion Levenshtein si applicable."""
```

#### Wizard — `hydromodpy/_cli/commands/config_cmd.py`

```python
def wizard(out: Path) -> None:
    """questionary interactive pas à pas : workspace, project, solver, period,
    geographic source, flow regime, calibration?, batch?
    Résultat : TOML écrit + syntax highlight via rich.syntax.Syntax."""
```

#### argcomplete — enregistrement dans `pyproject.toml`

```toml
[project.scripts]
hmp = "hydromodpy._cli.main:main"
hydromodpy = "hydromodpy._cli.main:main"
```

`hmp completion bash|zsh|fish` génère la configuration à sourcer.

#### Point d'entrée unique

- **Supprimer** `hydromodpy/__main__.py` (1223 L) → remplacé par `_cli/main.py`.
- **Runners** : `hydromodpy/runners/` [R] renommés en `hydromodpy/_cli/commands/` (détection workflow `detect_workflow()` conservée dans `_cli/dispatcher.py`).

### 14.2 Tests

`tests/unit/cli/test_parser.py` [N] : chaque sous-commande valide.
`tests/unit/cli/test_exit_codes.py` [N] : usage error → 2, config error → 3, solver error → 4, SIGINT → 130.
`tests/unit/cli/test_levenshtein_suggestion.py` [N] : `[calibartion]` → « Voulez-vous dire `[calibration]` ? ».
`tests/integration/cli/test_hmp_run_demo.py` [N] : `hmp run demo.toml` avec solveur fake, exit 0, fichier sortie créé.
`tests/integration/cli/test_hmp_doctor.py` [N] : détection dépendances manquantes.
`tests/integration/cli/test_hmp_completion.py` [N] : bash/zsh/fish.

### 14.3 Critère de succès

```bash
hmp --version                         # affiche 2.0.0
hmp --help                            # 13 verbes + completion
hmp config wizard /tmp/c.toml         # wizard complet ≤5 min
hmp run /tmp/c.toml                   # exit 0
hmp run /tmp/bad.toml                 # exit 3, HMPY.E001 + suggestion Levenshtein
hmp doctor                            # diagnose install
pytest tests/unit/cli/ tests/integration/cli/ -v
pytest tests/unit/ tests/regression/fast/ -q
```

### 14.4 Prompt Claude Code

```
Tu es un EXPERT CLI DESIGN (httpie, poetry, ruff). Tu exécutes la phase P09.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P09-cli depuis dev-database (après P08, parallèle P07/P10)
SPEC : architecture_cible/14_plan_migration.md §14
SPEC DÉTAILLÉE :
 - architecture_cible/10_ux_cli_api.md §5 (arbre CLI canonique), §5.3 (auto-détection)
 - architecture_cible/13_coherence_globale.md §3 (nommages verbes)

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. hydromodpy/__main__.py (1223 L, à éclater)
3. hydromodpy/runners/__init__.py (detect_workflow, à conserver)
4. audit_code/01_architecture_globale.md §4 (CLI critiques)

OBJECTIFS :
1. Créer hydromodpy/_cli/ structure (main, parser, console, errors, levenshtein, commands/).
2. Migrer chaque sous-commande existante vers un fichier commands/<verb>_cmd.py
   (init, new, config, run, display, list, show, inspect, export, import, compare,
   validate, delete, doctor, completion).
3. Ajouter les verbes NOUVEAUX : show, compare, delete, doctor, completion.
4. Supprimer le verbe `hmp test` (réinvention pytest).
5. Intégrer les sous-verbes de phases précédentes :
   - hmp solver list/check (P05)
   - hmp data add/list/remove/prune/export/import/check (P04)
   - hmp lock update/archive/restore (P04)
6. Intégrer argcomplete (hmp completion bash/zsh/fish).
7. Wizard interactif (hmp config wizard) via questionary.
8. Messages d'erreur : format RFC 7807-like avec code HMPY.Exxx, localisation
   fichier:ligne:col, cause, suggestion Levenshtein.
9. Exit codes POSIX : 0/1/2/3/4/5/130.
10. Supprimer __main__.py après migration.
11. Renommer hydromodpy/runners/ → hydromodpy/_cli/commands/ (garder
    detect_workflow dans _cli/dispatcher.py).
12. Écrire tous les tests (parser, exit_codes, levenshtein, integration hmp run,
    hmp doctor, hmp completion).

CONTRAINTES :
- pyproject.toml [project.scripts] : hmp et hydromodpy pointent sur _cli.main:main.
- rich, questionary, argcomplete au pyproject.toml (ajouter si absent).
- Aucun print(...) direct : utiliser rich.console.Console (stderr pour erreurs).
- rich.syntax.Syntax pour highlight TOML dans wizard.
- Distance Levenshtein : suggestion si ≤2 caractères diff sur noms de section.
- Commits atomiques "[P09] <action>".

RAPPORT FINAL : LOC ajoutées/supprimées (cible ~-800 nettes depuis __main__),
13 verbes canoniques + 3 sous-verbes (solver/data/lock), tests exit codes pass.
```

---

## 15. Phase P10 — Export ALL (architecture structurée en sous-dossiers)

**Objectif :** `hmp export <sim_id> --all` produit une arborescence auto-documentée (config, metadata, parameters, metrics, timeseries, observations, budget, fields, mesh, geographic, figures, calibration, paths, validation, `hydromodpy.lock`, `export.sha256`). Formats standards (CF-NetCDF 1.11, GeoPackage, WaterML 2.0, Parquet).

**Prérequis :** P01, P02, P07, P08 · **Risque :** faible · **Heures :** 20 · **Parallélisable avec :** P09, P11

### 15.1 Fichiers

#### `hydromodpy/results/export_all.py` [N]

```python
def export_all(sim: SimulationView, out_dir: Path,
               *, compress: bool = True,
               include_figures: bool = True) -> Path:
    """Produit l'arborescence canonique documentée §15.2. Retourne out_dir."""
```

#### Arborescence produite par `export_all`

```
<sim_id>_export/
├── README.md                           # human-readable summary
├── MANIFEST.json                       # machine-readable index + SHA-256 chaque fichier
├── config/
│   ├── config.toml                     # config originale
│   ├── config_resolved.toml            # config après defaults
│   └── config_schema.json              # JSON Schema qui a validé
├── metadata/
│   ├── simulation.json                 # sim_id, project, solver, status, dates
│   ├── runs_environment.json           # git_sha, python, hmp_version, solver_binary_sha
│   ├── provenance.json                 # SHA-256 inputs
│   └── fingerprint.json                # run_fingerprint + seed
├── parameters/
│   ├── parameters.parquet              # (sim_id, param_name, zone_id, value, unit)
│   └── parameters.csv                  # vue tabulaire user-friendly
├── metrics/
│   ├── metrics.parquet
│   └── metrics_wide.csv                # PIVOT
├── timeseries/
│   ├── simulated/<station>.parquet
│   ├── observations/<station>.parquet
│   └── simulated_waterml2.xml          # WaterML 2.0 export
├── budget/
│   ├── budget.parquet                  # par (timestep, zone, component)
│   ├── mass_balance.parquet
│   └── budget_plot.png                 # si include_figures
├── fields/
│   ├── head.nc                         # CF-1.11 + UGRID-1.0
│   ├── watertable_depth.nc
│   ├── seepage_mask.nc
│   ├── seepage_rate.nc
│   ├── concentration.nc                # si transport
│   └── *.tif                           # GeoTIFF COG fallback QGIS
├── mesh/
│   ├── mesh.nc                         # UGRID-1.0 standalone
│   ├── mesh.gpkg                       # GeoPackage
│   └── mesh.vtu                        # ParaView
├── geographic/
│   ├── watershed.gpkg
│   ├── rivers.gpkg
│   ├── dem.tif
│   └── geology.tif
├── figures/                            # si include_figures
│   ├── watertable_map.pdf
│   ├── hydrograph.pdf
│   └── ...
├── calibration/                        # si calibration
│   ├── session.json
│   ├── iterations.parquet
│   └── convergence.pdf
├── paths/                              # si particles
│   └── pathlines.parquet
├── validation/                         # validation_reports de InputCatalog
│   └── *.json
├── hydromodpy.lock                     # snapshot des artefacts d'entrée
└── export.sha256                       # checksum pour intégrité (sha256sum format)
```

Mode compressé : `<sim_id>_export.tar.zst` niveau 6 (≈50 % gain typique vs plain).

#### Formats d'export [F]
- `results/exporters/netcdf.py` : CF-1.11 + UGRID-1.0.
- `results/exporters/geopackage.py` : GeoPackage (remplace Shapefile).
- `results/exporters/waterml.py` : WaterML 2.0.
- `results/exporters/geotiff.py` : COG Float32.
- `results/exporters/parquet.py` : sidecar JSON metadata.
- `results/exporters/csv.py` : Frictionless `datapackage.json` adjacent.

### 15.2 Tests

`tests/integration/test_export_all.py` [N] :
- Toutes les sections produites (config/, metadata/, ..., export.sha256).
- `cfchecks fields/head.nc` → 0 warning.
- `xugrid.open_dataset(mesh/mesh.nc)` → OK.
- Checksum `export.sha256` → `sha256sum -c` passe.
- `MANIFEST.json` indexe tous les fichiers.

`tests/integration/test_export_all_compressed.py` [N] :
- Mode `compress=True` produit `.tar.zst`, extraction donne arborescence identique.

`tests/unit/results/exporters/test_waterml_conformance.py` [N] :
- WaterML 2.0 validé contre XSD (ou `requests-get` XSD local).

### 15.3 Critère de succès

```bash
hmp export <sim_id> --all --out /tmp/export/
ls /tmp/export/<sim_id>_export/           # arborescence attendue
cfchecks /tmp/export/<sim_id>_export/fields/head.nc    # 0 warning CF-1.11
sha256sum -c /tmp/export/<sim_id>_export/export.sha256  # OK
pytest tests/integration/test_export_all*.py -v
pytest tests/unit/ tests/regression/fast/ -q
```

### 15.4 Prompt Claude Code

```
Tu es un EXPERT STANDARDS INTEROPÉRABILITÉ (CF, UGRID, OGC, INSPIRE, WaterML).
Tu exécutes la phase P10 du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P10-export depuis dev-database (après P07+P08, parallèle P09/P11)
SPEC : architecture_cible/14_plan_migration.md §15
SPEC DÉTAILLÉE :
 - architecture_cible/13_coherence_globale.md §5 item 7 (hmp export --all), §7.2 (arborescence)
 - architecture_cible/03_data_contracts.md (formats pivot)

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. hydromodpy/results/exporters/ (état actuel)
3. audit_code/07_results_storage.md (critiques formats)
4. audit_code/08_analysis_display.md (NetCDF non CF)

OBJECTIFS :
1. Créer hydromodpy/results/export_all.py avec export_all(sim, out_dir, compress,
   include_figures) produisant l'arborescence complète documentée §15.1.
2. Refondre results/exporters/netcdf.py strict CF-1.11 + UGRID-1.0 :
   - Conventions="CF-1.11 UGRID-1.0"
   - mesh variable avec cf_role="mesh_topology", topology_dimension=2
   - face_node_connectivity avec start_index=0 et _FillValue=-1
   - grid_mapping="crs" (WKT2 + EPSG)
   - standard_name CF pour tous les champs
   - UDUnits lowercase
   - calendar="standard"
3. Créer results/exporters/geopackage.py (remplace Shapefile pour vecteurs).
4. Créer results/exporters/waterml.py (WaterML 2.0 XML pour séries observées/simulées).
5. Créer results/exporters/parquet.py avec sidecar JSON metadata.
6. Refondre results/exporters/csv.py avec datapackage.json Frictionless.
7. Vérifier geotiff.py : COG Float32, overviews, tuilé.
8. Fix bug VTU mesh mixte tri/quad (audit C9).
9. Ajouter MANIFEST.json et export.sha256 à l'export.
10. Ajouter CLI hmp export --all dans _cli/commands/export_cmd.py.
11. Ajouter méthode SimulationView.export_all(out_dir) (placeholder P08).
12. Écrire tests integration + conformance WaterML.

CONTRAINTES :
- cfchecks zéro warning sur tous les .nc exportés.
- xugrid.open_dataset doit réussir sur mesh.nc standalone.
- GeoPackage avec CRS WKT2, nodata explicite.
- Compression tar.zst niveau 6 optionnelle.
- SHA-256 de chaque fichier dans MANIFEST.json et export.sha256 (format sha256sum).
- Commits atomiques "[P10] <action>".

RAPPORT FINAL : LOC ajoutées, conformité cfchecks (0 warning), taille export
référence (compressed vs plain), latence export_all pour une sim standard.
```

---

## 16. Phase P11 — Suite de tests cible (pyramide 4 niveaux + tolérances + CI)

**Objectif :** refondre `tests/` : pyramide 75/17/6/2 (unit/integration/validation/e2e), ~115 fichiers vs 283, budgets de temps stricts, 20 tests critiques, `TOLERANCES.md`, CI 4 profils.

**Prérequis :** transverse (suivre chaque phase) · **Risque :** moyen · **Heures :** 48 · **Parallélisable avec :** P10

### 16.1 Fichiers

#### Structure cible

```
tests/
├── pytest.ini          [N]   config sort de pyproject.toml
├── conftest.py         [F]   ≤80 L (seeds autouse, TZ=UTC, BLAS single-thread)
├── TOLERANCES.md       [N]   justification Richardson / machine ε / littérature
├── _helpers/           [R]   renommé depuis support/
│   ├── __init__.py
│   ├── fixtures_mesh.py
│   ├── fixtures_catalog.py
│   ├── fixtures_config.py
│   ├── fixtures_data.py
│   ├── strategies.py        Hypothesis strategies
│   ├── signatures.py        FieldSignature 12 stats
│   ├── signature_io.py      JSON stable keys sorted
│   ├── signature_assertions.py
│   └── signature_cli.py
├── unit/              ~80 fichiers
│   ├── core/
│   ├── data/
│   ├── spatial/
│   ├── physics/
│   ├── solver/{boussinesq,modflow6,modflow_nwt}/
│   ├── results/
│   ├── simulation/
│   └── analysis/
├── integration/       ~18 fichiers (NOUVEAU)
├── validation/
│   ├── analytical/{steady,transient}/
│   ├── mms/
│   └── twins/
├── e2e/               ~5 fichiers (NOUVEAU)
└── fixtures/                Données figées (catalog_v1.duckdb, etc.)
```

#### `pytest.ini` [N]

```ini
[pytest]
minversion = 8.0
testpaths = tests
markers =
    unit
    integration
    validation
    e2e
    smoke
    slow
    nwt
    mf6
    boussinesq
    petsc
    binary
    network
    gpu
    mpi
timeout = 120
timeout_method = thread
addopts = -ra --strict-markers --strict-config
```

#### Auto-tag par layer — `tests/conftest.py`

```python
import pytest
def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
            item.add_marker(pytest.mark.timeout(2.0))
        elif "tests/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.timeout(8.0))
        # etc.

@pytest.fixture(autouse=True)
def _deterministic():
    import numpy as np, random, os
    np.random.seed(0); random.seed(0)
    os.environ["TZ"] = "UTC"
    for v in ("OPENBLAS","MKL","OMP","RAYON"): os.environ[f"{v}_NUM_THREADS"] = "1"
```

#### Hook anti-subprocess unit — `tests/unit/conftest.py`

```python
@pytest.fixture(autouse=True)
def no_subprocess(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("Subprocess interdit dans tests/unit/ — déplacer vers integration/")
    monkeypatch.setattr("subprocess.Popen", _boom)
    monkeypatch.setattr("subprocess.run", _boom)
```

#### Les 20 tests critiques

Liste nominative (voir doc 09 §3) à écrire prioritairement :
1. `test_hydromodpycfg_forbids_extra_fields`
2. `test_param_level_filters_user_profile_template`
3. `test_toml_roundtrip_preserves_semantic_content`
4. `test_unit_registry_rejects_ambiguous_labels`
5. `test_unit_conversion_propagates_via_hypothesis`
6. `test_data_planner_infers_geology_from_zone_ids`
7. `test_data_planner_strict_mode_raises_on_implicit_inference`
8. `test_provenance_hash_is_deterministic_and_cross_platform`
9. `test_mesh_topology_face_node_roundtrip`
10. `test_mesh_handles_degenerate_shapes_1x1_1xN_Nx1`
11. `test_field_param_resolves_mesh_zones_with_defaults`
12. `test_flow_config_rejects_incompatible_bcs`
13. `test_flow_initial_conditions_inline_units_parse`
14. `test_solver_registry_discovers_entry_points`
15. `test_capabilities_mismatch_raises_before_run`
16. `test_boussinesq_jacobian_partition_triplets_3x3`
17. `test_boussinesq_runtime_scipy_sparse_analytical_3x3`
18. `test_catalog_schema_version_migration_raises_on_downgrade`
19. `test_metric_nse_kge_hypothesis_properties`
20. `test_simulation_plan_is_frozen_and_deterministic`

#### Benchmarks scientifiques — `tests/validation/`
- **Theis** confined : NSE > 0.999, ordre convergence ≥ 1.9.
- **Hantush-Jacob** leaky (MF6 only) : NSE > 0.99.
- **Ogata-Banks** 1D advection-dispersion : NSE > 0.95 à Péclet=100.
- **MMS Laplacien** stationnaire : slope ∈ [1.8, 2.2].
- **MMS diffusion transitoire**.
- **Twins** NWT/Boussinesq : `|K_rec - K_true| / K_true < 0.05`.

#### CI workflow — `.github/workflows/ci.yml` [F]

4 profils :
- `pre-commit` : ≤30 s (lint, mypy, unit smoke)
- `pr` : ≤5 min (unit + integration)
- `nightly` : ≤1 h (validation + e2e)
- `release` : ≤3 h (multi-OS multi-Python + benchmarks)

#### À supprimer [K] (~30 000 LOC tests)
- `tests/unit/launchers/test_model_calibration_launcher.py` (2722 L)
- `tests/unit/launchers/test_regional_lab_launcher.py` (735 L)
- `tests/unit/launchers/test_launcher_run_id.py` (690 L)
- `tests/unit/geographic_synthethic/`
- `tests/unit/validation/` (migré validation_cases/)
- `tests/regression/reference/golden_references/normal/`
- `tests/unit/geographic/test_geographic_legacy_characterization.py` (519 L)
- `tests/validation/helpers/*.py` (wrappers vides)

### 16.2 Tests

Méta-tests :
`tests/_meta/test_no_subprocess_in_unit.py` : grep AST.
`tests/_meta/test_budget_durations.py` : rapport timing distribution.
`tests/_meta/test_import_dag.py` : profondeur max 4, pas de cycles.

### 16.3 Critère de succès

```bash
pytest tests/unit/ --duration    # <45 s série, <15 s -n auto
pytest tests/integration/         # <5 min
pytest -m "validation and not slow"
pytest tests/ -n auto             # 0 fail, 0 error
coverage report --fail-under=80
```

### 16.4 Prompt Claude Code

```
Tu es un EXPERT QUALITÉ LOGICIELLE et TESTING scientifique. Tu exécutes la phase P11.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P11-tests depuis dev-database (transverse, rebasée en continu)
SPEC : architecture_cible/14_plan_migration.md §16
SPEC DÉTAILLÉE :
 - architecture_cible/09_tests_ideaux.md (complet)
 - audit_code/09_tests_audit.md (critiques)

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. tests/conftest.py actuel
3. tests/regression/golden_utils.py (1104 L, à scinder)
4. tests/unit/solver/test_boussinesq_backend.py (1642 L, à scinder)

OBJECTIFS (par sprints) :
Sprint 1 (fondations) :
- Créer tests/pytest.ini (sortir config de pyproject.toml)
- Refondre tests/conftest.py (≤80 L, seeds autouse, TZ UTC, BLAS single-thread,
  auto-tag par layer, timeouts)
- Créer tests/unit/conftest.py avec hook anti-subprocess
- Renommer tests/support/ → tests/_helpers/
- Scinder golden_utils.py (1104 L) en signatures/signature_io/signature_assertions/signature_cli
- Créer tests/TOLERANCES.md avec justification Richardson / ε machine / littérature
- Écrire les 20 tests critiques (voir §16.1)

Sprint 2 (validation scientifique) :
- Écrire tests/validation/analytical/steady/test_theis_confined.py (NSE > 0.999)
- Écrire test_hantush_jacob.py (MF6 only, NSE > 0.99)
- Écrire tests/validation/mms/test_laplacian_steady.py (slope 1.8-2.2)
- Écrire tests/validation/twins/test_twin_nwt.py et test_twin_boussinesq.py

Sprint 3 (intégration + nettoyage) :
- Écrire 5 scénarios d'intégration
- Supprimer tests/unit/launchers/* (~4000 L)
- Supprimer tests/unit/geographic_synthethic/, tests/unit/validation/
- Scinder test_boussinesq_backend.py en 4 fichiers ≤350 L

Sprint 4 (CI + dégraissage) :
- Refondre .github/workflows/ci.yml (4 profils : pre-commit, pr, nightly, release)
- Ajouter pyproject.toml coverage config (source, parallel, omit, fail_under=80)
- Créer tools/tests/audit_unit_purity.py (vérif anti-régression)
- Supprimer marker `fast/extensive` (auto-tag via chemin)

CONTRAINTES :
- Budgets temps (pytest_collection_modifyitems + timeout) :
  - unit : median 200ms, hard 2s
  - integration : median 5s, hard 8s
  - validation : median 60s, hard 120s
  - e2e : median 10min, hard 900s
- pytest.ini et pyproject.toml synchronisés
- Dépendances : pytest>=8, pytest-timeout, pytest-xdist, pytest-benchmark, hypothesis,
  pytest-cov. Ajouter à pyproject.toml si absent.
- Hypothesis profiles : dev (rapide), ci (medium), nightly (exhaustif)
- Tests parallélisables (pytest -n auto --dist=loadfile)
- Couverture ≥80% (fail_under)
- Commits atomiques "[P11] <action>"

RAPPORT FINAL : LOC tests supprimées (~30000), fichiers tests (283 → ~115),
durée unit série (~10min → ≤45s), coverage unit/branch %, 20 tests critiques écrits,
benchmarks analytiques réussis.
```

---

## 17. Phase P12 — API REST (FastAPI + Arrow IPC + WS/SSE + tests parité)

**Objectif :** `hydromodpy/api/` optionnel (`pip install hydromodpy[web]`), ~50 endpoints, validation champ-par-champ <50 ms, streaming Arrow IPC/GeoJSON/MessagePack, progression WS/SSE. Frontend Angular hors dépôt. Parité Python⇄HTTP testée en CI.

**Prérequis :** P03, P08, P09 · **Risque :** faible · **Heures :** 40 · **Parallélisable avec :** P11, P13

### 17.1 Fichiers

```
hydromodpy/api/                            [N]
├── __init__.py
├── server.py              FastAPI app factory
├── dependencies.py        DI (workspace, auth, config cache)
├── settings.py            Pydantic BaseSettings (host, port, token, cors)
├── progress.py            ProgressBus NDJSON v1 (Redis v2)
├── ws.py                  WebSocket handlers
├── sse.py                 Server-Sent Events handlers
├── cli.py                 `hmp api start/stop/status`
├── routers/
│   ├── health.py          /health /ready /version /openapi.json
│   ├── config.py          /config/schema /validate /validate-field /serialize /parse
│   ├── workspaces.py      /workspaces/current /inventory /projects
│   ├── simulations.py     POST /simulations/run + CRUD
│   ├── fields.py          GET /simulations/{sim_id}/fields/{name} (Arrow/GeoJSON/JSON)
│   ├── timeseries.py      GET .../timeseries/{station}, /compare
│   ├── figures.py         GET .../figures, POST .../render
│   ├── calibration.py     POST /calibration/run, sessions, progress
│   ├── data.py            GET /data/variables, /data/cache
│   └── exports.py         POST .../export, GET /exports/{token}
├── schemas/
│   ├── envelopes.py       Pagination envelope, ProblemDetails RFC 7807
│   ├── config.py
│   ├── simulation.py
│   ├── catalog.py
│   ├── calibration.py
│   ├── fields.py
│   └── progress.py
├── streaming/
│   ├── arrow.py           pyarrow IPC
│   ├── geojson.py
│   ├── msgpack.py
│   └── ndjson.py
└── services/
    ├── validation.py      FieldValidator (ValidationMode.PARTIAL)
    ├── i18n.py            messages fr/en
    └── schema.py          JSON Schema export filtré par profil
```

#### pyproject.toml extra `web`

```toml
[project.optional-dependencies]
web = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pyarrow>=16.0",
    "msgpack>=1.1",
    "anyio>=4",
    "python-multipart>=0.0.9",
]
```

#### Tables DuckDB ajoutées (via migration v4)
- `api_idempotency` (key PK, response_hash, created_at, expires_at)
- `progress_log` (run_id, event_seq PK, event_type, payload_json, timestamp)
- `api_exports` (token PK, sim_id FK, format, path, created_at, expires_at)

### 17.2 Tests

`tests/api/conftest.py` : TestClient FastAPI + workspace temp.
`tests/api/test_config_schema.py` : snapshots JSON Schema par profil.
`tests/api/test_validate_field.py` : latence p95 <50 ms, cas limites.
`tests/api/test_simulations_crud.py` : POST /simulations/run + GET /simulations/{id}.
`tests/api/test_fields_streaming.py` : Arrow IPC round-trip.
`tests/api/test_progress_ws.py` : WebSocket mock.
`tests/api/test_calibration_sse.py` : SSE avec Last-Event-ID.
`tests/api/test_parity_python_http.py` : même opération via `hmp.Simulation` et via REST → résultat identique.
`tests/api/test_auth.py` : local sans token, distant avec X-HydroModPy-Token.

Marker `pytest -m api`, exclu par défaut du PR CI si `pip install hydromodpy[web]` non fait.

### 17.3 Critère de succès

```bash
pip install -e ".[web]"
hmp api start --port 8765                    # démarre uvicorn
curl http://127.0.0.1:8765/health            # 200 {"status":"ok"}
curl http://127.0.0.1:8765/openapi.json      # schéma OpenAPI
curl -X POST http://127.0.0.1:8765/config/validate-field \
     -H "Content-Type: application/json" \
     -d '{"path":"flow.param_payload.Sy","value":1.5}'   # <50 ms p95
pytest tests/api/ -v -m api
pytest tests/unit/ tests/regression/fast/ -q
```

### 17.4 Prompt Claude Code

```
Tu es un EXPERT FASTAPI + STREAMING HTTP (Arrow IPC, WebSocket, SSE).
Tu exécutes la phase P12 du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P12-rest depuis dev-database (après P09, parallèle P11/P13)
SPEC : architecture_cible/14_plan_migration.md §17
SPEC DÉTAILLÉE :
 - architecture_cible/11_frontend_ready.md (complet, ~50 endpoints, UiMeta, ValidationMode)

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. hydromodpy/core/config/partial.py (créé en P03, ValidationMode)
3. hydromodpy/core/config/ui_meta.py (P03)
4. hydromodpy/results/catalog/ (P02, SimulationCatalog API)

OBJECTIFS :
1. Ajouter extra [project.optional-dependencies].web au pyproject.toml
   (fastapi, uvicorn, pyarrow, msgpack, anyio, python-multipart).
2. Créer hydromodpy/api/ structure (server, dependencies, settings, progress, ws, sse, cli).
3. Créer routers/ (health, config, workspaces, simulations, fields, timeseries,
   figures, calibration, data, exports).
4. Créer schemas/ Pydantic pour réponses (envelopes avec pagination + ProblemDetails
   RFC 7807).
5. Créer streaming/ (arrow IPC, geojson, msgpack, ndjson).
6. Créer services/validation.py avec FieldValidator (ValidationMode.PARTIAL).
7. Migration DuckDB v4 : ajouter tables api_idempotency, progress_log, api_exports.
8. Implémenter ProgressBus v1 via NDJSON append-only workspace/.hmp/progress/{run_id}.ndjson
   + inotify/polling 100ms.
9. Créer hmp api start/stop/status dans _cli/commands/api_cmd.py.
10. Auth : local 127.0.0.1:8765 sans token, distant X-HydroModPy-Token (comparaison
    constant-time).
11. ETag + Cache-Control: immutable sur réponses immuables (simulations completed).
12. Versioning via Accept: application/vnd.hydromodpy.v1+json.
13. Idempotency-Key stocké dans api_idempotency.
14. Écrire tests api/ :
    - test_config_schema (snapshot)
    - test_validate_field (latence <50ms p95)
    - test_simulations_crud
    - test_fields_streaming (Arrow IPC)
    - test_progress_ws (WebSocket mock)
    - test_calibration_sse (Last-Event-ID rejeu)
    - test_parity_python_http (CRUCIAL : même résultat via Python et via REST)
    - test_auth

CONTRAINTES :
- Endpoints optionnels : fail explicite si pip install hydromodpy[web] pas fait.
- JSON snake_case strict (aligné Pydantic).
- Erreurs RFC 7807 Problem Details (type, title, status, detail, pointer, locale).
- Streaming Arrow IPC : application/vnd.apache.arrow.stream.
- WebSocket + SSE fournis en parallèle (client peut choisir).
- Parité Python⇄HTTP testée en CI (invariant strict).
- Solveur MOCKÉ au niveau submit_run dans les tests.
- Commits atomiques "[P12] <action>".

RAPPORT FINAL : LOC ajoutées, ~50 endpoints fonctionnels, latence validate-field
p95 (<50 ms), parité Python/HTTP preuve, OpenAPI.json export.
```

---

## 18. Phase P13 — Nettoyage final (suppression legacy, renommages finaux, docs)

**Objectif :** purger les ~9600 LOC de code mort identifiées par l'audit, appliquer les renommages différés (`process/→physics/`), mettre à jour la documentation, retirer les alias `DeprecationWarning` de P01.

**Prérequis :** tout · **Risque :** faible · **Heures :** 16 · **Parallélisable avec :** —

### 18.1 Fichiers à supprimer [K] (~9600 LOC totale)

| Fichier / module | LOC | Justification |
|---|---|---|
| `hydromodpy/watershed/` (entier) | ~500 | façade historique absorbée dans `spatial/geographic` |
| `hydromodpy/data/climatic/*` (`climatic`, `sim2_API`, `drias*`, `safransurfex`) | ~2700 | consolidé en `sources/meteofrance/sim2.py` (P04) |
| `hydromodpy/solver/utils/mesh/cartesian_grid/examples/*` | ~2700 | à déplacer dans `docs/examples/` ou supprimer |
| `hydromodpy/analysis/display/visualization_results.py` | 914 | monolithe legacy (P07) |
| `hydromodpy/analysis/display/visualization_watershed.py` | 469 | side-effects import (P07) |
| `hydromodpy/analysis/display/suites.py` + `posthoc*.py` + `orchestration*.py` | ~2200 | God modules (P07) |
| `hydromodpy/spatial/geographic/pipeline.py` | 521 | wrapper redondant |
| `hydromodpy/solver/boussinesq/boussinesq.py` duplication `_resolve_*` | 700 | à factoriser avec `modflow_common/` |
| `hydromodpy/solver/boussinesq/smoothing.py` | 170 | zéro appel |
| `hydromodpy/core/tools/folder_root.py` | 149 | `input()` bloquant, non CI-compatible |
| `hydromodpy/exceptions.py` (racine, après re-export P01) | 30 | déplacé dans `core/exceptions.py` |
| `hydromodpy/results/resample.py` | 31 | `NotImplementedError` |
| `hydromodpy/simulation/settings.py` | 16 | DeprecationWarning |
| `hydromodpy/simulation/forcing/__init__.py` | 31 | re-exports |
| `hydromodpy/simulation/adapters/display/stub.py` + `postprocess/stub.py` | 72 | stubs |
| `hydromodpy/workflow/pipelines/process_simulation.py` | 33 | re-exports |
| Sous-commande CLI `hmp test` | ~300 | réinvention pytest (retiré P09) |
| Autres legacy divers | ~200 | audit §7 |

### 18.2 Renommages finaux [R]

| Ancien | Nouveau | Impact |
|---|---|---|
| `hydromodpy/process/` | `hydromodpy/physics/` | **global** — différé de P01. Requiert `git mv` + grep+sed sur ~3000 lignes d'imports |
| `hydromodpy/core/backends/` | `hydromodpy/core/whitebox/` | un seul backend |
| `hydromodpy/core/config/hydromodpy_config.py` | `hydromodpy/core/config/aggregate_config.py` | convention `foo_config.py` |
| Retrait alias `SolverAdapter` (DeprecationWarning P01) | — | nettoyage final |
| Retrait alias `Geographic` (DeprecationWarning P01) | — | `CatchmentDelineation` seul nom |
| `catch_name` → `project_name` dans `WorkspaceConfig` | — | cohérence API |
| `rmse_manual/nse_manual/kge_manual` (s'ils subsistent) | `rmse/nse/kge` | sans suffixe |

### 18.3 Documentation

- Mettre à jour `CLAUDE.md` avec la structure finale.
- Mettre à jour `docs/readthedocs/` (Sphinx RST ou MyST).
- Générer `docs/api_reference/` via `sphinx-autodoc`.
- Rédiger `docs/migration_guide.md` : anciens noms → nouveaux pour utilisateurs externes.
- Rédiger `docs/architecture.md` (résumé des 13 docs `architecture_cible/`).
- Ajouter `CHANGELOG.md` détaillé (BREAKING CHANGES listés).

### 18.4 Tests

`tests/unit/test_no_legacy_suffixes.py` [N] :
- Grep zero pour `*Schema`, `*Model` (suffixes Pydantic v1) dans code source.
- Grep zero pour `common/`, `utils/`, `helpers/`, `misc/`, `tools/` (interdits par doc 01).
- Grep zero pour `urlretrieve` (remplacé par `HTTPClient`).

`tests/unit/test_no_deprecated_aliases.py` [N] :
- `from hydromodpy.simulation.adapters.base import SolverAdapter` → `ImportError` ou absence.
- `hydromodpy.Geographic` → pointe vers `CatchmentDelineation` sans warning.

`tests/unit/test_profondeur_imports.py` [N] :
- Profondeur max imports HMPY = 4 (AST parse).

### 18.5 Critère de succès

```bash
cloc hydromodpy/                         # total ~52 000 L (baseline 72 000)
git grep -l "SolverAdapter" hydromodpy/  # zéro match
git grep -l "import hydromodpy.process"  # zéro match (tout migré vers physics)
pytest tests/unit/test_no_legacy_suffixes.py -v
pytest tests/ -n auto                    # TOUT passe
sphinx-build docs/ _build/               # docs générées
```

### 18.6 Prompt Claude Code

```
Tu es un EXPERT NETTOYAGE LEGACY et REFACTOR MÉCANIQUE. Tu exécutes la phase P13,
dernière phase du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE : migration/P13-cleanup depuis dev-database (dernière)
SPEC : architecture_cible/14_plan_migration.md §18
SPEC DÉTAILLÉE :
 - audit_code/11_synthese_finale.md §5 (code mort), §8 (renommages)
 - architecture_cible/13_coherence_globale.md (cohérence finale)

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. audit_code/11_synthese_finale.md sections 5, 8, 10
3. architecture_cible/01_structure_packages.md (structure cible finale)

OBJECTIFS :
1. SUPPRESSIONS (~9600 LOC totale) — par commits séparés avec justification :
   - hydromodpy/watershed/ (entier, ~500 L)
   - hydromodpy/data/climatic/* (~2700 L, consolidé P04)
   - hydromodpy/solver/utils/mesh/cartesian_grid/examples/* (déplacer vers docs/)
   - hydromodpy/analysis/display/visualization_*.py (déjà retirés P07 si oublié)
   - hydromodpy/spatial/geographic/pipeline.py (521 L)
   - hydromodpy/solver/boussinesq/ duplication _resolve_* (~700 L)
   - hydromodpy/solver/boussinesq/smoothing.py (170 L)
   - hydromodpy/core/tools/folder_root.py (149 L)
   - hydromodpy/exceptions.py (racine)
   - hydromodpy/results/resample.py (NotImplementedError)
   - hydromodpy/simulation/settings.py, forcing/__init__.py
   - simulation/adapters/display/stub.py, postprocess/stub.py
   - Sous-commande hmp test (si pas déjà retirée en P09)
2. RENOMMAGE DIFFÉRÉ P01 :
   - hydromodpy/process/ → hydromodpy/physics/ (git mv + grep -rln + sed pour imports)
3. RENOMMAGES FINAUX :
   - core/backends/ → core/whitebox/
   - core/config/hydromodpy_config.py → core/config/aggregate_config.py
   - catch_name → project_name dans WorkspaceConfig
   - Retirer alias DeprecationWarning de P01 (SolverAdapter, Geographic,
     DataManagersPlanner, ParamSpace, SinkSource)
4. DOCUMENTATION :
   - Mettre à jour CLAUDE.md avec structure finale
   - Créer docs/migration_guide.md (anciens noms → nouveaux pour users externes)
   - Créer docs/architecture.md (résumé 13 docs)
   - Créer CHANGELOG.md avec BREAKING CHANGES liste
   - sphinx-build docs/ _build/ (vérifier 0 erreur)
5. TESTS :
   - tests/unit/test_no_legacy_suffixes.py (Schema/Model/common/utils interdits)
   - tests/unit/test_no_deprecated_aliases.py
   - tests/unit/test_profondeur_imports.py (max 4)

CONTRAINTES :
- Chaque suppression en commit SÉPARÉ avec justification ("[P13] remove watershed/ — ...").
- Pour process/→physics/ : 1 commit pour git mv, 1 commit pour grep+sed imports,
  1 commit pour fix tests cassés éventuels.
- Vérifier AVANT suppression qu'aucun call site n'est actif : git grep "from hydromodpy.X"
- sphinx-build doit passer.
- cloc hydromodpy/ cible ~52 000 L (baseline 72 000).
- pytest tests/ -n auto doit TOUT passer.

RAPPORT FINAL : LOC supprimées totales, liste fichiers retirés, renommages appliqués,
docs générées, cloc avant/après.
```

---

## 19. Scripts bash runners

Chaque script lance sa phase Claude Code avec gestion d'erreur/retry/backoff, calquée sur `run_audit.sh`. Pattern commun :

```bash
#!/usr/bin/env bash
# run_migration_PXX.sh — lance la phase PXX via claude -p
set -euo pipefail
PROJECT="/home/bb/Documents/01_Git_Repository/02-HydroModPy-dev"
OUTPUT="$PROJECT/reporting/migration"
LOG="$OUTPUT/migration.log"
STDERR_TMP="$OUTPUT/.stderr_PXX"
MAX_RETRIES=8
mkdir -p "$OUTPUT"
# ... (helpers : log, notify, compute_wait copiés depuis run_audit.sh) ...
# ... (fonction run_phase adaptée) ...
run_phase "PXX_<slug>" "<PROMPT>"
```

Les 13 scripts sont générés dans la section annexe §21 (contenu complet). Ils sont également regroupés dans un script maître `run_migration_all.sh` qui exécute la séquence avec respect des dépendances.

---

## 20. Lecture croisée des incohérences

Toute contradiction entre deux documents `architecture_cible/*` est tranchée par `13_coherence_globale.md`. Liste indicative :

| Incohérence | Tranché par | Décision |
|---|---|---|
| `SolverRunner.solve(ctx)` (doc 06) vs `solve()` (doc 05) | doc 13 §2.1 | `solve()` sans arg, `ctx` est attribut |
| `sim_id` UUID v4 (doc 10) vs v5 déterministe (docs 06/13) | doc 13 §3.1 | **UUID v5** |
| `write_field(sim_id, name, values, ...)` | doc 13 §2.2 | signature canonique normalisée |
| Ordre métriques `(sim, obs)` (certains modules) vs `(obs, sim)` | doc 13 §10 #13 | **`(obs, sim)`** convention hydrologique |
| `ParamLevel` (doc 02) vs `UiMeta.profile` (doc 11) | doc 13 §3 | `UiMeta.profile` **remplace** `ParamLevel` |
| `[data]` vs `[observations]+[recharge]` | doc 13 §3.3 | **coexistence contrôlée** |
| `seepage_areas` monobloc vs `seepage_mask+seepage_rate` | doc 13 §3.1 | **scindé** (P01 `field_registry`) |

---

## 21. Annexe — Scripts bash runners complets (P01..P13)

Les scripts sont à écrire dans `$PROJECT/` avec `chmod +x`. Ils appellent `claude -p "<prompt>"` et journalisent dans `reporting/migration/*.log`.

Chaque script se charge de :
1. Créer la branche `migration/PXX-<slug>` depuis `dev-database`.
2. Lancer le prompt de la phase via `claude -p`.
3. Retry avec backoff exponentiel (rate limit, erreurs réseau) calqué sur `run_audit.sh`.
4. À la fin : `pytest tests/unit/ tests/regression/fast/ -q` et rapport.

Voir fichiers `run_migration_P01.sh` … `run_migration_P13.sh` créés en annexe de ce plan (section §23).

---

## 22. Ordre d'exécution recommandé et parallélisme

```
Semaine 1 :  P01 ................................ (séquentiel, base)
Semaine 2 :  P02 + P03 (parallèle, 2 devs)
Semaine 3 :  P04 + P05 (parallèle, 2 devs)
Semaine 4 :  P04 + P05 (suite)
Semaine 5 :  P06 .........................(séquentiel, intègre P02-P05)
Semaine 6 :  P06 (suite) + P11 (démarré en continu depuis Sem 2)
Semaine 7 :  P07 + P08 (parallèle)
Semaine 8 :  P09 + P10 + P11 (parallèle)
Semaine 9 :  P12 + P11 (finalisation)
Semaine 10 : P13 (nettoyage final)
Semaine 11 : validation finale, docs, release RC
```

**Avec 1 seul dev (mode séquentiel) :** 11 semaines TFT.
**Avec 2 devs + 1 reviewer :** 7 semaines (parallélisation P02||P03, P04||P05, P07||P08, P09||P10||P11).

---

## 23. Scripts bash — contenu complet

Les scripts suivants sont à sauver dans `$PROJECT/scripts/migration/` puis rendus exécutables (`chmod +x *.sh`). Un script maître `run_migration_all.sh` orchestre la séquence.

### 23.1 Fichiers générés

Les scripts bash ont été générés dans `scripts/migration/` :

```
scripts/migration/
├── _lib.sh                               # helpers communs (log, retry, backoff, compute_wait)
├── run_migration_all.sh                  # orchestrateur global (séquentiel ou --parallel)
├── run_migration_P01_foundations.sh
├── run_migration_P02_storage.sh
├── run_migration_P03_config.sh
├── run_migration_P04_data.sh
├── run_migration_P05_solver.sh
├── run_migration_P06_pipeline.sh
├── run_migration_P07_postprocess.sh
├── run_migration_P08_api.sh
├── run_migration_P09_cli.sh
├── run_migration_P10_export.sh
├── run_migration_P11_tests.sh
├── run_migration_P12_rest.sh
└── run_migration_P13_cleanup.sh
```

Chaque script `run_migration_PXX_*.sh` :
1. Source `_lib.sh` (helpers retry/backoff).
2. Crée (ou checkout) la branche `migration/PXX-<slug>` depuis `dev-database`.
3. Lance `claude -p "<prompt>"` avec le prompt court de référence (qui pointe vers
   la section `§X` du plan, où Claude lit lui-même le prompt détaillé).
4. Gère rate limit, quota journalier, erreurs réseau avec backoff exponentiel
   jusqu'à `MAX_RETRIES=8`.
5. Journalise dans `reporting/migration/migration.log`.
6. Après succès du prompt, lance `validate_phase` :
   `pytest tests/unit/ tests/regression/fast/ -q --timeout=120` en mode headless.
7. Propose la commande de merge manuel vers `dev-database`.

### 23.2 Usage

```bash
# Une phase unique
tmux new-session -s mig_P01 './scripts/migration/run_migration_P01_foundations.sh'

# Toutes les phases en mode séquentiel (1 dev)
tmux new-session -s mig_all './scripts/migration/run_migration_all.sh'

# Parallélisme (2 devs, exécute les phases compatibles en parallèle)
tmux new-session -s mig_par './scripts/migration/run_migration_all.sh --parallel'

# Reprendre à partir d'une phase
./scripts/migration/run_migration_all.sh --start P06

# Exécuter seulement certaines phases
./scripts/migration/run_migration_all.sh --only P02,P03

# Voir le plan sans exécuter
./scripts/migration/run_migration_all.sh --dry-run
```

### 23.3 Extrait du prompt générique injecté dans chaque script

Le prompt court dans chaque script délègue l'instruction détaillée au plan lui-même :

```
Tu exécutes la phase PXX du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE COURANTE : migration/PXX-<slug> (déjà créée par le script)
PLAN DE MIGRATION : architecture_cible/14_plan_migration.md — section §X

Lis la section §X du plan. Le prompt détaillé contenu dans cette section est ta feuille
de route officielle : suis-le à la lettre.

LECTURE OBLIGATOIRE :
1. CLAUDE.md
2. architecture_cible/14_plan_migration.md (section §X complète)
3. Les documents sources référencés dans la section §X (architecture_cible + audit_code)

CONTRAINTES :
- Français technique
- Commits "[PXX] <action>" en anglais
- Jamais --no-verify / --no-gpg-sign / force-push
- Headless : HYDROMODPY_NO_DISPLAY=1 HYDROMODPY_NO_SAVE=1
- Ambiguïtés : 13_coherence_globale.md tranche
- Aucun test existant ne doit casser

CRITÈRE DE SUCCÈS : voir section §X sous-section "Critère de succès".

Commence par lire les documents, puis planifie, puis exécute.
```

---

## 24. Table des matières

| § | Section | Phases couvertes |
|---|---|---|
| 1 | Vue d'ensemble — 13 phases | — |
| 2 | Diagramme de Gantt ASCII | — |
| 3 | Stratégie de rollback (git branches) | — |
| 4 | Métriques de progrès | — |
| 5 | Instructions communes aux prompts | — |
| 6 | **P01 — Fondations** | P01 |
| 7 | **P02 — Storage DuckDB + Zarr** | P02 |
| 8 | **P03 — Config Pydantic** | P03 |
| 9 | **P04 — Data input** | P04 |
| 10 | **P05 — Solveurs** | P05 |
| 11 | **P06 — Pipeline** | P06 |
| 12 | **P07 — Post-traitement** | P07 |
| 13 | **P08 — API Python** | P08 |
| 14 | **P09 — CLI** | P09 |
| 15 | **P10 — Export ALL** | P10 |
| 16 | **P11 — Tests cible** | P11 |
| 17 | **P12 — API REST** | P12 |
| 18 | **P13 — Nettoyage final** | P13 |
| 19 | Scripts bash runners (overview) | — |
| 20 | Lecture croisée des incohérences | — |
| 21 | Annexe scripts runners | — |
| 22 | Ordre d'exécution et parallélisme | — |
| 23 | Scripts bash — contenu (référence scripts/migration/) | — |
| 24 | Table des matières | — |

---

## 25. Résumé des livrables attendus par phase

| Phase | Fichiers nouveaux | Fichiers modifiés | Fichiers supprimés | Tests ajoutés | LOC net |
|---|---|---|---|---|---|
| P01 | 4 | ~150 (call sites) | 1 | 4 | +300 |
| P02 | 15 | 3 | 2 | 5 | +400 |
| P03 | 10 | ~100 (heritage HydroModelBase) | 2 | 7 | +600 |
| P04 | 35 | ~50 | ~50 (climatic + apis) | 12 | -4 500 |
| P05 | 20 | ~30 | ~15 | 9 | +0 (refactor) |
| P06 | 20 | ~20 | 4 | 9 | -3 000 |
| P07 | 30 | ~10 | ~15 | 8 | -4 700 |
| P08 | 3 | ~20 | 1 (__init__ 319→80) | 6 | -500 |
| P09 | 18 | ~10 | 2 (__main__ 1223 L, runners) | 6 | -800 |
| P10 | 7 | 5 | 0 | 3 | +400 |
| P11 | 30 | ~50 (conftests) | ~60 (tests legacy) | 20 critiques + 20 autres | -30 000 (tests) |
| P12 | 35 | 5 | 0 | 9 | +2 500 (optionnel web) |
| P13 | 5 (docs) | ~200 (renommage process→physics) | ~20 | 3 | -9 600 |
| **Total** | **~230** | **~700** | **~170** | **~110** | **~-50 000 LOC** |

Estimation globale : **~72 000 → ~52 000 LOC** (hors `hydromodpy/api/` optionnel qui ajoute ~2 500 L si installé).

---

## 26. Définition de « Done » du projet global

Le projet est considéré **terminé et prêt à release `v2.0.0-rc1`** quand toutes les conditions suivantes sont remplies :

1. Les 13 phases sont mergées dans `dev-database` (tags `vMigration-PXX-complete`).
2. `dev-database` est mergé dans `master` via PR reviewée.
3. `pytest tests/ -n auto` : 0 fail, 0 error, couverture ≥80 %.
4. `cfchecks` : 0 warning sur tous les `.nc` exportés.
5. `xugrid.open_dataset` : succès sur tous les mesh.nc.
6. `mypy --strict hydromodpy/__init__.py` : pass.
7. `python -X importtime -c "import hydromodpy"` : <50 ms.
8. `hmp doctor` : green sur machine neuve.
9. `hmp config wizard` ≤5 min de bout en bout.
10. CI pipeline `pr` <5 min, `nightly` <1 h.
11. `docs/migration_guide.md` publié.
12. `CHANGELOG.md` complet avec BREAKING CHANGES listés.
13. Scorecard audit 5,0 → cible ≥7,5 (évalué par un re-run de `run_audit.sh`).

---

*Fin du plan de migration.*
