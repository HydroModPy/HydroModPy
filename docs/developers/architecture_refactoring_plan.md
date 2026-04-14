# Plan de refactoring architectural

> Objectif : unifier les chemins d'exécution (TOML, Python, calibration) autour
> d'une interface unique (`Project`), intégrer `launchers/` dans le package
> `hydromodpy/`, et clarifier le nommage des composants internes.

## 1. Diagnostic de l'existant

### 1.1 Trois chemins d'entrée, logique dupliquée

```
TOML   ──► HydroModPyLauncher.__init__ (144L) ──► prepare_runtime ──► run_prepared
Python ──► Project.__init__ (60L)              ──► run(**overrides)
Calib  ──► ModelCalibrationLauncher            ──► HydroModPyLauncher en boucle
```

`Project.__init__` et `HydroModPyLauncher.__init__` exécutent la même séquence :

| Étape | Project | Launcher |
|-------|---------|----------|
| `HydroModPyConfig.from_toml()` | oui | oui |
| `apply_explicit_time_window_to_tgrids()` | oui | oui |
| `require_flow_simulation_time_grid()` | oui | oui |
| `DataManagersPlanner().build()` | oui | oui |
| `cfg.data.with_resolved_types()` | oui | oui |
| `WorkflowContext(cfg=..., ...)` | oui | oui |
| `prepare_simulation_runtime(ctx)` | oui | oui |

~80% de code identique. La duplication est la source directe des divergences
fonctionnelles entre les deux chemins.

### 1.2 `Project` est une version amputée du launcher

Capacités manquantes dans `Project` par rapport à `HydroModPyLauncher` :

- Pas de detection de section `[mesh_catchment]` ni `[mesh_input]`
- Pas de registre de spatial supports (`build_default_spatial_support_provider_registry`)
- Pas de `PostprocessRunner`
- Pas de support transport (plan inline mono-ProcessRun, flow uniquement)
- Pas de multi-process (`SimulationPlanner` non utilisé)
- Pas de `domain_support_provider_names` dans le data plan

Le prototypage Python est donc fonctionnellement inférieur au mode TOML, alors
que l'utilisateur attend l'inverse (plus de flexibilité, pas moins).

### 1.3 `launchers/` est hors du package

`launchers/` est un package racine séparé de `hydromodpy/`. Pourtant :

- `hydromodpy/__main__.py` fait `from launchers import HydroModPyLauncher`
- `hydromodpy/workflow/pipelines/simulation.py` fait
  `from launchers.mesh_catchment.config import MeshCatchmentConfigSchema` (en TYPE_CHECKING)
- Les deux packages partagent les mêmes dépendances internes
- Ils ne sont jamais distribués séparément

La frontière est artificielle. Un `pip install hydromodpy` devrait inclure
l'ensemble du code exécutable.

### 1.4 Le mot "prototype" a deux sens

| Localisation | Signification réelle |
|---|---|
| `process/prototype/` | ABC et modèles de base (interfaces abstraites) |
| `solver/prototype/` | ABC et enum (interfaces abstraites) |
| `run_transient_prototype.py` | Script Python interactif (mode prototypage) |
| Docstring de `Project` | "programmatic equivalent" du launcher |

Un contributeur qui cherche "le code de prototypage" ne sait pas s'il doit
regarder les ABC ou la classe `Project`.

### 1.5 Asymétrie entre launchers

| Launcher | launcher.py | Modules aux. | Fichier le plus lourd |
|---|---|---|---|
| `process_simulation` | 243L | 0 | launcher.py (243L) |
| `data_overview` | 235L | 4 | launcher.py (235L) |
| `mesh_catchment` | 150L | 7 | config.py (800L) |
| `method_comparison` | 400L | 7 | visuals.py (2000L) |
| `model_calibration` | 270L | 10 | runtime.py (3467L) |
| `regional_lab` | 1828L | 3 | launcher.py (1828L) |

`process_simulation` a été refactoré : coquille mince qui délègue à
`workflow/`. Tous les autres restent monolithiques et mélangent orchestration
CLI et logique domaine.

### 1.6 Deux CLIs redondants

- `hydromodpy/__main__.py` : CLI principal (`hmp run`, `hmp overview`, etc.)
- `launchers/__main__.py` (611L) : CLI secondaire (`python -m launchers simulation`, etc.)

Les deux routes mènent aux mêmes classes. Le second est un doublon à supprimer.

### 1.7 Ce qui fonctionne bien

- `workflow/` (steps + pipelines) : la décomposition en étapes atomiques et
  pipelines composables est propre. `prepare_simulation_runtime()` et
  `execute_simulation()` servent déjà les deux chemins.
- `simulation/` (planning/execution/adapters) : excellente séparation entre
  le plan déclaratif immutable (`SimulationPlan`, frozen), l'exécution stateful
  (`SimulationRunner`), et les adapters par Protocol (`SolverAdapter`).
- `process/prototype/` et `solver/prototype/` : pattern ABC solide avec
  normalizers cohérents. Seul le nommage pose problème.
- `Project.run()` : le pattern setup-once/run-many avec `SimulationResult`
  (.field(), .timeseries(), .budget(), .export()) est la bonne interface pour
  le prototypage scientifique.
- `WorkflowContext` : extension naturelle de `LauncherRunState` avec store
  intégré, trois scopes bien définis (setup/loaded_data/execution).


## 2. Principe directeur : un `hmp run` est un `Project.run()` sans overrides

Un run TOML n'est qu'un cas particulier de l'API Python :

```python
# Ce que fait `hmp run config.toml` en réalité
project = Project("config.toml")
project.run()
project.close()
```

Conséquence : `Project` doit être l'unique interface de simulation.
Le runner CLI devient un one-liner qui crée un `Project`, appelle `run()`, et
ferme. Plus de `HydroModPyLauncher` comme classe séparée.

Ce même principe s'applique à la calibration :

```python
# Ce que fait `hmp calibrate config.toml` en réalité
project = Project("base_config.toml")
for params in optimizer:
    result = project.run(K=params["K"], Sy=params["Sy"])
    score = evaluate(result)
project.close()
```

Le calibrateur n'a pas besoin d'un launcher dédié. Il a besoin d'un `Project`
avec `run(**overrides)`.


## 3. Orchestration TOML : `hmp run` unique, le TOML décide

### 3.1 Commande unique : `hmp run config.toml`

En logiciel scientifique, le pattern standard est : **une commande, le config
détermine le workflow** (MODFLOW 6 avec `mf6`, OpenFOAM avec `foamRun`,
PEST++ avec `pestpp-ies`). L'utilisateur ne devrait pas avoir à mémoriser
quelle commande correspond à quel type de TOML.

HydroModPy adopte ce pattern :

```bash
hmp run config.toml           # le TOML détermine le workflow
hmp run script.py             # exécute un script Python (prototypage)
```

C'est la seule commande d'exécution. Pas de `hmp overview`, `hmp mesh`,
`hmp calibrate`, `hmp compare`, `hmp batch`. Pas de rétrocompatibilité
avec les anciennes commandes : on nettoie tout.

### 3.2 Auto-détection du workflow depuis le TOML

Le contenu du TOML suffit à déterminer le workflow. Tous les workflows
directs utilisent un seul modèle Pydantic (`HydroModPyConfig`) avec des
sections optionnelles :

| Section discriminante | Workflow | Ce qu'il fait |
|---|---|---|
| `[calibration]` | Calibration | `Project.run()` en boucle d'optimisation |
| `[batch]` | Batch régional | `Project` par site × recette |
| `[overview]` (sans `[simulation]`) | Overview | Setup → geographic → data → report |
| `[mesh_catchment]` (sans `[simulation]`) | Mesh-only | Setup → geographic → mesh |
| `[simulation]` ou `[flow]` (défaut) | Simulation | `Project.run()` single-shot |

