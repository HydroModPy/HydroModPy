# Architecture cible — Contrats d'interface des solveurs HydroModPy

**Document** : `architecture_cible/05_solver_contracts.md`
**Date** : 2026-04-18
**Auteur** : Architecte plugin / design d'interfaces (références : scikit-learn estimators, SQLAlchemy dialects, Keras backends, PyMT / BMI, Prefect TaskRunner, pluggy)
**Portée** : redéfinir l'interface qu'un solveur numérique (écoulement, transport, traçage) doit implémenter pour s'intégrer à HydroModPy **sans modifier le code existant**.
**Statut** : design complet, pas un patch.
**Sources** : audits `05_process_solver.md`, `06_simulation_engine.md` ; docs cibles `01_structure_packages.md`, `03_data_contracts.md`, `04_storage_ideal.md`.

> **Légende des tags**
> `[NOUVEAU]` n'existe pas · `[RENOMME]` existe sous un autre nom · `[REFACTORE]` existe mais change · `[CONSERVE]` existe et reste tel quel.

> **Objectif opérationnel** : un tiers installe `pip install hydromodpy-feflow`. Le package déclare un entry-point. HydroModPy détecte, valide, enregistre. L'utilisateur écrit `[simulation]` `solver = "feflow"` dans son TOML. `hmp run config.toml` fonctionne. Les figures, exports NetCDF, agrégations catchment, la calibration, la comparaison multi-solveurs, tout roule. **Aucun fichier du cœur n'a été édité.**

---

## Table des matières

