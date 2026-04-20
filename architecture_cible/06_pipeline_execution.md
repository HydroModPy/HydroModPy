# Architecture cible — Pipeline d'exécution HydroModPy

**Document** : `architecture_cible/06_pipeline_execution.md`
**Date** : 2026-04-18
**Auteur** : Architecte orchestration scientifique (références : Prefect 2.x, Dagster 1.x, Luigi, Snakemake 8, Nextflow DSL2, Airflow 2, MLflow Tracking, DVC 3, Metaflow, CWL).
**Portée** : conception complète du **pipeline d'exécution** d'HydroModPy — du TOML utilisateur jusqu'à l'écriture finale dans le catalog. Couvre le cas à 1 simulation et le batch à 10 000 simulations (calibration, sensitivity analysis).
**Statut** : design de référence — **pas un patch incrémental**, pas compatible ligne à ligne avec l'existant.
**Sources** : audits `06_simulation_engine.md`, `11_synthese_finale.md`, architectures cibles `01_structure_packages.md`, `04_storage_ideal.md`, `05_solver_contracts.md`.

> **Légende des tags**
> `[NOUVEAU]` n'existe pas · `[RENOMME]` existe sous un autre nom · `[REFACTORE]` existe mais doit changer · `[CONSERVE]` existe et reste tel quel · `[SUPPRIME]` dead code à retirer.

---

## Table des matières