La détection est un simple parcours de clés :

```python
def detect_workflow(raw_toml: dict) -> str:
    """Determine workflow type from top-level TOML sections."""
    if "calibration" in raw_toml:
        return "calibration"
    if "batch" in raw_toml:
        return "batch"
    if "overview" in raw_toml and "simulation" not in raw_toml:
        return "overview"
    if "mesh_catchment" in raw_toml and "simulation" not in raw_toml:
        return "mesh"
    return "simulation"
```

L'ordre de priorité gère les cas ambigus :
- `[mesh_catchment]` + `[simulation]` → simulation (le mesh est un input)
- `[mesh_catchment]` seul → mesh-only workflow
- `[overview]` seul → overview
- `[calibration]` + `[simulation]` + `[flow]` → calibration (la simulation
  est le socle, la calibration est le mode d'exécution)

### 3.3 Tout dans un seul TOML

`HydroModPyConfig` est le seul modèle de configuration. Toutes les sections
sont optionnelles sauf `[workspace]` et `[geographic]`. Le workflow est
déterminé par les sections présentes.

```python
class HydroModPyConfig(BaseModel):
    # Commun à tous les workflows
    workspace: WorkspaceConfig
    geographic: GeographicConfig
    data: DataManagersConfig | None = None
    domain: DomainConfig | None = None

    # Simulation
    flow: FlowConfig | None = None
    transport: TransportConfig | None = None
    simulation: SimulationConfig | None = None
    solver: SolverConfig | None = None
    modflownwt: ModflowNwtConfig | None = None
    modflow6: Modflow6Config | None = None

    # Modes d'exécution (mutuellement exclusifs avec overview/mesh-only)
    calibration: CalibrationSection | None = None
    batch: BatchSection | None = None

    # Workflows légers (sans simulation)
    overview: OverviewSection | None = None
    mesh_catchment: MeshCatchmentConfig | None = None

    # Post-traitement
    postprocess: PostprocessConfig | None = None
    display: DisplayConfig | None = None
```

La calibration n'est pas un workflow séparé avec sa propre config et son
propre TOML : c'est un **mode d'exécution** de la même simulation. Le
TOML contient la simulation complète (`[workspace]`, `[geographic]`,
`[flow]`, `[simulation]`) plus `[calibration]` qui dit "fais varier ces
paramètres".

### 3.4 La comparaison n'est pas un workflow

La comparaison opère sur des résultats **déjà calculés**. Ce n'est pas un
workflow d'exécution, c'est de l'analyse post-hoc.

L'utilisateur lance ses simulations indépendamment :

```bash
hmp run run_nwt.toml       # résultat stocké dans project.duckdb
hmp run run_mf6.toml       # résultat stocké dans project.duckdb
```

Puis compare depuis la base de données :

```bash
hmp display compare --sim nwt_run --sim mf6_run
```

Ou depuis Python :

```python
project = hmp.Project("project.toml")
r1 = project.run(name="nwt", solver="modflownwt")
r2 = project.run(name="mf6", solver="modflow6")

wt_nwt = r1.field("watertable_elevation", timestep=-1)
wt_mf6 = r2.field("watertable_elevation", timestep=-1)
diff = wt_mf6 - wt_nwt
```

Ce qui existait comme workflow comparison (métriques, visuals, exports,
reporting) reste dans `analysis/comparison/` mais est appelé par
`hmp display compare` ou depuis Python, pas par un runner de workflow.

Cela élimine :
- `MethodComparisonConfig` (classe entière)
- `runners/comparison.py` (runner)
- `[method_comparison]` dans `detect_workflow()`
- `[comparison]` dans `HydroModPyConfig`
- Le concept de "variant loop" comme workflow

### 3.5 Vue d'ensemble

```
                    hmp run config.toml
                            │
                     detect_workflow(raw_toml)
                            │
      ┌─────────────┬───────┼────────┬───────────┐
      │             │       │        │           │
   overview      mesh   simulation calibration  batch
      │             │       │        │           │
      ▼             ▼       ▼        ▼           ▼
   pipeline     pipeline  Project  Project×N   Project×S×R
      │             │       │       (optim)     (sites)
      ▼             ▼       ▼        │           │
      └─────────────┴───────┴────────┴───────────┘
                   HydroModPyConfig
                (sections optionnelles)

    hmp display compare --sim A --sim B
                            │
                    analysis/comparison/
                            │
                     lecture ResultStore
```

### 3.6 Pas de rétrocompatibilité

Les anciennes commandes (`hmp overview`, `hmp mesh`, `hmp calibrate`,
`hmp compare`, `hmp simulation`) sont supprimées. Pas d'alias, pas de
message de dépréciation. Le CLI :

```
hmp init [--path PATH]              # workspace
hmp new <project>                   # créer projet
hmp config [output.toml]            # template TOML
hmp run <config.toml | script.py>   # exécuter (auto-detect workflow)
hmp display <config.toml>           # figures post-hoc
hmp display compare --sim A --sim B # comparaison post-hoc
hmp list [project]                  # inventaire
hmp export <project>                # export résultats
hmp test <suite>                    # tests
```

### 3.7 Notes sur la structure du bloc `[simulation]`

La structure actuelle du bloc d'orchestration :

```toml
[simulation]
name = "..."

[simulation.time]
start_datetime = "2003-01-01"
end_datetime = "2003-03-31"
step_value = "30 day"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflownwt"]

[[simulation.process]]
id = "transport_main"
type = "transport"
solvers = ["modpath", "mt3dms"]
```

**Points à améliorer à terme** (pas bloquants pour le refactoring, mais à
noter pour une v2 du format) :

1. **`[[simulation.process]]` est un array alors qu'il y a au maximum un
   process par type** (contrainte `_validate_unique_process_types`). Un dict
   serait plus honnête :
   ```toml
   # Alternative : dict au lieu d'array-of-tables
   [simulation.flow]
   solvers = ["modflownwt"]
   [simulation.transport]
   solvers = ["modpath", "mt3dms"]
   ```

2. **Le champ `id` est redondant** quand il n'y a qu'un process par type.
   `"flow_main"` n'apporte rien quand `type = "flow"` suffit à identifier.

3. **Les solvers sont déclarés dans `[simulation]` mais configurés dans des
   sections top-level séparées** (`[modflownwt]`, `[modflow6]`). Ça crée
   de la distance entre déclaration et configuration.

4. **La fenêtre temporelle est dans `[simulation.time]` mais aussi dans
   `[overview]` et `[data.recharge]`**. Trois endroits pour dire
   "de quand à quand".

Ces points sont des améliorations de format TOML, indépendantes du
refactoring architectural. Ils seront traités séparément.

### 3.8 Exemples de TOML par workflow

**Simulation**
```toml
base_config = "project.toml"

[[simulation.process]]
type = "flow"
solvers = ["modflownwt"]

[simulation.time]
start_datetime = "2003-01-01"
end_datetime = "2003-03-31"
step_value = "30 day"

[simulation.results.derived]
accumulation_flux = true
outflow_drain = true
```

**Overview** — exploration data-only, pas de simulation
```toml
[workspace]
project_root = "."

[geographic]
dem_init_path = "data/dem.tif"
x_outlet = 350000
y_outlet = 6200000

[data]
types = ["hydrometry", "piezometry", "geology"]

[overview]
name = "Bassin du Nancon"
date_start = "2000-01-01"
date_end = "2025-12-31"

[overview.panels]
map_dem = true
timeseries_discharge = true
climatic_summary = true
```

**Mesh-only** — maillage sans simulation
```toml
[workspace]
project_root = "."

[geographic]
dem_init_path = "data/dem.tif"
x_outlet = 350000
y_outlet = 6200000

[mesh_catchment]
constraints_mode = "geology_rivers"

[mesh_catchment.zone_meshing]
element_size_m = 200.0
```

**Calibration** — simulation complète + boucle d'optimisation dans un seul TOML
```toml
base_config = "project.toml"

[[simulation.process]]
type = "flow"
solvers = ["modflownwt"]

[simulation.time]
start_datetime = "2003-01-01"
end_datetime = "2005-12-31"
step_value = "1 month"

[calibration]
method = "scipy_differential_evolution"

[[calibration.parameter]]
name = "K"
target = "flow.param.K"
bounds = [1e-6, 1e-3]

[[calibration.parameter]]
name = "Sy"
target = "flow.param.Sy"
bounds = [0.001, 0.30]

[calibration.objective]
metric = "nse"
observed_variable = "outflow_drain"
observed_station = "J736422001"
```

**Batch régional** — simulation × N sites, référence un template externe
(nécessaire car chaque site a un geographic différent)
```toml
[batch]
catalog = "sites_catalog.csv"
output_root = "batch_results"

[[batch.recipe]]
id = "baseline_nwt"
config_template = "template_nwt.toml"
```


## 4. Architecture cible

### 4.1 Config unifiée : `HydroModPyConfig` avec sections optionnelles

Overview et mesh-only ne sont pas des workflows indépendants — ce sont des
**sous-ensembles de la simulation**. Ils partagent `[workspace]`,
`[geographic]`, `[data]` avec le workflow de simulation. Créer des modèles
Pydantic séparés (`DataOverviewConfig`, `MeshCatchmentConfigSchema`) a
forcé à dupliquer la logique de chargement de ces sections.

La cible : **un seul modèle de config** avec des sections optionnelles.

```python
class HydroModPyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Commun à tous les workflows
    workspace: WorkspaceConfig
    geographic: GeographicConfig
    data: DataManagersConfig = Field(default_factory=DataManagersConfig)
    domain: DomainConfig = Field(default_factory=DomainConfig)

    # Simulation (absent pour overview et mesh-only)
    flow: FlowConfig | None = None
    transport: TransportConfig | None = None
    simulation: SimulationConfig | None = None
    solver: SolverConfig | None = None
    modflownwt: ModflowNwtConfig | None = None
    modflow6: Modflow6Config | None = None

    # Modes d'exécution avancés (sections optionnelles)
    calibration: CalibrationSection | None = None
    batch: BatchSection | None = None

    # Workflows légers (sans simulation)
    overview: OverviewSection | None = None
    mesh_catchment: MeshCatchmentConfig | None = None

    # Post-traitement
    postprocess: PostprocessConfig | None = None
    display: DisplayConfig | None = None
```

`detect_workflow()` utilise les sections présentes :
- `overview` sans `simulation` → overview pipeline
- `mesh_catchment` sans `simulation` → mesh-only pipeline
- `simulation` ou `flow` → simulation via `Project`

Les **méta-workflows** (calibration, comparaison, batch) gardent des configs
propres parce qu'ils référencent d'autres TOMLs. Leur structure est
fondamentalement différente : un TOML de calibration ne décrit pas une
simulation, il décrit une campagne qui pointe vers un TOML de simulation.

Cela donne **deux catégories** au lieu de trois :
- **Workflows directs** : `HydroModPyConfig` (simulation, overview, mesh-only)
- **Méta-workflows** : configs propres (calibration, comparison, batch)

### 4.2 Arborescence du package

```
hydromodpy/
  __init__.py                            # API publique (lazy imports)
  __main__.py                            # CLI unique (hmp run = auto-detect)
  project.py                             # Interface simulation (setup-once, run-many)

  core/                                  # Infrastructure
    config/
      hydromodpy_config.py               #   HydroModPyConfig (UNIFIÉ, sections optionnelles)
      toml_loader.py                     #   base_config inheritance
      generate_toml.py                   #   template TOML generation
    state/                               #   SetupContext, LoadedDataContext, ExecutionRegistry
    workspace/
    time/
    tools/
    units/

  data/                                  # Données d'entrée
    registry/
    variables/
    common/

  spatial/                               # Domaine spatial
    geographic/
    domain/
    field/
    mesh/
      config.py                          #   ← MeshCatchmentConfig (depuis launchers)

  process/
    base/                                # ← renommé depuis prototype/
      process_spatial.py                 #   ABC ProcessSpatial[T]
      process_spatial_config.py          #   ProcessSpatialConfig
      initial_conditions.py              #   InitialCondition
      boundary_conditions.py             #   BoundaryCondition
      sinks_sources.py                   #   SinkSource
      *_config.py                        #   normalizers
    flow/
    transport/

  solver/
    base/                                # ← renommé depuis prototype/
      solver.py                          #   ABC Solver
      solver_config.py                   #   SolverConfig
      solver_engine.py                   #   SolverEngine enum
    modflow6/
    modflow_nwt/
    boussinesq/
    utils/

  simulation/                            # Planning + exécution
    planning/
      config.py                          #   SimulationConfig, SimulationProcessConfig
      planner.py                         #   SimulationPlanner
      plan.py                            #   SimulationPlan, ProcessRun (frozen)
    execution/
      runner.py                          #   SimulationRunner, ProcessCallbacks
    adapters/
      base.py                            #   SolverAdapter Protocol
      registry.py                        #   get_solver_adapter(), register_adapter()
      flow/                              #   Modflow6FlowAdapter, BoussinesqFlowAdapter, ...
      transport/                         #   ModpathAdapter, Mt3dmsAdapter, ...
    results/
      extractors/
      post_run.py
    forcing/

  workflow/                              # Couche pipeline composable
    __init__.py                          #   exporte WorkflowContext
    context.py                           #   WorkflowContext (@dataclass)
    steps/                               # Étapes atomiques (ctx → mutation)
      setup.py
      data_loading.py
      mesh.py
      spatial_supports.py
      store_lifecycle.py                 #   step_open_store() idempotent
      result_ingestion.py
    pipelines/                           # Séquences composées de steps
      simulation.py                      #   prepare + execute (existe)
      overview.py                        #   setup → geographic → data → report
      mesh.py                            #   setup → geographic → mesh

  results/                               # ResultStore, schéma, exporteurs
    store.py
    schema.py
    config.py
    exporters/

  analysis/                              # Post-traitement et analyse
    calibration/
      core/                              #   engine_config, objective_function (existe)
      engine/                            #   ← logique depuis launchers/model_calibration/
        session.py                       #     PreparedCalibrationSession, CandidateRunRequest
        objective_mapping.py             #     run_objective_mapping
        output_selection.py              #     CanonicalOutputVariable
        property_arrays.py               #     HydraulicPropertyArray, PropertyArraySet
        reporting.py                     #     build_calibration_report
    comparison/                          #   Analyse post-hoc (pas un workflow)
      metrics.py                         #     build_comparison_metrics
      visuals.py                         #     generate_comparison_figures
      exports.py                         #     write_comparison_exports
      reporting.py                       #     build_comparison_report
    batch/                               #   ← logique depuis launchers/regional_lab/
      runtime.py                         #     run_regional_batch
      bootstrap.py                       #     build_site_catalog_from_outlet_table
    display/
      report/
        overview_config.py               #   OverviewSection, OverviewPanelsConfig
        overview_report.py               #   generate_overview_report
      compare.py                         #   CLI hmp display compare → analysis/comparison/
    postprocess/

  runners/                               # Coquilles CLI minces
    __init__.py                          #   detect_workflow(), dispatch
    simulation.py                        #   ~30L, wrapper autour de Project
    overview.py                          #   ~50L, coquille → workflow/pipelines/overview
    mesh.py                              #   ~80L, coquille + batch
    calibration.py                       #   ~80L, coquille → analysis/calibration/engine/
    batch.py                             #   ~100L, coquille → analysis/batch/
    templates/                           #   générateurs TOML consolidés
```

### 4.3 Ce qui disparaît

| Composant actuel | Raison de suppression |
|---|---|
| `launchers/` (package racine entier) | Intégré dans `hydromodpy/runners/` et `analysis/` |
| `DataOverviewConfig` (classe séparée) | `[overview]` intégré comme section optionnelle de `HydroModPyConfig` |
| `MeshCatchmentConfigSchema` (dans launchers) | Déplacé dans `spatial/mesh/config.py`, référencé par `HydroModPyConfig` |
| `ModelCalibrationConfig` (classe séparée) | `[calibration]` intégré comme section optionnelle de `HydroModPyConfig` |
| `MethodComparisonConfig` (classe entière) | Supprimé — la comparaison est de l'analyse post-hoc, pas un workflow |
| `runners/comparison.py` | Supprimé — la comparaison passe par `hmp display compare` |
| `HydroModPyLauncher` (classe) | Remplacé par `Project` |
| `LauncherRunState` (classe) | Remplacé par `WorkflowContext` |
| `process/prototype/` | Renommé `process/base/` |
| `solver/prototype/` | Renommé `solver/base/` |
| `domain/`, `field/`, `mesh/`, `postprocess/`, `modeling/` (facades) | Supprimées |
| `hmp overview`, `hmp mesh`, `hmp calibrate`, `hmp compare` (commandes CLI) | Supprimées, `hmp run` auto-détecte |

### 4.4 Ce qui ne change pas

- `project.py` : API publique (`hmp.Project`, `.run()`, `.close()`)
- `simulation/` : planning, execution, adapters
- `workflow/steps/` : étapes atomiques
- `workflow/pipelines/simulation.py` : pipeline de simulation existant
- `core/`, `data/`, `spatial/`, `results/` : stables
- `hydromodpy_annex/` : package périphérique, dépendance unidirectionnelle


## 5. `Project` : l'interface unique de simulation

### 5.1 Responsabilités actuelles vs cibles

| Responsabilité | Actuel (`Project`) | Actuel (`Launcher`) | Cible (`Project`) |
|---|---|---|---|
| Parse TOML → config | oui | oui | oui |
| Time grid | oui | oui | oui |
| Data plan | oui (simplifié) | oui (complet) | oui (complet) |
| Mesh section detection | non | oui | oui |
| Spatial supports | non | oui | oui |
| PostprocessRunner | non | oui | oui |
| Transport | non | oui | oui |
| Multi-process plan | non | oui | oui |
| Parameter overrides | oui | non | oui |
| Run-many pattern | oui | non | oui |
| `SimulationResult` API | oui | non (retourne `WorkflowContext`) | oui |
| Store lifecycle | ouvert au `__init__` | ouvert/fermé par pipeline | ouvert au `__init__` |

### 5.2 API publique cible

```python
class Project:
    """Setup-once, run-many interface for HydroModPy simulations.

    Sert les trois modes d'utilisation :
    - Python interactif (prototypage, sensibilité, debug)
    - CLI single-shot (hmp run config.toml)
    - Calibration (run en boucle avec overrides)

    Parameters
    ----------
    config_path : str or Path
        Path to a project/run TOML file.
    solver : str, optional
        Flow solver override. Auto-detected from TOML if absent.

    Examples
    --------
    ::

        import hydromodpy as hmp

        # Interactive usage
        project = hmp.Project("project.toml")
        r = project.run(Sy=0.05, K=5e-5, name="baseline")
        wt = r.field("watertable_depth", timestep=12)
        project.close()

        # Context manager
        with hmp.Project("project.toml") as project:
            for sy in [0.001, 0.05, 0.30]:
                r = project.run(Sy=sy, name=f"sy_{sy}")

        # CLI equivalent (single-shot)
        project = hmp.Project("run_config.toml")
        project.run()
        project.close()
    """

    def __init__(self, config_path: str | Path, *, solver: str | None = None) -> None:
        ...

    def run(self, *, name: str | None = None, **overrides) -> SimulationResult:
        """Execute one simulation with optional parameter overrides.

        Without overrides, runs the TOML configuration as-is (equivalent to
        hmp run config.toml).

        Parameters
        ----------
        name : str, optional
            Run name. Auto-generated if absent.
        **overrides
            Parameter overrides: Sy, K, Ss, thickness, first_clim, etc.

        Returns
        -------
        SimulationResult
            Read-only view on the run's results.
        """
        ...

    @property
    def geographic(self): ...
    @property
    def domain(self): ...
    @property
    def store(self) -> ResultStore: ...
    @property
    def time_grid(self): ...
    @property
    def data(self) -> LoadedDataContext: ...

    def close(self) -> None: ...
    def __enter__(self): return self
    def __exit__(self, *exc): self.close()
```

### 5.3 `SimulationResult` (inchangé)

```python
class SimulationResult:
    """Read-only view on one simulation's results."""

    sim_id: str
    name: str

    def field(self, variable: str, timestep: int, layer: int | None = None) -> np.ndarray: ...
    def timeseries(self, variable: str, station: str = "_catchment", period=None) -> pd.Series: ...
    def budget(self, zone_id: int | None = None, period=None) -> pd.DataFrame: ...
    def export(self, variable: str = "*", fmt: str = "csv", path=None, **kwargs) -> None: ...
```

### 5.4 Ce que `Project.__init__` doit récupérer du launcher

Concrètement, l'`__init__` de `Project` doit intégrer les étapes que seul
`HydroModPyLauncher` fait aujourd'hui :

```python
def __init__(self, config_path, *, solver=None):
    # 1. Config (identique)
    self.cfg = HydroModPyConfig.from_toml(config_path)
    raw_toml = load_toml_with_base_config(config_path)

    # 2. Solver detection (identique)
    self._solver = solver or self._detect_solver()
    self._ensure_simulation_block()

    # 3. Time grid (identique)
    apply_explicit_time_window_to_tgrids(self.cfg)
    self._time_grid = require_flow_simulation_time_grid(self.cfg)

    # 4. Mesh section detection (NOUVEAU dans Project)
    self._mesh_section_data = resolve_optional_mesh_section(raw_toml)
    self._external_mesh_input = resolve_optional_mesh_input(raw_toml, config_path)
    # ... validation mutuelle, prepare_geographic_config_for_meshing

    # 5. Spatial supports (NOUVEAU dans Project)
    self._spatial_support_registry = build_default_spatial_support_provider_registry()
    self._requested_support_ids = collect_requested_support_ids(self.cfg.flow)
    self._requested_domain_supports = resolve_support_configs(
        self.cfg.domain, self._requested_support_ids,
    )

    # 6. Data plan (ENRICHI : ajouter domain_support_provider_names)
    data_plan = DataManagersPlanner().build(
        self.cfg.data,
        domain_zone_ids=self.cfg.domain.zone_ids,
        domain_support_provider_names=support_provider_names(self._requested_domain_supports),
        requested_spatial_support_ids=self._requested_support_ids,
        raw_toml=raw_toml,
        flow_active_bc=self.cfg.flow.active_bc,
    )

    # 7. WorkflowContext + preparation pipeline (enrichi avec mesh + supports)
    self._ctx = WorkflowContext(cfg=self.cfg, config_path=config_path, raw_toml=raw_toml)
    self._ctx.data_plan = data_plan
    self._ctx.setup.time_grid = self._time_grid

    prepare_simulation_runtime(
        self._ctx,
        mesh_section_data=self._mesh_section_data,
        constraints_mode=self._mesh_constraints_mode,
        external_mesh_input=self._external_mesh_input,
        requested_domain_supports=self._requested_domain_supports,
        spatial_support_registry=self._spatial_support_registry,
        requested_spatial_support_ids=self._requested_support_ids,
    )

    # 8. PostprocessRunner (NOUVEAU dans Project)
    self._postprocess_runner = PostprocessRunner(self.cfg.postprocess)
    self._ctx.postprocess_runner = self._postprocess_runner

    # 9. Store (identique)
    self._store = ResultStore(project_path=..., workspace_path=...)
    persist_geographic_to_store(self.geographic, self._store)
```

### 5.5 `Project.run()` enrichi

La méthode `run()` doit aussi évoluer pour supporter le multi-process :

```python
def run(self, *, name=None, **overrides):
    # Si des overrides sont fournis : construire un Flow frais + appliquer
    # Si aucun override : utiliser SimulationPlanner pour le plan complet

    if overrides:
        # Mode prototypage : plan minimal, overrides appliqués
        flow = Flow(config=self.cfg.flow)
        for key, value in overrides.items():
            flow.parameters[key].value = value
        plan = self._build_minimal_plan()
    else:
        # Mode TOML pur : plan complet via SimulationPlanner
        plan = SimulationPlanner().build(self.cfg.simulation)

    # Exécution commune
    self._ctx.execution.simulation_plan = plan
    SimulationRunner(...).execute(plan, self._ctx)
    # ... ingestion, finalisation
    return SimulationResult(sim_id, name, self._store)
```


## 6. `runners/` : coquilles CLI minces

### 6.1 Principe

Chaque runner fait exactement trois choses :
1. Charger et valider le TOML
2. Instancier l'objet approprié (`Project`, ou une pipeline dédiée)
3. Appeler `.run()` et remonter le résultat au CLI

Si un fichier runner dépasse ~150 lignes, de la logique domaine y a été
mélangée et doit être extraite.

### 6.2 `runners/simulation.py`

```python
"""CLI adapter for hmp run <config.toml>."""

from pathlib import Path
from hydromodpy.project import Project


def run_simulation(config_path: str | Path) -> dict:
    """Execute a single simulation from a TOML file.

    This is the CLI entry point for `hmp run config.toml`.
    It creates a Project, runs once (no overrides), and closes.
    """
    with Project(config_path) as project:
        result = project.run()
        return {
            "name": result.name,
            "sim_id": result.sim_id,
        }
```

~15 lignes. Tout le reste vit dans `Project` et `workflow/`.

### 6.3 `runners/overview.py`

```python
"""CLI adapter for hmp overview <config.toml>."""

from pathlib import Path
from hydromodpy.workflow.pipelines.overview import run_overview_pipeline


def run_overview(config_path: str | Path) -> dict:
    """Generate a watershed identity card from a TOML file."""
    config = DataOverviewConfig.from_toml(config_path)
    return run_overview_pipeline(config, config_path)
```

La logique actuelle de `DataOverviewLauncher` (4 phases : workspace, DEM
bootstrap, geographic, report) devient `workflow/pipelines/overview.py`.

### 6.4 `runners/mesh.py`

```python
"""CLI adapter for hmp mesh <config.toml>."""

from pathlib import Path
from hydromodpy.workflow.pipelines.mesh import run_mesh_pipeline


def run_mesh(config_path: str | Path) -> dict:
    """Generate a catchment mesh from a TOML file."""
    config = MeshConfig.from_toml(config_path)
    return run_mesh_pipeline(config, config_path)
```

La logique actuelle de `MeshCatchmentLauncher` (single + batch) devient
`workflow/pipelines/mesh.py`. La config Pydantic (800L) reste dans
`runners/mesh_config.py` ou migre dans `spatial/mesh/config.py`.

### 6.5 `runners/calibration.py`

```python
"""Runner for calibration workflow (detect_workflow → 'calibration')."""

from pathlib import Path
from hydromodpy.analysis.calibration.engine.session import (
    prepare_calibration_session,
    run_calibration_loop,
)


def run_calibration(config_path: str | Path) -> dict:
    """Run a parameter calibration campaign from a TOML file."""
    session = prepare_calibration_session(config_path)
    return run_calibration_loop(session)
```

La logique actuelle de `model_calibration/runtime.py` (3467L) est déplacée
dans `analysis/calibration/engine/`. Le runner ne fait que wirer le TOML vers
le moteur.

### 6.6 `runners/comparison.py`

```python
"""CLI adapter for hmp compare <config.toml>."""

from pathlib import Path
from hydromodpy.analysis.comparison.runtime import run_method_comparison


def run_comparison(config_path: str | Path) -> dict:
    """Run a solver/mesh method comparison from a TOML file."""
    return run_method_comparison(config_path)
```

La logique actuelle de `method_comparison/{runtime,metrics,visuals,exports}.py`
(~5800L) est déplacée dans `analysis/comparison/`.

### 6.7 `runners/batch.py`

```python
"""CLI adapter for hmp batch <config.toml>."""

from pathlib import Path
from hydromodpy.analysis.batch.runtime import run_regional_batch


def run_batch(config_path: str | Path) -> dict:
    """Run a multi-site batch campaign from a TOML file."""
    return run_regional_batch(config_path)
```

La logique actuelle de `regional_lab/launcher.py` (1828L) est déplacée dans
`analysis/batch/`.

### 6.8 `runners/templates/`

Les générateurs TOML sont consolidés dans un sous-package dédié, un fichier par
type de runner :

```
runners/templates/
  __init__.py
  simulation.py         # render_simulation_template()
  overview.py           # render_overview_template()
  mesh.py               # render_mesh_template()
  calibration.py        # render_calibration_template()
  comparison.py         # render_comparison_template()
  batch.py              # render_batch_template()
```

Chaque template renderer est invoqué par la commande `hmp config --type <X>`.


## 7. `workflow/` : la couche pipeline composable

### 7.1 Steps atomiques (existants, inchangés)

Chaque step est une fonction `(ctx: WorkflowContext) -> None` qui mute le
contexte. Pas de retour, pas de connaissance du pipeline englobant.

```
workflow/steps/
  setup.py              # workspace, geographic, domain, flow, transport
  data_loading.py       # external forcings (DEM, recharge, géologie, etc.)
  mesh.py               # Gmsh ou external mesh loading
  spatial_supports.py   # registre des spatial supports
  store_lifecycle.py    # open_store(), finalize_store()
  result_ingestion.py   # post_run_results(), save_run_artifacts()
```

### 7.2 Pipelines (à compléter)

```
workflow/pipelines/
  simulation.py         # EXISTE : prepare_simulation_runtime + execute_simulation
  overview.py           # NOUVEAU : setup → DEM bootstrap → geographic → data → report
  mesh.py               # NOUVEAU : setup → geographic → mesh (+ batch)
```

Les pipelines de calibration et comparaison ne sont pas dans `workflow/`
car ils ne composent pas des steps atomiques simples : ils orchestrent des
boucles multi-run. Leur logique vit dans `analysis/calibration/` et
`analysis/comparison/`.

### 7.3 `WorkflowContext`

```python
@dataclass
class WorkflowContext:
    cfg: HydroModPyConfig
    config_path: Path
    raw_toml: dict[str, Any] = field(default_factory=dict)
    data_plan: DataLoadPlan | None = None

    setup: SetupContext = field(default_factory=SetupContext)
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)

    store: ResultStore | None = None
    sim_id: str | None = None
    postprocess_runner: Any = None
```

`LauncherRunState` devient un alias de `WorkflowContext` pendant la migration,
puis est supprimé.


## 8. Renommage `prototype/` → `base/`

### 8.1 Pourquoi `base/`

Le nom `base/` est la convention Python standard pour les classes de base :
- `collections.abc` (Abstract Base Classes)
- `logging.handlers` (base Handler)
- `pydantic.BaseModel`
- `django.db.models.base`

Il n'y a aucune ambiguïté : `process/base/` contient les classes de base des
processus. `solver/base/` contient les classes de base des solveurs.

### 8.2 Contenu (identique, seul le nom change)

```
process/base/
  __init__.py                   # exporte ProcessSpatial, ProcessSpatialConfig, etc.
  process_spatial.py            # ABC ProcessSpatial[TInitialConditions]
  process_spatial_config.py     # ProcessSpatialConfig(BaseModel)
  initial_conditions.py         # InitialCondition(BaseModel)
  boundary_conditions.py        # BoundaryCondition(BaseModel)
  sinks_sources.py              # SinkSource(BaseModel)
  initial_conditions_config.py  # normalize_initial_condition_payload()
  boundary_conditions_config.py # normalize_boundary_condition_payload()
  sinks_sources_config.py       # normalize_sink_source_payload()

solver/base/
  __init__.py                   # exporte Solver, SolverConfig, SolverEngine
  solver.py                     # ABC Solver (pre_processing, processing, post_processing)
  solver_config.py              # SolverConfig(BaseModel)
  solver_engine.py              # SolverEngine(str, Enum)
```

### 8.3 Pas de rétrocompatibilité pour `prototype/`

Le renommage est direct. Pas de réexport temporaire, pas d'alias. Tous les
imports internes sont migrés d'un coup :

```python
# Avant
from hydromodpy.process.prototype import ProcessSpatial
from hydromodpy.solver.prototype import Solver

# Après
from hydromodpy.process.base import ProcessSpatial
from hydromodpy.solver.base import Solver
```

Le dossier `prototype/` est supprimé entièrement.


## 9. CLI unique

### 9.1 Principe : pas de rétrocompatibilité

Les anciennes commandes (`hmp overview`, `hmp mesh`, `hmp calibrate`,
`hmp compare`, `hmp simulation`) sont supprimées. Pas d'alias, pas de
message de dépréciation, pas de redirection. Le CLI `launchers/__main__.py`
(611L) est supprimé. Le hidden alias `hmp simulation` est supprimé.

On ne garde que le strict nécessaire.

### 9.2 Commandes

```
hmp init [--path PATH]                    # workspace
hmp new <project>                         # créer projet
hmp config [output.toml]                  # template TOML
hmp run <config.toml | script.py>         # exécuter (auto-detect workflow)
hmp display <config.toml>                 # figures post-hoc d'une simulation
hmp display compare --sim A --sim B       # comparaison post-hoc entre simulations
hmp list [project]                        # inventaire
hmp export <project>                      # export résultats
hmp test <suite>                          # tests
```

`hmp run` est la seule commande d'exécution. Elle accepte un `.toml`
(auto-détection du workflow) ou un `.py` (exécution comme subprocess).

### 9.3 Routage dans `__main__.py`

```python
def _cmd_run(args):
    target = Path(args.config).resolve()

    if target.suffix == ".py":
        _cmd_run_script(target, args.script_args)
        return

    if target.suffix != ".toml":
        print(f"Unsupported: {target.suffix} (expected .toml or .py)")
        sys.exit(1)

    import tomllib
    with open(target, "rb") as f:
        raw_toml = f.read()
    raw = tomllib.loads(raw_toml.decode())

    workflow = detect_workflow(raw)

    dispatch = {
        "simulation":  "hydromodpy.runners.simulation",
        "overview":    "hydromodpy.runners.overview",
        "mesh":        "hydromodpy.runners.mesh",
        "calibration": "hydromodpy.runners.calibration",
        "batch":       "hydromodpy.runners.batch",
    }
    module = importlib.import_module(dispatch[workflow])
    module.run(target)
```

Le routage est entièrement piloté par `detect_workflow()`. Ajouter un
nouveau type de workflow = ajouter une entrée dans `detect_workflow()` et
un module dans `runners/`.


## 10. Graphe de dépendances

```
         core/
          ↑
    ┌─────┼──────────┐
    ↑     ↑          ↑
  data/  spatial/   process/base/   solver/base/
    ↑     ↑          ↑                ↑
    │     │     process/flow/    solver/modflow6/
    │     │     process/transport/  solver/boussinesq/
    │     │          ↑                ↑
    │     └────┬─────┘         ┌──────┘
    │          ↑               ↑
    │     simulation/      results/
    │          ↑               ↑
    │     workflow/steps/ ─────┘
    │          ↑
    │     workflow/pipelines/
    │          ↑
    ├────analysis/calibration/engine/
    ├────analysis/comparison/
    ├────analysis/batch/
    │          ↑
    │     project.py ←──── runners/
    │                        ↑
    └──────────────── __main__.py
```

Règle absolue : les flèches ne descendent jamais. `runners/` importe depuis
`project.py`, `workflow/` et `analysis/`, jamais l'inverse. `workflow/`
importe depuis `simulation/` et `data/`, jamais l'inverse.


## 11. Cas des `cases/` module-level

Les répertoires `cases/` dispersés dans les modules (`spatial/domain/cases/`,
`solver/utils/temporal/cases/`, `spatial/field/cases/`) sont des scripts de
debug/démo au niveau module.

### Recommandation

- Placeholders vides (juste un `.gitignore`) : supprimer
- Scripts utiles au développeur (`run_domain_case.py`, `run_tmesh_case.py`) :
  garder avec une docstring en tête de fichier précisant
  "Developer-only script, not part of the public API"
- `validation_cases/` à la racine : garder tel quel (bon pattern séparé)


## 12. Plan de migration

Chaque phase laisse le code fonctionnel et les tests de régression au vert.

### Principe général : pas de rétrocompatibilité

Aucun alias, aucun réexport temporaire, aucune commande CLI dépréciée.
Chaque phase fait le changement proprement et supprime l'ancien code.
Les facades de compatibilité existantes (`domain/`, `field/`, `mesh/`,
`postprocess/`, `modeling/` à la racine du package) sont aussi supprimées.

### Phase 1 — Renommages structurels

1. Renommer `process/prototype/` → `process/base/` (déplacer, pas copier)
2. Renommer `solver/prototype/` → `solver/base/` (déplacer, pas copier)
3. Migrer tous les imports internes en une passe
4. Supprimer `process/prototype/` et `solver/prototype/`

Validation : `pytest tests/unit/ -n auto` + `pytest tests/regression/fast/ -n auto`

### Phase 2 — Enrichir `Project` avec les capacités du launcher

1. Ajouter la mesh section detection dans `Project.__init__`
2. Ajouter le spatial support registry dans `Project.__init__`
3. Ajouter le `PostprocessRunner` dans `Project.__init__`
4. Enrichir le data plan avec `domain_support_provider_names`
5. Passer tous les paramètres à `prepare_simulation_runtime()`
6. Adapter `Project.run()` pour utiliser `SimulationPlanner` quand pas d'overrides

Validation :
- `run_transient_prototype.py` fonctionne identiquement
- `hmp run config.toml` via `Project` produit les mêmes résultats
  qu'avec `HydroModPyLauncher`

### Phase 3 — Intégrer `launchers/` dans `hydromodpy/runners/` + CLI unifié

1. Créer `hydromodpy/runners/` avec `detect_workflow()` dans `__init__.py`
2. Créer `runners/simulation.py` (wrapper autour de `Project`)
3. Créer `runners/overview.py` (coquille → `workflow/pipelines/overview`)
4. Créer `runners/mesh.py` (coquille → `workflow/pipelines/mesh`)
5. Réécrire `hydromodpy/__main__.py` :
   - Supprimer les commandes `overview`, `mesh`, `calibrate`, `compare`,
     `simulation` (hidden alias)
   - `hmp run` fait `detect_workflow(raw_toml)` puis dispatch au runner
6. Supprimer `launchers/__main__.py` (611L)
7. Supprimer `launchers/__init__.py` (lazy loader)
8. Supprimer les facades de compatibilité à la racine du package
   (`domain/`, `field/`, `mesh/`, `postprocess/`, `modeling/`)

Validation :
- `hmp run simulation.toml` fonctionne (auto-detect "simulation")
- `hmp run overview.toml` fonctionne (auto-detect "overview")
- `hmp run mesh.toml` fonctionne (auto-detect "mesh")

### Phase 4 — Extraire la logique domaine des launchers

1. Déplacer `launchers/model_calibration/runtime.py` (3467L) →
   `analysis/calibration/engine/session.py`
2. Déplacer `launchers/model_calibration/objective_mapping.py` →
   `analysis/calibration/engine/objective_mapping.py`
3. Déplacer `launchers/model_calibration/output_selection.py` →
   `analysis/calibration/engine/output_selection.py`
4. Déplacer `launchers/model_calibration/property_arrays.py` →
   `analysis/calibration/engine/property_arrays.py`
5. Déplacer `launchers/method_comparison/{metrics,visuals,exports,reporting}.py`
   → `analysis/comparison/` (analyse post-hoc, plus de runner)
6. Créer `analysis/display/compare.py` pour `hmp display compare`
7. Créer `runners/calibration.py` (coquille mince)
8. Déplacer `launchers/regional_lab/launcher.py` (1828L) →
   `analysis/batch/runtime.py` + `runners/batch.py`
9. Supprimer `launchers/` à la racine du dépôt

Validation :
- `hmp run calibration.toml` fonctionne (auto-detect "calibration")
- `hmp run batch.toml` fonctionne (auto-detect "batch")
- `hmp display compare --sim A --sim B` fonctionne

### Phase 5 — Migrer le pont calibration vers `Project`

1. Étendre `Project.run()` pour accepter des `PropertyArraySet` (tableaux
   hydrauliques spatialisés) en plus des scalaires
2. Ajouter le flag `headless` à `Project.__init__` (disable display/postprocess)
3. Réécrire `ModelCalibrationObjectiveEvaluator.evaluate()` pour appeler
   `project.run(**params)` au lieu de `execute_candidate_run(launcher)`
4. Réécrire l'extraction d'objectif pour utiliser `SimulationResult`
   au lieu de `run_state`
5. Simplifier `prepare_calibration_session()` : créer un `Project`
   au lieu de parser le TOML et cacher un launcher
6. Supprimer `actualize_candidate()`, `execute_candidate_run()`,
   `_prepare_runtime_direct_launcher()`, `_get_or_create_runtime_reusable_launcher()`
7. Déplacer le code restant de `runtime.py` dans `analysis/calibration/engine/`

Validation :
- `hmp run calibration.toml` produit les mêmes résultats d'optimisation
- Le best-rerun et les distribution-reruns fonctionnent
- Les itérations persistées sont identiques

### Phase 6 — Créer les pipelines manquants

1. Créer `workflow/pipelines/overview.py` en extrayant la logique de
   `runners/overview.py`
2. Créer `workflow/pipelines/mesh.py` en extrayant la logique de
   `runners/mesh.py`
3. Amincir `runners/overview.py` et `runners/mesh.py`

Validation :
- `hmp run overview.toml` produit les mêmes résultats
- `hmp run mesh.toml` produit les mêmes résultats

### Phase 7 — Nettoyage final

1. Supprimer `LauncherRunState` (remplacé par `WorkflowContext`)
2. Supprimer `HydroModPyLauncher` (remplacé par `Project`)
3. Supprimer les `cases/` placeholder vides (juste un `.gitignore`)
4. Supprimer les facades de compatibilité restantes (`domain/`, `field/`,
   `mesh/`, `postprocess/`, `modeling/`)
5. Mettre à jour `CLAUDE.md`
6. Ajouter `dev-database` aux triggers CI


## 13. Impact sur la calibration

### 13.1 Ce qui ne change pas

La couche `analysis/calibration/core/` reste identique. Elle est agnostique
du solveur et n'a aucune dépendance vers les launchers ou `Project` :

- `CalibrationEngine` : moteur générique qui prend un `objective_evaluator`
  et appelle `calibrate(method, **kwargs)`.
- `CalibrationParameterSet` : espace de paramètres avec bornes.
- `CalibrationResults` : résultat d'optimisation (cost_best, x_best, etc.).
- `CompositeObjective` / `CompositeObjectiveBlock` : fonction objectif
  multi-bloc avec pondération.
- Les méthodes d'optimisation (`methods_dispatcher.py`,
  `scipy_differential_evolution`, etc.).
