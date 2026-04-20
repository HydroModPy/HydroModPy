# Architecture cible — Calibration, sensibilité et inversion dans HydroModPy

**Document** : `architecture_cible/07_calibration.md`
**Date** : 2026-04-18
**Auteur** : Architecte calibration hydrogéologique (références : PEST / PEST++ IES / PESTPP-OPT, OSTRICH, pyEMU, Optuna, CMA-ES / pycma, SciPy, DREAM / emcee / PyMC, SALib, Nevergrad, MLflow Tracking, Ax / BoTorch).
**Portée** : conception **complète** du sous-système de calibration, d'analyse de sensibilité et d'inversion dans HydroModPy. Couvre l'intégration avec le catalog DuckDB/Zarr et le pipeline d'exécution (doc 06).
**Statut** : design de référence. **Pas un patch incrémental** de l'existant (10 058 lignes dans `analysis/calibration/` dont `engine/session.py` 3 409 lignes → à refactorer intégralement).
**Sources** :
- audits `audit_code/05_process_solver.md`, `audit_code/06_simulation_engine.md`
- architectures cibles `01_structure_packages.md`, `04_storage_ideal.md`, `05_solver_contracts.md`, `06_pipeline_execution.md`
- code existant : `hydromodpy/analysis/calibration/{core,engine,analysis,cases,devkit}`

> **Légende des tags**
> `[NOUVEAU]` n'existe pas · `[RENOMME]` existe sous un autre nom · `[REFACTORE]` existe mais doit changer · `[CONSERVE]` existe et reste tel quel · `[SUPPRIME]` dead code à retirer.

---

## Table des matières