0. [Principes directeurs](#0-principes-directeurs)
1. [Vue d'ensemble — les 5 contrats](#1-vue-densemble--les-5-contrats)
2. [Contrat n°1 — `SolverPlugin` (point d'entrée d'un solveur)](#2-contrat-n1--solverplugin-point-dentrée-dun-solveur)
3. [Contrat n°2 — `ProcessKind` (processus physiques supportés)](#3-contrat-n2--processkind-processus-physiques-supportés)
4. [Contrat n°3 — `SolverRunner` (cycle de vie d'une exécution)](#4-contrat-n3--solverrunner-cycle-de-vie-dune-exécution)
5. [Contrat n°4 — `ResultExtractor` (écriture dans le catalog)](#5-contrat-n4--resultextractor-écriture-dans-le-catalog)
6. [Contrat n°5 — `SolverConfig` (Pydantic model)](#6-contrat-n5--solverconfig-pydantic-model)
7. [Registre et découverte — entry-points + fallback](#7-registre-et-découverte--entry-points--fallback)
8. [Gestion d'erreurs et états terminaux](#8-gestion-derreurs-et-états-terminaux)
9. [Exemple complet — plugin `mysolver` en 100 lignes](#9-exemple-complet--plugin-mysolver-en-100-lignes)
10. [Tableau comparatif des solveurs (actuels + extensions)](#10-tableau-comparatif-des-solveurs-actuels--extensions)
11. [Migration — mapping ancien → cible](#11-migration--mapping-ancien--cible)
12. [Tests de conformité d'un plugin](#12-tests-de-conformité-dun-plugin)

---

## 0. Principes directeurs

| # | Principe | Conséquence pratique |
|---|----------|----------------------|
| 1 | **Protocol structurel, pas ABC** | Duck-typing vérifié par `@runtime_checkable Protocol` (PEP 544). Un solveur tiers n'a pas besoin d'importer de classe de base. Aucun couplage parent/enfant. |
| 2 | **Séparation 5 contrats clairs** | `SolverPlugin` (façade), `SolverRunner` (cycle de vie), `ResultExtractor` (I/O), `SolverConfig` (Pydantic), `ProcessKind` (Enum). Chacun remplit UN rôle. |
| 3 | **Cycle de vie explicite** | `setup → build → solve → extract → cleanup`. Cinq étapes séquentielles, contractuelles. Pas d'héritage multi-niveaux (actuel NWT: 7 niveaux d'indirection). |
| 4 | **Grille unifiée côté HydroModPy** | Le solveur reçoit une `HydroMesh` UGRID 1.0 (cf. `03_data_contracts.md` §3). Il renvoie des champs indexés par `face_id`. L'aval (display, export) ne connaît pas le solveur. |
| 5 | **Registre via entry-points setuptools** | `pyproject.toml` d'un plugin déclare `[project.entry-points."hydromodpy.solver"]`. Zéro monkey-patching, zéro édition de `registry.py`. Modèle SQLAlchemy dialects. |
| 6 | **Fallback `register()` programmatique** | Pour les solveurs embarqués (NWT, MF6, Boussinesq) et le développement local, un appel direct `hmp.solver.register(SolverPlugin)` reste disponible. |
| 7 | **Capacités déclaratives** | Chaque plugin publie `SolverCapabilities` (process_kinds, mesh_types, regimes, parallel, transport, particles, …). Le `SimulationPlanner` interroge les capacités **avant** exécution. Les incompatibilités sont détectées au plan, pas au run. |
| 8 | **Erreurs typées, pas de booléen** | Un solveur lève `SolverDivergedError`, `SolverTimeoutError`, `SolverInputError`, `SolverBinaryNotFoundError`. Fini `return False`. Le runner les capte et les journalise en DuckDB (`simulations.status`, `simulations.error_kind`). |
| 9 | **Schéma de sortie unique** | Tous les solveurs écrivent dans `SimulationCatalog` via `ResultExtractor`. Zarr layout commun (`head`, `budget/*`, `derived/*`), DuckDB tables communes (`timeseries`, `budgets`, `mass_balance`). La figure `watertable_map` ne sait pas si c'est MF6 ou MySolver. |
| 10 | **Conformité testable en CLI** | `hmp solver check <name>` exécute une suite de ~30 tests de contrat (dry-run, solve stationnaire analytique, extraction schéma). Un plugin tiers peut valider localement avant release. |

### 0.1 Comparaison aux projets de référence

| Projet | Ce qu'on reprend | Ce qu'on ne reprend pas |
|--------|------------------|--------------------------|
| **scikit-learn estimators** | Duck-typing `fit/predict`, `get_params/set_params`, introspection automatique | Pas de classe `BaseEstimator` — on préfère Protocol |
| **SQLAlchemy dialects** | Entry-points `sqlalchemy.dialects`, capacités déclaratives (`supports_*`), dispatch par URL scheme | Pas de SQL abstraction — domaine différent |
| **Keras backends** | Interface backend unique (TF/JAX/Torch), bascule transparente | Pas de tensor abstraction — HydroMesh suffit |
| **PyMT / BMI v2** | Cycle de vie explicite `initialize/update/finalize`, capacités `get_*_info()` | BMI trop générique (chaîne de types Fortran), on reste pythonique |
| **Prefect TaskRunner** | `setup/run/teardown`, gestion d'erreurs typées, callbacks | Pas de scheduler distribué |
| **pluggy (pytest, tox)** | Hook specs + hook implementations, collecte automatique, priorités | Pas besoin des priorités ni du multi-hook (un seul plugin par solveur) |
| **SQLAlchemy `Dialect.type_descriptor`** | Méthode de spécialisation (process → solver-specific payload) | — |
| **Dask `Scheduler` plugin** | Entry-points + capabilities | — |

---

## 1. Vue d'ensemble — les 5 contrats

Un plugin solveur HydroModPy = **une classe qui expose cinq contrats**. Tout le reste (TOML, figures, exports, calibration) est fourni par le cœur.

```
┌──────────────────────────────────────────────────────────────────────┐
│                     PLUGIN SOLVEUR (un fichier)                      │
│                                                                      │
│  @hmp.solver.register                                                │
│  class FeflowPlugin(SolverPlugin):                                   │
│      name = "feflow"                                                 │
│      capabilities = SolverCapabilities(...)                          │
│                                                                      │
│      config_model = FeflowConfig         ◄── Contrat 5 (Pydantic)    │
│                                                                      │
│      def runner(self, ctx) -> SolverRunner:   ◄── Contrat 3          │
│          return FeflowRunner(ctx)                                    │
│                                                                      │
│      def extractor(self) -> ResultExtractor: ◄── Contrat 4          │
│          return FeflowExtractor()                                    │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                                 │ enregistré via entry-point
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     CŒUR HYDROMODPY (ne change pas)                  │
│                                                                      │
│   SolverRegistry  ←─────  découverte automatique                     │
│       │                                                              │
│       ▼                                                              │
│   SimulationPlanner                                                  │
│       │  valide capabilities, résout dépendances                     │
│       ▼                                                              │
│   SimulationRunner                                                   │
│       │  pour chaque ProcessRun :                                    │
│       │     runner = plugin.runner(ctx)                              │
│       │     runner.setup()       ◄── préparation scratch dir         │
│       │     runner.build()       ◄── écriture fichiers d'entrée      │
│       │     runner.solve()       ◄── exécution numérique             │
│       │     runner.cleanup()     ◄── libération ressources           │
│       ▼                                                              │
│   ResultIngest                                                       │
│       │  extractor = plugin.extractor()                              │
│       │  extractor.extract(sim_id, scratch_dir, store)               │
│       │  extractor.derive(sim_id, store, derived_flags)              │
│       ▼                                                              │
│   SimulationCatalog (DuckDB + Zarr) ──► display/, exports, figures   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### Arborescence cible des fichiers cœur

```
hydromodpy/solver/
├── __init__.py                     # exporte : register, SolverPlugin, SolverRunner, ...
├── contracts/                      # [REFACTORE] — consolidation de solver/contracts.py
│   ├── __init__.py                 # ré-exports publics
│   ├── plugin.py                   # [NOUVEAU] SolverPlugin Protocol + SolverCapabilities
│   ├── runner.py                   # [NOUVEAU] SolverRunner Protocol + RunContext
│   ├── extractor.py                # [NOUVEAU] ResultExtractor Protocol + ExtractContext
│   ├── config.py                   # [RENOMME] SolverConfig (depuis solver/base/solver_config.py)
│   ├── process_kind.py             # [NOUVEAU] ProcessKind enum (flow, transport, particles, ...)
│   └── errors.py                   # [NOUVEAU] hiérarchie d'exceptions typées
├── registry/                       # [NOUVEAU] remplace simulation/adapters/registry.py
│   ├── __init__.py                 # register(), get_plugin(), list_plugins()
│   ├── registry.py                 # SolverRegistry (single source of truth)
│   ├── discovery.py                # découverte entry-points setuptools
│   └── builtin.py                  # enregistrement des solveurs embarqués (NWT, MF6, Boussinesq)
│
├── modflow_nwt/                    # [CONSERVE structure, REFACTORE contenu]
│   ├── plugin.py                   # [NOUVEAU] implémentation des 5 contrats
│   ├── runner.py                   # [NOUVEAU] FloPy NWT runner
│   ├── extractor.py                # [NOUVEAU] extraction .hds/.cbc → catalog
│   └── config.py                   # [REFACTORE] ModflowNwtConfig
├── modflow6/                       # idem
├── boussinesq/                     # idem
└── modflow_common/                 # [CONSERVE] helpers partagés NWT/MF6
```

### Une comparaison rapide avec l'existant

| Élément | État actuel | Cible | Statut |
|---------|-------------|-------|--------|
| Base ABC `Solver` | `solver/base/solver.py` (pre_processing/processing/post_processing) | Protocol `SolverRunner` avec 5 méthodes | `[REFACTORE]` |
| Contrat `SolverAdapter` | `simulation/adapters/base.py` | Absorbé dans `SolverRunner` (plus de double abstraction) | `[REFACTORE]` |
| Registre adapters | `simulation/adapters/registry.py` (dict statique) | `SolverRegistry` + entry-points + `register()` | `[REFACTORE]` |
| Registre compatibilité | `solver/compatibility.py` (dict parallèle) | Fusionné dans `SolverCapabilities.depends_on` | `[REFACTORE]` |
| Protocol extracteur | `simulation/results/extractors/base.py` (`OutputAdapter`) | `ResultExtractor` (même idée, signature figée) | `[RENOMME]` |
| `ProcessRun.process_type: str` | chaîne libre | `ProcessKind` enum | `[REFACTORE]` |
| Double registre (exec + extract) | dict 1 : `_ADAPTERS` (execution) ; dict 2 : `_ADAPTER_REGISTRY` (extract) | UN seul `SolverRegistry` → `plugin.runner()` et `plugin.extractor()` | `[REFACTORE]` |

---

## 2. Contrat n°1 — `SolverPlugin` (point d'entrée d'un solveur)

Le `SolverPlugin` est la **façade** que HydroModPy voit quand il charge un plugin. Il déclare l'identité, les capacités et les usines (factories) pour créer les objets `SolverRunner` et `ResultExtractor`.

### 2.1 Définition du Protocol

```python
# hydromodpy/solver/contracts/plugin.py           [NOUVEAU]
from __future__ import annotations
from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field
from pydantic import BaseModel

from hydromodpy.solver.contracts.process_kind import ProcessKind
from hydromodpy.solver.contracts.runner import SolverRunner, RunContext
from hydromodpy.solver.contracts.extractor import ResultExtractor


@dataclass(frozen=True)
class SolverCapabilities:
    """Capacités déclaratives d'un solveur. Interrogées par le planner.

    Tout est matérialisé comme frozen dataclass : inspectable, testable,
    sérialisable (écrit dans ``simulations.capabilities_json`` du catalog).
    """
    # Processus physiques supportés (au moins un).
    process_kinds: frozenset[ProcessKind]

    # Régimes temporels supportés.
    regimes: frozenset[str]              # {"steady", "transient"}

    # Types de mailles acceptés (HydroMesh UGRID topology type).
    mesh_types: frozenset[str]           # {"cartesian2d", "vertex2d", "layered3d"}

    # Dépendances capacitaires. Ex: transport requiert un flow.
    # Format : tuple[ProcessKind] qui doit être déjà planifié en amont.
    depends_on: tuple[ProcessKind, ...] = ()

    # Régimes hétérogènes. Pour matérialiser les limites connues du solveur.
    max_cells: int | None = None         # None = illimité
    max_heterogeneity: float | None = None  # contraste max en K (ex. 1e6)
    supports_dry_cells: bool = False
    supports_unconfined: bool = True
    supports_confined: bool = False

    # Backends binaires ou externes.
    requires_binary: bool = False
    binary_name: str | None = None       # ex. "mf6", "mfnwt", None pour pur Python
    binary_env_var: str | None = None    # ex. "HMP_MF6_BIN"


@runtime_checkable
class SolverPlugin(Protocol):
    """Façade d'un solveur. Un module déclare une classe avec cette forme."""

    # Identifiant unique dans le registre. Utilisé dans TOML : solver = "<name>".
    name: str

    # Version sémantique du plugin (pour trace dans DuckDB).
    version: str

    # Capacités publiées pour introspection par le planner.
    capabilities: SolverCapabilities

    # Modèle Pydantic de la config TOML [solver.<name>].
    # Le type exact est validé par le chargeur TOML.
    config_model: type[BaseModel]

    def runner(self, ctx: RunContext) -> SolverRunner:
        """Construit un SolverRunner pour UN run de simulation.

        Appelé UNE fois par ProcessRun par le SimulationRunner du cœur.
        Le runner est jetable : un run = un runner.
        """
        ...

    def extractor(self) -> ResultExtractor:
        """Retourne le ResultExtractor. Peut être un singleton stateless.

        Appelé après chaque solve réussi pour écrire les résultats
        dans le SimulationCatalog.
        """
        ...
```

### 2.2 Les méthodes optionnelles

Un plugin **peut** implémenter les méthodes suivantes. Le cœur les détecte par `hasattr()` et les utilise si présentes. Elles ne sont pas dans le Protocol pour garder l'interface minimale.

| Méthode | Signature | Utilité |
|---------|-----------|---------|
| `validate_environment()` | `() -> None` | Vérifier qu'un binaire externe existe, qu'une dépendance optionnelle est installée. Appelée au `register()`. Lève `SolverEnvironmentError` sinon. |
| `upgrade_config(old: dict, from_version: str) -> dict` | migration config | Permettre aux plugins de gérer leurs propres migrations de schéma TOML. |
| `describe_diagnostics(runner)` | `(SolverRunner) -> dict` | Retourner un dict de diagnostics lisibles (itérations Newton, conditionnement, etc.) — stocké dans `simulations.diagnostics_json`. |
| `benchmark_cases()` | `() -> list[Path]` | Déclarer une liste de cas de validation analytique embarqués dans le plugin. Utilisés par `hmp solver check`. |

### 2.3 Enregistrement — deux voies

**Voie A — entry-point (production)** :

```toml
# pyproject.toml du plugin tiers
[project.entry-points."hydromodpy.solver"]
feflow = "hydromodpy_feflow.plugin:FeflowPlugin"
```

Le cœur scanne `importlib.metadata.entry_points(group="hydromodpy.solver")` au premier accès au registre.

**Voie B — appel programmatique (dev/interne)** :

```python
# à l'import du module plugin
import hydromodpy as hmp

@hmp.solver.register
class FeflowPlugin:
    name = "feflow"
    ...
```

L'appel `hmp.solver.register` :
1. vérifie que la classe conforme au Protocol (`isinstance(instance, SolverPlugin)` grâce à `runtime_checkable`),
2. appelle `validate_environment()` si présent,
3. insère dans le registre,
4. retourne la classe inchangée (utilisable comme décorateur).

---

## 3. Contrat n°2 — `ProcessKind` (processus physiques supportés)

Finis les `str` libres pour `process_type`. Fini le mapping implicite `"flow"`/`"transport"`/`"particles"` éparpillé dans 4 registres.

```python
# hydromodpy/solver/contracts/process_kind.py    [NOUVEAU]
from enum import Enum

class ProcessKind(str, Enum):
    """Types de processus physiques orchestrables par le planner.

    L'énumération est héritière de ``str`` pour compatibilité TOML
    (une chaîne dans le config suffit : ``process_kind = "flow"``).
    """
    FLOW = "flow"                 # écoulement souterrain saturé
    VARIABLY_SATURATED = "variably_saturated"  # zone non-saturée (Richards, UZF)
    TRANSPORT = "transport"       # advection-dispersion solutés conservatifs
    REACTIVE_TRANSPORT = "reactive_transport"  # transport réactif (PHT3D, pflotran)
    PARTICLES = "particles"       # traçage particulaire (pathlines, endpoints)
    HEAT = "heat"                 # transfert thermique (SEAWAT, pflotran)
    DENSITY = "density"           # flux à densité variable (intrusion saline)
    SURFACE_WATER = "surface_water"  # ruissellement / routage
    RECHARGE = "recharge"         # modèle de recharge externe (PyHELP, etc.)
```

### 3.1 Contrat minimal par `ProcessKind`

Chaque `ProcessKind` définit **l'interface physique** que le solveur doit matérialiser — quels `inputs` il lit dans l'état partagé, quels `outputs` il écrit dans le Zarr / DuckDB, et les conditions limites / sources que le traducteur reçoit.

```python
# hydromodpy/solver/contracts/process_kind.py    [NOUVEAU] (suite)
from dataclasses import dataclass

@dataclass(frozen=True)
class ProcessContract:
    """Contrat d'I/O physique pour un ProcessKind.

    Lu par le ResultExtractor pour savoir quels champs écrire,
    lu par le SolverRunner pour savoir quels attributs de state lire.
    """
    kind: ProcessKind

    # Champs physiques obligatoires dans le Zarr layout.
    required_fields: frozenset[str]

    # Champs optionnels (dépendent du solveur).
    optional_fields: frozenset[str]

    # Timeseries obligatoires (stations).
    required_timeseries: frozenset[str]

    # Métriques acceptées pour ce processus.
    supported_metrics: frozenset[str]


# Registre des contrats (immuable).
PROCESS_CONTRACTS: dict[ProcessKind, ProcessContract] = {
    ProcessKind.FLOW: ProcessContract(
        kind=ProcessKind.FLOW,
        required_fields=frozenset({"head"}),
        optional_fields=frozenset({
            "budget/recharge", "budget/drain", "budget/well",
            "budget/chd", "budget/riv", "budget/ghb",
            "derived/watertable_elevation", "derived/watertable_depth",
            "derived/seepage_areas",
        }),
        required_timeseries=frozenset({"head"}),
        supported_metrics=frozenset({"nse", "kge", "rmse", "r2", "mae"}),
    ),
    ProcessKind.TRANSPORT: ProcessContract(
        kind=ProcessKind.TRANSPORT,
        required_fields=frozenset({"concentration"}),
        optional_fields=frozenset({"budget/ssm", "derived/mass_seepage"}),
        required_timeseries=frozenset({"concentration"}),
        supported_metrics=frozenset({"nse", "rmse", "r2"}),
    ),
    ProcessKind.PARTICLES: ProcessContract(
        kind=ProcessKind.PARTICLES,
        required_fields=frozenset(),  # pas de champ gridded
        optional_fields=frozenset({"pathlines", "endpoints"}),
        required_timeseries=frozenset(),
        supported_metrics=frozenset(),
    ),
    # ... (autres kinds)
}
```

### 3.2 Comment un solveur déclare quels processus il supporte

Un plugin publie `capabilities.process_kinds`. Le `SimulationPlanner` :

1. vérifie que chaque `ProcessRun` demandé dans le TOML correspond à un `ProcessKind` supporté par le solveur choisi,
2. vérifie que les dépendances capacitaires (`depends_on`) sont satisfaites par les runs antérieurs,
3. émet une `ConfigError` précoce en cas d'incompatibilité.

Le plugin peut supporter plusieurs processus (ex: MODFLOW 6 supporte `FLOW`, `TRANSPORT`, `HEAT`). Le runner reçoit dans `RunContext.process_kind` la valeur exacte demandée par le run courant.

---

## 4. Contrat n°3 — `SolverRunner` (cycle de vie d'une exécution)

Le `SolverRunner` est l'objet **jetable** qui porte une exécution numérique. C'est le remplacement du `Solver` ABC actuel et du `SolverAdapter` Protocol actuel — **fusionnés en une seule abstraction**.

### 4.1 Pourquoi fusionner `Solver` + `SolverAdapter`

L'architecture actuelle a deux couches :

- `Solver` (ABC) : `pre_processing / processing / post_processing` → pensé pour instanciation manuelle, signatures floues (`**kwargs`).
- `SolverAdapter` (Protocol) : `execute(RunContext)` → pensé pour orchestration, signature rigide.

Le `SolverAdapter` actuel ne fait qu'**adapter** le `Solver` au `RunContext`. C'est de l'indirection pure : chaque adapter est 60-150 lignes qui emballent `Solver.*` et collectent les paramètres dans `RunContext.state`.

**Cible** : UNE abstraction `SolverRunner` qui **est** le runner. Le cœur du solveur (code FloPy, PETSc, …) est une dépendance interne au plugin, pas un contrat séparé.

### 4.2 Définition du Protocol

```python
# hydromodpy/solver/contracts/runner.py           [NOUVEAU]
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from hydromodpy.solver.contracts.process_kind import ProcessKind


@dataclass(frozen=True)
class RunContext:
    """Contexte IMMUTABLE passé au runner au moment de sa construction.

    Remplace l'actuel ``simulation/planning/plan.RunContext`` avec une
    interface typée et une séparation claire entre état setup (immutable)
    et workspace de travail (scratch, mutable).
    """
    # Identité du run.
    sim_id: str                   # UUID de la simulation
    run_id: str                   # id unique du ProcessRun (ex: "flow_main")
    process_kind: ProcessKind
    solver_name: str

    # Domaine spatial et physique. Matérialisés par le cœur.
    mesh: "HydroMesh"             # depuis hydromodpy.spatial.mesh
    domain: "Domain"              # zones, boundaries sémantiques
    fields: "FieldParamCollection"  # K, Sy, Ss, porosité effective, etc.

    # Forçages et conditions initiales.
    forcings: "ForcingsBundle"    # recharge, ETP, pompages, stations météo
    initial_conditions: "InitialConditions"

    # Fenêtre temporelle.
    time_grid: "TimeGrid | None"   # None en régime permanent

    # Dépendances amont (ex: un flow solver pour un transport).
    upstream: "UpstreamResults"    # handles vers simulations.duckdb amont

    # Répertoire scratch où le solveur peut écrire ses fichiers.
    scratch_dir: Path

    # Config Pydantic spécifique au solveur (ex: FeflowConfig).
    config: Any                    # instance de plugin.config_model

    # Overrides issus de calibration / overrides runtime.
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SolveResult:
    """Résultat d'un solve. Transmis au ResultExtractor.

    Remplace ``RunExecutionResult``. Schéma minimal et typé.
    """
    # Répertoire contenant les fichiers produits par le solveur.
    output_dir: Path

    # Indicateurs de convergence (lus depuis solver diagnostics).
    converged: bool
    iterations: int | None
    wall_time_s: float

    # Diagnostics spécifiques au solveur (format libre, sérialisé en JSON).
    diagnostics: dict[str, Any] = field(default_factory=dict)

    # Résidu final. Plus petit = mieux. None si non applicable.
    residual: float | None = None


@runtime_checkable
class SolverRunner(Protocol):
    """Contrat du cycle de vie d'un solveur pour UN run.

    Le cycle de vie est strict : setup → build → solve → cleanup.
    Le runner est jetable : le cœur instancie un runner, appelle les cinq
    méthodes dans l'ordre, puis laisse le GC collecter.
    """

    ctx: RunContext

    def setup(self) -> None:
        """Prépare le répertoire scratch, valide les pré-conditions.

        Effets attendus :
        - ``ctx.scratch_dir`` existe et est vide,
        - les binaires externes sont accessibles (``shutil.which``),
        - les modèles amont (upstream) sont résolus en chemins absolus,
        - aucune écriture scientifique pour l'instant.

        Erreurs typées : ``SolverEnvironmentError``, ``SolverInputError``.
        """
        ...

    def build(self) -> None:
        """Traduit l'input physique (mesh, domain, fields, forcings) en
        payload solveur (packages FloPy, fichiers .nam, matrices PETSc, etc.).

        Effets attendus :
        - fichiers d'entrée du solveur écrits dans ``ctx.scratch_dir``,
        - aucune exécution numérique encore.

        Erreurs typées : ``SolverInputError`` si des conditions limites ou
        des forçages ne sont pas représentables par le solveur (ex: un
        solveur 2D reçoit un domaine 3D).
        """
        ...

    def solve(self) -> SolveResult:
        """Exécute le solveur numérique.

        Contrat :
        - retourne ``SolveResult`` avec ``converged=True/False``,
        - ne fait PAS d'extraction ni de post-traitement,
        - ne clean PAS les fichiers intermédiaires.

        Erreurs typées :
        - ``SolverDivergedError`` — Newton ou linéaire n'a pas convergé,
        - ``SolverTimeoutError`` — dépassement de ``config.timeout_s``,
        - ``SolverBinaryError`` — binaire externe exit code != 0,
        - ``SolverMassBalanceError`` — mass balance global > tolérance.

        En cas d'erreur, le runner DOIT laisser ``scratch_dir`` en l'état
        (pour diagnostic) ; le nettoyage est fait par ``cleanup()``.
        """
        ...

    def cleanup(self) -> None:
        """Libère les ressources non couvertes par le GC.

        Typiquement : fermer des handles de fichiers binaires, libérer
        PETSc, supprimer les fichiers temporaires si ``config.keep_files``
        est False.

        Appelée par le cœur dans un ``finally``, toujours, même en cas
        d'erreur. Ne doit jamais lever.
        """
        ...
```

### 4.3 Gestion d'erreurs — que retourner si divergence ?

**Jamais de `bool`**. Jamais de `None` silencieux. Quatre cas :

| Cas | Exception | Récupération |
|-----|-----------|--------------|
| Non-convergence Newton | `SolverDivergedError(iterations, final_residual)` | Calibration catche, marque l'itération en `failed`, continue. |
| Dépassement timeout | `SolverTimeoutError(wall_s, limit_s)` | Comme ci-dessus. |
| Binaire exit != 0 | `SolverBinaryError(returncode, stderr)` | Stocké tel quel dans `simulations.error_message`. |
| Mass balance > tolérance | `SolverMassBalanceError(percent_error, tolerance)` | Warning par défaut, error si `config.strict_mass_balance=True`. |
| Entrée physiquement infaisable | `SolverInputError(detail)` | Échec rapide avant solve — planner devrait avoir attrapé. |
| Environnement invalide | `SolverEnvironmentError(missing_binary)` | Levée à `setup()`, non-récupérable. |

Toutes héritent de `SolverError(HydroModPyError)`. Définies dans `hydromodpy/solver/contracts/errors.py` `[NOUVEAU]`.

```python
# hydromodpy/solver/contracts/errors.py            [NOUVEAU]
from hydromodpy.core.exceptions import HydroModPyError

class SolverError(HydroModPyError): ...
class SolverDivergedError(SolverError):
    def __init__(self, *, iterations: int, residual: float, detail: str = ""):
        self.iterations = iterations
        self.residual = residual
        super().__init__(
            f"Solver diverged after {iterations} iterations "
            f"(final residual = {residual:.3e}). {detail}"
        )
class SolverTimeoutError(SolverError):
    def __init__(self, *, wall_s: float, limit_s: float): ...
class SolverBinaryError(SolverError):
    def __init__(self, *, returncode: int, stderr: str): ...
class SolverMassBalanceError(SolverError):
    def __init__(self, *, percent_error: float, tolerance: float): ...
class SolverInputError(SolverError): ...
class SolverEnvironmentError(SolverError): ...
```

Le `SimulationRunner` du cœur capte ces erreurs typées et met à jour `simulations.status` ∈ {`completed`, `diverged`, `timeout`, `binary_error`, `input_error`, `environment_error`, `interrupted`}.

---

## 5. Contrat n°4 — `ResultExtractor` (écriture dans le catalog)

Le `ResultExtractor` transforme les fichiers bruts du solveur (`.hds`, `.cbc`, `.npz`, …) en enregistrements dans le `SimulationCatalog` (DuckDB + Zarr). C'est le **seul** point où le solveur connaît le schéma de sortie.

### 5.1 Le Protocol

```python
# hydromodpy/solver/contracts/extractor.py        [NOUVEAU]
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from hydromodpy.solver.contracts.process_kind import ProcessKind


@dataclass(frozen=True)
class ExtractContext:
    """Contexte d'extraction passé à chaque méthode.

    Tous les paramètres que ``OutputAdapter.extract`` recevait implicitement
    en ``**kwargs`` sont désormais nominaux et typés.
    """
    sim_id: str
    run_id: str
    process_kind: ProcessKind
    output_dir: Path              # == SolveResult.output_dir
    store: "SimulationCatalog"    # handle ouvert
    mesh: "HydroMesh"             # pour unifier les noms de face/node/layer
    time_grid: "TimeGrid | None"

    # Flags d'extraction (depuis TOML [extraction]).
    extract_budget_spatial: bool = False
    extract_pathlines: bool = False
    extract_timeseries: bool = True

    # Paramètres de déréférencement de sentinelles (en dernier recours).
    # Normalement vide — les extracteurs doivent masquer en amont.
    sentinels: dict[str, float] = None


@runtime_checkable
class ResultExtractor(Protocol):
    """Contrat d'extraction des résultats d'un solveur vers le catalog.

    Un extracteur est stateless et peut être un singleton du plugin.
    """

    # Les ProcessKinds qu'il sait extraire. Redondant avec SolverPlugin
    # pour autoriser un découplage (un extracteur commun pour plusieurs
    # solveurs MF6-like).
    supported: frozenset[ProcessKind]

    def extract(self, ctx: ExtractContext) -> None:
        """Lit les fichiers bruts, écrit dans ``ctx.store``.

        Champs obligatoires à écrire (selon ``ctx.process_kind``) :
        - FLOW : ``head`` (Zarr), ``timeseries[head]`` (DuckDB), mass balance.
        - TRANSPORT : ``concentration``, ``timeseries[concentration]``.
        - PARTICLES : ``pathlines`` ou ``endpoints`` (Zarr).

        Champs optionnels selon ``ctx.extract_budget_spatial`` etc.

        Masquage des sentinelles (dry cells, nodata) OBLIGATOIRE ici.
        ``derived.py`` du cœur ne doit PAS avoir à re-masquer.

        Erreur typée : ``ExtractionError`` si un fichier attendu manque.
        """
        ...

    def derive(self, ctx: ExtractContext, flags: "DerivedFlags") -> None:
        """Calcule les champs dérivés.

        Cette méthode est optionnelle. Si le plugin n'a rien de solveur-
        spécifique à faire (cas courant), il peut la laisser vide — le
        cœur fournit un ``DerivedComputerRegistry`` qui calcule
        watertable_depth, seepage_areas, outflow_drain, etc. à partir
        du head et du mesh, sans connaissance du solveur.

        Un plugin qui a des dérivés spécifiques (ex: Boussinesq expose
        une partition wet/dry explicite) peut surcharger ici.
        """
        ...
```

### 5.2 Schéma de sortie UNIFIÉ — tout solveur doit écrire ça

Le Zarr layout est fixé par `results/storage/spec.py` `[NOUVEAU]` (cf. `04_storage_ideal.md`). Indépendant du solveur.

```
simulations/<uuid>.zarr/
├── mesh/                       # UGRID 1.0 (cf. 03_data_contracts §3)
│   ├── face_coordinates
│   ├── face_node_connectivity
│   ├── z_interfaces
│   └── attrs : "Conventions"="UGRID-1.0", "topology"="vertex"
│
├── head/                       # (n_time, n_layer, n_face) float32
│   ├── attrs : "standard_name"="groundwater_head_above_reference_level",
│   │           "units"="m", "solver"="feflow", "solver_version"="9.5"
│   └── .zarray
│
├── concentration/              # (n_time, n_layer, n_face, n_species) float32
│                               # optionnel — ProcessKind.TRANSPORT
│
├── budget/
│   ├── recharge/               # (n_time, n_layer, n_face) float32
│   ├── drain/
│   ├── well/
│   ├── chd/
│   ├── riv/ghb/                # NEW — nommage BC physique
│   └── attrs : "units"="m3/s"
│
├── derived/                    # calculs dérivés par le cœur (core) OU le plugin
│   ├── watertable_elevation/   # (n_time, n_face) float32
│   ├── watertable_depth/
│   ├── seepage_areas/          # uint8 mask
│   └── attrs : "computed_by"="hydromodpy.core" ou "plugin.feflow"
│
├── pathlines/                  # structured dtype, variable length
└── endpoints/
```

### 5.3 Ce que le plugin doit écrire vs. ce que le cœur fournit

Règle : **le plugin écrit uniquement ce qui dépend du solveur** (head, budgets, concentrations). Les champs **dérivés universels** (watertable_depth, seepage_areas, outflow_drain) sont calculés par un registre central `DerivedComputerRegistry` du cœur.

```python
# hydromodpy/results/virtual_fields.py            [REFACTORE]
from typing import Callable

# Registre ouvert, dict[str, Callable].
_DERIVED_COMPUTERS: dict[str, Callable] = {}

def register_derived(name: str):
    def decorator(fn: Callable) -> Callable:
        _DERIVED_COMPUTERS[name] = fn
        return fn
    return decorator

@register_derived("watertable_depth")
def _watertable_depth(sim_id, store, mesh, head_array) -> None:
    top = mesh.top_elevation()  # (n_face,)
    wt = head_array.max(axis=1)  # sur les couches
    depth = np.maximum(top - wt, 0)
    store.write_field(sim_id, "derived/watertable_depth", depth)

# ... idem pour watertable_elevation, seepage_areas, outflow_drain, etc.
```

**Résultat** : un nouveau solveur n'a qu'à écrire `head` et `budget/*`. Toutes les figures (`watertable_map`, `seepage_plot`) et les exports fonctionnent automatiquement.

### 5.4 Champs obligatoires vs optionnels par `ProcessKind`

| ProcessKind | Obligatoire | Optionnel | Commentaire |
|-------------|-------------|-----------|-------------|
| FLOW | `head`, `timeseries[head]`, `mass_balance` | `budget/*`, `observation_points` | Head suffit pour toutes les figures via `derived/`. |
| VARIABLY_SATURATED | `head`, `saturation` | `moisture_content` | — |
| TRANSPORT | `concentration`, `timeseries[concentration]` | `budget/ssm`, `mass_balance_species` | — |
| REACTIVE_TRANSPORT | `concentration` + `species_mass` | `reaction_rates` | — |
| PARTICLES | au moins `endpoints` | `pathlines` | Pathlines coûteux — opt-in. |
| HEAT | `temperature` | `heat_flux` | — |
| DENSITY | `head_freshwater`, `density` | — | — |
| SURFACE_WATER | `discharge`, `water_depth` | — | — |
| RECHARGE | `timeseries[recharge]` | grilles mensuelles | Pas de solve, écrit directement. |

### 5.5 Comment gérer les différences entre solveurs

Exemple concret : MODFLOW écrit des flux de budget **face par face** (`CellBudgetFile`). Boussinesq n'a qu'une reconstruction cell-centered. Le cœur attend un champ `budget/drain` cell-centered.

**Convention** : `ResultExtractor.extract()` est responsable de la normalisation. Le MF6 extractor reconstitue un budget cell-centered à partir des flux par face (somme signée des flux sortants). Le Boussinesq extractor écrit directement. Le cœur ne sait pas d'où ça vient.

**Pour les capacités non disponibles** (ex: un solveur sans support de particles) : ne rien écrire. Le display détecte l'absence et émet un warning `"pathlines unavailable for solver=boussinesq"`. Pas d'erreur.

---

## 6. Contrat n°5 — `SolverConfig` (Pydantic model)

Chaque solveur publie son propre Pydantic `BaseModel` **indépendant** de la hiérarchie. La config TOML est sectionnelle.

### 6.1 Schéma TOML

```toml
# config.toml — section solveur est DYNAMIQUE (clé = nom du plugin)
[simulation]
name = "canut_run_01"
solver = "feflow"               # clé unique, vérifiée contre le registre

[simulation.process]
kind = "flow"                    # ProcessKind

[solver.feflow]                  # section dynamique correspondant au plugin
binary_path = "/opt/feflow/bin/feflow"
license_file = "/opt/feflow/license.dat"
max_iterations = 200
tolerance = 1e-6
parallel_nodes = 4

[solver.feflow.transient]
sub_stepping = "adaptive"
dt_max_days = 30.0
```

### 6.2 Agrégation dynamique dans `HydroModPyConfig`

La classe racine n'a plus de champ `feflow: FeflowConfig = Field(...)` **codé en dur**. À la place, un mécanisme dynamique :

```python
# hydromodpy/core/config/aggregate_config.py      [REFACTORE]
from __future__ import annotations
from pydantic import BaseModel, Field, model_validator
from typing import Any

from hydromodpy.solver.registry import SolverRegistry


class HydroModPyConfig(BaseModel):
    """Configuration racine. La section [solver.<name>] est validée dynamiquement."""
    model_config = {"extra": "allow"}  # pour accepter [solver.*] inconnus statiquement

    # ... autres champs (simulation, spatial, data, ...)
    solver: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_solver_section(self) -> "HydroModPyConfig":
        """Valide chaque sous-section [solver.<name>] contre le config_model
        du plugin correspondant.

        L'utilisateur peut laisser des sections [solver.feflow] même s'il
        choisit solver = "modflow6" — elles sont juste ignorées à l'exécution,
        mais toutes les sections présentes sont validées à parse-time.
        """
        registry = SolverRegistry.instance()
        for name, payload in self.solver.items():
            plugin = registry.get(name)  # KeyError si inconnu → ConfigError
            plugin.config_model.model_validate(payload)
        return self
```

### 6.3 Génération automatique de template par plugin

La commande `hmp config --solver feflow user.toml` introspecte `FeflowConfig`, respecte `ParamLevel`, et génère un template TOML complet. Aucun fichier de template manuscrit côté plugin.

---

## 7. Registre et découverte — entry-points + fallback

### 7.1 Le singleton `SolverRegistry`

```python
# hydromodpy/solver/registry/registry.py           [NOUVEAU]
from __future__ import annotations
from hydromodpy.solver.contracts.plugin import SolverPlugin


class SolverRegistry:
    """Registre unique des plugins solveurs. Singleton process-level.

    Remplace `simulation/adapters/registry.py::_ADAPTERS`.
    Remplace `solver/compatibility.py::PROCESS_SOLVER_REQUIREMENTS`.
    Remplace `results/post_run.py::_ADAPTER_REGISTRY`.

    TROIS registres fusionnés EN UN. Source unique de vérité.
    """
    _instance: "SolverRegistry | None" = None

    def __init__(self) -> None:
        self._plugins: dict[str, SolverPlugin] = {}
        self._discovered: bool = False

    @classmethod
    def instance(cls) -> "SolverRegistry":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._discover()
        return cls._instance

    def _discover(self) -> None:
        """Découverte automatique :
        1. solveurs embarqués (modflow_nwt, modflow6, boussinesq),
        2. entry-points setuptools ``hydromodpy.solver``.
        """
        from hydromodpy.solver.registry.builtin import register_builtin_plugins
        register_builtin_plugins(self)
        from hydromodpy.solver.registry.discovery import discover_entry_points
        discover_entry_points(self)
        self._discovered = True

    def register(self, plugin_cls: type) -> type:
        """Ajoute un plugin au registre.

        Utilisable comme décorateur ou par appel direct.
        """
        instance = plugin_cls()
        if not isinstance(instance, SolverPlugin):
            raise TypeError(
                f"{plugin_cls.__name__} does not conform to the SolverPlugin "
                f"Protocol. Missing attributes: "
                f"{_missing_attrs(instance, SolverPlugin)}"
            )
        if instance.name in self._plugins:
            raise ValueError(
                f"Solver '{instance.name}' already registered by "
                f"{type(self._plugins[instance.name]).__module__}."
            )
        # Validation d'environnement optionnelle.
        if hasattr(instance, "validate_environment"):
            instance.validate_environment()
        self._plugins[instance.name] = instance
        return plugin_cls

    def get(self, name: str) -> SolverPlugin:
        if name not in self._plugins:
            raise KeyError(
                f"Unknown solver '{name}'. Available: "
                f"{sorted(self._plugins)}. Did you forget to install a plugin?"
            )
        return self._plugins[name]

    def list_names(self) -> list[str]:
        return sorted(self._plugins)

    def find_supporting(self, kind: "ProcessKind") -> list[str]:
        """Retourne les plugins qui supportent ce ProcessKind."""
        return sorted(
            name for name, plugin in self._plugins.items()
            if kind in plugin.capabilities.process_kinds
        )
```

### 7.2 Découverte par entry-points

```python
# hydromodpy/solver/registry/discovery.py          [NOUVEAU]
from importlib.metadata import entry_points
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

ENTRY_POINT_GROUP = "hydromodpy.solver"


def discover_entry_points(registry: "SolverRegistry") -> None:
    """Charge tous les plugins déclarés comme entry-points."""
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            plugin_cls = ep.load()
        except Exception as exc:
            logger.warning(
                "Failed to load solver plugin %r from %s: %s",
                ep.name, ep.value, exc,
            )
            continue
        try:
            registry.register(plugin_cls)
        except Exception as exc:
            logger.warning(
                "Solver plugin %r refused registration: %s", ep.name, exc,
            )
```

### 7.3 Solveurs embarqués

```python
# hydromodpy/solver/registry/builtin.py            [NOUVEAU]
def register_builtin_plugins(registry: "SolverRegistry") -> None:
    """Enregistre les 3 solveurs embarqués.

    L'import est paresseux : FloPy et PETSc ne sont chargés qu'à
    l'instanciation du runner.
    """
    from hydromodpy.solver.modflow_nwt.plugin import ModflowNwtPlugin
    from hydromodpy.solver.modflow6.plugin import Modflow6Plugin
    from hydromodpy.solver.boussinesq.plugin import BoussinesqPlugin

    for plugin_cls in (ModflowNwtPlugin, Modflow6Plugin, BoussinesqPlugin):
        try:
            registry.register(plugin_cls)
        except Exception as exc:
            # En particulier SolverEnvironmentError si binaire manquant.
            logger.warning("Built-in %s unavailable: %s", plugin_cls.__name__, exc)
```

### 7.4 Fallback en cas d'indisponibilité

Un solveur embarqué dont `validate_environment()` échoue (binaire MF6 introuvable, PETSc non installé) **est absent du registre**. L'utilisateur voit à `hmp run`:

```
ConfigError: Unknown solver 'modflow6'. Available: ['boussinesq', 'modflownwt'].
Install the MODFLOW 6 binary (https://www.usgs.gov/software/modflow-6)
and set HMP_MF6_BIN, or choose another solver.
```

Pas de crash au parse TOML, pas de stacktrace effrayante, pas de `ImportError`.

### 7.5 CLI d'introspection

Le cœur expose :

```bash
hmp solver list              # liste les plugins installés + version + capabilities
hmp solver info feflow       # détail d'un plugin (capabilities, binary path, schema TOML)
hmp solver check feflow      # exécute la suite de tests de conformité (cf. §12)
```

---

## 8. Gestion d'erreurs et états terminaux

### 8.1 Mapping exception → `simulations.status`

| Exception levée par runner | `simulations.status` | `simulations.error_kind` | Recoverable ? |
|-----------|---------|-----------|--------------|
| (aucune) | `completed` | `null` | — |
| `SolverDivergedError` | `diverged` | `"non_convergence"` | oui (calibration skip) |
| `SolverTimeoutError` | `timeout` | `"timeout"` | oui |
| `SolverBinaryError` | `binary_error` | `"binary_exit"` | non |
| `SolverMassBalanceError` | `mass_balance_error` | `"mass_balance"` | configurable (strict/warn) |
| `SolverInputError` | `input_error` | `"invalid_input"` | non (bug dans la config) |
| `SolverEnvironmentError` | jamais atteinte (levée à `register`) | — | — |
| `KeyboardInterrupt` | `interrupted` | `"user_interrupt"` | — |
| autre `Exception` | `internal_error` | `type(e).__name__` | non |

### 8.2 Champ `error_message` et traçabilité

```sql
-- DuckDB schema additions [NOUVEAU]
ALTER TABLE simulations ADD COLUMN error_kind VARCHAR;
ALTER TABLE simulations ADD COLUMN error_message TEXT;
ALTER TABLE simulations ADD COLUMN diagnostics_json JSON;
ALTER TABLE simulations ADD COLUMN capabilities_json JSON;
ALTER TABLE simulations ADD COLUMN solver_version VARCHAR;
```

Le `ResultExtractor` (ou le cœur en cas d'échec avant extract) remplit ces champs.

### 8.3 Reproductibilité

Le plan (`SimulationPlan`) et les capabilities du plugin sont sérialisés en JSON et stockés dans la colonne `plan_json` / `capabilities_json` de `simulations`. Un `hmp inspect <sim_id>` peut lire un run d'il y a 6 mois, voir quel solveur, quelle version, quels paramètres.

---

## 9. Exemple complet — plugin `mysolver` en 100 lignes

Démonstration : un plugin fictif **MySolver**, un solveur Python pur qui résout une équation de diffusion 2D stationnaire avec différences finies. Montre tout : registre, config, runner, extracteur.

### 9.1 Arborescence

```
hydromodpy_mysolver/              # package distribué sur PyPI
├── pyproject.toml                # déclare l'entry-point
├── src/hydromodpy_mysolver/
│   ├── __init__.py               # vide
│   ├── plugin.py                 # SolverPlugin + SolverConfig
│   ├── runner.py                 # SolverRunner
│   └── extractor.py              # ResultExtractor
└── tests/
    └── test_conformance.py       # utilise hmp.solver.test_conformance()
```

### 9.2 `pyproject.toml`

```toml
[project]
name = "hydromodpy-mysolver"
version = "0.1.0"
dependencies = ["hydromodpy>=2.0", "numpy", "scipy"]

[project.entry-points."hydromodpy.solver"]
mysolver = "hydromodpy_mysolver.plugin:MySolverPlugin"
```

### 9.3 `plugin.py`

```python
# src/hydromodpy_mysolver/plugin.py
from __future__ import annotations
from pydantic import BaseModel, Field
import hydromodpy as hmp
from hydromodpy.solver import SolverCapabilities, ProcessKind

from .runner import MySolverRunner
from .extractor import MySolverExtractor


class MySolverConfig(BaseModel):
    """Config TOML [solver.mysolver]."""
    max_iterations: int = Field(default=500, ge=1, le=10_000)
    tolerance: float = Field(default=1e-6, gt=0)
    relaxation: float = Field(default=1.0, gt=0, le=2.0,
                               description="SOR relaxation factor")


class MySolverPlugin:
    """Plugin fictif — diffusion 2D stationnaire en Python pur."""
    name = "mysolver"
    version = "0.1.0"
    config_model = MySolverConfig
    capabilities = SolverCapabilities(
        process_kinds=frozenset({ProcessKind.FLOW}),
        regimes=frozenset({"steady"}),
        mesh_types=frozenset({"cartesian2d"}),
        max_cells=50_000,
        supports_dry_cells=False,
        supports_unconfined=True,
        requires_binary=False,
    )

    def runner(self, ctx):
        return MySolverRunner(ctx)

    def extractor(self):
        return MySolverExtractor()
```

### 9.4 `runner.py`

```python
# src/hydromodpy_mysolver/runner.py
from __future__ import annotations
import time
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve

from hydromodpy.solver import RunContext, SolveResult, SolverDivergedError


class MySolverRunner:
    """Solveur de Laplace avec conditions aux limites Dirichlet."""

    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self._matrix = None
        self._rhs = None
        self._head = None

    def setup(self) -> None:
        self.ctx.scratch_dir.mkdir(parents=True, exist_ok=True)

    def build(self) -> None:
        mesh = self.ctx.mesh
        n = mesh.n_faces
        # Assemblage TPFA : moyenne harmonique K aux faces, diagonale dominante.
        rows, cols, data = [], [], []
        rhs = np.zeros(n)
        K = self.ctx.fields["K"].values   # (n,) en m/s
        for edge in mesh.edges:
            i, j = edge.faces
            T = 2 * K[i] * K[j] / (K[i] + K[j]) * edge.length / edge.distance
            rows += [i, i, j, j]; cols += [i, j, j, i]; data += [T, -T, T, -T]
        # Conditions Dirichlet (head fixé, ex: ocean/stream).
        for fid, h_fixed in self.ctx.domain.dirichlet_faces():
            rows.append(fid); cols.append(fid); data.append(1e10)
            rhs[fid] += 1e10 * h_fixed
        # Recharge.
        rhs += self.ctx.forcings.recharge.steady_values() * mesh.face_areas
        self._matrix = csr_matrix((data, (rows, cols)), shape=(n, n))
        self._rhs = rhs

    def solve(self) -> SolveResult:
        t0 = time.perf_counter()
        try:
            head = spsolve(self._matrix, self._rhs)
        except Exception as exc:
            raise SolverDivergedError(iterations=0, residual=float("inf"),
                                       detail=str(exc)) from exc
        self._head = head
        np.save(self.ctx.scratch_dir / "head.npy", head)
        return SolveResult(
            output_dir=self.ctx.scratch_dir,
            converged=True,
            iterations=1,
            wall_time_s=time.perf_counter() - t0,
            diagnostics={"n_dof": len(head), "condition_estimate": None},
        )

    def cleanup(self) -> None:
        self._matrix = None
        self._rhs = None
```

### 9.5 `extractor.py`

```python
# src/hydromodpy_mysolver/extractor.py
from __future__ import annotations
import numpy as np
from hydromodpy.solver import ExtractContext, ProcessKind


class MySolverExtractor:
    supported = frozenset({ProcessKind.FLOW})

    def extract(self, ctx: ExtractContext) -> None:
        head = np.load(ctx.output_dir / "head.npy")
        # Régime stationnaire → un seul timestep.
        ctx.store.write_field(
            ctx.sim_id, "head", timestep=0,
            values=head.reshape(1, -1),      # (n_layer=1, n_face)
            n_timesteps=1,
        )
        # Mass balance global : ∫ recharge = ∫ Dirichlet flux (en steady).
        ctx.store.write_mass_balance(
            ctx.sim_id, timestep=0,
            total_in=0.0, total_out=0.0, percent_error=0.0,
        )

    def derive(self, ctx: ExtractContext, flags) -> None:
        # Rien de spécifique — le cœur calcule watertable_depth,
        # seepage_areas, etc. à partir du head écrit ci-dessus.
        pass
```

### 9.6 Utilisation

```toml
# config.toml utilisateur
[simulation]
name = "my_run"
solver = "mysolver"

[simulation.process]
kind = "flow"

[solver.mysolver]
tolerance = 1e-8
```

```bash
$ hmp run config.toml
[info] solver=mysolver v0.1.0 registered from entry-point
[info] plan: 1 run — flow_main::mysolver
[info] run flow_main::mysolver : setup → build → solve (0.12 s) → extract
[info] wrote sim_id=a3f2... (status=completed)

$ hmp display config.toml
[info] generating watertable_map… OK
[info] generating head_timeseries_outlet… OK
```

**Tout fonctionne** — figures, export NetCDF, agrégation catchment, comparaison multi-solveurs. Le plugin fait ~100 lignes de code scientifique. Le reste est fourni par le cœur.

---

## 10. Tableau comparatif des solveurs (actuels + extensions)

### 10.1 Capacités des solveurs embarqués (cible)

| Capacité | Boussinesq | MODFLOW-NWT | MODFLOW 6 |
|----------|:----------:|:-----------:|:---------:|
| `ProcessKind.FLOW` | ✅ | ✅ | ✅ |
| `ProcessKind.VARIABLY_SATURATED` | ⚠️ (MCP partiel) | ⚠️ (UPW dewatering) | ❌ (UZF non implémenté) |
| `ProcessKind.TRANSPORT` | ❌ | ✅ (via MT3DMS) | ✅ (via GWT) |
| `ProcessKind.REACTIVE_TRANSPORT` | ❌ | ❌ | ❌ |
| `ProcessKind.PARTICLES` | ❌ | ✅ (MODPATH 7 cible) | ✅ (MODPATH 7 cible) |
| `ProcessKind.HEAT` | ❌ | ❌ | ⚠️ (à ajouter via plugin) |
| `ProcessKind.DENSITY` | ❌ | ⚠️ (SEAWAT) | ❌ |
| Régime stationnaire | ✅ | ✅ | ✅ |
| Régime transient | ✅ | ✅ | ✅ |
| Mesh cartesian2d | ✅ | ✅ | ✅ |
| Mesh vertex2d (DISV) | ✅ | ❌ | ✅ |
| Mesh layered3d | ❌ (dépth-int.) | ✅ | ✅ |
| Max cellules (réaliste) | 50 k (Python) | 1 M | 10 M |
| Parallélisme MPI | ⚠️ (PETSc en COMM_SELF) | ❌ | ✅ (IMS + HYPRE) |
| Binaire externe requis | ❌ | ✅ (`mfnwt`) | ✅ (`mf6`) |
| Mass balance auto | ⚠️ (à ajouter) | ✅ (via LST) | ✅ (via LST) |

### 10.2 Ce que le nouveau design permet d'ajouter

Avec l'interface plugin, les extensions suivantes deviennent **uniformément intégrables** :

| Solveur candidat | Domaine | Effort intégration | Obstacles actuels levés |
|------------------|---------|--------------------|--------------------------|
| **FEFLOW** (DHI) | FEM 3D saturé + non-saturé + transport + heat | Moyen (binaire propriétaire + API Python IFM) | Plus besoin d'éditer `compatibility.py` ni `registry.py` |
| **ParFlow** | Parallèle 3D Richards | Moyen | Déclare `supports_unsaturated=True`, `requires_binary=True` |
| **HYDRUS 2D/3D** | FEM zone non-saturée | Moyen | Nouveau `ProcessKind.VARIABLY_SATURATED` exploitable |
| **SUTRA** (USGS) | Saturé/non-saturé, transport densité variable | Moyen | Nouveau `ProcessKind.DENSITY` |
| **PFLOTRAN** | Réactif multi-phase | Moyen | `REACTIVE_TRANSPORT` |
| **OpenFOAM (groundwaterFoam)** | CFD étendu à aquifères | Important | Architecture plugin flexible absorbe le coût |
| **GW3A** (solveur FEM léger) | FEM 2D/3D saturé | Faible | Exemple de §9 directement applicable |
| **MODFLOW-USG** | DISU non-structuré | Faible (branche de MF6) | `mesh_types={"unstructured"}` |
| **SHETRAN / MIKE SHE** | Intégré surface-subsurface | Important | `ProcessKind.SURFACE_WATER` + couplages |
| **GR4J / Sacramento** | Modèle conceptuel pluie-débit | Faible | `ProcessKind.RECHARGE` — déjà présent comme stub |

### 10.3 Matrice fournisseur / cœur par solveur

Pour chaque solveur, qui écrit quoi :

| Élément | Plugin fournit | Cœur fournit |
|---------|:--------------:|:------------:|
| Config Pydantic (solveur-spécifique) | ✅ | — |
| Runner (setup/build/solve/cleanup) | ✅ | — |
| Extractor (champs bruts vers Zarr) | ✅ | — |
| Derived (watertable_depth, etc.) | optionnel | ✅ (par défaut) |
| Schéma DuckDB | — | ✅ |
| Layout Zarr | — | ✅ |
| Figures (watertable_map, timeseries) | — | ✅ |
| Exports (NetCDF, CSV, VTU, GeoTIFF) | — | ✅ |
| Agrégation catchment | — | ✅ |
| Calibration | — | ✅ (lit head, appelle runner en boucle) |
| Comparaison multi-solveurs | — | ✅ (compare sim_ids au même projet) |

---

## 11. Migration — mapping ancien → cible

### 11.1 Table des fichiers

| Actuel | Cible | Statut | Action |
|--------|-------|--------|--------|
| `hydromodpy/solver/base/solver.py` (ABC) | `hydromodpy/solver/contracts/runner.py` | `[REFACTORE]` | Convertir ABC en Protocol, splitter `processing()` en `setup/build/solve/cleanup`. |
| `hydromodpy/solver/base/solver_config.py` | `hydromodpy/solver/contracts/config.py` | `[RENOMME]` | Rester Pydantic, suppression de `solver_engine` enum (→ `name: str` libre). |
| `hydromodpy/solver/base/solver_engine.py` (enum) | — | `[SUPPRIME]` | Enum hard-codé remplacé par registre dynamique. |
| `hydromodpy/solver/compatibility.py` | `hydromodpy/solver/contracts/process_kind.py` + `capabilities.depends_on` | `[REFACTORE]` | Fusionné dans `SolverCapabilities`. |
| `hydromodpy/solver/contracts.py` (re-export 16 l) | `hydromodpy/solver/contracts/__init__.py` | `[REFACTORE]` | Devient un vrai package avec vrais Protocols. |
| `hydromodpy/simulation/adapters/base.py` (`SolverAdapter`) | fusionné dans `SolverRunner` | `[SUPPRIME]` | Double abstraction éliminée. |
| `hydromodpy/simulation/adapters/registry.py` | `hydromodpy/solver/registry/registry.py` | `[DEPLACE+REFACTORE]` | Seul registre, unifié avec compatibilité. |
| `hydromodpy/simulation/adapters/flow/*` | `hydromodpy/solver/<name>/runner.py` | `[DEPLACE]` | Chaque adapter devient le runner du plugin. |
| `hydromodpy/simulation/results/extractors/base.py` (`OutputAdapter`) | `hydromodpy/solver/contracts/extractor.py` (`ResultExtractor`) | `[RENOMME]` | Même contrat, signature typée. |
| `hydromodpy/simulation/results/extractors/modflow6.py` | `hydromodpy/solver/modflow6/extractor.py` | `[DEPLACE]` | Co-localisé avec le plugin. |
| `hydromodpy/simulation/results/extractors/modflownwt.py` | `hydromodpy/solver/modflow_nwt/extractor.py` | `[DEPLACE]` | idem. |
| `hydromodpy/simulation/results/extractors/derived.py` (581 l) | `hydromodpy/results/virtual_fields.py` (registre extensible) | `[REFACTORE]` | Registre `@register_derived`, sentinelles retirées. |
| `hydromodpy/simulation/results/post_run.py::_ADAPTER_REGISTRY` | `SolverRegistry.get(name).extractor()` | `[SUPPRIME]` | Double registre mort. |
| `hydromodpy/simulation/adapters/display/stub.py` | supprimer | `[SUPPRIME]` | Dead code. |
| `hydromodpy/simulation/adapters/postprocess/stub.py` | supprimer | `[SUPPRIME]` | Dead code. |
| `hydromodpy/process/contracts.py` (29 l) | `hydromodpy/physics/base/` (cf. doc 01) | `[REFACTORE]` | Vrais Protocols physiques. |

### 11.2 Table des classes

| Classe actuelle | Classe cible | Fichier cible | Statut |
|-----------------|--------------|---------------|--------|
| `Solver` (ABC) | `SolverRunner` (Protocol) | `contracts/runner.py` | `[REFACTORE]` |
| `SolverConfig` | `SolverConfig` (base Pydantic facultative) | `contracts/config.py` | `[CONSERVE]` |
| `SolverEngine` (enum) | `ProcessKind` (enum, sémantique différente) | `contracts/process_kind.py` | `[REFACTORE]` |
| `SolverAdapter` (Protocol) | absorbé dans `SolverRunner` | — | `[SUPPRIME]` |
| `RunContext` (dataclass) | `RunContext` (dataclass, typée) | `contracts/runner.py` | `[REFACTORE]` |
| `RunExecutionResult` | `SolveResult` | `contracts/runner.py` | `[RENOMME]` |
| `OutputAdapter` (Protocol) | `ResultExtractor` (Protocol) | `contracts/extractor.py` | `[RENOMME]` |
| `Modflow6` (ABC subclass) | `Modflow6Plugin` + `Modflow6Runner` | `solver/modflow6/plugin.py,runner.py` | `[REFACTORE]` |
| `Modflow` (NWT) | `ModflowNwtPlugin` + `ModflowNwtRunner` | `solver/modflow_nwt/plugin.py,runner.py` | `[REFACTORE]` |
| `Boussinesq` | `BoussinesqPlugin` + `BoussinesqRunner` | `solver/boussinesq/plugin.py,runner.py` | `[REFACTORE]` |
| `Modflow6FlowAdapter` | `Modflow6Runner` (fusionné) | `solver/modflow6/runner.py` | `[SUPPRIME]` |
| `ModflowNwtFlowAdapter` | `ModflowNwtRunner` (fusionné) | `solver/modflow_nwt/runner.py` | `[SUPPRIME]` |
| `BoussinesqFlowAdapter` | `BoussinesqRunner` (fusionné) | `solver/boussinesq/runner.py` | `[SUPPRIME]` |

### 11.3 Changements d'API publique

```python
# Avant (actuel)
from hydromodpy.simulation.adapters.registry import register_adapter, get_solver_adapter
from hydromodpy.solver.compatibility import register_process_solver
from hydromodpy.solver.base import Solver

# Après (cible)
import hydromodpy as hmp
hmp.solver.register(MyPlugin)          # unique voie programmatique
plugin = hmp.solver.get("modflow6")    # unique voie de lookup
hmp.solver.list_names()
hmp.solver.find_supporting(hmp.solver.ProcessKind.FLOW)
```

---

## 12. Tests de conformité d'un plugin

Le cœur fournit une **suite de tests paramétrée** que tout plugin peut exécuter :

```python
# hydromodpy/solver/testing.py                   [NOUVEAU]
from typing import Callable
import pytest

def solver_conformance_suite(plugin_name: str) -> Callable:
    """Retourne un test paramétré conforme pytest.

    Usage dans un plugin :
        # tests/test_conformance.py
        from hydromodpy.solver.testing import solver_conformance_suite
        test_mysolver_conformance = solver_conformance_suite("mysolver")
    """
    def _test(tmp_path):
        plugin = _get_registered(plugin_name)
        # 1. Protocol conformance
        _assert_protocol(plugin, SolverPlugin)
        # 2. Capabilities cohérentes
        assert plugin.capabilities.process_kinds  # non vide
        # 3. Config model Pydantic valide
        assert issubclass(plugin.config_model, BaseModel)
        # 4. Analytical benchmark (steady Laplace 1D)
        _run_laplace_1d(plugin, tmp_path)
        # 5. Schema output compliant (head écrit, dtypes, shapes)
        _assert_zarr_layout(tmp_path, ProcessKind.FLOW)
        # 6. Erreurs typées (input invalide → SolverInputError)
        _assert_error_types(plugin, tmp_path)
        # 7. Cleanup idempotent
        runner = plugin.runner(_fake_ctx(tmp_path))
        runner.setup(); runner.cleanup(); runner.cleanup()  # pas d'erreur
    return _test
```

Le développeur de plugin exécute `pytest tests/test_conformance.py` avant release. Le cœur garantit ainsi la compatibilité descendante.

### 12.1 La CLI `hmp solver check`

```bash
hmp solver check mysolver
[1/7] Protocol conformance              ✓
[2/7] Capabilities published             ✓
[3/7] Pydantic config model              ✓
[4/7] Analytical benchmark (Laplace 1D)  ✓ (rel. L2 err = 4.2e-4)
[5/7] Zarr schema compliance             ✓ (head written, shape=(1,1,100))
[6/7] Typed errors on invalid input      ✓
[7/7] Idempotent cleanup                 ✓

mysolver v0.1.0 — CONFORMANT
```

Seuil de benchmark (err < 1e-3) et liste des champs obligatoires lus depuis `PROCESS_CONTRACTS` du §3.1.

---

## 13. Récapitulatif — les décisions clés

1. **Un Protocol, pas un ABC** : structural typing, découplage maximal.
2. **Fusion `Solver` + `SolverAdapter` en `SolverRunner`** : une seule abstraction, cycle de vie `setup/build/solve/cleanup` explicite.
3. **Registre unique** : `SolverRegistry` remplace les trois registres parallèles (`adapters/registry`, `compatibility`, `post_run._ADAPTER_REGISTRY`).
4. **Entry-points setuptools** : extensibilité standard Python, zéro monkey-patching, zéro édition des fichiers cœur.
5. **Capacités déclaratives** : le planner interroge `SolverCapabilities` avant exécution. Incompatibilités détectées au plan, pas au run.
6. **Erreurs typées** : hiérarchie `SolverError` → `SolverDivergedError`, `SolverTimeoutError`, `SolverBinaryError`, … mapping vers `simulations.status` en DuckDB.
7. **ProcessKind enum + ProcessContract** : remplace les chaînes libres `"flow"`/`"transport"` par une énumération typée avec contrats I/O associés.
8. **Schéma de sortie unifié (Zarr + DuckDB)** : le plugin n'écrit que ce qui dépend du solveur ; les champs dérivés (watertable_depth, seepage) sont calculés par un registre `DerivedComputerRegistry` central.
9. **CLI de conformité** : `hmp solver check <name>` valide un plugin contre le contrat. Garantit la compatibilité descendante.
10. **Ajout d'un nouveau solveur = un package PyPI indépendant** de ~100-1000 lignes qui déclare cinq contrats. Aucune modification du cœur.

---

## 14. Impact — chiffres

| Métrique | Actuel | Cible | Variation |
|----------|-------:|------:|----------:|
| Abstractions solveur (Solver + SolverAdapter + OutputAdapter) | 3 | 2 (Runner + Extractor) | **-33 %** |
| Registres parallèles | 3 | 1 | **-66 %** |
| Lignes `simulation/adapters/*` | ~960 | ~0 (tout déplacé dans `solver/<name>/`) | **-100 %** |
| Lignes `solver/compatibility.py` | 101 | fusionné dans `SolverCapabilities` | **-100 %** |
| Lignes `solver/base/` (ABC + config + enum) | ~140 | ~60 (Protocol + config) | **-57 %** |
| Lignes pour ajouter un nouveau solveur | ~400-600 (config + adapter + extractor + compatibility + registry) | ~100-200 (plugin + runner + extractor) | **-60 %** |
| Fichiers du cœur à éditer pour ajouter un solveur | 7 | 0 (entry-point) | **-100 %** |
| Erreurs typées de solveur | 0 (booléen `success`) | 6 exceptions nommées | **+∞** |
| Tests de conformité standardisés | 0 | 7 checks CLI | **+∞** |

---

## 15. Conclusion

Le design actuel superpose **trois niveaux d'abstraction** (`Solver` ABC, `SolverAdapter` Protocol, `OutputAdapter` Protocol), **trois registres non synchronisés** (adapters, compatibility, extractors), et **un enum hard-codé** (`SolverEngine`). Ajouter un solveur demande d'éditer 7 fichiers du cœur et de re-comprendre trois cycles de vie différents.

Le design cible consolide tout en **cinq contrats simples** (`SolverPlugin`, `SolverRunner`, `ResultExtractor`, `SolverConfig`, `ProcessKind`), **un seul registre** avec découverte par entry-points, et un **cycle de vie explicite** `setup → build → solve → cleanup`.

Le résultat : un plugin tiers FEFLOW, ParFlow, HYDRUS ou MySolver se distribue comme un package PyPI indépendant, s'installe par `pip install`, et s'intègre automatiquement à tout le pipeline HydroModPy (config, figures, exports, calibration, comparaison).

**Architecture terminée.**