- `ModelCalibrationConfig` : config TOML de calibration (bornes, paramètres,
  objectif, méthode).

La session de calibration (manifest, persistence des itérations,
`calibration_root`, `candidates_root`) reste aussi. C'est de la gestion
de campagne, indépendante du mode d'exécution du solveur.

### 13.2 Ce qui change : le pont entre le moteur et le solveur

Aujourd'hui, le pont est implémenté dans `launchers/model_calibration/runtime.py`
(3467L). La chaîne d'exécution par candidat est :

```
CalibrationEngine.calibrate()
  → ModelCalibrationObjectiveEvaluator.evaluate(params)
    → actualize_candidate(params)
    │   écrit un TOML overlay dans candidates_root/iter_NNNN/
    │
    → execute_candidate_run(request, launcher_factory)
    │   → _get_or_create_runtime_reusable_launcher()
    │   │   crée un HydroModPyLauncher, appelle prepare_runtime()
    │   │   met en cache dans session.runtime_launcher_cache
    │   │
    │   → _prepare_runtime_direct_launcher(launcher, request)
    │   │   restaure le baseline, puis patche :
    │   │     launcher.cfg.simulation.run_id = candidate_run_id
    │   │     launcher.cfg.display.enabled = False
    │   │     launcher.cfg.postprocess.enabled = False
    │   │     launcher.run_state.setup.flow_runtime_overrides = {properties}
    │   │     launcher.run_state.raw_toml["simulation"]["run_id"] = ...
    │   │
    │   → launcher.run_prepared()
    │
    → evaluate_candidate_objective(cfg, run_state, result_store, store_sim_id)
```