0. [Principes directeurs](#0-principes-directeurs)
1. [Vue d'ensemble — trois responsabilités, trois contrats](#1-vue-densemble--trois-responsabilités-trois-contrats)
2. [Arborescence cible du package `analysis/calibration/`](#2-arborescence-cible)
3. [Contrat n°1 — `Objective` (fonction coût)](#3-contrat-n1--objective)
4. [Contrat n°2 — `Optimizer` (ask / tell)](#4-contrat-n2--optimizer-ask--tell)
5. [Contrat n°3 — `Evaluator` (simulation = appel coûteux)](#5-contrat-n3--evaluator)
6. [Le `CalibrationEngine` — orchestration](#6-le-calibrationengine--orchestration)
7. [Déclaration des paramètres calibrables](#7-déclaration-des-paramètres-calibrables)
8. [Métriques et objectifs multi-sites / multi-objectifs](#8-métriques-et-objectifs)
9. [Schéma DuckDB étendu pour la calibration](#9-schéma-duckdb-étendu)
10. [Sensibilité — SALib et lien avec la calibration](#10-sensibilité--salib)
11. [Warm start, cache, reprise, parallélisation](#11-warm-start-cache-reprise-parallélisation)
12. [Interface utilisateur — TOML, CLI, API Python](#12-interface-utilisateur)
13. [Diagramme de séquence d'une calibration complète](#13-diagramme-de-séquence)
14. [Comparaison aux projets de référence](#14-comparaison-aux-projets-de-référence)
15. [Tableau de migration actuel → cible](#15-tableau-de-migration-actuel--cible)
16. [Tests de conformité](#16-tests-de-conformité)

---

## 0. Principes directeurs

| # | Principe | Conséquence pratique |
|---|----------|----------------------|
| 1 | **Trois responsabilités découplées** | `Objective` (quoi), `Optimizer` (comment), `Evaluator` (mesurer). Chacun est un `Protocol` de ≤ 4 méthodes. Les trois se composent par injection de dépendance, jamais par héritage. |
| 2 | **Ask / tell** | Tout optimiseur expose `ask() -> list[params]` et `tell(results: list[EvaluationResult])`. Pattern homogène pour scipy, optuna, pycma, PEST, CMA-ES custom, DREAM, Nevergrad, grid, random, Sobol. |
| 3 | **Une simulation = un sim_id = un UUID** | Chaque évaluation est *une vraie simulation HydroModPy* écrite dans le catalog via le pipeline standard (cf. doc 06). Pas de "simulateur léger" parallèle. On hérite ainsi de toute la traçabilité. |
| 4 | **Cache content-addressable par `params_hash`** | Deux évaluations avec les **mêmes paramètres résolus** (après transform) ⇒ même `sim_id` retourné depuis le catalog. Gain massif en warm-start et reprise. |
| 5 | **Itérations écrites au fil de l'eau** | `calibration_iterations` est peuplé *par chaque `tell`*, pas en bulk post-calibration. Une interruption laisse un état cohérent ; on reprend à la volée. |
| 6 | **Paramètres = contrat Pydantic, pas strings** | Les bornes, le log-transform, le prior se déclarent via annotations sur les champs existants (`core/config/`). Pas de parser ad-hoc. Le TOML `[calibration.parameters]` déclare seulement **quoi** calibrer, pas les bornes. |
| 7 | **Multi-objectif natif** | `Objective` peut être scalaire ou vectoriel ; `Optimizer` publie `accepts_multi_objective: bool`. Pareto front quand l'optimiseur le supporte (NSGA-III, MOEA/D), pondération sinon. |
| 8 | **Sensibilité = premier citoyen** | Un `SensitivityAnalyzer` partage le contrat `Evaluator` et écrit ses résultats dans les mêmes tables DuckDB (`sensitivity_sessions`, `sensitivity_indices`). Pas de tooling séparé. |
| 9 | **Parallélisme par `concurrent.futures`** | Un `BatchEvaluator` distribue les évaluations sur `ProcessPoolExecutor` (local) ou `dask.distributed.Client` (cluster). L'`Optimizer` reste synchrone côté API, asynchrone en interne. |
| 10 | **Analyse post-hoc via DataFrame** | `session.to_dataframe()` retourne `n_iter × (params + metrics + meta)`. Entraîner un modèle ML dessus, faire un pair-plot, un parallel-coordinates plot = 3 lignes de pandas/seaborn. |
| 11 | **Pas de tools graphiques dans le noyau** | Toutes les visualisations (convergence, dotty, parallel-coords) sont dans `display/calibration/`, jamais dans l'engine. Le noyau produit des tables ; le display produit des figures. |
| 12 | **Reproductibilité** | Seed propagé via `CalibrationConfig.seed: int`. `session_id = UUIDv4`, `params_hash = SHA-256(canonical_json)`, `run_id = sim_id`. Deux runs même config + même seed ⇒ mêmes `params_hash`. |

### 0.1 Ce qui change par rapport à l'existant

| Défaut actuel | Fix proposé | Section |
|---|---|---|
| `engine/session.py` 3 409 lignes, mélange workspace, propriété, évaluation, réécriture TOML | Éclaté en 6 fichiers ≤ 350 l. chacun | §2 |
| Deux `engine` (`core/engine.py` + `engine/launcher.py`) | Un seul `CalibrationEngine` dans `calibration/engine.py` | §6 |
| Optimiseurs hardcodés dans `core/methods/*.py` | Registry `Optimizer` + plugins entry-points | §4 |
| Pas d'itération persistée pendant le run | Ecriture DuckDB à chaque `tell` | §5, §9 |
| Pas de cache `params_hash` ⇒ même param = nouvelle simu | `SimulationCache` content-addressable | §11 |
| Pas de parallélisme | `BatchEvaluator` + `ProcessPoolExecutor` | §11.3 |
| Calibration bypass du pipeline standard (cf. audit 06 §7.3) | Chaque eval = `Pipeline.run()` complet écrit dans le catalog | §5 |
| Pas d'interface `optuna` / `pycma` native | Adapters `OptunaAdapter`, `PycmaAdapter`, `ScipyAdapter`, `PESTAdapter` | §4.3 |
| Pas de SALib | `SensitivityAnalyzer` (Sobol, Morris, FAST) | §10 |
| `calibration_iterations.parameters JSON` peu requêtable | Table normalisée `calibration_iterations_params` (longue) + vue dé-normalisée | §9 |

---

## 1. Vue d'ensemble — trois responsabilités, trois contrats

```
┌────────────────────────────────────────────────────────────────────────┐
│                      CalibrationEngine (orchestrateur)                 │
│                                                                        │
│   CalibrationConfig  ──►   session_id = uuid4()                        │
│                            open DuckDB, INSERT calibration_sessions    │
│                                                                        │
│   ┌──────────────┐    ask    ┌─────────────────┐    evaluate            │
│   │              │ ────────► │                 │ ───────────────►      │
│   │  Optimizer   │           │    Evaluator    │                       │
│   │  (Contrat 2) │ ◄──────── │    (Contrat 3)  │ ◄───────────────      │
│   │              │   tell    │                 │   EvaluationResult    │
│   └──────────────┘           └─────────────────┘                       │
│          ▲                            │                                │
│          │ knows                      │ uses                           │
│          │                            ▼                                │
│          │                   ┌─────────────────┐                       │
│          │                   │    Objective    │                       │
│          └───── objective ──►│   (Contrat 1)   │                       │
│                              └─────────────────┘                       │
│                                                                        │
│   persist each tell → calibration_iterations                           │
│   persist best      → calibration_sessions.best_sim_id                 │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

- **`Objective`** = *quoi optimiser*. Reçoit `(observed, simulated, sim_metadata) → objective_value` (scalaire ou vecteur).
- **`Optimizer`** = *comment échantillonner l'espace des paramètres*. Expose `ask/tell/best/converged`.
- **`Evaluator`** = *comment évaluer un point*. Encapsule **une simulation HydroModPy complète** (pipeline doc 06), lit les résultats du catalog, applique l'`Objective`, écrit l'itération.

Les trois sont des `Protocol`s de ≤ 4 méthodes. Aucun héritage.

---

## 2. Arborescence cible

```
hydromodpy/analysis/calibration/                          [REFACTORE majeur]
│
├── __init__.py                   [REFACTORE]   Exports publics : CalibrationEngine, Objective, Optimizer, calibrate()
│
├── engine.py                     [NOUVEAU]     CalibrationEngine (~300 l.) — remplace engine/launcher.py + engine/session.py
├── config.py                     [NOUVEAU]     CalibrationConfig Pydantic (~200 l.) — remplace core/engine_config.py
│
├── contracts/                    [NOUVEAU]     Contrats Protocol
│   ├── __init__.py
│   ├── objective.py              Protocol Objective + MultiObjective
│   ├── optimizer.py              Protocol Optimizer (ask/tell)
│   ├── evaluator.py              Protocol Evaluator
│   └── trial.py                  ParamSuggestion, EvaluationResult, Trial (frozen dataclasses)
│
├── parameters/                   [REFACTORE]  (remplace core/parameters.py + core/methods_config.py/parameterization)
│   ├── __init__.py
│   ├── space.py                  ParameterSpace, CalibParameter (prior, transform, bounds)
│   ├── transform.py              Transform Protocol + identity/log/logit/boxcox
│   ├── distribution.py           Prior Protocol + Uniform/LogUniform/Normal/Beta
│   └── mapping.py                Mapping paramètre continu ↔ propriété physique (zone, couche)
│
├── objectives/                   [REFACTORE]  (remplace core/objective_function.py + composite_objective.py)
│   ├── __init__.py
│   ├── metrics.py                NSE, KGE, RMSE, MAE, NSE_log, PBIAS, R²
│   ├── scalar.py                 ScalarObjective (une métrique × une station)
│   ├── composite.py              CompositeObjective (somme pondérée multi-sites)
│   ├── multi.py                  MultiObjective (vecteur, pour Pareto)
│   └── transforms.py             Transformations pré-métrique (log, sqrt, inverse, boxcox) [RENOMME depuis core/objective_transformations.py]
│
├── optimizers/                   [REFACTORE]  (remplace core/methods/)
│   ├── __init__.py               Registre + découverte entry-points
│   ├── base.py                   AskTellOptimizer (base commune pour écrire un optimiseur)
│   ├── registry.py               _OPTIMIZERS dict + register_optimizer decorator
│   │
│   ├── builtin/                  Optimiseurs embarqués
│   │   ├── grid.py               Grid search (déterministe)
│   │   ├── lhs.py                Latin hypercube sampling [NOUVEAU]
│   │   ├── sobol.py              Sobol sequence sampling [NOUVEAU]
│   │   ├── random.py             Random search
│   │   └── nelder_mead.py        Simplex local
│   │
│   └── adapters/                 Adaptateurs vers bibliothèques externes
│       ├── scipy_adapter.py      scipy.optimize.differential_evolution, minimize
│       ├── pycma_adapter.py      CMA-ES via pycma
│       ├── optuna_adapter.py     TPE, NSGA-II, Bayesian via optuna
│       ├── emcee_adapter.py      MCMC DREAM-like via emcee
│       ├── pymc_adapter.py       Full Bayesian via PyMC (optional dep)
│       ├── nevergrad_adapter.py  CMA, DE, BO via nevergrad
│       └── pestpp_adapter.py     PESTPP-IES via pyemu [NOUVEAU]
│
├── evaluator.py                  [NOUVEAU]    SimulationEvaluator (default) : 1 ask → 1 pipeline.run → 1 sim_id → 1 metric
├── batch.py                      [NOUVEAU]    BatchEvaluator : fan-out parallel via ProcessPoolExecutor / dask
├── cache.py                      [NOUVEAU]    SimulationCache content-addressable (sha256 sur params canoniques)
│
├── persistence.py                [NOUVEAU]    CalibrationPersistence (écritures DuckDB : session, iterations, metrics)
├── dataframe.py                  [NOUVEAU]    Export DataFrame pour ML / pandas / sklearn
│
├── sensitivity/                  [NOUVEAU]    Intégration SALib
│   ├── __init__.py
│   ├── analyzer.py               SensitivityAnalyzer (façade commune)
│   ├── sobol.py                  Sobol (variance-based)
│   ├── morris.py                 Morris screening (elementary effects)
│   ├── fast.py                   FAST (Fourier Amplitude Sensitivity Test)
│   └── persistence.py            Écritures DuckDB : sensitivity_sessions, sensitivity_indices
│
├── convergence.py                [NOUVEAU]    Critères d'arrêt (StallCriterion, ToleranceCriterion, TimeBudget)
│
├── cli.py                        [NOUVEAU]    hmp calibrate (thin shell, ~60 l.)
│
└── tests/                        → migré sous tests/unit/calibration/ et tests/regression/calibration/
                                  Les cases groundwater_1d / recession_brutsaert / reservoir deviennent
                                  tests/validation/calibration/<case>/
```

Contraintes :
- aucun fichier > 400 lignes (sauf `engine.py` qui peut aller à 400).
- tous les imports internes vont de la droite vers la gauche du schéma (`engine.py` dépend de `contracts/`, `contracts/` ne dépend de rien).
- `analysis/calibration/` n'importe aucun autre package `analysis/*`. Dépend uniquement de `core/`, `results/`, `simulation/` (pipeline).

---

## 3. Contrat n°1 — `Objective`

### 3.1 Protocol

```python
# hydromodpy/analysis/calibration/contracts/objective.py                  [NOUVEAU]

from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
import numpy as np


@dataclass(frozen=True, slots=True)
class ObservationSet:
    """Observations indexées par station. Typiquement chargées depuis le catalog."""
    stations: tuple[str, ...]
    times: np.ndarray                   # shape (n_t,), datetime64[ns]
    values: dict[str, np.ndarray]       # station_id -> shape (n_t,)
    variable: str                       # e.g. "head", "discharge", "concentration"
    weights: dict[str, np.ndarray] | None = None  # optional per-station weights


@dataclass(frozen=True, slots=True)
class SimulationOutput:
    """Sortie extraite d'UN sim_id du catalog, déjà alignée sur les observations."""
    sim_id: str
    stations: tuple[str, ...]
    times: np.ndarray
    values: dict[str, np.ndarray]
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class ObjectiveValue:
    """Résultat d'une évaluation objective (scalaire ou vectoriel)."""
    total: float                        # Somme/moyenne pondérée (score minimisable)
    components: dict[str, float]        # Détail : {"NSE@P01": 0.78, "NSE@P02": 0.62, ...}
    is_scalar: bool = True              # False pour multi-objectif (Pareto)
    vector: tuple[float, ...] | None = None  # Pour MultiObjective uniquement


@runtime_checkable
class Objective(Protocol):
    """Contrat : mesurer la distance entre observé et simulé."""

    name: str
    is_multi_objective: bool            # False par défaut

    def evaluate(
        self,
        observations: ObservationSet,
        simulation: SimulationOutput,
    ) -> ObjectiveValue:
        """Retourne un coût minimisable (nombres ∈ [0, +∞[ ou Pareto-vecteur)."""
        ...

    def best_possible(self) -> float:
        """Valeur de `total` que prend un modèle parfait (généralement 0.0)."""
        ...
```

### 3.2 Implémentations — `ScalarObjective`, `CompositeObjective`, `MultiObjective`

```python
# hydromodpy/analysis/calibration/objectives/scalar.py                     [REFACTORE]

from hydromodpy.analysis.calibration.objectives.metrics import METRICS
from hydromodpy.analysis.calibration.contracts.objective import (
    Objective, ObjectiveValue, ObservationSet, SimulationOutput,
)

class ScalarObjective:
    """Une métrique, une variable, potentiellement multi-stations avec pondération."""

    name = "scalar"
    is_multi_objective = False

    def __init__(
        self,
        metric: str = "nse",              # "nse" | "kge" | "rmse" | "mae" | "nse_log" | "pbias"
        transform: str = "identity",      # Pre-metric: "log" | "sqrt" | "boxcox" | "identity"
        station_weights: dict[str, float] | None = None,
        reduction: str = "weighted_mean", # "weighted_mean" | "weighted_sum" | "max"
    ):
        self._metric_fn = METRICS[metric]
        self._higher_is_better = metric in {"nse", "nse_log", "kge"}
        self._transform = _build_transform(transform)
        self._station_weights = station_weights or {}
        self._reduction = reduction
        self.name = f"{metric}__{transform}"

    def evaluate(self, observations, simulation):
        components = {}
        for station in observations.stations:
            obs = self._transform(observations.values[station])
            sim = self._transform(simulation.values[station])
            value = float(self._metric_fn(obs, sim))
            cost = (1.0 - value) if self._higher_is_better else value
            components[f"{self.name}@{station}"] = cost

        total = self._reduce(components, observations.stations)
        return ObjectiveValue(total=total, components=components)

    def best_possible(self) -> float:
        return 0.0

    def _reduce(self, components, stations):
        weights = np.array([self._station_weights.get(s, 1.0) for s in stations])
        values = np.array(list(components.values()))
        if self._reduction == "weighted_mean":
            return float(np.average(values, weights=weights))
        if self._reduction == "weighted_sum":
            return float(np.sum(values * weights))
        if self._reduction == "max":
            return float(np.max(values))
        raise ValueError(self._reduction)
```

`CompositeObjective` et `MultiObjective` suivent le même pattern. `MultiObjective.evaluate` remplit `vector` et laisse `total` = `np.inf` pour forcer l'appelant à utiliser le vecteur.

### 3.3 Métriques — formules exactes (rappel)

| Nom | Formule | Domaine | Optimum | Réf |
|---|---|---|---|---|
| **NSE** | $1 - \dfrac{\sum(s_t - o_t)^2}{\sum(o_t - \bar o)^2}$ | $(-\infty, 1]$ | 1.0 (cost 0) | Nash & Sutcliffe 1970 |
| **NSE_log** | NSE appliqué à $\log(o_t), \log(s_t)$ (requiert $o_t, s_t > 0$) | idem | 1.0 | Krause et al. 2005 |
| **KGE** | $1 - \sqrt{(r-1)^2 + (\alpha-1)^2 + (\beta-1)^2}$, $\alpha = \sigma_s/\sigma_o$, $\beta = \mu_s/\mu_o$ | $(-\infty, 1]$ | 1.0 | Gupta et al. 2009 |
| **RMSE** | $\sqrt{\tfrac{1}{n}\sum(s_t - o_t)^2}$ | $[0, +\infty)$ | 0 | — |
| **MAE** | $\tfrac{1}{n}\sum|s_t - o_t|$ | $[0, +\infty)$ | 0 | — |
| **PBIAS** | $100 \cdot \dfrac{\sum(s_t - o_t)}{\sum o_t}$ (%) | $(-\infty, +\infty)$ | 0 | Moriasi et al. 2007 |
| **R²** | $\text{corr}(o, s)^2$ | $[0, 1]$ | 1 | — |

**Convention** : `Objective.evaluate` retourne toujours un **coût** (minimiser). Pour NSE/KGE/NSE_log/R² : `cost = 1 - value`. Pour RMSE/MAE/|PBIAS| : `cost = value` directement.

### 3.4 Multi-sites et multi-objectifs

**Multi-sites** (même variable, plusieurs stations) → `ScalarObjective` avec `station_weights` + `reduction`.

**Multi-variables** (e.g. head + discharge) → `CompositeObjective(blocks=[...])` avec un `ObjectiveBlock` par variable :

```python
# hydromodpy/analysis/calibration/objectives/composite.py                  [REFACTORE]

@dataclass(frozen=True, slots=True)
class ObjectiveBlock:
    name: str                              # "heads"
    objective: Objective                   # ScalarObjective(metric="nse", …)
    observations: ObservationSet           # block-specific obs
    simulation_selector: Callable          # SimulationOutput → SimulationOutput filtered
    weight: float = 1.0
    reference_scale: float | None = None   # Pour normaliser le cost (IQR obs)


class CompositeObjective:
    is_multi_objective = False
    name = "composite"

    def __init__(self, blocks: list[ObjectiveBlock]):
        self._blocks = tuple(blocks)

    def evaluate(self, observations, simulation):
        total = 0.0
        components = {}
        for blk in self._blocks:
            sel_sim = blk.simulation_selector(simulation)
            block_val = blk.objective.evaluate(blk.observations, sel_sim)
            scale = blk.reference_scale or 1.0
            block_cost = block_val.total / scale
            total += blk.weight * block_cost
            for k, v in block_val.components.items():
                components[f"{blk.name}/{k}"] = v
        return ObjectiveValue(total=total, components=components)
```

**Multi-objectif** (Pareto) → `MultiObjective` publie `is_multi_objective = True`, son `ObjectiveValue.vector` est consommé par un `Optimizer` qui le supporte (`OptunaAdapter` avec NSGA-II/III, par exemple). Les optimiseurs scalaires lèvent `TypeError` au `ask()` si `objective.is_multi_objective and not self.accepts_multi_objective`.

---

## 4. Contrat n°2 — `Optimizer` (ask / tell)

### 4.1 Protocol

```python
# hydromodpy/analysis/calibration/contracts/optimizer.py                   [NOUVEAU]

from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
import numpy as np

from hydromodpy.analysis.calibration.parameters.space import ParameterSpace


@dataclass(frozen=True, slots=True)
class ParamSuggestion:
    """Un point d'échantillonnage proposé par l'optimiseur."""
    trial_id: int                                       # ordre local à la session
    values_physical: dict[str, float]                   # {"K_aquifer": 1.3e-4, ...}
    values_transformed: np.ndarray                      # vecteur après transform (ex: log10)
    source: str                                         # "ask" | "warm_start" | "initial" | "restart"


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Le résultat d'une évaluation, rendu par l'Evaluator, consommé par l'Optimizer via tell()."""
    trial_id: int
    sim_id: str                                         # UUID dans SimulationCatalog (None si eval crashée)
    objective_value: float                              # cost scalaire (inf si crash)
    objective_vector: tuple[float, ...] | None = None   # pour multi-objectif
    objective_components: dict[str, float] | None = None
    status: str = "completed"                           # "completed" | "diverged" | "timeout" | "crashed"
    duration_s: float = 0.0
    metadata: dict[str, object] | None = None


@runtime_checkable
class Optimizer(Protocol):
    """Contrat : proposer des points (ask), ingérer des résultats (tell), converger."""

    name: str
    space: ParameterSpace
    accepts_multi_objective: bool
    supports_parallel_ask: bool       # True si ask(n>1) fait sens
    supports_warm_start: bool

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        """Propose ``n`` nouveaux points à évaluer."""
        ...

    def tell(self, results: list[EvaluationResult]) -> None:
        """Ingère les résultats ; met à jour l'état interne."""
        ...

    def best(self) -> EvaluationResult | None:
        """Meilleur point connu (objective_value minimal)."""
        ...

    def converged(self) -> bool:
        """True si un critère d'arrêt interne est atteint."""
        ...

    def warm_start(self, history: list[EvaluationResult]) -> None:
        """Ingère un historique d'évaluations pour reprendre une session."""
        ...

    def snapshot(self) -> dict:
        """État sérialisable (JSON) pour checkpointing."""
        ...

    def restore(self, snapshot: dict) -> None:
        """Restaure l'état depuis un snapshot."""
        ...
```

### 4.2 Base commune — `AskTellOptimizer`

Pour écrire un optimiseur built-in sans dupliquer la gestion d'état :

```python
# hydromodpy/analysis/calibration/optimizers/base.py                       [NOUVEAU]

class AskTellOptimizer:
    """Base commune : gère history, best-so-far, conversion transform↔physique."""

    supports_parallel_ask = False
    supports_warm_start = True
    accepts_multi_objective = False

    def __init__(self, space: ParameterSpace, seed: int | None = None):
        self.space = space
        self._rng = np.random.default_rng(seed)
        self._history: list[EvaluationResult] = []
        self._n_asked = 0

    def _make_suggestion(self, values_transformed: np.ndarray, source="ask") -> ParamSuggestion:
        values_phys = self.space.inverse_transform(values_transformed)
        self._n_asked += 1
        return ParamSuggestion(
            trial_id=self._n_asked,
            values_physical=values_phys,
            values_transformed=values_transformed,
            source=source,
        )

    def tell(self, results):
        self._history.extend(results)
        self._on_tell(results)

    def best(self):
        valid = [r for r in self._history if r.status == "completed"]
        return min(valid, key=lambda r: r.objective_value, default=None)

    def warm_start(self, history):
        self._history.extend(history)
        self._n_asked += len(history)
        self._on_warm_start(history)

    def snapshot(self):
        return {"history": [asdict(r) for r in self._history], "n_asked": self._n_asked,
                "rng_state": self._rng.bit_generator.state}

    def restore(self, snap):
        self._history = [EvaluationResult(**d) for d in snap["history"]]
        self._n_asked = snap["n_asked"]
        self._rng.bit_generator.state = snap["rng_state"]

    # Hooks
    def _on_tell(self, results): pass
    def _on_warm_start(self, history): pass
```

### 4.3 Adaptateurs vers bibliothèques externes

Exemple d'adaptateur Optuna (TPE + NSGA-II + Bayesian natif) :

```python
# hydromodpy/analysis/calibration/optimizers/adapters/optuna_adapter.py    [NOUVEAU]

import optuna

class OptunaAdapter(AskTellOptimizer):
    name = "optuna"
    supports_parallel_ask = True
    accepts_multi_objective = True

    def __init__(self, space, *, sampler="tpe", seed=None, **kw):
        super().__init__(space, seed)
        sampler_obj = {
            "tpe":    optuna.samplers.TPESampler(seed=seed),
            "random": optuna.samplers.RandomSampler(seed=seed),
            "cmaes":  optuna.samplers.CmaEsSampler(seed=seed),
            "nsga":   optuna.samplers.NSGAIISampler(seed=seed),
            "botorch": optuna.integration.BoTorchSampler(seed=seed),
        }[sampler]
        self._study = optuna.create_study(sampler=sampler_obj, direction="minimize")
        self._pending: dict[int, optuna.Trial] = {}

    def ask(self, n=1):
        suggestions = []
        for _ in range(n):
            trial = self._study.ask()
            x = np.array([
                trial.suggest_float(p.name, *self.space.transformed_bounds[p.name])
                for p in self.space.parameters
            ])
            sugg = self._make_suggestion(x, source="ask")
            self._pending[sugg.trial_id] = trial
            suggestions.append(sugg)
        return suggestions

    def _on_tell(self, results):
        for r in results:
            trial = self._pending.pop(r.trial_id, None)
            if trial is None:
                continue
            self._study.tell(trial, r.objective_value, state=(
                optuna.trial.TrialState.COMPLETE if r.status == "completed"
                else optuna.trial.TrialState.FAIL))

    def converged(self):
        return False   # Optuna n'a pas de convergence naturelle ; le budget est géré par l'engine
```

**Tableau des adaptateurs** :

| Adaptateur | Lib | Algos | Multi-obj | Parallèle | Warm-start |
|---|---|---|:-:|:-:|:-:|
| `ScipyAdapter` | scipy.optimize | `differential_evolution`, `minimize/L-BFGS-B`, `dual_annealing` | ✗ | ✗ | ✗ |
| `PycmaAdapter` | pycma | CMA-ES, sep-CMA-ES, BIPOP | ✗ | ✔ | ✔ |
| `OptunaAdapter` | optuna | TPE, CMA-ES, NSGA-II, BoTorch | ✔ | ✔ | ✔ |
| `NevergradAdapter` | nevergrad | DE, PSO, ES, OnePlusOne, NGOpt | ✔ | ✔ | ✗ |
| `EmceeAdapter` | emcee | Affine-invariant MCMC | ✗ | ✔ | ✔ |
| `PyMCAdapter` | pymc | NUTS, MH, Slice | ✗ | ✔ | ✗ |
| `PESTPPAdapter` | pyemu + PEST++ binaires | IES, GLM, OPT, SEN | ✗ | ✔ | ✔ |

Built-in (sans dépendance externe) : `GridSearch`, `LatinHypercube`, `SobolSequence`, `RandomSearch`, `NelderMead` (via scipy).

### 4.4 Registre + entry-points

```python
# hydromodpy/analysis/calibration/optimizers/registry.py                   [NOUVEAU]

from importlib.metadata import entry_points
from typing import Callable

_BUILTIN: dict[str, Callable[..., Optimizer]] = {}

def register_optimizer(name: str):
    def deco(cls):
        _BUILTIN[name] = cls
        return cls
    return deco

def build_optimizer(name: str, space, **kwargs) -> Optimizer:
    # 1) Registres built-in
    if name in _BUILTIN:
        return _BUILTIN[name](space, **kwargs)
    # 2) Entry-points tiers "hydromodpy.optimizer"
    for ep in entry_points(group="hydromodpy.optimizer"):
        if ep.name == name:
            return ep.load()(space, **kwargs)
    raise KeyError(f"Unknown optimizer: {name}")
```

Modèle SQLAlchemy dialects / sklearn estimators / Prefect TaskRunner.

---

## 5. Contrat n°3 — `Evaluator`

### 5.1 Protocol

```python
# hydromodpy/analysis/calibration/contracts/evaluator.py                   [NOUVEAU]

from typing import Protocol, runtime_checkable

@runtime_checkable
class Evaluator(Protocol):
    """Contrat : évaluer un point de l'espace des paramètres, produire un EvaluationResult."""

    supports_parallel: bool

    def evaluate_one(self, suggestion: ParamSuggestion) -> EvaluationResult:
        ...

    def evaluate_batch(self, suggestions: list[ParamSuggestion]) -> list[EvaluationResult]:
        """Version bulk ; peut être parallèle."""
        ...
```

### 5.2 Implémentation canonique — `SimulationEvaluator`

```python
# hydromodpy/analysis/calibration/evaluator.py                             [NOUVEAU]

from hydromodpy.simulation.pipeline import Pipeline, PipelineConfig
from hydromodpy.results.catalog import SimulationCatalog

class SimulationEvaluator:
    """
    Évaluateur canonique : pour chaque suggestion, lance un `Pipeline.run()` complet,
    extrait la variable cible du catalog, applique l'Objective.

    Aucune magie : chaque évaluation = une vraie simulation persistée (sim_id stable),
    ce qui ouvre warm-start, cache, et analyse post-hoc.
    """

    supports_parallel = False

    def __init__(
        self,
        base_config,                       # HydroModPyConfig (template pour toutes les évaluations)
        objective: Objective,
        observations: ObservationSet,
        catalog: SimulationCatalog,
        session_id: str,
        param_mapping,                     # cf. §7.3
        cache: "SimulationCache | None" = None,
        timeout_s: float | None = None,
    ):
        self._base_config = base_config
        self._objective = objective
        self._observations = observations
        self._catalog = catalog
        self._session_id = session_id
        self._mapping = param_mapping
        self._cache = cache
        self._timeout = timeout_s

    def evaluate_one(self, sugg: ParamSuggestion) -> EvaluationResult:
        # 1. Hash canonique pour cache content-addressable
        params_hash = _canonical_hash(sugg.values_physical)
        if self._cache is not None:
            hit = self._cache.lookup(params_hash)
            if hit is not None:
                return self._score_from_sim_id(sugg, hit.sim_id, from_cache=True)

        # 2. Construire la config en injectant les paramètres (via mapping)
        cfg = self._mapping.apply(self._base_config, sugg.values_physical)

        # 3. Exécuter le pipeline standard (doc 06) — écrit dans le catalog
        pipeline = Pipeline.default(cfg)
        t0 = time.perf_counter()
        try:
            final_state = pipeline.run(PipelineConfig(timeout_s=self._timeout))
            sim_id = final_state.sim_id
            status = "completed"
        except SolverDivergedError as e:
            sim_id = e.sim_id or ""
            status = "diverged"
            return self._crash_result(sugg, sim_id, status, time.perf_counter() - t0)
        except Exception:
            return self._crash_result(sugg, "", "crashed", time.perf_counter() - t0)

        # 4. Scorer
        result = self._score_from_sim_id(sugg, sim_id, from_cache=False)

        # 5. Mettre en cache
        if self._cache is not None:
            self._cache.insert(params_hash, sim_id)
        return result

    def _score_from_sim_id(self, sugg, sim_id, from_cache):
        sim = self._catalog.simulation(sim_id)
        sim_out = SimulationOutput(
            sim_id=sim_id,
            stations=self._observations.stations,
            times=self._observations.times,
            values={
                s: sim.timeseries(self._observations.variable, station=s).values
                for s in self._observations.stations
            },
            metadata={"from_cache": from_cache, "wall_seconds": sim.duration_s},
        )
        obj = self._objective.evaluate(self._observations, sim_out)
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=sim_id,
            objective_value=obj.total,
            objective_components=obj.components,
            status="completed",
            duration_s=sim.duration_s,
            metadata={"from_cache": from_cache},
        )

    def evaluate_batch(self, suggestions):
        return [self.evaluate_one(s) for s in suggestions]
```

### 5.3 Pourquoi tout passer par le pipeline standard ?

**Avantage décisif sur l'existant** (où `Simulation.run()` bypass `execute_simulation`, cf. audit 06 §7.3) :

1. **Tracabilité gratuite** : chaque itération = une ligne `simulations` dans DuckDB + un Zarr complet.
2. **Un `sim_id` calibré est rejouable** en dehors de la session de calibration (affichage, export `.hmp`, comparaison).
3. **Warm-start trivial** : `SELECT sim_id FROM simulations WHERE session_id = …` redonne l'historique complet.
4. **Provenance unique** : une seule source d'écriture DuckDB/Zarr, zéro risque de divergence.
5. **Reuse code complet** : hashing des inputs, logs, context-managed store, fermeture propre — tout vient gratuitement.

---

## 6. Le `CalibrationEngine` — orchestration

### 6.1 Structure

```python
# hydromodpy/analysis/calibration/engine.py                                [NOUVEAU]

@dataclass
class CalibrationSession:
    session_id: str
    config: CalibrationConfig
    space: ParameterSpace
    optimizer: Optimizer
    evaluator: Evaluator
    objective: Objective
    catalog: SimulationCatalog
    persistence: CalibrationPersistence
    convergence: ConvergenceCriterion


class CalibrationEngine:
    """
    Orchestrateur de calibration.

    Usage :
        engine = CalibrationEngine(config)
        session = engine.run(max_trials=500)
        df = session.to_dataframe()
    """

    def __init__(self, config: CalibrationConfig):
        self._config = config

    def run(
        self,
        *,
        max_trials: int | None = None,
        max_time_s: float | None = None,
        batch_size: int = 1,
        resume_session_id: str | None = None,
    ) -> CalibrationSession:
        session = self._init_session(resume=resume_session_id)
        self._warm_start_if_any(session, resume_session_id)

        convergence = ConvergenceCriterion.from_config(self._config.convergence)
        convergence.set_budget(max_trials=max_trials, max_time_s=max_time_s)

        while not (convergence.met(session.optimizer) or session.optimizer.converged()):
            suggestions = session.optimizer.ask(n=batch_size)
            results = session.evaluator.evaluate_batch(suggestions)
            session.optimizer.tell(results)
            session.persistence.append_iterations(session.session_id, suggestions, results)
            convergence.update(results)

        best = session.optimizer.best()
        session.persistence.finalize(session.session_id, best)
        return session

    def _init_session(self, resume):
        session_id = resume or uuid.uuid4().hex
        space = ParameterSpace.from_config(self._config.parameters)
        optimizer = build_optimizer(
            self._config.optimizer.name, space,
            seed=self._config.seed,
            **self._config.optimizer.kwargs,
        )
        observations = _load_observations(self._config, self._config.catalog_path)
        objective = _build_objective(self._config.objective)
        catalog = SimulationCatalog(self._config.workspace)
        persistence = CalibrationPersistence(catalog)
        if resume is None:
            persistence.start(session_id, self._config)
        evaluator = (
            BatchEvaluator if self._config.parallel.n_workers > 1 else SimulationEvaluator
        )(
            base_config=self._config.simulation,
            objective=objective,
            observations=observations,
            catalog=catalog,
            session_id=session_id,
            param_mapping=ParameterMapping.from_config(self._config.parameters),
            cache=SimulationCache(catalog) if self._config.cache.enabled else None,
        )
        return CalibrationSession(
            session_id=session_id, config=self._config, space=space,
            optimizer=optimizer, evaluator=evaluator, objective=objective,
            catalog=catalog, persistence=persistence,
            convergence=ConvergenceCriterion.from_config(self._config.convergence),
        )

    def _warm_start_if_any(self, session, resume):
        if resume is None:
            return
        history = session.persistence.load_history(resume)
        session.optimizer.warm_start(history)
```

### 6.2 Invariants

- `session_id` est stable sur toute la session. Un résume charge l'existant sans re-créer.
- Chaque `tell` **persiste** immédiatement les itérations. Pas d'accumulation mémoire.
- Les `sim_id` produits sont tous liés à `session_id` via `calibration_iterations.session_id`.
- La convergence est calculée **entre** `tell` et prochain `ask`. Jamais à l'intérieur d'`ask`.

---

## 7. Déclaration des paramètres calibrables

### 7.1 Annotation dans les Pydantic models existants

**Principe** : un champ Pydantic devient calibrable en ajoutant un dictionnaire `calibration` dans `Field.json_schema_extra`. Le TOML de calibration référence le chemin dotted du champ, pas ses bornes.

```python
# hydromodpy/core/config/calibration_meta.py                               [NOUVEAU]

from pydantic import Field
from typing import Annotated

def CalibField(
    *,
    default=None,
    bounds: tuple[float, float] | None = None,
    transform: str = "identity",           # "log" | "logit" | "boxcox" | "identity"
    prior: str = "uniform",                # "uniform" | "log_uniform" | "normal" | "beta"
    prior_params: dict | None = None,
    units: str | None = None,
    description: str = "",
    **kwargs,
):
    """Field Pydantic enrichi de métadonnées de calibration."""
    return Field(
        default=default,
        description=description,
        json_schema_extra={
            "calibration": {
                "calibrable": True,
                "bounds": bounds,
                "transform": transform,
                "prior": prior,
                "prior_params": prior_params or {},
                "units": units,
            },
        },
        **kwargs,
    )
```

Dans un modèle solveur existant, on enrichit juste un champ :

```python
# hydromodpy/solver/modflow6/config.py                                     [REFACTORE mineur]

class ModflowHydroConductivityConfig(BaseModel):
    k_aquifer: float = CalibField(
        default=1e-4,
        bounds=(1e-7, 1e-2),
        transform="log",
        prior="log_uniform",
        units="m/s",
        description="Horizontal hydraulic conductivity of the main aquifer",
    )
    k_aquitard: float = CalibField(
        default=1e-8,
        bounds=(1e-12, 1e-5),
        transform="log",
        prior="log_uniform",
        units="m/s",
    )
```

Un utilitaire `hydromodpy.analysis.calibration.parameters.introspect.discover_calibrable(config)` parcourt le `HydroModPyConfig` complet et retourne la liste des paramètres calibrables détectés — utile pour générer un template TOML `[calibration.parameters]` automatiquement via `hmp config --calibrate`.

### 7.2 Déclaration TOML — `[calibration.parameters.*]`

Le TOML **active** les paramètres déclarés calibrables dans les Pydantic models et peut **surcharger** les bornes/transform/priors :

```toml
[calibration.parameters]
# Nom → chemin dotted dans HydroModPyConfig
"K_aquifer"  = { path = "flow.properties.k_aquifer", bounds = [1e-6, 1e-3] }
"K_aquitard" = { path = "flow.properties.k_aquitard" }          # hérite des annotations Pydantic
"Sy_main"    = { path = "flow.properties.specific_yield",
                 bounds = [0.01, 0.30], transform = "logit", prior = "beta",
                 prior_params = { alpha = 2, beta = 5 } }

# Paramètre lié à une zone géologique (mapping discret)
"K_granite" = { path = "flow.properties.k_aquifer",
                mapping = "zone", zone_id = "granite",
                bounds = [1e-8, 1e-5], transform = "log" }

"K_schist" = { path = "flow.properties.k_aquifer",
               mapping = "zone", zone_id = "schist",
               bounds = [1e-9, 1e-6], transform = "log" }
```

### 7.3 Mapping continu → propriété physique discrète

Le `ParameterMapping` traduit un `dict` continu en injection dans le `HydroModPyConfig`. Trois modes :

| Mode | Usage | Exemple |
|---|---|---|
| **scalar** | Surcharge d'un champ | `flow.properties.k_aquifer = 1.3e-4` |
| **zone** | Affectation à une zone (géol/occup. sol) | `flow.properties.k_aquifer[zone=granite] = 1e-6` |
| **field** | Générer un champ spatial par interpolation de N pilotes | Krigeage de $N$ pilot points → raster K |
| **callable** | Expression Python déclarée via `formula` | `k_aquitard = 0.01 * k_aquifer` (ratio) |

```python
# hydromodpy/analysis/calibration/parameters/mapping.py                    [NOUVEAU]

@dataclass(frozen=True, slots=True)
class ParameterBinding:
    name: str
    path: str                      # "flow.properties.k_aquifer"
    mode: str                      # "scalar" | "zone" | "field" | "callable"
    zone_id: str | None = None
    pilot_points: list | None = None
    formula: Callable | None = None


class ParameterMapping:
    def __init__(self, bindings: list[ParameterBinding]):
        self._bindings = tuple(bindings)

    @classmethod
    def from_config(cls, parameters_cfg) -> "ParameterMapping":
        return cls([ParameterBinding(**p) for p in parameters_cfg])

    def apply(self, base_config: HydroModPyConfig, values: dict[str, float]) -> HydroModPyConfig:
        cfg = base_config.model_copy(deep=True)
        for b in self._bindings:
            v = values[b.name]
            if b.mode == "scalar":
                _set_by_path(cfg, b.path, v)
            elif b.mode == "zone":
                _set_zone_value(cfg, b.path, b.zone_id, v)
            elif b.mode == "field":
                field_arr = _interpolate_pilot_points(b.pilot_points, values)
                _set_by_path(cfg, b.path, field_arr)
            elif b.mode == "callable":
                _set_by_path(cfg, b.path, b.formula(values))
        return cfg
```

### 7.4 Espace de paramètres — `ParameterSpace`

```python
# hydromodpy/analysis/calibration/parameters/space.py                      [REFACTORE — remplace core/parameters.py]

@dataclass(frozen=True, slots=True)
class CalibParameter:
    name: str
    lower: float               # physique
    upper: float               # physique
    transform: Transform       # identity | log | logit | boxcox
    prior: Prior               # uniform | log_uniform | normal | beta
    units: str | None = None

    @property
    def lower_transformed(self) -> float:
        return self.transform.forward(self.lower)

    @property
    def upper_transformed(self) -> float:
        return self.transform.forward(self.upper)


class ParameterSpace:
    """Collection ordonnée de CalibParameter ; gère vector <-> dict + transforms."""

    def __init__(self, parameters: list[CalibParameter]):
        self._params = tuple(parameters)
        self._by_name = {p.name: p for p in parameters}

    @property
    def dim(self) -> int: return len(self._params)
    @property
    def parameters(self) -> tuple[CalibParameter, ...]: return self._params

    def transform(self, values_physical: dict[str, float]) -> np.ndarray:
        return np.array([p.transform.forward(values_physical[p.name]) for p in self._params])

    def inverse_transform(self, values_transformed: np.ndarray) -> dict[str, float]:
        return {
            p.name: p.transform.inverse(float(values_transformed[i]))
            for i, p in enumerate(self._params)
        }

    def sample_prior(self, rng: np.random.Generator, n: int = 1) -> np.ndarray:
        out = np.empty((n, self.dim))
        for i, p in enumerate(self._params):
            out[:, i] = p.prior.sample(rng, n)
        return out

    @property
    def transformed_bounds(self) -> dict[str, tuple[float, float]]:
        return {p.name: (p.lower_transformed, p.upper_transformed) for p in self._params}
```

---

## 8. Métriques et objectifs

### 8.1 Métriques standard — `metrics.py`

Le fichier `hydromodpy/analysis/calibration/objectives/metrics.py` expose **un dict** au lieu d'une classe à switch (antipattern du `engine_config.py` actuel) :

```python
METRICS: dict[str, Callable[[np.ndarray, np.ndarray], float]] = {
    "nse":     nse,
    "nse_log": nse_log,
    "kge":     kge,
    "rmse":    rmse,
    "mae":     mae,
    "pbias":   pbias,
    "r2":      r2,
}

HIGHER_IS_BETTER: frozenset[str] = frozenset({"nse", "nse_log", "kge", "r2"})
```

Chaque fonction prend `(obs, sim) -> float`, masquant les non-finis. Un nouveau critère = une fonction + une entrée dans le dict. Pas d'héritage.

### 8.2 Combinaison multi-sites

Trois stratégies standard, toutes implémentées via `reduction` kwarg de `ScalarObjective` :

| Réduction | Formule | Quand l'utiliser |
|---|---|---|
| `"weighted_mean"` | $\sum_s w_s \cdot cost_s / \sum_s w_s$ | Calibrage équilibré multi-stations |
| `"weighted_sum"` | $\sum_s w_s \cdot cost_s$ | Quand le nombre de stations est fixe |
| `"max"` | $\max_s cost_s$ | Robustesse au pire |
| `"softmax_p"` | $\left(\sum_s w_s cost_s^p\right)^{1/p}$ | Entre somme et max ($p \in (1, +\infty)$) |

Poids `w_s` configurables par station via TOML.

### 8.3 Multi-objectif — Pareto, pondération, epsilon-contrainte

Trois stratégies supportées :

| Stratégie | Configuration TOML | Optimiseur approprié |
|---|---|---|
| **Weighted sum** (scalarisation simple) | `objective.strategy = "weighted_sum"` + poids par bloc | Tout optimiseur scalaire |
| **Pareto front** (vrai multi-objectif) | `objective.strategy = "pareto"` | `OptunaAdapter(sampler="nsga")`, `NevergradAdapter(algo="NSGA")` |
| **Epsilon-constraint** (un objectif, les autres en contrainte) | `objective.strategy = "epsilon_constraint"` + `[calibration.objective.constraints]` | Tout optimiseur scalaire + cost pénalisé |

Exemple TOML Pareto :

```toml
[calibration.objective]
strategy = "pareto"

[[calibration.objective.blocks]]
name = "heads"
variable = "head"
metric = "nse"
stations = ["P01", "P02", "P03"]

[[calibration.objective.blocks]]
name = "discharge"
variable = "discharge"
metric = "kge"
stations = ["Q_outlet"]
```

Post-traitement du Pareto front via `session.pareto_front() -> pd.DataFrame` (ligne par sim non-dominée, colonnes = objectifs).

---

## 9. Schéma DuckDB étendu

### 9.1 État actuel

Les tables `calibration_sessions` et `calibration_iterations` existent déjà (cf. `results/catalog_schema.py:149-171`) mais sont **minimales** :
- `calibration_sessions(session_id, best_sim_id, method, n_iterations, best_objective, duration_s, config JSON, created_at)`
- `calibration_iterations(session_id, iteration, parameters JSON, objective_value, metrics JSON, duration_s)`

**Limites** :
- `parameters JSON` : pas de requête SQL sur un paramètre précis sans `json_extract`.
- Pas de lien `sim_id` → `session_id` : on ne peut pas chercher « toutes les simulations de la session X ».
- Pas de status par iteration (diverged/completed/crashed).

### 9.2 Schéma cible — tables enrichies et normalisées

```sql
-- [REFACTORE] calibration_sessions : enrichissement (+status, +best_iteration, +optimizer_kwargs, +objective_spec)
CREATE TABLE calibration_sessions (
    session_id         UUID PRIMARY KEY,
    name               VARCHAR,                      -- label utilisateur
    optimizer          VARCHAR NOT NULL,             -- "optuna", "pycma", "scipy_de", ...
    optimizer_kwargs   JSON,
    objective_spec     JSON,                         -- blocks, weights, metric per block
    parameter_space    JSON,                         -- bounds, transforms, priors
    seed               INTEGER,
    n_trials_target    INTEGER,
    n_trials_completed INTEGER,
    n_trials_crashed   INTEGER,
    best_sim_id        UUID,
    best_iteration     INTEGER,
    best_objective     DOUBLE,
    status             VARCHAR CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    duration_s         DOUBLE,
    started_at         TIMESTAMPTZ,
    finished_at        TIMESTAMPTZ,
    config             JSON,                         -- full snapshot TOML
    environment        JSON                          -- PROV-O : git_sha, python_version, ...
);

-- [REFACTORE] calibration_iterations : +status, +sim_id FK
CREATE TABLE calibration_iterations (
    session_id        UUID NOT NULL REFERENCES calibration_sessions(session_id) ON DELETE CASCADE,
    iteration         INTEGER NOT NULL,
    sim_id            UUID,                          -- FK vers simulations(sim_id) ; NULL si crashed sans run
    status            VARCHAR CHECK (status IN ('completed', 'diverged', 'timeout', 'crashed')),
    objective_value   DOUBLE,
    objective_vector  DOUBLE[],                      -- pour multi-objectif
    components        JSON,                          -- {"nse@P01": 0.78, ...}
    duration_s        DOUBLE,
    from_cache        BOOLEAN DEFAULT FALSE,
    started_at        TIMESTAMPTZ,
    PRIMARY KEY (session_id, iteration)
);

-- [NOUVEAU] calibration_iterations_params : long-format normalisé (1 ligne par param × iter)
CREATE TABLE calibration_iterations_params (
    session_id        UUID NOT NULL,
    iteration         INTEGER NOT NULL,
    param_name        VARCHAR NOT NULL,
    value_physical    DOUBLE,
    value_transformed DOUBLE,
    PRIMARY KEY (session_id, iteration, param_name),
    FOREIGN KEY (session_id, iteration)
        REFERENCES calibration_iterations(session_id, iteration) ON DELETE CASCADE
);

-- [NOUVEAU] Vue dé-normalisée pour chargement pandas direct
CREATE VIEW calibration_iterations_wide AS
SELECT
    i.session_id, i.iteration, i.sim_id, i.status, i.objective_value,
    i.duration_s, i.from_cache, i.started_at, i.components,
    PIVOT p.value_physical FOR p.param_name IN (SELECT DISTINCT param_name FROM calibration_iterations_params)
FROM calibration_iterations i
LEFT JOIN calibration_iterations_params p USING (session_id, iteration);

-- [NOUVEAU] sensitivity_sessions & sensitivity_indices — cf. §10
CREATE TABLE sensitivity_sessions (
    sa_session_id     UUID PRIMARY KEY,
    method            VARCHAR NOT NULL CHECK (method IN ('sobol', 'morris', 'fast')),
    parameter_space   JSON,
    variable          VARCHAR,                       -- "head", "discharge"
    station           VARCHAR,
    metric            VARCHAR,                       -- "nse"
    n_samples         INTEGER,
    n_simulations     INTEGER,
    seed              INTEGER,
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    config            JSON
);

CREATE TABLE sensitivity_indices (
    sa_session_id  UUID NOT NULL REFERENCES sensitivity_sessions(sa_session_id) ON DELETE CASCADE,
    param_name     VARCHAR NOT NULL,
    index_name     VARCHAR NOT NULL,                 -- 'S1', 'ST', 'mu_star', 'sigma'
    value          DOUBLE,
    confidence_lo  DOUBLE,
    confidence_hi  DOUBLE,
    PRIMARY KEY (sa_session_id, param_name, index_name)
);

-- Index utiles
CREATE INDEX idx_iter_obj ON calibration_iterations(session_id, objective_value);
CREATE INDEX idx_iter_sim ON calibration_iterations(sim_id);
CREATE INDEX idx_sess_best ON calibration_sessions(best_objective);
```

### 9.3 Exemples de requêtes courantes

**Top-10 itérations par NSE** :

```sql
SELECT iteration, sim_id, objective_value, components->>'nse@P01' AS nse_p01
FROM calibration_iterations
WHERE session_id = $1 AND status = 'completed'
ORDER BY objective_value ASC
LIMIT 10;
```

**Trajectoire d'un paramètre sur toute la session** :

```sql
SELECT i.iteration, p.value_physical, i.objective_value
FROM calibration_iterations i
JOIN calibration_iterations_params p USING (session_id, iteration)
WHERE i.session_id = $1 AND p.param_name = 'K_aquifer'
ORDER BY i.iteration;
```

**Pivot paramètres+métriques pour analyse ML en pandas** :

```python
df = catalog.read_sql(f"SELECT * FROM calibration_iterations_wide WHERE session_id = '{sid}'")
# df.columns == ['session_id','iteration','sim_id','status','objective_value',
#                'K_aquifer','K_aquitard','Sy_main', ...]
```

### 9.4 API Python — `CalibrationPersistence`

```python
# hydromodpy/analysis/calibration/persistence.py                           [NOUVEAU]

class CalibrationPersistence:
    """Écriture idempotente des itérations de calibration dans DuckDB."""

    def __init__(self, catalog: SimulationCatalog):
        self._catalog = catalog

    def start(self, session_id: str, config: CalibrationConfig) -> None:
        self._catalog.execute(
            """
            INSERT INTO calibration_sessions
              (session_id, name, optimizer, optimizer_kwargs, objective_spec,
               parameter_space, seed, n_trials_target, status, started_at, config, environment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', now(), ?, ?)
            """,
            [session_id, config.name, config.optimizer.name,
             json(config.optimizer.kwargs), json(config.objective.dict()),
             json(config.parameters), config.seed, config.max_trials,
             json(config.dict()), json(_collect_environment())],
        )

    def append_iterations(self, session_id, suggestions, results):
        for sugg, res in zip(suggestions, results):
            self._catalog.execute(
                """INSERT INTO calibration_iterations
                   (session_id, iteration, sim_id, status, objective_value, objective_vector,
                    components, duration_s, from_cache, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, now())
                   ON CONFLICT (session_id, iteration) DO UPDATE
                   SET sim_id = EXCLUDED.sim_id, status = EXCLUDED.status,
                       objective_value = EXCLUDED.objective_value, components = EXCLUDED.components""",
                [session_id, sugg.trial_id, res.sim_id or None, res.status,
                 res.objective_value, list(res.objective_vector) if res.objective_vector else None,
                 json(res.objective_components), res.duration_s,
                 (res.metadata or {}).get("from_cache", False)],
            )
            for name, val in sugg.values_physical.items():
                self._catalog.execute(
                    """INSERT INTO calibration_iterations_params
                       (session_id, iteration, param_name, value_physical, value_transformed)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT DO UPDATE SET value_physical = EXCLUDED.value_physical""",
                    [session_id, sugg.trial_id, name, val,
                     float(sugg.values_transformed[list(sugg.values_physical).index(name)])],
                )

    def finalize(self, session_id, best: EvaluationResult | None):
        self._catalog.execute(
            """UPDATE calibration_sessions
               SET status = 'completed', finished_at = now(),
                   best_sim_id = ?, best_iteration = ?, best_objective = ?,
                   n_trials_completed = (SELECT COUNT(*) FROM calibration_iterations
                                         WHERE session_id = ? AND status = 'completed'),
                   n_trials_crashed   = (SELECT COUNT(*) FROM calibration_iterations
                                         WHERE session_id = ? AND status != 'completed')
               WHERE session_id = ?""",
            [best.sim_id if best else None,
             best.trial_id if best else None,
             best.objective_value if best else None,
             session_id, session_id, session_id],
        )

    def load_history(self, session_id) -> list[EvaluationResult]:
        rows = self._catalog.read_sql(
            """SELECT iteration, sim_id, status, objective_value, components, duration_s
               FROM calibration_iterations WHERE session_id = ? ORDER BY iteration""",
            [session_id],
        )
        return [EvaluationResult(**r) for r in rows]
```

### 9.5 Export DataFrame pour analyse ML

```python
# hydromodpy/analysis/calibration/dataframe.py                             [NOUVEAU]

def to_dataframe(
    catalog: SimulationCatalog,
    session_id: str,
    *,
    include_components: bool = True,
    only_completed: bool = True,
) -> pd.DataFrame:
    """
    Retourne un DataFrame plat prêt pour sklearn / seaborn / pandas.

    Colonnes:
      - session_id, iteration, sim_id, status, objective_value, duration_s
      - <param_name_1>, <param_name_2>, ...    (valeurs physiques)
      - <component_1>, <component_2>, ...      (si include_components)
    """
    where = "WHERE session_id = ?"
    if only_completed:
        where += " AND status = 'completed'"
    df = catalog.read_sql(f"SELECT * FROM calibration_iterations_wide {where}", [session_id])
    if include_components:
        comps = pd.json_normalize(df.pop("components"))
        df = pd.concat([df, comps], axis=1)
    return df


# Usage notebook:
#   df = to_dataframe(catalog, sid)
#   sns.pairplot(df[["K_aquifer", "Sy", "objective_value"]])
#   from sklearn.ensemble import RandomForestRegressor
#   RandomForestRegressor().fit(df[param_names], df.objective_value).feature_importances_
```

---

## 10. Sensibilité — SALib

### 10.1 Façade unique `SensitivityAnalyzer`

```python
# hydromodpy/analysis/calibration/sensitivity/analyzer.py                  [NOUVEAU]

from SALib.sample import sobol as sobol_sample, morris as morris_sample, fast_sampler
from SALib.analyze import sobol as sobol_analyze, morris as morris_analyze, fast

class SensitivityAnalyzer:
    """Wrapper uniforme sur SALib. Réutilise Evaluator et ParameterSpace."""

    def __init__(
        self,
        method: str,                    # "sobol" | "morris" | "fast"
        space: ParameterSpace,
        evaluator: Evaluator,           # idem calibration : BatchEvaluator recommandé
        scalar_output: Callable[[SimulationOutput], float],
        n_samples: int = 1024,
        seed: int | None = None,
    ):
        self.method = method
        self.space = space
        self.evaluator = evaluator
        self.scalar = scalar_output
        self.n_samples = n_samples
        self.seed = seed

    def _salib_problem(self) -> dict:
        return {
            "num_vars": self.space.dim,
            "names": [p.name for p in self.space.parameters],
            "bounds": [[p.lower_transformed, p.upper_transformed] for p in self.space.parameters],
        }

    def _sample(self):
        prob = self._salib_problem()
        if self.method == "sobol":
            return sobol_sample.sample(prob, self.n_samples, seed=self.seed)
        if self.method == "morris":
            return morris_sample.sample(prob, self.n_samples, num_levels=4, seed=self.seed)
        if self.method == "fast":
            return fast_sampler.sample(prob, self.n_samples, seed=self.seed)
        raise ValueError(self.method)

    def run(self, *, sa_session_id: str | None = None) -> "SensitivityResult":
        sa_session_id = sa_session_id or uuid.uuid4().hex
        X = self._sample()                           # shape (N, dim) transformed
        suggestions = [self._suggestion_from_x(i, row) for i, row in enumerate(X)]
        results = self.evaluator.evaluate_batch(suggestions)
        Y = np.array([self.scalar(r) for r in results])
        prob = self._salib_problem()
        if self.method == "sobol":
            idx = sobol_analyze.analyze(prob, Y, seed=self.seed)
        elif self.method == "morris":
            idx = morris_analyze.analyze(prob, X, Y, num_levels=4, seed=self.seed)
        elif self.method == "fast":
            idx = fast.analyze(prob, Y, seed=self.seed)
        self._persist(sa_session_id, idx)
        return SensitivityResult(sa_session_id=sa_session_id, indices=idx, raw_X=X, raw_Y=Y)
```

### 10.2 Mapping des indices → DuckDB

| Méthode | Indices stockés |
|---|---|
| **Sobol** | `S1`, `ST`, `S2_{i,j}` (optionnel matrix → flatten), conf low/high (bootstrap) |
| **Morris** | `mu`, `mu_star`, `sigma`, `mu_star_conf` |
| **FAST** | `S1`, `ST` (pas de conf SALib) |

Une ligne par `(sa_session_id, param_name, index_name)`.

### 10.3 Lien avec la calibration — screening avant optimisation

Flux recommandé :

```
[1] Morris screening       → identifie params non-influents (mu_star ≈ 0)
[2] Fix non-influents à midpoint
[3] Sobol sur params retenus → confirme importance
[4] Calibration sur params importants uniquement
```

CLI :

```bash
hmp sensitivity config.toml --method morris --samples 100
hmp sensitivity config.toml --method sobol  --samples 1024   # après screening
hmp calibrate   config.toml --fix-low-sensitivity            # gèle les params mu_star < seuil
```

Le flag `--fix-low-sensitivity` lit la dernière `sensitivity_session` de la table et retire les paramètres à faible `mu_star` de `ParameterSpace`.

---

## 11. Warm start, cache, reprise, parallélisation

### 11.1 Reprise de session

Une session interrompue (Ctrl-C, crash, OOM) reste `status='running'` en DuckDB. Deux commandes pour reprendre :

```bash
hmp calibrate config.toml --resume                    # reprend la dernière session "running"
hmp calibrate config.toml --resume <session_id>       # reprend une session spécifique
```

**Mécanisme** :
1. `CalibrationEngine._init_session(resume=sid)` reload la session DuckDB.
2. `persistence.load_history(sid)` charge tous les `EvaluationResult`.
3. `optimizer.warm_start(history)` restaure l'état interne.
4. Boucle reprend à `trial_id = max(iteration) + 1`.

### 11.2 Cache content-addressable — `SimulationCache`

```python
# hydromodpy/analysis/calibration/cache.py                                 [NOUVEAU]

class SimulationCache:
    """
    Cache content-addressable : deux suggestions avec les mêmes paramètres physiques
    canoniques mappent au même sim_id, réutilisé sans ré-exécuter le pipeline.
    """

    def __init__(self, catalog: SimulationCatalog):
        self._catalog = catalog
        self._ensure_table()

    def _ensure_table(self):
        self._catalog.execute(
            """CREATE TABLE IF NOT EXISTS simulation_cache (
                  params_hash VARCHAR PRIMARY KEY,
                  sim_id      UUID NOT NULL REFERENCES simulations(sim_id) ON DELETE CASCADE,
                  inserted_at TIMESTAMPTZ DEFAULT now()
            )"""
        )

    def lookup(self, params_hash: str) -> "CacheHit | None":
        row = self._catalog.read_sql(
            "SELECT sim_id FROM simulation_cache WHERE params_hash = ?",
            [params_hash],
        ).fetchone()
        return CacheHit(sim_id=row[0]) if row else None

    def insert(self, params_hash: str, sim_id: str) -> None:
        self._catalog.execute(
            "INSERT OR REPLACE INTO simulation_cache (params_hash, sim_id) VALUES (?, ?)",
            [params_hash, sim_id],
        )


def _canonical_hash(values: dict[str, float], *, decimals: int = 8) -> str:
    """Hash stable : tri des clés, arrondi des valeurs, SHA-256 du JSON canonique."""
    canonical = {k: round(float(values[k]), decimals) for k in sorted(values)}
    return hashlib.sha256(json.dumps(canonical).encode()).hexdigest()
```

### 11.3 Parallélisation — `BatchEvaluator`

```python
# hydromodpy/analysis/calibration/batch.py                                 [NOUVEAU]

from concurrent.futures import ProcessPoolExecutor, as_completed

class BatchEvaluator:
    """
    Évaluateur parallèle. Distribue les suggestions sur `n_workers` processus.

    Backend:
      - "process" : concurrent.futures.ProcessPoolExecutor (local multi-core)
      - "dask"    : dask.distributed.Client (cluster) — via optional dep
    """

    supports_parallel = True

    def __init__(
        self,
        single: SimulationEvaluator,
        n_workers: int,
        backend: str = "process",
        max_retries: int = 1,
    ):
        self._single = single
        self._n = n_workers
        self._backend = backend
        self._max_retries = max_retries

    def evaluate_one(self, sugg): return self._single.evaluate_one(sugg)

    def evaluate_batch(self, suggestions):
        if len(suggestions) <= 1 or self._n <= 1:
            return [self.evaluate_one(s) for s in suggestions]
        if self._backend == "process":
            return self._run_process(suggestions)
        if self._backend == "dask":
            return self._run_dask(suggestions)
        raise ValueError(self._backend)

    def _run_process(self, suggestions):
        results: list[EvaluationResult | None] = [None] * len(suggestions)
        with ProcessPoolExecutor(max_workers=self._n) as ex:
            futures = {ex.submit(self._single.evaluate_one, s): i
                       for i, s in enumerate(suggestions)}
            for fut in as_completed(futures):
                i = futures[fut]
                results[i] = fut.result()
        return results
```

**Contraintes critiques pour que `ProcessPoolExecutor` fonctionne** :
- `SimulationEvaluator` doit être picklable (uses context, not file handles).
- `SimulationCatalog` ouvert dans chaque worker (DuckDB ne supporte pas le partage cross-process du handle).
- Les `sim_id` ainsi produits sont tous dans le même `hydromodpy.duckdb` (`filelock` évite la corruption, mais linearize l'écriture : réaliste pour N < ~16 workers).

### 11.4 Warm start depuis un historique externe

Cas d'usage : calibration précédente sur un domaine similaire.

```python
prior_session = catalog.read_sql("SELECT * FROM calibration_iterations_wide WHERE session_id = ?", [prev_sid])
engine = CalibrationEngine(config)
session = engine.run(warm_start_from=prior_session)
```

L'`Optimizer.warm_start(history)` accepte un DataFrame qu'il interprète selon l'adaptateur :
- `OptunaAdapter` : `study.add_trials(prior_trials)`.
- `PycmaAdapter` : initialise la moyenne / covariance de CMA-ES depuis les meilleurs.
- `AskTellOptimizer` de base : ingère l'historique en `_history`.

---

## 12. Interface utilisateur

### 12.1 Section TOML `[calibration]`

```toml
# ============================================================
# CALIBRATION — Configuration complète
# ============================================================

[calibration]
name        = "canut_monthly_2020_2023"
seed        = 42
max_trials  = 500
max_time_s  = 7200                 # optional budget temps

# --- Optimiseur -----------------------------------------------
[calibration.optimizer]
name = "optuna"
kwargs = { sampler = "tpe", n_startup_trials = 20 }

# --- Paramètres calibrables -----------------------------------
[calibration.parameters]
K_aquifer  = { path = "flow.properties.k_aquifer",
               bounds = [1e-6, 1e-3], transform = "log", prior = "log_uniform" }

K_granite  = { path = "flow.properties.k_aquifer",
               mapping = "zone", zone_id = "granite",
               bounds = [1e-8, 1e-5], transform = "log" }

Sy_main    = { path = "flow.properties.specific_yield",
               bounds = [0.02, 0.30], transform = "logit",
               prior = "beta", prior_params = { alpha = 2, beta = 5 } }

drain_cond = { path = "flow.drain.conductance",
               bounds = [1e-4, 1e-1], transform = "log" }

# --- Objectif -------------------------------------------------
[calibration.objective]
strategy = "composite"              # "scalar" | "composite" | "pareto" | "epsilon_constraint"

[[calibration.objective.blocks]]
name     = "heads"
variable = "head"
metric   = "nse"
transform = "identity"
stations = ["P01", "P02", "P03", "P05"]
station_weights = { P01 = 2.0, P02 = 1.0 }
reduction = "weighted_mean"
weight   = 1.0

[[calibration.objective.blocks]]
name     = "discharge"
variable = "discharge"
metric   = "kge"
transform = "log"                   # pré-métrique log
stations = ["Q_outlet"]
weight   = 2.0

# --- Observations (chemin vers séries) ------------------------
[calibration.observations]
heads_csv      = "data/observations/heads_2020_2023.csv"
discharge_csv  = "data/observations/discharge_outlet_2020_2023.csv"
time_range     = ["2020-01-01", "2023-12-31"]

# --- Cache et parallélisme ------------------------------------
[calibration.cache]
enabled = true
decimals = 8                        # précision du hash

[calibration.parallel]
n_workers = 4
backend   = "process"               # "process" | "dask"

# --- Convergence ----------------------------------------------
[calibration.convergence]
tolerance              = 1e-4
patience               = 50          # stop si pas d'amélioration pendant 50 iter
min_trials             = 100
```

### 12.2 CLI — `hmp calibrate`

```bash
# Usage de base
hmp calibrate config.toml

# Reprise
hmp calibrate config.toml --resume
hmp calibrate config.toml --resume <session_id>

# Budget explicite (override TOML)
hmp calibrate config.toml --max-trials 1000 --max-time 1h

# Pre-screening + calibration
hmp sensitivity config.toml --method morris --samples 200
hmp calibrate   config.toml --fix-low-sensitivity --sa-session latest

# Post-hoc
hmp calibration list                                       # toutes les sessions du workspace
hmp calibration show <session_id>                          # résumé
hmp calibration export <session_id> --format dataframe > iters.parquet
hmp calibration plot <session_id> --kind convergence
hmp calibration plot <session_id> --kind dotty --param K_aquifer
```

**Sortie CLI** (exemple live) :

```
╭─ calibration : canut_monthly_2020_2023 ──────────────────╮
│ session : 7f3e9c1a…                                      │
│ optimizer : optuna (TPE)                                 │
│ params : K_aquifer, K_granite, Sy_main, drain_cond       │
│ target : cost → 0  (strategy: composite, 2 blocks)       │
│ budget : max_trials=500 | max_time=7200s                 │
├──────────────────────────────────────────────────────────┤
│ Trial 127/500  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━   25% (127) │
│                                                          │
│ best so far : trial #84, cost=0.187 (heads NSE=0.823)    │
│ last        : trial #127, cost=0.245 (from cache: false) │
│ workers     : 4 active (1.2s avg/eval)                   │
│ ETA         : 18m32s                                     │
╰──────────────────────────────────────────────────────────╯
```

### 12.3 API Python

```python
import hydromodpy as hmp

# Haut niveau : une fonction, un TOML
session = hmp.calibrate("config.toml", max_trials=500)
print(session.best.sim_id, session.best.objective_value)

# Moyen niveau : builder explicit
cfg = hmp.CalibrationConfig.from_toml("config.toml")
engine = hmp.CalibrationEngine(cfg)
session = engine.run(max_trials=500, batch_size=4)

# Bas niveau : ask/tell programmatique (pour un use-case custom)
space = hmp.ParameterSpace.from_toml("config.toml")
optimizer = hmp.build_optimizer("pycma", space, sigma=0.3)
evaluator = hmp.SimulationEvaluator(base_config=cfg.simulation, ...)
for step in range(100):
    suggs = optimizer.ask(n=4)
    res = evaluator.evaluate_batch(suggs)
    optimizer.tell(res)
best = optimizer.best()

# Post-hoc — analyse ML
df = hmp.calibration.to_dataframe(session.session_id)
# df.columns : ['iteration', 'sim_id', 'status', 'objective_value',
#               'K_aquifer', 'K_granite', 'Sy_main', 'drain_cond',
#               'heads/nse@P01', 'heads/nse@P02', ...]

# Visualisation (dans hydromodpy.display.calibration)
hmp.display.convergence(session.session_id)
hmp.display.dotty(session.session_id, param="K_aquifer")
hmp.display.parallel_coordinates(session.session_id)
hmp.display.pareto(session.session_id)                        # if multi-objective
```

---

## 13. Diagramme de séquence

### 13.1 Calibration standard (single-objective, scalar, n_workers=1)

```
┌─────────┐  ┌────────────┐ ┌─────────┐ ┌───────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐
│  User   │  │CalibEngine │ │Optimizer│ │Evaluator  │ │Pipeline  │ │Objective│ │Catalog   │
└────┬────┘  └─────┬──────┘ └────┬────┘ └─────┬─────┘ └────┬─────┘ └────┬────┘ └────┬─────┘
     │ run()       │             │            │            │            │           │
     │────────────►│             │            │            │            │           │
     │             │ INSERT calibration_sessions(status=running)         │           │
     │             │────────────────────────────────────────────────────────────────►│
     │             │ ask(1)      │            │            │            │           │
     │             │────────────►│            │            │            │           │
     │             │◄────── ParamSuggestion[] │            │            │           │
     │             │ evaluate_batch(suggs)    │            │            │           │
     │             │─────────────────────────►│            │            │           │
     │             │             │            │ hash & lookup cache     │           │
     │             │             │            │───────────────────────────────────► │
     │             │             │            │◄─────────── hit?=False               │
     │             │             │            │ apply mapping + Pipeline.run(cfg)    │
     │             │             │            │───────────►│            │           │
     │             │             │            │            │ solve / extract / agg  │
     │             │             │            │            │───────────────────────►│
     │             │             │            │◄─────── sim_id          │           │
     │             │             │            │ load simulated series   │           │
     │             │             │            │◄──────────────────────────────────── │
     │             │             │            │ objective.evaluate(obs, sim)         │
     │             │             │            │─────────────────────────►│           │
     │             │             │            │◄─── ObjectiveValue(total, components)│
     │             │             │            │ cache.insert(hash, sim_id)           │
     │             │             │            │───────────────────────────────────► │
     │             │◄─────────── EvaluationResult[]                                   │
     │             │ tell(results)            │            │            │           │
     │             │────────────►│            │            │            │           │
     │             │ persistence.append_iterations(...)                              │
     │             │────────────────────────────────────────────────────────────────►│
     │             │    ▲                     │            │            │           │
     │             │    └── loop until convergence (ask/tell/persist)   │           │
     │             │ finalize(best)           │            │            │           │
     │             │────────────────────────────────────────────────────────────────►│
     │◄──────────── CalibrationSession                                                │
```

### 13.2 Calibration parallèle (n_workers=4, BatchEvaluator)

```
 Engine ──ask(4)──► Optimizer
 Engine ──evaluate_batch(4 suggs)──► BatchEvaluator
                                       ├─── worker 1 : Pipeline.run(cfg_1) ──► sim_1
                                       ├─── worker 2 : Pipeline.run(cfg_2) ──► sim_2
                                       ├─── worker 3 : Pipeline.run(cfg_3) ──► sim_3
                                       └─── worker 4 : Pipeline.run(cfg_4) ──► sim_4
                                       (as_completed re-agrège les 4 EvaluationResults)
 Engine ──tell(results)──► Optimizer      (cible: mise à jour interne, e.g. TPE model)
 Engine ──persistence.append_iterations(4 rows)──► DuckDB
 (loop)
```

---

## 14. Comparaison aux projets de référence

| Projet | Ce qu'on reprend | Ce qu'on ne reprend pas |
|---|---|---|
| **PEST / PEST++** | Pilot points, Tikhonov regularization, IES (iterative ensemble smoother via pyemu). Adaptateur `PESTPPAdapter`. Concept `template.tpl`/`instruction.ins` remplacé par l'injection directe via `ParameterMapping.apply(config)` — plus propre. | Pas de syntaxe PEST verbeuse ; pas de template files ; pas de binaire natif requis si l'adaptateur est inactif. |
| **OSTRICH** | Idée « optimization framework as wrapper over any model » (multi-algo). | Pas de DSL OSTRICH ; on reste en Python pur. |
| **Optuna** | Pattern `study.ask() / study.tell(trial, value)`, samplers pluggables, pruners, multi-objective NSGA-II, dashboard web (optional dep). | Pas de storage SQLite Optuna duplicated ; on persiste directement dans notre DuckDB (adapter `OptunaAdapter` remappe). |
| **Ax / BoTorch (Meta)** | Bayesian optimization avec GP + acquisition (UCB, EI, qNEHVI pour multi-obj). Via `OptunaAdapter` (BoTorch integration) ou adaptateur dédié. | Pas de `AxClient` natif : over-engineering pour nos cas d'usage. |
| **scipy.optimize** | `differential_evolution`, `minimize`, `dual_annealing`, `shgo`. Adaptateur `ScipyAdapter`. | Les callbacks scipy sont monothread-only ; on n'expose pas `scipy.optimize.basinhopping` (redondant avec DE). |
| **pycma** | CMA-ES state-of-the-art boîte noire. Adaptateur `PycmaAdapter`. Warm-start via mean/covariance. | Pas de dépendance runtime obligatoire (optional). |
| **emcee / DREAM** | MCMC affine-invariant pour calibration bayésienne complète. Adaptateur `EmceeAdapter`. Posterior samples stockés en DuckDB → `calibration_posterior_samples`. | Pas de réimplémentation de DREAM ; l'adaptateur emcee suffit. |
| **PyMC** | NUTS sampler, full Bayesian inference. Adaptateur `PyMCAdapter` (optional). | PyMC requiert PyTensor + compilateur C ; dep lourde, optional. |
| **SALib** | Sobol, Morris, FAST, Delta moment-independent. Intégration directe. | On ne ré-implémente pas SALib. |
| **MLflow Tracking** | Log params + metrics par run, run_id UUID. | Pas de serveur MLflow ; DuckDB est notre backend. La *structure* est la même. |
| **Prefect / Dagster** | Contrat "task + state", `on_failure`, checkpointing. | Pas de scheduler ; on reste en CLI + notebook. |
| **Nevergrad (FAIR)** | Benchmark massif d'optimiseurs, `Optimizer.ask()/tell()`. | Ajouté via `NevergradAdapter` optional. |

---

## 15. Tableau de migration actuel → cible

| Élément actuel | Localisation | Cible | Statut |
|---|---|---|---|
| `core/engine.py :: CalibrationEngine` | 336 l. | `engine.py :: CalibrationEngine` (plus haut niveau, remplace launcher + engine) | [REFACTORE] |
| `core/engine_config.py` | 390 l. | `config.py :: CalibrationConfig` (Pydantic) | [REFACTORE] |
| `core/parameters.py :: CalibrationParameterSet` | 255 l. | `parameters/space.py :: ParameterSpace` + `CalibParameter` (priors, transforms, units) | [REFACTORE] |
| `core/objective_function.py` | 263 l. | `objectives/metrics.py` (dict) + `objectives/scalar.py` (classe) | [REFACTORE] |
| `core/composite_objective.py` | 271 l. | `objectives/composite.py` + `multi.py` | [REFACTORE] |
| `core/objective_wrappers.py` | 134 l. | supprimé — inline dans `ScalarObjective` | [SUPPRIME] |
| `core/objective_transformations.py` | 131 l. | `objectives/transforms.py` | [RENOMME] |
| `core/methods_config.py` | 522 l. | supprimé — kwargs opaques dans `[calibration.optimizer.kwargs]` | [SUPPRIME] |
| `core/methods_dispatcher.py` | 155 l. | `optimizers/registry.py` (registry + entry-points) | [REFACTORE] |
| `core/methods/` (7 fichiers) | — | `optimizers/builtin/` + `optimizers/adapters/` | [REFACTORE] |
| `core/case_interface.py`, `core/case_orchestrator.py` | 328 l. | supprimés — les "cases" deviennent des tests de validation classiques | [SUPPRIME] |
| `core/results.py :: CalibrationResults` | 205 l. | remplacé par `CalibrationSession` + requêtes DuckDB + DataFrame | [REFACTORE] |
| `engine/launcher.py :: ModelCalibrationLauncher` | 292 l. | supprimé — remplacé par `CalibrationEngine` + CLI `hmp calibrate` | [SUPPRIME] |
| `engine/session.py` | **3 409 l.** | éclaté : `evaluator.py` (200 l.) + `parameters/mapping.py` (250 l.) + `batch.py` (150 l.) + code supprimé | [REFACTORE majeur] |
| `engine/config.py :: ModelCalibrationConfig` | 563 l. | fusionné dans `config.py :: CalibrationConfig` | [REFACTORE] |
| `engine/objective_mapping.py` | 825 l. | supprimé — redondant avec `ParameterMapping` + `Objective` | [SUPPRIME] |
| `engine/output_selection.py` | 1 177 l. | supprimé — on lit le catalog via `SimulationCatalog.simulation(sim_id).timeseries(var, station)` | [SUPPRIME] |
| `engine/property_arrays.py` | 343 l. | fusionné dans `parameters/mapping.py` (mode `"field"`) | [REFACTORE] |
| `engine/reporting.py` | 344 l. | déplacé sous `display/calibration/` | [RENOMME] |
| `engine/state.py` | 25 l. | supprimé — l'état vit dans `CalibrationSession` | [SUPPRIME] |
| `analysis/diagnostics.py` + `plotting.py` + `objective_surface.py` | 1 200 l. env. | déplacés sous `display/calibration/` | [RENOMME] |
| `cases/groundwater_1d/`, `cases/recession_brutsaert/`, `cases/reservoir/` | — | `tests/validation/calibration/<case>/` | [RENOMME] |
| `devkit/` | — | supprimé — pas besoin de devkit quand le contrat est un TOML + Protocol | [SUPPRIME] |
| Table DuckDB `calibration_sessions` | 9 col. | Enrichie (16 col.) + FK status + environment | [REFACTORE] |
| Table DuckDB `calibration_iterations` | 6 col. | +sim_id FK, +status, +objective_vector, +from_cache, +components | [REFACTORE] |
| Table `calibration_iterations_params` | absente | Table longue normalisée | [NOUVEAU] |
| Table `sensitivity_sessions`, `sensitivity_indices` | absentes | Persistence SA | [NOUVEAU] |
| Table `simulation_cache` | absente | Cache content-addressable | [NOUVEAU] |
| Vue `calibration_iterations_wide` | absente | Pivot pour pandas ML | [NOUVEAU] |

**Bilan** : ≈ 10 058 l. actuelles → ≈ 3 500 l. cibles (–65 %), et une hiérarchie de 6 fichiers ≤ 400 l. chacun remplace 1 fichier de 3 409 l. + 2 fichiers > 500 l.

---

## 16. Tests de conformité

### 16.1 Tests du contrat `Optimizer`

Chaque optimiseur (built-in ou adapter) doit passer la suite `tests/unit/calibration/test_optimizer_contract.py` :

| Test | Vérifie |
|---|---|
| `test_ask_returns_n_suggestions` | `ask(n=3)` → list de 3 `ParamSuggestion` |
| `test_ask_values_in_bounds` | Tous les `values_transformed` ∈ `space.transformed_bounds` |
| `test_tell_accepts_any_status` | `tell([result_crashed, result_completed])` ne lève pas |
| `test_best_returns_minimum` | Après 20 `ask`/`tell` aléatoires, `best()` renvoie bien l'objective_value minimal |
| `test_warm_start_improves_best` | `warm_start` avec un bon historique → `best()` ≤ meilleur de l'historique après 1 ask/tell |
| `test_snapshot_round_trip` | `snapshot()` → JSON → `restore()` → même séquence d'`ask()` |
| `test_converged_eventually_true` | Sur un problème sphère 2D, 200 iters → `converged() == True` (si l'optimiseur implémente un critère) |

### 16.2 Tests du contrat `Objective`

| Test | Vérifie |
|---|---|
| `test_scalar_nse_perfect` | obs == sim ⇒ `cost == 0.0` |
| `test_scalar_weighted_mean` | Poids par station respectés |
| `test_composite_blocks_weights` | Somme pondérée correcte |
| `test_multi_vector_length` | `evaluate.vector` a la bonne dimension |
| `test_mask_nans` | NaN dans obs ou sim ⇒ ignoré, pas d'erreur |
| `test_best_possible_is_lower_bound` | Pour tous les `(obs, sim)` valides, `evaluate(...).total ≥ best_possible()` |

### 16.3 Tests intégration — calibration end-to-end

Cases hérités de `analysis/calibration/cases/` devenus tests de validation :

```
tests/validation/calibration/
├── groundwater_1d/
│   ├── test_grid_search.py             # optimizer=grid, métrique=NSE, 5 params
│   ├── test_random_search.py           # optimizer=random, seed=42, reproductible
│   ├── test_cma_es.py                  # optimizer=pycma, convergence < 1e-3 NSE
│   └── test_optuna_tpe.py              # optimizer=optuna[tpe], 200 trials
├── recession_brutsaert/
│   └── test_brutsaert_recession.py     # 2 params, convergence vers valeurs analytiques
├── reservoir/
│   └── test_two_reservoir_calibration.py
└── twin/
    ├── test_twin_exp_mf6_known_params.py        # génère synthetic obs, recalibre, vérifie r² > 0.95
    └── test_twin_exp_boussinesq_known_params.py
```

### 16.4 Tests de persistence et reprise

| Test | Vérifie |
|---|---|
| `test_session_resume_after_interrupt` | KeyboardInterrupt au trial 50 / 100 → reprise → 50 trials additionnels → total = 100 |
| `test_cache_hit_after_same_params` | 2 suggestions identiques → 1 seul `Pipeline.run()`, 1 seul `sim_id` |
| `test_parallel_determinism` | 4 workers, seed=42 → `best.objective_value` identique à 1 worker seed=42 (modulo tolérance) |
| `test_dataframe_round_trip` | `to_dataframe(sid)` puis `catalog.reinsert(df)` → même résultats |

### 16.5 Tests SALib

| Test | Vérifie |
|---|---|
| `test_sobol_indices_sum_leq_1` | $\sum_i S_1^i \leq 1$, $\sum_i S_T^i \geq 1$ |
| `test_morris_fixed_param_has_zero_mu_star` | Un paramètre figé a un $\mu^*$ nul |
| `test_persistence_sensitivity` | Les indices SALib sont relisibles depuis DuckDB |

---

## 17. Conclusion

Cette architecture remplace **10 058 lignes réparties sur 21 fichiers** par **~3 500 lignes réparties sur 25 fichiers courts**, tout en :

1. **Ouvrant l'écosystème** : n'importe quel optimiseur `ask/tell` (Optuna, pycma, scipy, PEST++, Nevergrad, DREAM, PyMC, ou un plugin tiers) s'intègre via un `Protocol` de 8 méthodes et un entry-point `hydromodpy.optimizer`.
2. **Réutilisant le pipeline standard** : plus de bypass `Simulation.run()` comme dans l'audit 06 §7.3 — chaque évaluation est une vraie simulation persistée, tracée, rejouable.
3. **Traçant intégralement** : chaque `tell` écrit dans DuckDB ; 3 tables (sessions, iterations, params) avec FK, vue `wide` pour pandas/sklearn direct.
4. **Mettant le cache au cœur** : content-addressable `params_hash → sim_id` ; deux points identiques ne sont jamais ré-exécutés.
5. **Parallélisant sans duplication** : `BatchEvaluator` distribue sur `ProcessPoolExecutor`/`dask` avec 150 lignes de code.
6. **Intégrant la sensibilité** : `SensitivityAnalyzer` partage le même `Evaluator`, ses indices vivent dans deux tables DuckDB jumelles des tables de calibration. Workflow Morris → Sobol → Calibration en 3 commandes CLI.
7. **Rendant l'analyse post-hoc triviale** : `to_dataframe(sid)` → colonnes = paramètres + métriques + statuts, prêts pour seaborn, sklearn, ou un notebook Kaggle.
8. **Respectant les 12 principes directeurs** (cf. §0) : Protocols pas ABC, 3 fichiers ≤ 350 l. par composant critique, aucun cycle d'import.

Le facteur x3 de réduction de code vient de la suppression systématique de la sur-architecture actuelle : `case_interface`, `case_orchestrator`, `output_selection` 1 177 l., `objective_mapping` 825 l., `property_arrays` 343 l., `methods_config` 522 l. — autant de couches devenues inutiles quand chaque évaluation est simplement `Pipeline.run(cfg)` + `Objective.evaluate(obs, sim)`.

**Le résultat** : un data scientist ouvre DuckDB, lance `SELECT * FROM calibration_iterations_wide WHERE session_id = '…'`, et a toutes les données — paramètres, métriques, statuts, composants — dans un DataFrame. Un modélisateur avec PEST change un flag dans le TOML et passe de CMA-ES à PEST++-IES. Un chercheur ajoute un algorithme d'optimisation en 80 lignes avec un entry-point. Aucun fichier du cœur n'a été édité.

---

**Fin du document.**