0. [Principes directeurs](#0-principes-directeurs)
1. [Vue d'ensemble — le pipeline en 11 étapes](#1-vue-densemble--le-pipeline-en-11-étapes)
2. [Diagramme de séquence complet](#2-diagramme-de-séquence-complet)
3. [Les 11 étapes — contrats I/O typés](#3-les-11-étapes--contrats-io-typés)
4. [Reproductibilité — hashing, lockfile, provenance](#4-reproductibilité--hashing-lockfile-provenance)
5. [Checkpointing et reprise après échec](#5-checkpointing-et-reprise-après-échec)
6. [Gestion d'erreurs — exceptions typées, retries, logs structurés](#6-gestion-derreurs--exceptions-typées-retries-logs-structurés)
7. [Le context manager `Simulation` — cycle de vie](#7-le-context-manager-simulation--cycle-de-vie)
8. [Batch et calibration — fan-out, optimisateurs, parallélisme](#8-batch-et-calibration--fan-out-optimisateurs-parallélisme)
9. [API publique — trois niveaux d'abstraction](#9-api-publique--trois-niveaux-dabstraction)
10. [Comparaison aux standards industrie](#10-comparaison-aux-standards-industrie)
11. [Mapping ancien → cible](#11-mapping-ancien--cible)
12. [Tests de conformité du pipeline](#12-tests-de-conformité-du-pipeline)

---

## 0. Principes directeurs

| # | Principe | Conséquence pratique |
|---|----------|----------------------|
| 1 | **Un pipeline = une liste ordonnée de *steps* purs** | Chaque step est une fonction `(PipelineState) -> PipelineState`. Pas d'état global, pas de singleton, pas de mutation latérale. Tests unitaires triviaux. |
| 2 | **DAG implicite linéaire + fork explicite pour le batch** | Pour une simulation : 11 étapes linéaires, pas de parallélisme interne. Pour un batch : fan-out de `Simulation` indépendantes (process-level), pas de parallélisme intra-simulation. |
| 3 | **I/O typés entre étapes** | Chaque step déclare `in: Type` et `out: Type` via des `dataclass(frozen=True)`. Aucun step ne dépend d'un attribut « caché » du state. Vérifié au import. |
| 4 | **Checkpointing opt-in, granularité step** | Entre étapes, l'état peut être sérialisé dans `workspace/.hmp/checkpoints/<run_id>/<step_name>.pkl.zst`. Au redémarrage, on reprend au dernier step validé. |
| 5 | **Hashing content-addressable** | `run_id = SHA-256(config_canonical_json + inputs_fingerprint + env_lockfile_hash)`. Déterministe, reproductible, auditable. Deux runs identiques → même `run_id` → dédoublonnage natif. |
| 6 | **Provenance PROV-O complète** | Table `runs_environment` en DuckDB : `user`, `host`, `platform`, `python_version`, `git_sha`, `env_lockfile_sha`, `solver_binary_sha256`, `step_durations_ms`. Traçabilité totale. |
| 7 | **Exceptions typées, pas de booléens** | `PipelineError` hiérarchie : `ConfigError`, `DataLoadError`, `MeshError`, `SolverError` (avec sous-types `SolverDivergedError`, `SolverTimeoutError`, `SolverBinaryNotFoundError`), `ExtractError`, `ExportError`. Plus jamais de `except Exception: pass`. |
| 8 | **Logs structurés `structlog` + corrélation run_id** | Chaque ligne porte `run_id`, `step`, `elapsed_ms`. Sortie JSONL sur fichier, humaine sur stdout. Agrégeable par `jq`, `DuckDB read_json_auto()`, Loki. |
| 9 | **Un seul orchestrateur `Pipeline`** | Fini la triple orchestration actuelle `project.py` ↔ `workflow/pipelines/` ↔ `runners/`. Une classe `Pipeline(steps)` avec une seule méthode `run(state)`. |
| 10 | **Le batch n'est PAS un pipeline spécial** | Un batch = N instances de `Simulation` + un `BatchRunner` qui gère le fan-out. Le pipeline d'une simulation ne sait pas qu'il tourne dans un batch. Séparation `hmp.simulation.Pipeline` ≠ `hmp.batch.BatchRunner`. |
| 11 | **Interface optimizer agnostique** | `Objective.evaluate(params) -> metrics` est un `Protocol`. Consommé par `scipy.optimize`, `optuna`, `pyDOE`, `pyPEST`. Le projet ne dépend de **aucun** optimizer spécifique. |
| 12 | **Déterminisme par défaut** | Seed `numpy.random.default_rng(seed)` propagée à travers les étapes stochastiques (mesh gmsh, Latin hypercube). Config TOML `[simulation.seed] value = 42`. |

### 0.1 Comparaison aux projets de référence

| Projet | Ce qu'on reprend | Ce qu'on ne reprend pas |
|--------|------------------|--------------------------|
| **Prefect 2.x** | Tasks typés, retries déclaratifs, state machine, hooks `on_failure`/`on_completion`, structured logging. | Pas de serveur Prefect (API, UI), pas d'orchestrateur distribué. HydroModPy vit en CLI+notebook. |
| **Dagster 1.x** | `IOManager` (séparation calcul/persistance), `Op`/`Graph` (pipeline composable), asset-centric materialization, checkpointing natif. | Pas de `Repository`/`Schedule` Dagster (scope plus petit). |
| **Luigi** | `output()`-based dependency resolution (présence d'un fichier marque un step terminé). | Modèle file-based peu adapté quand l'output est en DuckDB. On remplace par un **ledger DuckDB** des steps complétés. |
| **Snakemake 8** | DAG implicite à partir des `rule input`/`output`, reprise après crash native, `--dry-run`, `--until <rule>`, containerization. | Pas de DSL Python-extension-maison ; on garde l'API Python pure. |
| **Nextflow DSL2** | Channels, fan-out/fan-in automatique pour batch, `resume` basé sur cache. | Pas de DSL Groovy, pas de Docker obligatoire. |
| **Airflow 2** | XCom pour passage de state entre tasks, `on_retry_callback`, SLA. | Scheduler centralisé over-engineered pour nos usages. |
| **MLflow Tracking** | `params`/`metrics`/`artifacts` par run, auto-logging, `run_id` UUID. | Pas de serveur MLflow ; on écrit dans DuckDB directement (cf. doc 04). |
| **DVC 3** | Cache content-addressable (CAS) par hash d'input, `dvc repro` au lieu de `dvc run`. | Pas de git-annex overhead ; on utilise un CAS interne workspace. |
| **Metaflow (Netflix)** | `@step` décorateur + `self.next(step)`, résumé local/cloud avec même API. | Pas de clients S3/Batch packaged ; on reste local + optional dask. |
| **CWL (Common Workflow Language)** | Interfaces typées, reproductibilité, portable. | YAML verbeux, inadapté pour expression programmatique. |

### 0.2 Comparaison à ce qui existe (audit 06)

| Défaut actuel | Fix dans ce document | Section |
|---|---|---|
| `Simulation.run()` (207 l.) duplique `execute_simulation()` | `Simulation` devient wrapper mince (≤ 60 l.) | §7 |
| `_run_with_overrides` bypass le `SimulationPlanner` | Overrides s'appliquent sur `PipelineState.config`, pas sur le plan | §8.4 |
| Deux registres adapters/extractors désynchronisés | Un seul registre `SolverPlugin` (cf. doc 05) | §3.5 |
| `except Exception: logger.debug` masque les bugs | Exceptions typées + `on_step_error` callback | §6 |
| `try/finally` manquant dans `execute_simulation` | Pipeline garantit cleanup via `ExitStack` | §5.3 |
| `_auto_export` appelé après chaque run | Export une fois, après `aggregate` | §3.9 |
| DAG implicite / ordre codé en dur | DAG explicite : `Pipeline(steps=[...])` | §1, §3 |
| Plan pas sérialisable | `PipelineState.to_checkpoint()` + `from_checkpoint()` | §4, §5 |
| Batch absent — `BatchRuntime` 1828 l. ad-hoc | `BatchRunner` en 200 l. | §8 |
| Calibration bypass complet du pipeline standard | Calibration = N `Simulation` + un optimizer | §8.3 |

---

## 1. Vue d'ensemble — le pipeline en 11 étapes

### 1.1 Liste canonique

Le pipeline standard d'une simulation HydroModPy est une **liste ordonnée de 11 étapes effectives** (code : `hydromodpy/pipeline/steps/`, registre : `standard_steps()`). Chaque étape est pure (pas d'effet de bord sur l'état précédent, elle **renvoie** un nouvel état).

```
  0 │ validate          │ HydroModPyConfig → ValidatedConfig      │ Pydantic + contraintes physiques
  1 │ resolve           │ ValidatedConfig → ResolvedConfig        │ Résolution chemins, time window, CRS
  2 │ load_data         │ ResolvedConfig → LoadedData             │ DataPlanner + managers + cache
  3 │ build_geographic  │ ResolvedConfig, LoadedData → Geography  │ Délinéation catchment, streams
  4 │ build_mesh        │ Geography, MeshConfig → HydroMesh       │ Cartesian ou Gmsh
  5 │ setup_process     │ HydroMesh, LoadedData → Domain          │ Zones, FieldParam, BC, SimulationPlan
  6 │ prepare_solver    │ Domain, Plan → SolverReady              │ Open DuckDB + Zarr, build solver model
  7 │ run_solver        │ SolverReady → SolveReport               │ Boucle sur plan.runs + after_run ingestion
  8 │ extract           │ SolveReport, StoreHandle → Extracted    │ Finalisation extraction (pass-through)
  9 │ derive            │ Extracted, StoreHandle → Derived        │ DerivedRegistry : watertable, seepage, flux
 10 │ export            │ Derived, ExportConfig → Exports         │ NetCDF, GeoTIFF, VTU, CSV (opt-in)
```

> Les 11 étapes sont **obligatoires** dans l'ordre ; la sortie `export` est opt-in par configuration mais la step est exécutée (no-op silencieux quand rien n'est demandé).
>
> **Écart assumé vis-à-vis de la rédaction initiale** : la liste conceptuelle d'origine énumérait 14 positions (0–14) en considérant `domain`, `plan`, `open_store`, `aggregate`, `display`, `finalize` comme steps indépendants. L'implémentation les a fusionnés — `setup_process` absorbe `domain` + `plan`, `prepare_solver` absorbe `open_store` + la construction du modèle solver, l'affichage et l'agrégation sont résolus ailleurs (`display/` à la demande, `results.catalog` pour les scalaires), et `finalize` est garanti par le `Pipeline` via le ledger `steps` en DuckDB. Cette réduction à 11 étapes est désormais la référence.
>
> **`derive` (step 9)** s'appuie sur le registre :class:`hydromodpy.pipeline.derived.DerivedRegistry`. Chaque entrée déclare `required_inputs` et `required_derived`, la step ordonne topologiquement les dérivées et skippe silencieusement celles dont les inputs manquent. Derivations canoniques : `watertable_elevation`, `watertable_depth`, `seepage_mask`, `fluxes_from_budget`.

### 1.2 Propriétés d'un step

Tout step est une fonction `step_<name>(state_in: TState) -> TState_next` avec :

- **Typage explicite** : `TState` et `TState_next` sont des `dataclass(frozen=True)` distincts. Le retour contient *toujours* `state_in` sous forme d'attribut (`previous=state_in`) pour construire le chaînage.
- **Pureté** : pas de mutation de `state_in`, pas d'accès à un singleton. Seules les ressources I/O externes (DuckDB, Zarr, filesystem) peuvent muter — et elles sont passées via un `ResourceHandle` explicite.
- **Idempotence conditionnelle** : rejouer un step avec le même input produit le même output octet-à-octet (hors horodatages journalisés). Exceptions : `solve` (dépend du binaire solver), `display` (timestamp dans figure).
- **Durée mesurée** : le wrapper `@timed_step` injecte `elapsed_ms` dans le state de sortie.
- **Cacheable** : si `PipelineConfig.enable_cache = True`, le résultat est persisté dans `workspace/.hmp/cache/<step_hash>/` et réutilisé si `step_hash` match.

### 1.3 Signature générique `PipelineStep` — `[NOUVEAU]`

```python
# hydromodpy/simulation/pipeline/step.py   [NOUVEAU]

from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable, Generic

TIn = TypeVar("TIn", bound="StepState")
TOut = TypeVar("TOut", bound="StepState")


@dataclass(frozen=True, slots=True)
class StepState:
    """Base class for all typed pipeline states (frozen dataclasses)."""
    run_id: str
    step_index: int
    elapsed_ms: float = 0.0


@runtime_checkable
class PipelineStep(Protocol, Generic[TIn, TOut]):
    """Canonical pipeline step contract.

    A step is a pure function from ``TIn`` to ``TOut``. The framework wraps it
    with timing, logging, caching, and error handling.
    """

    name: str           # "validate", "mesh", ...
    in_type: type[TIn]  # used for cache key derivation
    out_type: type[TOut]

    def __call__(
        self,
        state: TIn,
        *,
        resources: "ResourceHandle",
        ctx: "StepContext",
    ) -> TOut: ...

    def fingerprint(self, state: TIn) -> str:
        """Return a SHA-256 hex over state content used for cache lookup."""
        ...
```

### 1.4 `PipelineState` — l'état traversant

Chaque step émet un `StepState` spécifique (`ValidatedState`, `MeshedState`, ...). Le state **final** (step 14) est :

```python
# hydromodpy/simulation/pipeline/state.py   [NOUVEAU]

@dataclass(frozen=True, slots=True)
class FinalState(StepState):
    config: ResolvedConfig
    loaded_data: LoadedData
    geography: Geography
    mesh: HydroMesh
    domain: Domain
    plan: SimulationPlan
    solve_report: SolveReport
    extracted: ExtractedFields
    derived: DerivedFields
    aggregated: AggregatedScalars
    exports: tuple[ExportResult, ...]
    figures: tuple[FigureResult, ...]
    step_durations: dict[str, float]
```

Cette structure explicite remplace l'actuel `WorkflowContext` **mutable** (`setup/loaded_data/execution` non-frozen, `setattr` clandestin dans `BoussinesqFlowAdapter`). Toutes les transitions de state sont traçables.

---

## 2. Diagramme de séquence complet

### 2.1 Cas standard — 1 simulation, pas de cache, pas de reprise

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         PIPELINE STANDARD                                │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  TOML path                                                               │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   HydroModPyConfig  (Pydantic)                          │
│  │ 0.validate  │──────────────────────────►  ValidatedState               │
│  └─────────────┘   + extra="forbid" + physical bounds (K>0, Sy∈]0,1[)    │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   ResolvedConfig                                        │
│  │ 1.resolve   │──────────────────────────►  ResolvedState                │
│  └─────────────┘   (paths absolus, TimeGrid, CRS, seed)                  │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   DataPlan + LoadedData                                 │
│  │ 2.load_data │──────────────────────────►  LoadedState                  │
│  └─────────────┘   (DataPlanner + managers + cache.duckdb)               │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   Geography (Watershed delineation)                     │
│  │ 3.geographic│──────────────────────────►  GeographicState              │
│  └─────────────┘   (whitebox / pysheds)                                  │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   HydroMesh (UGRID 1.0)                                 │
│  │ 4.mesh      │──────────────────────────►  MeshedState                  │
│  └─────────────┘   (cartesian or gmsh)                                   │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   Domain (zones, FieldParam, BC)                        │
│  │ 5.domain    │──────────────────────────►  DomainState                  │
│  └─────────────┘                                                         │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   SimulationPlan (frozen, ordered runs)                 │
│  │ 6.plan      │──────────────────────────►  PlannedState                 │
│  └─────────────┘   (SolverPlanner reads resolved capabilities)           │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   StoreHandle (DuckDB+Zarr open, register_simulation)   │
│  │ 7.open_store│──────────────────────────►  OpenedState                  │
│  └─────────────┘   sim_id computed from fingerprint                      │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   SolveReport (per-run primary model + logs)            │
│  │ 8.solve     │──────────────────────────►  SolvedState                  │
│  └─────────────┘   SolverRunner.execute(plan, domain, store)             │
│     │         ▲                                                          │
│     │         │ solver-specific side effects: .hds, .cbc, .lst, .npz     │
│     │         │ written to workspace/.hmp/scratch/<sim_id>/              │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   ExtractedFields (Zarr heads, budget, timeseries)      │
│  │ 9.extract   │──────────────────────────►  ExtractedState               │
│  └─────────────┘   ResultExtractor.extract(report, store)                │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   DerivedFields (watertable, seepage, flux)             │
│  │ 10.derive   │──────────────────────────►  DerivedState                 │
│  └─────────────┘   compute_derived(flags, store)                         │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   AggregatedScalars (catchment mean/sum per period)     │
│  │ 11.aggregate│──────────────────────────►  AggregatedState              │
│  └─────────────┘   writes into DuckDB timeseries table                   │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   ExportResults (NetCDF, GeoTIFF, VTU - optional)       │
│  │ 12.export   │──────────────────────────►  ExportedState                │
│  └─────────────┘   ExporterRegistry.export_all(store, sim_id)            │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   FigureResults (matplotlib - optional)                 │
│  │ 13.display  │──────────────────────────►  DisplayedState               │
│  └─────────────┘   DisplaySuite.render(store, sim_id)                    │
│     │                                                                    │
│     ▼                                                                    │
│  ┌─────────────┐   None                                                  │
│  │ 14.finalize │──────────────────────────►  FinalState                   │
│  └─────────────┘   store.finalize + store.close                          │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Cas avec reprise (step 8/14 a crashé précédemment)

```
  $ hmp run config.toml --resume
    │
    ▼
  [Pipeline.run] :
     checkpoint = CheckpointStore.latest_success(run_id)
     → found: "solve.8"  (crashed during step 9)
     → resume_from = "extract" (step 9)
     │
     ▼
  reload Step 0..8 states from .hmp/checkpoints/<run_id>/solve.8.state
  │
  ▼  (execute only 9, 10, 11, 12, 13, 14)
  [9. extract] ─► [10. derive] ─► ... ─► [14. finalize]
```

### 2.3 Cas batch (calibration, 1000 simulations)

```
  BatchRunner (1 process)
       │
       ├── ObjectiveFunction ───► optuna.Study ───► suggest N param sets
       │
       ▼
  ┌──────────────── ProcessPoolExecutor (n_workers) ───────────────┐
  │                                                                 │
  │   worker 1:  Pipeline(params_1).run()  ──► SimulationResult_1   │
  │   worker 2:  Pipeline(params_2).run()  ──► SimulationResult_2   │
  │   ...                                                           │
  │   worker N:  Pipeline(params_N).run()  ──► SimulationResult_N   │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
               BatchReport (aggregated metrics, best/worst)
                              │
                              ▼
               optuna.Study.tell(trial, metric)
                              │
                   (next iteration OR convergence)
```

---

## 3. Les 11 étapes — contrats I/O typés

Chaque étape vit dans `hydromodpy/simulation/pipeline/steps/`. Un fichier par step.

```
hydromodpy/simulation/pipeline/             [NOUVEAU]
├── __init__.py                             exports Pipeline, PipelineState, StepState
├── pipeline.py                             Pipeline (the orchestrator, ≤ 200 l.)
├── step.py                                 PipelineStep Protocol, @timed_step, @cached_step
├── state.py                                StepState base + 14 frozen variants
├── context.py                              StepContext (run_id, logger, cache, resources)
├── resources.py                            ResourceHandle (DuckDB, Zarr, fs, RNG seed)
├── cache.py                                CAS cache (fingerprint → artifact)
├── checkpoint.py                           CheckpointStore (pickle.zst of state)
├── fingerprint.py                          canonical hashing utilities
├── errors.py                               PipelineError hierarchy
└── steps/                                  ONE FILE PER STEP
    ├── __init__.py
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

### 3.0 Step 0 — `validate` — `[REFACTORE]`

**Rôle** : charger le TOML, le valider via Pydantic, appliquer des contraintes physiques (K > 0, Sy ∈ ]0, 1[, etc. — cf. audit 10).

```python
# steps/step_00_validate.py    [REFACTORE : remplace Simulation.__init__ partial]

@dataclass(frozen=True, slots=True)
class ValidatedState(StepState):
    raw_toml_path: Path
    raw_toml_sha256: str     # hash du contenu brut
    config: HydroModPyConfig  # Pydantic validated

class ValidateStep:
    name = "validate"
    in_type = InputState       # juste (toml_path: Path)
    out_type = ValidatedState

    def __call__(self, s: InputState, *, resources, ctx) -> ValidatedState:
        raw_bytes = s.toml_path.read_bytes()
        toml_sha = hashlib.sha256(raw_bytes).hexdigest()
        toml_data = tomllib.loads(raw_bytes.decode())
        try:
            cfg = HydroModPyConfig.model_validate(toml_data)
        except ValidationError as e:
            raise ConfigError.from_pydantic(e, path=s.toml_path) from e
        PhysicalBoundsValidator().check(cfg)   # K > 0, Sy ∈ ]0, 1[, ...
        return ValidatedState(
            run_id=s.run_id, step_index=0,
            raw_toml_path=s.toml_path, raw_toml_sha256=toml_sha, config=cfg,
        )

    def fingerprint(self, s: InputState) -> str:
        return hashlib.sha256(s.toml_path.read_bytes()).hexdigest()
```

**Sorties** : `ValidatedState(config: HydroModPyConfig, raw_toml_sha256)`.
**Erreurs** : `ConfigError` (Pydantic `ValidationError` wrappé avec line+column), `PhysicalBoundsError`.

### 3.1 Step 1 — `resolve` — `[REFACTORE]` (ex-parties de `step_setup`)

**Rôle** : résoudre les chemins relatifs → absolus, construire le `TimeGrid`, résoudre le CRS, tirer le seed.

```python
@dataclass(frozen=True, slots=True)
class ResolvedState(ValidatedState):
    workspace: Workspace              # résolution workspace root
    time_grid: TimeGrid               # cf. architecture cible 01/02
    crs: pyproj.CRS
    rng: np.random.Generator          # seed déterministe
    env_lockfile_sha256: str | None   # hash du environment.yml/poetry.lock si présent
```

**Invariant** : après ce step, **aucun chemin relatif, aucun champ `str` ambigu**. Tout est résolu.

### 3.2 Step 2 — `load_data` — `[RENOMME]` (ex-`step_data_loading`)

**Rôle** : exécuter le `DataPlan` et remplir `LoadedData`.

```python
@dataclass(frozen=True, slots=True)
class LoadedState(ResolvedState):
    data_plan: DataLoadPlan
    loaded_data: LoadedData           # cf. architecture cible 03
    cache_hits: tuple[str, ...]       # pour provenance
    provenance_inputs: tuple[InputFingerprint, ...]
```

**Important** : après ce step, les fichiers sources sont **fingerprintés** (SHA-256 sur le contenu, pas sur `.tobytes()` numpy). Ces fingerprints iront en DuckDB `provenance` au step 7.

### 3.3 Step 3 — `geographic` — `[NOUVEAU]` (ex-fusion `step_setup` + `step_spatial_supports`)

**Rôle** : délinéation catchment + extraction streams + sous-bassins.

```python
@dataclass(frozen=True, slots=True)
class GeographicState(LoadedState):
    geography: Geography              # Watershed(polygon, streams, subbasins, dem)
```

### 3.4 Step 4 — `mesh` — `[CONSERVE logique, RENOMME fichier]` (ex-`step_mesh` + `step_mesh_input`)

**Rôle** : générer le `HydroMesh` (UGRID 1.0). Cartesian ou Gmsh. Ou importer un mesh externe.

```python
@dataclass(frozen=True, slots=True)
class MeshedState(GeographicState):
    mesh: HydroMesh
    mesh_sha256: str                  # hash (vertices+faces+z_interfaces)
```

### 3.5 Step 5 — `domain` — `[NOUVEAU regroupé]`

**Rôle** : construire `Domain` (zones, `FieldParam`, BC pré-résolues).

```python
@dataclass(frozen=True, slots=True)
class DomainState(MeshedState):
    domain: Domain                    # zones, fields, BC pré-résolues au mesh
```

**Conséquence architecturale** : cet étape **absorbe** toute la logique actuellement dispersée entre `ensure_flow`, `ensure_transport`, et les ré-invocations de spatial_supports dans l'adapter MF6 (cf. audit 06 §3.3). Les adapters ne créent plus **aucun** objet `Flow`/`Transport` latéralement.

### 3.6 Step 6 — `plan` — `[CONSERVE]`

**Rôle** : `SolverPlanner.build(config.simulation) → SimulationPlan`.

```python
@dataclass(frozen=True, slots=True)
class PlannedState(DomainState):
    plan: SimulationPlan              # frozen, ordered runs
    plan_json: str                    # serialized pour DuckDB simulations.plan_json
```

**Nouveauté vs existant** : `SimulationPlan` **se sérialise** en JSON (méthode `to_json()` / `from_json()`). Cela permet (a) de le logger, (b) de le stocker en DuckDB pour inspection a posteriori, (c) de le reconstruire au resume.

### 3.7 Step 7 — `open_store` — `[REFACTORE]` (ex-`step_open_store`)

**Rôle** : calculer le `sim_id` déterministe, ouvrir le `SimulationCatalog`, `register_simulation`, écrire mesh, parameters, provenance.

```python
@dataclass(frozen=True, slots=True)
class OpenedState(PlannedState):
    sim_id: str                       # uuid5-style deterministic OR uuid4 fallback
    store: StoreHandle                # wrapper autour SimulationCatalog
    run_fingerprint: str              # SHA-256 utilisé pour reproductibilité
```

**Nouveauté critique** : `sim_id` n'est plus `uuid4()` aveugle mais :

```python
sim_id = uuid.uuid5(
    namespace=HMP_NAMESPACE,
    name=run_fingerprint,              # SHA-256(config + inputs + env + seed)
)
```

Deux runs **strictement identiques** → même `sim_id` → on détecte un rerun inutile (ou on force `--force-new-uuid`). Si l'utilisateur veut forcer un nouvel UUID (par ex. pour rerun après fix binaire), l'option CLI `--force-new-uuid` injecte un salt aléatoire dans le fingerprint.

### 3.8 Step 8 — `solve` — `[REFACTORE]`

**Rôle** : exécuter `SimulationPlan` run par run. **Ne touche plus au store** sauf pour `write_mass_balance` par run (transactionnel).

```python
@dataclass(frozen=True, slots=True)
class SolveReport:
    runs: tuple[RunResult, ...]
    wall_seconds: float
    solver_binary_sha256s: dict[str, str]   # "mf2005nwt" → "abc123..."

@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    solver_name: str
    exit_status: Literal["ok", "diverged", "timeout", "failed"]
    solver_output_dir: Path              # scratch/<sim_id>/<run_id>/
    primary_model_ref: str               # opaque handle (not serializable)
    logs: tuple[LogLine, ...]
    mass_balance: MassBalance | None
```

```python
@dataclass(frozen=True, slots=True)
class SolvedState(OpenedState):
    solve_report: SolveReport
```

**Nouveauté critique** : `SolverRunner` ne fait **que** appeler les adapters. L'écriture DuckDB/Zarr des résultats est décalée au step `extract`. Cela découple calcul et persistance (cf. principe #9 `IOManager` de Dagster).

### 3.9 Step 9 — `extract` — `[REFACTORE]`

**Rôle** : lire les outputs solveurs (.hds, .cbc, .lst, .npz) et écrire les champs dans Zarr. **Un extracteur par solveur, factorisé via `_BinaryHeadExtractor`** (cf. audit 06 §5.2).

```python
@dataclass(frozen=True, slots=True)
class ExtractedState(SolvedState):
    n_timesteps_written: int
    head_array_shape: tuple[int, int, int]   # (T, L, C)
    budget_variables: tuple[str, ...]        # ["recharge", "drn", ...]
    timeseries_stations: tuple[str, ...]
```

**Nouveauté** : l'API `StoreHandle.write_fields_batch(var_name, arr_TLC, chunk_time=...)` écrit **un array entier** par variable, pas un pas de temps à la fois (cf. audit 06 §5.6 → optimisation ×2-×5).

### 3.10 Step 10 — `derive` — `[REFACTORE]`

**Rôle** : calculer les champs dérivés (`watertable_elevation`, `watertable_depth`, `seepage_areas`, `groundwater_flux`, ...). Aucune heuristique `_SENTINEL_THRESHOLD = -50.0` (cf. audit 06 §6.2). Les sentinelles doivent avoir été nettoyées au step `extract`.

```python
@dataclass(frozen=True, slots=True)
class DerivedState(ExtractedState):
    derived_variables: tuple[str, ...]       # ["watertable_depth", "seepage_areas", ...]
```

**Architecture extensible** : `DerivedRegistry` dict `{name: DerivedComputer}` enregistrable depuis plugins (cf. audit 06 §6.4).

```python
@runtime_checkable
class DerivedComputer(Protocol):
    name: str
    requires: tuple[str, ...]              # e.g. ("head", "top_elevation")
    def compute(
        self, store: StoreHandle, sim_id: str, rng: np.random.Generator,
    ) -> None: ...

DERIVED_REGISTRY: dict[str, DerivedComputer] = {}
def register_derived(computer: DerivedComputer) -> None: ...
```

### 3.11 Step 11 — `aggregate` — `[REFACTORE]`

**Rôle** : calculer les scalaires agrégés catchment-wide (mean, sum). Lire `n_periods` **depuis DuckDB** (`simulations.n_timesteps`), jamais par heuristique `n_per ∈ [12, 6, 4, 3, 2, 1]` (cf. audit 06 §5.7 — bug sur 7 périodes).

```python
@dataclass(frozen=True, slots=True)
class AggregatedState(DerivedState):
    timeseries_rows: int                    # DuckDB rows inserted
    metrics_rows: int
```

### 3.12 Step 12 — `export` — `[REFACTORE]`

**Rôle** : exports portables **une seule fois**, après l'agrégation (ne plus appeler après chaque run, cf. audit 06 §8).

```python
@dataclass(frozen=True, slots=True)
class ExportedState(AggregatedState):
    exports: tuple[ExportResult, ...]

@dataclass(frozen=True, slots=True)
class ExportResult:
    format: Literal["netcdf", "geotiff", "geopackage", "shapefile", "vtu", "csv", "waterml"]
    path: Path
    bytes_written: int
    sha256: str
```

### 3.13 Step 13 — `display` — `[REFACTORE]`

**Rôle** : figures matplotlib opt-in. Isolé du pipeline pour pouvoir être rejoué post-hoc via `hmp display <config>` sans re-simulation.

```python
@dataclass(frozen=True, slots=True)
class DisplayedState(ExportedState):
    figures: tuple[FigureResult, ...]

@dataclass(frozen=True, slots=True)
class FigureResult:
    name: str
    path: Path
    backend: Literal["matplotlib", "pyvista"]
```

### 3.14 Step 14 — `finalize` — `[RENOMME]`

**Rôle** : teardown, **toujours exécuté** (via `ExitStack` du `Pipeline`). Marque `simulations.status = 'completed'` (ou `'failed'` si exception en amont), ferme DuckDB, consolide le Zarr, génère le manifest si demandé.

```python
@dataclass(frozen=True, slots=True)
class FinalState(DisplayedState):
    status: Literal["completed", "failed", "partial"]
    duration_s: float
    checkpoint_path: Path | None
```

---

## 4. Reproductibilité — hashing, lockfile, provenance

### 4.1 Fingerprint canonique d'un run

Le `run_fingerprint` est **le** contrat de reproductibilité. Il est calculé au step 7 (`open_store`) à partir de :

```
run_fingerprint = SHA-256(
    canonical_json(config) ||               # config Pydantic dumped en JSON déterministe
    sorted(inputs_fingerprints) ||          # SHA-256 de chaque fichier source
    env_lockfile_sha256 ||                  # SHA-256(environment.lock OR poetry.lock)
    hydromodpy_version ||                   # hmp.__version__ + git_sha
    solver_binary_sha256s ||                # SHA-256 de chaque binaire solver utilisé
    str(seed)                                # seed numpy explicite
)
```

**Canonical JSON** : utilise `json.dumps(obj, sort_keys=True, separators=(",", ":"))` après `config.model_dump(mode="json", exclude_none=False)`. Aucune ambiguïté de whitespace ou d'ordre de clé.

### 4.2 Lockfile des dépendances — `[NOUVEAU]`

HydroModPy génère automatiquement au `hmp init` :

- `workspace/.hmp/env.lock` — snapshot `pip freeze` + `conda list --json` à l'init.
- À chaque run, `env_lockfile_sha256` est recalculé et comparé. Si divergence → **warning** dans `logs/<run_id>.log` (pas erreur bloquante, mais tracé dans DuckDB).

```python
# hydromodpy/simulation/pipeline/lockfile.py    [NOUVEAU]

def capture_environment() -> EnvCapture:
    """Return a structured snapshot of the current Python/conda environment."""
    return EnvCapture(
        python_version=sys.version,
        platform=platform.platform(),
        pip_freeze=subprocess.run(
            [sys.executable, "-m", "pip", "freeze"], check=True, capture_output=True
        ).stdout.decode(),
        conda_list=_safe_conda_list(),
        hmp_version=hmp.__version__,
        hmp_git_sha=_resolve_hmp_git_sha(),
    )

def write_lockfile(path: Path, capture: EnvCapture) -> str:
    path.write_text(capture.to_canonical_json())
    return hashlib.sha256(path.read_bytes()).hexdigest()
```

### 4.3 Provenance DuckDB — schéma — `[NOUVEAU]`

Enrichissement de la table `runs_environment` définie dans l'architecture cible 04 :

```sql
CREATE TABLE runs_environment (
    sim_id               UUID PRIMARY KEY REFERENCES simulations(sim_id) ON DELETE CASCADE,
    run_fingerprint      CHAR(64) NOT NULL,           -- hex SHA-256
    user_name            VARCHAR(255),
    host_name            VARCHAR(255),
    platform             VARCHAR(255),
    python_version       VARCHAR(64),
    hmp_version          VARCHAR(64),
    hmp_git_sha          CHAR(40),
    env_lockfile_sha256  CHAR(64),
    seed                 BIGINT,
    started_at           TIMESTAMPTZ NOT NULL,
    ended_at             TIMESTAMPTZ,
    step_durations_json  JSON,                         -- {"validate": 12.3, ...}
    solver_binaries_json JSON                          -- {"mf2005nwt": "sha256:..."}
);

CREATE INDEX idx_runs_env_fingerprint ON runs_environment(run_fingerprint);
```

**Propriété** : `SELECT sim_id FROM runs_environment WHERE run_fingerprint = $1` retourne la ou les simulations **bit-à-bit équivalentes**. Utilisé par :

- **Dédoublonnage** : avant `open_store`, le pipeline interroge cette table. Si un hit existe et `--dedupe` est activé, on lève `DuplicateRunWarning` (ou on skip silencieusement en mode batch).
- **Audit** : `hmp inspect <sim_id> --provenance` dump toute la ligne.

### 4.4 Fingerprint content-addressable des inputs — `[REFACTORE]`

**Avant** (audit 03) : hash `numpy.tobytes()` → non-portable cross-platform (endianness).
**Après** : hash **octet-à-octet du fichier source** (`.tif`, `.nc`, `.csv`, `.gpkg`) au load. Pour les timeseries reconstruites en mémoire : hash `pandas.util.hash_pandas_object(df).sum()` (portable).

```python
@dataclass(frozen=True, slots=True)
class InputFingerprint:
    variable: str                    # "dem", "recharge", ...
    source_kind: Literal["file", "api", "synthetic"]
    source_uri: str                  # path OR "hubeau://stations/J9204010"
    sha256: str                      # content hash
    size_bytes: int
    fetched_at: datetime
```

### 4.5 Test de reproductibilité — `[NOUVEAU]`

```python
# tests/validation/test_reproducibility.py     [NOUVEAU]

@pytest.mark.validation
def test_same_toml_twice_same_fingerprint(tmp_workspace):
    res1 = Pipeline.from_toml("config.toml", workspace=tmp_workspace).run()
    res2 = Pipeline.from_toml("config.toml", workspace=tmp_workspace).run()
    assert res1.run_fingerprint == res2.run_fingerprint
    # sim_id diverges only if --force-new-uuid used
    # numerical reproducibility: head arrays byte-identical
    h1 = tmp_workspace / "simulations" / f"{res1.sim_id}.zarr"
    h2 = tmp_workspace / "simulations" / f"{res2.sim_id}.zarr"
    assert _zarr_array_equal(h1, h2, var="head")
```

---

## 5. Checkpointing et reprise après échec

### 5.1 Où est l'état, à chaque étape ?

| Étape | État persistant (on disk) | État en RAM |
|-------|---------------------------|-------------|
| 0–6 | aucun | `StepState` courant |
| 7 | `hydromodpy.duckdb` (ligne `simulations` + `runs_environment`) | `OpenedState` |
| 8 | fichiers solver scratch (`.hds`, `.cbc`, ...) | `SolvedState` |
| 9 | Zarr `simulations/<sim_id>.zarr/head/`, `budget/` | `ExtractedState` |
| 10 | Zarr `simulations/<sim_id>.zarr/derived/` | `DerivedState` |
| 11 | DuckDB `timeseries`, `metrics`, `mass_balance` | `AggregatedState` |
| 12 | `workspace/exports/*` | `ExportedState` |
| 13 | `workspace/figures/<sim_id>/*.png` | `DisplayedState` |
| 14 | `simulations.status = 'completed'` | `FinalState` |

### 5.2 CheckpointStore — `[NOUVEAU]`

Après **chaque step réussi**, si `pipeline_cfg.checkpoint = True`, on écrit le state sérialisé :

```
workspace/
└── .hmp/
    └── checkpoints/
        └── <run_id>/
            ├── ledger.duckdb              # table "steps": step_index, step_name, status, ts
            ├── 00_validate.state.pkl.zst   # pickle.zst(ValidatedState)
            ├── 01_resolve.state.pkl.zst
            ├── ...
            └── 08_solve.state.pkl.zst
```

**Ledger DuckDB** (idée empruntée à Luigi/Dagster) :

```sql
CREATE TABLE steps (
    run_id         VARCHAR PRIMARY KEY,   -- external run id (user-assigned)
    step_index     INTEGER,
    step_name      VARCHAR,
    status         VARCHAR CHECK (status IN ('pending','running','completed','failed','skipped')),
    started_at     TIMESTAMPTZ,
    ended_at       TIMESTAMPTZ,
    elapsed_ms     BIGINT,
    error_kind     VARCHAR,               -- "SolverDivergedError", ...
    error_msg      VARCHAR,
    state_path     VARCHAR                -- relative path to the .pkl.zst
);
```

### 5.3 API de reprise — `[NOUVEAU]`

```python
# hydromodpy/simulation/pipeline/checkpoint.py   [NOUVEAU]

class CheckpointStore:
    def __init__(self, workspace: Workspace, run_id: str): ...

    def latest_success(self) -> int | None:
        """Return step_index of the last completed step, or None."""
        ...

    def restore(self, step_index: int) -> StepState:
        """Load the state at the end of step `step_index`."""
        path = self._state_path(step_index)
        with zstandard.ZstdDecompressor().stream_reader(open(path, "rb")) as r:
            return pickle.load(r)

    def persist(self, state: StepState) -> Path:
        """Persist `state` as the output of its step."""
        path = self._state_path(state.step_index)
        with zstandard.ZstdCompressor(level=3).stream_writer(open(path, "wb")) as w:
            pickle.dump(state, w, protocol=pickle.HIGHEST_PROTOCOL)
        return path
```

### 5.4 CLI `hmp run --resume` — `[NOUVEAU]`

```
$ hmp run config.toml --resume
▶ Found checkpoint for run_id='canut-baseline-2026-04-18': step 8 (solve) completed.
▶ Resuming from step 9 (extract)...
  [9/14] extract      ✓  12.3s
  [10/14] derive       ✓   5.1s
  [11/14] aggregate    ✓   0.8s
  [12/14] export       ✓  22.6s
  [13/14] display      ✓  18.4s
  [14/14] finalize     ✓   0.2s
✓ Simulation completed in 59.4s (of which resumed from 73% progress).
```

Autres flags :

- `--until <step_name>` : exécute jusqu'à ce step inclus et s'arrête (dry-run partiel).
- `--from <step_name>` : force la reprise à partir de ce step (écrase les checkpoints suivants).
- `--no-checkpoint` : désactive la persistance (utile pour les runs courts).
- `--dry-run` : affiche le plan de pipeline sans exécuter.

### 5.5 Atomicité des écritures DuckDB — `[REFACTORE]`

Chaque step qui écrit dans DuckDB (`open_store`, `extract`, `aggregate`, `finalize`) le fait **dans une transaction** :

```python
with store.transaction() as tx:
    tx.register_simulation(...)
    tx.write_parameters(...)
    tx.write_mesh_metadata(...)
# commit atomic; on exception, tx.rollback() automatique via __exit__
```

Cela évite l'état « moitié peuplé » décrit dans l'audit 06 §8.

### 5.6 Garantie de cleanup — `Pipeline.run()` avec `ExitStack`

```python
# hydromodpy/simulation/pipeline/pipeline.py    [NOUVEAU, remplace execute_simulation]

class Pipeline:
    def __init__(self, steps: Sequence[PipelineStep], *, cfg: PipelineConfig): ...

    def run(self, initial_state: InputState) -> FinalState:
        with ExitStack() as stack:
            logger = stack.enter_context(structlog_ctx(run_id=initial_state.run_id))
            resources = stack.enter_context(ResourceHandle.open(self.cfg))
            checkpoints = stack.enter_context(
                CheckpointStore(resources.workspace, initial_state.run_id)
            )

            state: StepState = initial_state
            try:
                for step in self.steps:
                    state = self._execute_step(step, state, resources, checkpoints)
                return state  # FinalState
            except PipelineError as e:
                self._handle_failure(state, e, resources, checkpoints)
                raise
            except KeyboardInterrupt:
                logger.warning("pipeline_interrupted", step=state.step_name)
                raise
```

Le `ExitStack` garantit que `ResourceHandle` ferme **toujours** DuckDB et Zarr, même si `KeyboardInterrupt` ou `SystemExit`.

---

## 6. Gestion d'erreurs — exceptions typées, retries, logs structurés

### 6.1 Hiérarchie d'exceptions — `[NOUVEAU]`

```python
# hydromodpy/simulation/pipeline/errors.py    [NOUVEAU]

class PipelineError(Exception):
    """Base class for all pipeline-originated errors."""
    step_name: str
    run_id: str

class ConfigError(PipelineError): ...
class PhysicalBoundsError(ConfigError): ...

class DataLoadError(PipelineError):
    variable: str
    source_uri: str
class NetworkError(DataLoadError):   # HTTP 5xx, 429, timeout
    retryable: bool = True
class CacheCorruptionError(DataLoadError): ...

class MeshError(PipelineError):
    mesh_kind: str

class SolverError(PipelineError):
    solver_name: str
    exit_code: int | None = None
class SolverDivergedError(SolverError): ...
class SolverTimeoutError(SolverError): ...
class SolverInputError(SolverError): ...
class SolverBinaryNotFoundError(SolverError): ...

class ExtractError(PipelineError):
    variable: str
class ExportError(PipelineError):
    format: str
class DisplayError(PipelineError):
    figure_name: str
```

**Bénéfice** : un `except SolverDivergedError` dans la calibration permet de noter la tentative divergée sans tuer le batch. Un `except NetworkError` déclenche un retry exponentiel. Un `except ConfigError` remonte à l'utilisateur directement.

### 6.2 Retry déclaratif — `[NOUVEAU]`

Inspiré de Prefect. Chaque step déclare sa politique :

```python
@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1
    retry_on: tuple[type[Exception], ...] = ()
    backoff_s: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_s: float = 60.0

class LoadDataStep:
    name = "load_data"
    retry = RetryPolicy(
        max_attempts=5,
        retry_on=(NetworkError,),
        backoff_s=2.0, backoff_multiplier=2.0, max_backoff_s=60.0,
    )
    ...
```

**Règle** : le pipeline ne retry **que** si l'exception est dans `retry.retry_on`. Pas de retry aveugle sur `Exception`.

### 6.3 Logs structurés `structlog` — `[NOUVEAU]`

```python
# hydromodpy/core/logging/setup.py    [REFACTORE]

import structlog

def configure_logging(log_dir: Path, run_id: str) -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.contextvars.merge_contextvars,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),         # fichier JSONL
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    structlog.contextvars.bind_contextvars(run_id=run_id)
```

**Exemple de ligne JSONL écrite dans `workspace/logs/<run_id>.log`** :

```json
{"ts":"2026-04-18T14:32:01.123Z","level":"info","event":"step_completed","run_id":"canut-2026","step":"extract","elapsed_ms":12308,"n_timesteps_written":3650}
```

**Agrégation CLI** :

```bash
$ hmp inspect canut-2026 --logs
$ duckdb -c "SELECT step, elapsed_ms FROM read_json_auto('workspace/logs/canut-2026.log') WHERE event='step_completed'"
```

### 6.4 Callbacks d'erreur — `[NOUVEAU]`

```python
@dataclass(frozen=True, slots=True)
class PipelineCallbacks:
    on_step_started:   Callable[[StepContext], None] | None = None
    on_step_completed: Callable[[StepContext, StepState], None] | None = None
    on_step_failed:    Callable[[StepContext, Exception], None] | None = None
    on_pipeline_completed: Callable[[FinalState], None] | None = None
    on_pipeline_failed:    Callable[[Exception, StepState], None] | None = None
```

**Usage** :

- CLI (`hmp run`) : progress bar via `on_step_started`.
- Calibration : `on_step_failed` enregistre l'échec dans la table `calibration_iterations` et continue.
- Tests : assertions sur la séquence d'événements.

### 6.5 Règles d'or — `[NOUVEAU]`

1. **Jamais** de `except Exception: pass`.
2. **Jamais** de `except Exception: logger.debug(...)`. Utiliser `logger.exception(...)` ou lever une `PipelineError` typée.
3. **Toujours** `except PipelineSubclassError:` spécifique, puis `except Exception as e: raise PipelineError("unexpected", ...) from e`.
4. Les `try/finally` sont remplacés par `ExitStack` ou `with`.
5. `KeyboardInterrupt` et `SystemExit` ne sont **jamais** absorbés par `except BaseException`.

---

## 7. Le context manager `Simulation` — cycle de vie

### 7.1 Responsabilité unique

L'audit 06 §7.1 reproche à `Simulation` (project.py, 705 l.) d'avoir **16 responsabilités**. La version cible en a **une seule** : *gérer le cycle de vie d'une exécution de pipeline et exposer ses résultats*. Tout ce qui était dans l'ancienne classe (chargement TOML, détection solver, synthèse `[simulation]`, mesh resolution, etc.) est réparti dans les steps 0–14.

### 7.2 Squelette complet — `[REFACTORE]`

```python
# hydromodpy/simulation/api.py   [REFACTORE ex-project.py, ~80 lignes target]

from __future__ import annotations
from contextlib import ExitStack
from pathlib import Path
from types import TracebackType
from typing import Self

from hydromodpy.simulation.pipeline import Pipeline, PipelineConfig
from hydromodpy.simulation.pipeline.state import InputState, FinalState
from hydromodpy.simulation.pipeline.steps import STANDARD_STEPS
from hydromodpy.results import Simulation as SimulationView


class Simulation:
    """Execute one simulation and expose its results.

    This class is a **thin context manager** around ``Pipeline``. Its single
    responsibility is lifecycle:

    - bind a config to a workspace,
    - run the standard 14-step pipeline,
    - guarantee teardown (store close, scratch cleanup),
    - expose a read-only handle to the produced results.

    All parsing/validation/meshing/solving logic lives in the pipeline steps.

    Example
    -------
    >>> with hmp.Simulation("config.toml", workspace="~/runs") as sim:
    ...     result = sim.run()
    >>> result.sim_id
    'b1c2d3e4-…'
    >>> result.final_state.aggregated.nse
    0.81
    """

    def __init__(
        self,
        config: str | Path | HydroModPyConfig,
        *,
        workspace: str | Path | Workspace | None = None,
        pipeline_cfg: PipelineConfig | None = None,
        steps: Sequence[PipelineStep] | None = None,
    ) -> None:
        self._config_ref = config
        self._workspace_ref = workspace
        self._pipeline_cfg = pipeline_cfg or PipelineConfig.default()
        self._steps = tuple(steps) if steps is not None else STANDARD_STEPS
        self._stack: ExitStack | None = None
        self._final: FinalState | None = None

    # --- Context manager ---------------------------------------------------

    def __enter__(self) -> Self:
        self._stack = ExitStack()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        """Close resources. Does not suppress exceptions."""
        assert self._stack is not None
        self._stack.__exit__(exc_type, exc, tb)
        self._stack = None
        return False          # re-raise

    # --- Public API --------------------------------------------------------

    def run(
        self,
        *,
        overrides: Mapping[str, Any] | None = None,
        run_id: str | None = None,
    ) -> SimulationResult:
        """Execute the pipeline. Requires being in a `with` block."""
        if self._stack is None:
            raise RuntimeError("Simulation must be used as a context manager")
        initial = InputState.build(
            config=self._config_ref,
            workspace=self._workspace_ref,
            overrides=overrides,
            run_id=run_id,
            pipeline_cfg=self._pipeline_cfg,
        )
        pipeline = Pipeline(steps=self._steps, cfg=self._pipeline_cfg)
        self._final = pipeline.run(initial)
        return SimulationResult(self._final)

    @property
    def last_result(self) -> SimulationResult | None:
        return None if self._final is None else SimulationResult(self._final)


@dataclass(frozen=True, slots=True)
class SimulationResult:
    final_state: FinalState

    @property
    def sim_id(self) -> str:
        return self.final_state.sim_id

    @property
    def run_fingerprint(self) -> str:
        return self.final_state.run_fingerprint

    def view(self, catalog: SimulationCatalog | None = None) -> SimulationView:
        """Return a read-only SimulationView bound to the catalog."""
        cat = catalog or SimulationCatalog(self.final_state.config.workspace)
        return cat.simulation(self.sim_id)
```

### 7.3 Bénéfice — diff en ligne de code

| Métrique | Actuel (`project.py`) | Cible (`api.py`) |
|----------|----------------------:|-----------------:|
| Lignes | 705 | ≤ 150 |
| Responsabilités | 16 | **1** |
| Duplications avec `execute_simulation()` | ~200 l. | 0 |
| `_run_with_overrides` bypass planner | oui | non |
| Context manager `__exit__` avec cleanup chainé | partiel | `ExitStack` garanti |
| Testabilité | God class, tests E2E obligatoires | test unitaire par step |

### 7.4 Overrides — `[REFACTORE]`

L'overriding de paramètres **ne passe plus jamais** par une construction manuelle de `SimulationPlan` (bypass du planner signalé audit 06 §7.3). Il passe toujours par `overrides: Mapping[str, Any]` appliqué au state d'entrée :

```python
# hydromodpy/simulation/pipeline/overrides.py    [NOUVEAU]

def apply_overrides(cfg: HydroModPyConfig, overrides: Mapping[str, Any]) -> HydroModPyConfig:
    """Apply dotted-path overrides to the config, returning a fresh instance.

    Example
    -------
    >>> new_cfg = apply_overrides(cfg, {"flow.param.K.value": 1e-4})
    """
    data = cfg.model_dump()
    for dotted, value in overrides.items():
        _set_dotted(data, dotted, value)
    return HydroModPyConfig.model_validate(data)
```

Le pipeline standard retourne alors simplement au planner, qui produit un plan valide conforme aux contraintes (`required_bindings`, unicité).

---

## 8. Batch et calibration — fan-out, optimisateurs, parallélisme

### 8.1 Trois niveaux d'usage

| Niveau | Cas d'usage | Outil |
|--------|-------------|-------|
| 1 sim | Dev, visualisation, 1 simulation | `Simulation` + `Pipeline` |
| N sims indépendantes | Sensitivity, regional batch | `BatchRunner` |
| N sims optimisées | Calibration | `Calibrator` (= `BatchRunner` + `Optimizer`) |

**Propriété** : le pipeline d'une simulation **ne sait pas** qu'il tourne dans un batch. Tout le code de calibration actuel (ex-`ModelCalibrationLauncher`, `analysis/calibration/engine/session.py` 3 409 l.) se réduit à des orchestrateurs qui invoquent `Pipeline.run()` N fois.

### 8.2 `BatchRunner` — `[REFACTORE]` (ex-`analysis/batch/batch.py` 1 828 l.)

```python
# hydromodpy/batch/runner.py    [NOUVEAU]

@dataclass(frozen=True, slots=True)
class BatchConfig:
    n_workers: int = 1
    parallelism: Literal["serial", "process", "thread", "dask"] = "process"
    retry: RetryPolicy = RetryPolicy(max_attempts=2, retry_on=(NetworkError,))
    fail_fast: bool = False
    checkpoint_per_sim: bool = True


class BatchRunner:
    """Fan out N independent Simulation executions.

    Not a pipeline itself. Each trial is a full Pipeline.run().
    """

    def __init__(self, cfg: BatchConfig): ...

    def run(
        self,
        trials: Iterable[TrialSpec],
        *,
        callbacks: BatchCallbacks | None = None,
    ) -> BatchReport:
        executor = self._build_executor()          # Process / Thread / Dask
        futures = []
        with executor:
            for trial in trials:
                fut = executor.submit(_run_one_trial, trial, self.cfg)
                futures.append((trial, fut))
            results: list[TrialResult] = []
            for trial, fut in as_completed_(futures):
                try:
                    results.append(fut.result())
                except PipelineError as e:
                    results.append(TrialResult.failure(trial, e))
                    if self.cfg.fail_fast: break
        return BatchReport(trials=tuple(results))


@dataclass(frozen=True, slots=True)
class TrialSpec:
    trial_id: str
    config: HydroModPyConfig         # OR config_ref + overrides
    workspace: Path
    run_id: str | None = None


def _run_one_trial(trial: TrialSpec, cfg: BatchConfig) -> TrialResult:
    """Top-level callable for ProcessPoolExecutor (must be pickleable)."""
    with hmp.Simulation(trial.config, workspace=trial.workspace) as sim:
        result = sim.run(run_id=trial.run_id)
    return TrialResult.success(trial, result)
```

### 8.3 Interface optimizer — `[NOUVEAU]`

L'objectif est d'être agnostique de l'optimiseur : scipy, optuna, pyDOE, PEST++, DREAM doivent se connecter sans modifier le cœur.

```python
# hydromodpy/calibration/objective.py    [NOUVEAU]

@runtime_checkable
class Objective(Protocol):
    """Callable objective for external optimizers."""
    param_space: ParamSpace              # bounds + priors
    def evaluate(
        self, params: Mapping[str, float],
    ) -> ObjectiveEvaluation: ...

@dataclass(frozen=True, slots=True)
class ObjectiveEvaluation:
    metrics: dict[str, float]            # {"nse": 0.81, "kge": 0.75}
    sim_id: str
    success: bool
    duration_s: float
    trial_metadata: dict[str, Any] = field(default_factory=dict)
```

#### 8.3.1 Implémentation de référence

```python
class SimulationObjective(Objective):
    def __init__(
        self,
        base_config: HydroModPyConfig,
        workspace: Workspace,
        *,
        param_space: ParamSpace,
        metric_names: tuple[str, ...] = ("nse",),
        station_id: str = "outlet",
        aggregation: Callable[[dict[str, float]], float] = operator.itemgetter("nse"),
    ): ...

    def evaluate(self, params: Mapping[str, float]) -> ObjectiveEvaluation:
        overrides = {f"flow.param.{k}.value": v for k, v in params.items()}
        with hmp.Simulation(self.base_config, workspace=self.workspace) as sim:
            try:
                res = sim.run(overrides=overrides)
                metrics = _extract_metrics(res, self.metric_names, self.station_id)
                return ObjectiveEvaluation(
                    metrics=metrics, sim_id=res.sim_id,
                    success=True, duration_s=res.final_state.duration_s,
                )
            except PipelineError as e:
                return ObjectiveEvaluation(
                    metrics={"nse": -np.inf}, sim_id="",
                    success=False, duration_s=0.0,
                    trial_metadata={"error_kind": type(e).__name__, "error_msg": str(e)},
                )
```

#### 8.3.2 Adapteurs d'optimiseurs — `[NOUVEAU]`

```python
# hydromodpy/calibration/adapters/optuna.py   [NOUVEAU]

def optimize_with_optuna(
    obj: Objective, *, n_trials: int, sampler: optuna.samplers.BaseSampler | None = None,
) -> optuna.Study:
    study = optuna.create_study(direction="maximize", sampler=sampler)
    def _objective(trial: optuna.Trial) -> float:
        params = {
            name: trial.suggest_float(name, lo, hi, log=log)
            for name, (lo, hi, log) in obj.param_space.items()
        }
        evaluation = obj.evaluate(params)
        return evaluation.metrics.get("nse", -np.inf) if evaluation.success else -np.inf
    study.optimize(_objective, n_trials=n_trials)
    return study


# hydromodpy/calibration/adapters/scipy.py    [NOUVEAU]

def optimize_with_scipy(
    obj: Objective, *, x0: np.ndarray, method: str = "Nelder-Mead", **kwargs
) -> OptimizeResult:
    names = tuple(obj.param_space.keys())
    def _fun(x: np.ndarray) -> float:
        params = dict(zip(names, x))
        evaluation = obj.evaluate(params)
        return -evaluation.metrics.get("nse", -np.inf)
    return scipy.optimize.minimize(_fun, x0=x0, method=method, **kwargs)


# hydromodpy/calibration/adapters/pest.py     [NOUVEAU]

def emit_pest_control_file(obj: Objective, path: Path) -> None:
    """Emit a PEST++ control file (.pst) wiring the objective as a template run."""
    ...
```

### 8.4 `Calibrator` — `[RENOMME]` (ex-`ModelCalibrationLauncher`)

```python
# hydromodpy/calibration/calibrator.py        [RENOMME]

class Calibrator:
    """High-level driver: ties an Objective to an optimizer adapter."""

    def __init__(
        self,
        objective: Objective,
        *,
        method: Literal["optuna", "scipy", "pyDOE", "pest"] = "optuna",
        batch: BatchRunner | None = None,
    ): ...

    def run(self, n_trials: int, **kwargs) -> CalibrationReport:
        if self.method == "optuna":
            study = optimize_with_optuna(self.objective, n_trials=n_trials, **kwargs)
            return CalibrationReport.from_optuna(study)
        if self.method == "scipy":
            res = optimize_with_scipy(self.objective, **kwargs)
            return CalibrationReport.from_scipy(res)
        ...
```

### 8.5 Parallélisme — choix et justification

| Mode | Quand l'utiliser | Quand l'éviter |
|------|------------------|----------------|
| `serial` | debug, 1 sim, tests CI | batch > 5 sims |
| `process` (par défaut) | batch local, machines multi-core | quand le solveur est déjà multi-threadé (MF6 openMP) |
| `thread` | rarement utile en scientifique Python (GIL) | tout sauf I/O-bound |
| `dask` | batch distribué HPC (SLURM), milliers de sims | installation locale simple |

**Règle** : `process` par défaut. MF6/NWT/Boussinesq libèrent le GIL dans leurs binaires natifs, donc `thread` ne profite pas. `dask` est une extension opt-in (`pip install hydromodpy[dask]`).

### 8.6 Pickleabilité — `[REFACTORE]`

Pour `ProcessPoolExecutor` et `dask.distributed`, **`HydroModPyConfig` et toutes les dataclasses du pipeline doivent être picklable**. Contraintes :

- Pas de `Logger` dans les dataclasses (reconstruit côté worker via `structlog.get_logger()`).
- Pas de connexion DuckDB dans les dataclasses (ouverte dans le worker).
- Pas de handle de fichier, pas de `threading.Lock`.

Un test CI `test_pickleability.py` vérifie `pickle.dumps(cfg)` pour chaque classe publique.

### 8.7 Concurrence DuckDB — `[NOUVEAU]`

DuckDB ne supporte pas nativement l'écriture multi-process. Stratégie :

- **Chaque worker** écrit dans **son propre** `hydromodpy.duckdb.partial-<trial_id>.duckdb`.
- **Merge** en fin de batch : le `BatchRunner` consolide via `ATTACH ... AS tmp; INSERT INTO simulations SELECT * FROM tmp.simulations; DETACH tmp;`.
- **Alternative** (extensive): écrire chaque sim dans un Zarr, DuckDB n'ouvre les partitions que en lecture.

---

## 9. API publique — trois niveaux d'abstraction

### 9.1 Niveau 1 — CLI (usage production)

```bash
# Un seul verbe, plusieurs workflows détectés par section TOML
hmp run config.toml                       # dispatch automatique
hmp run config.toml --resume              # reprise depuis dernier checkpoint
hmp run config.toml --until mesh          # dry-run partiel
hmp run config.toml --seed 42             # override seed
hmp run config.toml --workers 8           # fan-out batch (si [batch] ou [calibration] présent)

# Commandes auxiliaires
hmp inspect <sim_id> --provenance         # affiche runs_environment + step_durations
hmp list --project canut --since 7d
hmp display <sim_id> --suite watertable   # post-hoc figures
hmp export <sim_id> --format netcdf
hmp validate config.toml                  # Dry-run du step 0 uniquement
```

### 9.2 Niveau 2 — API Python haut-niveau

```python
import hydromodpy as hmp

# Cas 1 : 1 simulation
with hmp.Simulation("config.toml", workspace="~/runs") as sim:
    result = sim.run()
print(result.sim_id, result.final_state.aggregated.metrics)

# Cas 2 : batch régional (50 bassins versants)
specs = [hmp.TrialSpec(trial_id=b, config=f"configs/{b}.toml", workspace="~/runs")
         for b in ["canut", "blavet", "oust", ...]]
report = hmp.batch.BatchRunner(BatchConfig(n_workers=8)).run(specs)
report.summary()                          # DataFrame avec NSE par bassin

# Cas 3 : calibration avec optuna
base_cfg = hmp.load_config("canut.toml")
param_space = {
    "K":  (1e-6, 1e-2, True),     # log-uniform
    "Sy": (0.05, 0.35, False),
}
obj = hmp.calibration.SimulationObjective(
    base_cfg, workspace="~/runs", param_space=param_space, station_id="outlet",
)
cal = hmp.calibration.Calibrator(obj, method="optuna")
report = cal.run(n_trials=200)
print(report.best_params, report.best_metrics)
```

### 9.3 Niveau 3 — API bas-niveau (tests, plugins, recherche)

```python
from hydromodpy.simulation.pipeline import Pipeline, PipelineConfig
from hydromodpy.simulation.pipeline.steps import (
    ValidateStep, ResolveStep, LoadDataStep, MeshStep, ..., FinalizeStep,
)
from hydromodpy.simulation.pipeline.state import InputState

# Pipeline personnalisé : sans display ni export
custom_steps = [
    ValidateStep(), ResolveStep(), LoadDataStep(), GeographicStep(),
    MeshStep(), DomainStep(), PlanStep(), OpenStoreStep(),
    SolveStep(), ExtractStep(), DeriveStep(), AggregateStep(), FinalizeStep(),
]
pipeline = Pipeline(steps=custom_steps, cfg=PipelineConfig(enable_cache=True))
initial = InputState.build(config="config.toml", workspace="~/runs")
final = pipeline.run(initial)

# Inspection étape par étape via le CheckpointStore
cp = CheckpointStore(workspace="~/runs", run_id=final.run_id)
meshed_state = cp.restore(step_index=4)
print(meshed_state.mesh.n_cells)
```

Les trois niveaux partagent le **même code** — le pipeline standard est une liste constante utilisée par `Simulation` ; la CLI utilise `Simulation` ; la calibration utilise `Simulation`.

---

## 10. Comparaison aux standards industrie

### 10.1 Matrice détaillée

| Aspect | HydroModPy actuel | HydroModPy cible | Prefect 2.x | Dagster 1.x | Snakemake 8 | Nextflow | Airflow 2 |
|---|---|---|---|---|---|---|---|
| DAG explicite | Non (ordre script) | **Oui (list + type-checked)** | Oui | Oui (assets) | Oui (rules) | Oui (channels) | Oui |
| Sérialisation plan | Implicite (dataclass) | **Oui (JSON to_json/from_json)** | Oui | Oui | Implicite | Implicite | Oui |
| Retry par step | Non | **Oui (RetryPolicy déclaratif)** | Oui | Oui | Oui | Oui | Oui |
| Resume from checkpoint | Non | **Oui (CheckpointStore)** | Oui | Oui | Oui (natif) | Oui (-resume) | Oui (XCom) |
| Cache content-addressable | Non | **Oui (CAS par fingerprint)** | Oui | Oui (IOManager) | Oui (natif) | Oui (-resume) | Non |
| Structured logging | Partiel (stdlib) | **Oui (structlog JSONL)** | Oui | Oui | Stdlib | Stdlib + channel | Oui |
| Typage I/O | Non | **Oui (frozen dataclass TIn/TOut)** | Pydantic | Oui (types) | Non | Non | Non |
| Provenance | Partielle | **PROV-O complet (DuckDB)** | Partiel | Oui (materialization) | Partiel | Partiel | Partiel |
| Pluginability solver | Registry statique dual | **Entry-points setuptools** | N/A | Oui | N/A | Plugins | Providers |
| Batch natif | Runtime ad-hoc 1 828 l. | **BatchRunner 200 l.** | Oui (Map) | Oui (Partitions) | Oui (wildcards) | Oui (channels) | Oui (TaskGroup) |
| Calibration | Couplé pipeline | **Optimizer-agnostic Objective** | N/A | N/A | N/A | N/A | N/A |
| Déterminisme | Non contractuel | **run_fingerprint SHA-256** | N/A | Oui (asset keys) | Oui (params hash) | Oui (hashes) | N/A |
| Testabilité step-level | Difficile | **1 fichier = 1 step = 1 test** | Oui | Oui | Non (rule test) | Non | Difficile |

### 10.2 Justifications des choix

**Pourquoi pas Prefect ?**
Prefect impose un serveur (API + UI) pour exploiter le resume et le monitoring. Coût d'adoption élevé pour un outil scientifique installé localement. **HydroModPy implémente le sous-ensemble Prefect nécessaire** (retries, hooks, state machine) sans le serveur.

**Pourquoi pas Dagster ?**
Dagster est idéal pour les data pipelines production avec UI. Overkill pour un outil scientifique où chaque étude = 1 pipeline dédié. On reprend **IOManager** conceptuellement (séparation calcul/persistance) et **assets** (par `sim_id`).

**Pourquoi pas Snakemake / Nextflow ?**
Ces outils sont excellents pour les pipelines **bioinformatiques** (fichiers ↔ rules). Notre stockage est **DuckDB + Zarr** à la fois. Un wrapper Snakemake forcerait à exposer des paths intermédiaires faux pour déclencher les rules. Mauvaise impédance.

**Pourquoi `structlog` et pas `loguru` ou stdlib pur ?**
- `loguru` : excellent pour format humain, mais JSONL et propagation de contextvars moins idiomatiques.
- `logging` stdlib : verbeux, peu de propagation contextuelle.
- `structlog` : JSONL natif, `bind_contextvars(run_id=...)`, processors composables, compatibilité `logging`.

**Pourquoi `zstandard` pour les checkpoints et pas `gzip` ?**
- Compression ratio équivalent ou meilleur.
- Décompression 3-5× plus rapide.
- Standard dans l'écosystème data (Parquet, RocksDB, Kafka). Déjà dépendance indirecte de DuckDB.

---

## 11. Mapping ancien → cible

### 11.1 Tableau de migration complet

| Ancien (branche dev-database) | Cible | Statut |
|-------------------------------|-------|--------|
| `hydromodpy/project.py` (`Simulation`, 705 l.) | `hydromodpy/simulation/api.py` (≤ 150 l.) | **[REFACTORE]** |
| `hydromodpy/workflow/pipelines/simulation.py` | `hydromodpy/simulation/pipeline/pipeline.py` | **[REFACTORE]** |
| `hydromodpy/workflow/pipelines/process_simulation.py` (33 l. re-exports) | — | **[SUPPRIME]** (dead code) |
| `hydromodpy/workflow/pipelines/overview.py` | `hydromodpy/simulation/workflows/overview_workflow.py` | **[RENOMME + REFACTORE]** |
| `hydromodpy/workflow/pipelines/mesh.py` | `hydromodpy/simulation/workflows/mesh_workflow.py` | **[RENOMME]** |
| `hydromodpy/workflow/steps/setup.py` | éclaté dans `steps/step_01_resolve.py`, `step_03_geographic.py`, `step_05_domain.py` | **[REFACTORE]** |
| `hydromodpy/workflow/steps/data_loading.py` | `simulation/pipeline/steps/step_02_load_data.py` | **[RENOMME]** |
| `hydromodpy/workflow/steps/mesh.py` | `simulation/pipeline/steps/step_04_mesh.py` | **[RENOMME]** |
| `hydromodpy/workflow/steps/spatial_supports.py` | absorbé dans `step_03_geographic.py` + `step_05_domain.py` | **[REFACTORE]** |
| `hydromodpy/workflow/steps/store_lifecycle.py` | `simulation/pipeline/steps/step_07_open_store.py` + `step_14_finalize.py` | **[REFACTORE]** |
| `hydromodpy/workflow/steps/result_ingestion.py` | `simulation/pipeline/steps/step_09_extract.py` | **[REFACTORE]** |
| `hydromodpy/workflow/context.py` (`WorkflowContext` mutable) | `hydromodpy/simulation/pipeline/state.py` (14 frozen dataclasses) | **[REFACTORE]** |
| `hydromodpy/simulation/execution/runner.py` (`SimulationRunner`) | `hydromodpy/simulation/pipeline/steps/step_08_solve.py` + `solver/runner.py` | **[REFACTORE]** |
| `hydromodpy/simulation/planning/planner.py` | `hydromodpy/simulation/pipeline/steps/step_06_plan.py` (+ `planning/` conservé) | **[CONSERVE]** (wrapping) |
| `hydromodpy/simulation/planning/plan.py` (`SimulationPlan` frozen) | idem + `.to_json()` / `.from_json()` | **[REFACTORE]** |
| `hydromodpy/simulation/adapters/registry.py` (`_ADAPTERS`) | fusion avec `simulation/results/post_run.py:_ADAPTER_REGISTRY` sous `solver/registry.py` | **[REFACTORE]** (cf. doc 05) |
| `hydromodpy/simulation/adapters/display/stub.py` + `postprocess/stub.py` | — | **[SUPPRIME]** (dead code) |
| `hydromodpy/simulation/results/extractors/` (9 fichiers) | `hydromodpy/simulation/extraction/` + `_BinaryHeadExtractor` factorisé | **[REFACTORE]** |
| `hydromodpy/simulation/results/extractors/derived.py` (581 l.) | `simulation/pipeline/steps/step_10_derive.py` + `DerivedRegistry` | **[REFACTORE]** |
| `hydromodpy/simulation/results/extractors/catchment_aggregation.py` (heuristique `n_per` bugguée) | `simulation/pipeline/steps/step_11_aggregate.py` (lit DuckDB) | **[REFACTORE]** |
| `hydromodpy/simulation/settings.py` (16 l. DeprecationWarning) | — | **[SUPPRIME]** |
| `hydromodpy/simulation/forcing/__init__.py` (31 l. re-exports) | — | **[SUPPRIME]** |
| `hydromodpy/analysis/calibration/engine/session.py` (3 409 l.) | `hydromodpy/calibration/calibrator.py` + adapters (≤ 800 l. total) | **[REFACTORE]** |
| `hydromodpy/analysis/batch/batch.py` (1 828 l.) | `hydromodpy/batch/runner.py` (≤ 300 l.) | **[REFACTORE]** |
| — | `hydromodpy/simulation/pipeline/checkpoint.py` | **[NOUVEAU]** |
| — | `hydromodpy/simulation/pipeline/fingerprint.py` | **[NOUVEAU]** |
| — | `hydromodpy/simulation/pipeline/errors.py` | **[NOUVEAU]** |
| — | `hydromodpy/simulation/pipeline/cache.py` | **[NOUVEAU]** |
| — | `hydromodpy/simulation/pipeline/resources.py` | **[NOUVEAU]** |
| — | `hydromodpy/simulation/pipeline/context.py` | **[NOUVEAU]** |
| — | `hydromodpy/calibration/adapters/optuna.py` | **[NOUVEAU]** |
| — | `hydromodpy/calibration/adapters/scipy.py` | **[NOUVEAU]** |
| — | `hydromodpy/calibration/adapters/pest.py` | **[NOUVEAU]** |
| — | `hydromodpy/core/logging/structlog_setup.py` | **[NOUVEAU]** |

### 11.2 Impact chiffré

| Métrique | Avant | Après | Delta |
|---|---:|---:|---|
| LOC simulation/workflow | ~5 377 | **~2 400** | **−55 %** |
| Classes God (>500 l.) | 3 (`Simulation`, `session`, `batch`) | **0** | |
| Duplications MF6↔NWT | ~200 l. | **0** (via `_BinaryHeadExtractor`) | |
| Registres parallèles | 2 | **1** | |
| Tests unitaires step-level | ~8 | **14 (1 par step)** | +75 % |
| Reprise après crash | ✗ | ✓ | nouveau |
| Déterminisme contractuel | ✗ | ✓ | nouveau |

---

## 12. Tests de conformité du pipeline

### 12.1 Suite de conformité — `[NOUVEAU]`

Chaque pipeline doit passer la suite `tests/pipeline/conformance/` :

```python
# tests/pipeline/conformance/test_step_purity.py    [NOUVEAU]

@pytest.mark.parametrize("step_cls", STANDARD_STEPS)
def test_step_is_pure(step_cls, sample_input_state, resources, ctx):
    """A step must not mutate its input state."""
    s_before = dataclasses.asdict(sample_input_state)
    _ = step_cls()(sample_input_state, resources=resources, ctx=ctx)
    assert dataclasses.asdict(sample_input_state) == s_before


@pytest.mark.parametrize("step_cls", STANDARD_STEPS)
def test_step_fingerprint_is_deterministic(step_cls, sample_input_state):
    """Two calls with equal input → identical fingerprint."""
    f1 = step_cls().fingerprint(sample_input_state)
    f2 = step_cls().fingerprint(sample_input_state)
    assert f1 == f2


def test_pipeline_is_dag_linear():
    """Standard pipeline = exactly 15 ordered steps."""
    assert len(STANDARD_STEPS) == 15
    for i, step in enumerate(STANDARD_STEPS):
        assert step().in_type == (STANDARD_STEPS[i-1]().out_type if i > 0 else InputState)


def test_resume_after_any_failure(tmp_workspace, failing_step_factory):
    """Injecting failure at step N produces valid checkpoint up to step N-1."""
    for fail_index in range(1, 14):
        steps = [failing_step_factory(i, fail_index) for i in range(15)]
        with pytest.raises(PipelineError):
            Pipeline(steps, cfg=PipelineConfig(checkpoint=True)).run(initial_state)
        cp = CheckpointStore(tmp_workspace, run_id=initial_state.run_id)
        assert cp.latest_success() == fail_index - 1
```

### 12.2 Tests de reproductibilité

```python
@pytest.mark.validation
def test_batch_100_sims_determinism(tmp_workspace):
    """Running 100 sims twice must produce identical aggregate DataFrame."""
    trials = [TrialSpec(trial_id=f"t{i}", config=_param_config(i), workspace=tmp_workspace)
              for i in range(100)]
    r1 = BatchRunner(BatchConfig(n_workers=4)).run(trials)
    r2 = BatchRunner(BatchConfig(n_workers=4)).run(trials)
    # Same trial_id + same config → same run_fingerprint
    fp1 = {t.trial_id: t.result.run_fingerprint for t in r1.trials}
    fp2 = {t.trial_id: t.result.run_fingerprint for t in r2.trials}
    assert fp1 == fp2
```

### 12.3 Tests de performance

```python
@pytest.mark.benchmark
def test_pipeline_overhead_under_threshold(benchmark, tiny_config):
    """Non-solve steps total overhead < 5% of solve duration on a tiny case."""
    result = benchmark(lambda: hmp.Simulation(tiny_config).run())
    overhead = sum(v for k, v in result.final_state.step_durations.items() if k != "solve")
    solve = result.final_state.step_durations["solve"]
    assert overhead / solve < 0.05


@pytest.mark.benchmark
def test_batch_parallel_scaling(tmp_workspace):
    """Batch 32 sims on 8 workers ≥ 5× faster than serial (linear scaling > 60%)."""
    trials = [TrialSpec(...) for _ in range(32)]
    t_serial = _time(lambda: BatchRunner(BatchConfig(n_workers=1)).run(trials))
    t_par    = _time(lambda: BatchRunner(BatchConfig(n_workers=8)).run(trials))
    assert t_serial / t_par > 5.0
```

### 12.4 Tests de robustesse

```python
@pytest.mark.parametrize("kill_step", ["solve", "extract", "aggregate"])
def test_crash_then_resume_gives_same_state(tmp_workspace, kill_step):
    """Crash at step X → --resume → final state identical to non-crashing run."""
    ...


def test_keyboard_interrupt_closes_resources(tmp_workspace):
    """Ctrl-C mid-pipeline: DuckDB closed, Zarr consistent, scratch cleaned."""
    ...


def test_concurrent_pipelines_different_workspaces(tmp_workspace_factory):
    """Running 4 pipelines in parallel in 4 workspaces → no lock contention."""
    ...
```

---

## 13. Récapitulatif — ce qui change concrètement

### 13.1 Pour l'utilisateur final

- Le verbe `hmp run config.toml` inchangé.
- Nouveautés : `--resume`, `--until`, `--from`, `--dry-run`, `--seed`, `--force-new-uuid`.
- Logs JSONL exploitables (`duckdb -c "SELECT ... FROM read_json_auto('workspace/logs/*')"`).
- Même config TOML identique, `sim_id` désormais **déterministe** à partir du contenu.
- Nouveau : `hmp inspect <sim_id> --provenance` pour audit reproductibilité.

### 13.2 Pour l'auteur de script Python

- `Simulation` devient un vrai context manager propre (≤ 150 l., 1 responsabilité).
- `hmp.batch.BatchRunner` remplace tout le code ad-hoc de `regional_lab`.
- `hmp.calibration.Calibrator` + `Objective` remplacent `ModelCalibrationLauncher` (3 409 l. → 800 l.).
- Support natif de **optuna**, **scipy.optimize**, **PEST++** via adapters.
- API bas-niveau `Pipeline(steps=[...])` pour recherche/tests.

### 13.3 Pour le mainteneur

- 14 steps = 14 fichiers = 14 tests unitaires isolés.
- Plus de `God class` (`Simulation`, `session`, `batch`).
- Plus de `except Exception: pass`.
- Exceptions typées : calibration peut réagir finement à `SolverDivergedError` sans parser de message.
- Checkpointing natif : reprise au step X sans replay des X-1 précédents.
- Cache CAS : deux configs identiques → 0 recalcul.
- `run_fingerprint` DuckDB-indexé : dédoublonnage, audit, reproductibilité en une requête SQL.

### 13.4 Pour la CI

- Temps total de CI réduit (cache CAS entre jobs via artefact).
- Test `test_pipeline_is_dag_linear()` garantit qu'on n'oublie pas un step.
- Test `test_step_is_pure()` bloque les régressions de mutabilité.
- Test `test_reproducibility()` bloque les régressions de déterminisme.

---

## 14. En une phrase

> Le pipeline cible transforme HydroModPy **d'un script scientifique avec une god-class** en un **orchestrateur déclaratif à 14 steps typés, reproductible, interruptible-reprenable, et agnostique de l'optimiseur** — sans adhérer à Prefect/Dagster/Airflow et sans serveur supplémentaire, en s'appuyant uniquement sur `dataclass(frozen=True)`, `structlog`, `zstandard`, et le catalog DuckDB déjà prévu par les architectures cibles 04 et 05.