Ce code manipule les **internals** du launcher via `setattr` et `getattr` :
- `launcher.run_state.setup.flow_runtime_overrides` (injection directe dans
  le state)
- `launcher.cfg.simulation.run_id` (mutation de la config)
- `launcher.cfg.display.enabled = False` (désactivation manuelle)
- `launcher._result_store` et `launcher._sim_id` (attributs privés)
- `_capture_runtime_direct_launcher_baseline()` /
  `_restore_runtime_direct_launcher_baseline()` (sauvegarde/restauration
  d'état mutable)

Ce code existe parce que `HydroModPyLauncher` n'a pas été conçu pour le
run-many. Le calibrateur est forcé de le "hacker" pour le réutiliser.

### 13.3 Chaîne cible avec `Project`

```
CalibrationEngine.calibrate()
  → ModelCalibrationObjectiveEvaluator.evaluate(params)
    → project.run(K=params["K"], Sy=params["Sy"], name=f"iter_{i}")
    │   Project crée un Flow frais, applique les overrides,
    │   exécute, ingère les résultats, retourne SimulationResult
    │
    → evaluate_objective(result)
    │   result.field(), result.timeseries(), result.budget()
```

Les étapes intermédiaires disparaissent :
- Plus de TOML overlay → les overrides sont des kwargs Python
- Plus de cache de launcher → le `Project` est nativement réutilisable
- Plus de patch d'attributs internes → `run()` crée un `Flow` frais
- Plus d'accès à `_result_store` → `project.store` est public

### 13.4 Points d'attention pour la migration

**1. Tableaux hydrauliques spatialisés (`PropertyArraySet`)**

Le calibrateur supporte des paramètres non-scalaires : un K par zone
géologique (mode `parameterization = "lithology_value"`). Aujourd'hui,
ces tableaux sont injectés via `flow_runtime_overrides`.

`Project.run(K=0.05)` ne supporte que les scalaires. Il faut étendre
l'API pour accepter des tableaux ou des dicts de valeurs par zone :

```python
# Option A : kwarg direct
project.run(K={"granite": 1e-5, "schiste": 5e-4}, name="iter_0042")

# Option B : argument dédié
project.run(properties=property_array_set, name="iter_0042")
```

Le choix sera fait lors de l'implémentation en fonction de la complexité
du `PropertyArraySet` existant.

**2. Désactivation display/postprocess**

Le calibrateur force `display.enabled = False` pour éviter de générer des
figures à chaque itération. Avec `Project`, deux approches :

```python
# Option A : paramètre du constructeur (recommandé)
project = Project("config.toml", headless=True)

# Option B : flag dans run()
project.run(K=..., headless=True)
```

L'option A est préférable : le mode headless est une propriété de la session,
pas du run individuel.

**3. `candidate_run_id` et nommage des runs**

Le calibrateur attribue un `run_id` structuré (`calibration_id__iter_NNNN`).
Avec `Project`, c'est le paramètre `name` de `run()` :

```python
project.run(K=..., name=f"{calibration_id}__iter_{i:04d}")
```

Aucune adaptation nécessaire.

**4. Évaluation de l'objectif post-run**

Aujourd'hui, `evaluate_candidate_objective()` accède au `run_state` et au
`ResultStore` directement. Avec `Project`, l'évaluation utilise
`SimulationResult` :

```python
result = project.run(K=..., Sy=...)
# Avant : extraire depuis run_state.execution.models_by_run_id
# Après : extraire depuis result.field(), result.timeseries()
score = compute_objective(result, cfg.objective)
```

L'interface `SimulationResult` expose exactement ce dont l'évaluation a
besoin : champs spatiaux, séries temporelles, budgets.

**5. Re-run du meilleur candidat et distribution**

`execute_best_candidate_rerun()` et `execute_model_distribution_reruns()`
relancent des simulations avec les paramètres stockés. Avec `Project`,
c'est un simple `project.run(**best_params, name="best_rerun")`.

### 13.5 Tableau d'impact par composant

| Composant | Change ? | Détail |
|---|---|---|
| `analysis/calibration/core/engine.py` | Non | Moteur agnostique, inchangé |
| `analysis/calibration/core/parameters.py` | Non | Espace de paramètres, inchangé |
| `analysis/calibration/core/composite_objective.py` | Non | Fonction objectif, inchangée |
| `analysis/calibration/core/methods_dispatcher.py` | Non | Registre des méthodes, inchangé |
| `ModelCalibrationConfig` | Non | Config TOML calibration, inchangée |
| `ModelCalibrationObjectiveEvaluator` | **Oui** | `execute_candidate_run(launcher)` → `project.run(**params)` |
| `actualize_candidate()` | **Supprimé** | Plus besoin d'overlay TOML |
| `execute_candidate_run()` | **Supprimé** | Remplacé par `project.run()` |
| `_prepare_runtime_direct_launcher()` | **Supprimé** | Plus de hack du launcher |
| `_get_or_create_runtime_reusable_launcher()` | **Supprimé** | `Project` est nativement réutilisable |
| `prepare_calibration_session()` | **Simplifié** | Crée un `Project` au lieu de parser le TOML |
| `PreparedCalibrationSession` | **Simplifié** | Stocke un `Project` au lieu d'un cache de launcher |
| `PropertyArraySet` / `build_property_array_set()` | **Adapté** | Doit passer par `Project.run()` au lieu d'injection directe |
| Session manifest, persistence itérations | Non | Logique de campagne inchangée |
| `objective_mapping` | Non | Utilise `evaluate()`, agnostique |
| `execute_best_candidate_rerun()` | **Simplifié** | `project.run(**best_params)` |
| `execute_model_distribution_reruns()` | **Simplifié** | Boucle de `project.run()` |
| Reporting calibration | Non | Lit le manifest, indépendant |

### 13.6 Estimation de l'effort

Sur les ~3467 lignes de `runtime.py` :

- ~1500L de code de pont (actualize, execute, prepare/restore launcher,
  TOML overlay, cache) : **supprimées**, remplacées par des appels à
  `Project.run()`.
- ~800L de logique d'évaluation objectif et extraction d'outputs :
  **adaptées** pour utiliser `SimulationResult` au lieu de `run_state`.
- ~700L de gestion de session (manifest, persistence, signature) :
  **inchangées**, déplacées dans `analysis/calibration/engine/session.py`.
- ~400L d'utilitaires (hashing, formatting, logging) : **inchangés**.

Le résultat net est une réduction significative de la complexité : le code
de "hack du launcher" disparaît, remplacé par un contrat public stable
(`Project.run(**params) → SimulationResult`).


## 14. Risques et mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Casser les tests de régression pendant le refactoring | Moyenne | Fort | Migrer step-by-step, valider après chaque extraction. Garder les réexports de compatibilité jusqu'à migration complète. |
| `Project.__init__` devient trop long en absorbant le launcher | Faible | Moyen | Extraire les étapes d'initialisation dans des méthodes privées (`_detect_mesh_config()`, `_build_spatial_support_registry()`, etc.). L'__init__ reste un orchestrateur de ~40 lignes appelant des sous-méthodes. |
| `WorkflowContext` god-object | Faible | Moyen | Garder les 3 scopes stricts (setup/loaded_data/execution). Le store est le seul ajout par rapport à `LauncherRunState`. Ne pas ajouter de nouveaux champs sans justification. |
| Import circulaire `workflow/` ↔ `analysis/` | Faible | Fort | `workflow/steps/` importe `simulation/`, jamais l'inverse. `analysis/` importe `workflow/`, jamais l'inverse. Les runners importent les deux. |
| La calibration dépend de l'API interne de `Project` | Moyenne | Moyen | Le calibrateur utilise `Project.run(**overrides)` comme API publique. Il ne manipule pas `Project._ctx` directement. Si un override supplémentaire est nécessaire, il est ajouté à l'API publique de `run()`. |
| `runners/` trop maigres, développeurs ne savent pas où regarder | Faible | Faible | Chaque runner a un docstring qui pointe vers le module de logique domaine correspondant. Le CLAUDE.md documente la convention. |
| Effort de migration important | Haute | Moyen | Les phases sont indépendantes. Chacune peut être livrée séparément. La phase 1 (renommages) et la phase 2 (enrichir Project) apportent le plus de valeur avec le moins de risque. |


## 15. Bénéfices attendus

1. **Un seul chemin de logique** pour les trois modes (TOML, Python,
   calibration). Fin de la duplication entre `Project` et `HydroModPyLauncher`.

2. **Project gagne toutes les capacités** : mesh, spatial supports, transport,
   multi-process, postprocess. Le prototypage Python n'est plus une version
   dégradée du mode TOML.

3. **Package unifié** : `pip install hydromodpy` inclut tout. Plus de package
   `launchers/` fantôme à la racine.

4. **Runners de ~30-150 lignes** au lieu de monolithes de 1828-3467 lignes.
   Plus lisibles, plus faciles à auditer, plus faciles à tester.

5. **Logique domaine à sa place** : métriques de calibration dans
   `analysis/calibration/`, visualisations de comparaison dans
   `analysis/comparison/`. Pas dans un runner CLI.

6. **Nommage sans ambiguïté** : `base/` pour les ABC, `Project` pour
   l'interface Python, `runners/` pour les coquilles CLI. Un contributeur
   sait immédiatement où chercher.

7. **Extensibilité** : ajouter un nouveau type de workflow = créer un fichier
   dans `runners/` + un module dans `analysis/` ou `workflow/pipelines/`.
   Pas besoin de re-coder l'orchestration.
