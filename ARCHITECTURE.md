# Architecture HydroModPy

> Document de reference pour l'architecture du projet.
> Derniere mise a jour : 2026-03-08 (branche dev-refact).

---

## 1. Vision

HydroModPy est une plateforme de modelisation hydrologique et hydrogeologique.
Elle doit servir **trois niveaux d'usage** avec le **meme code** :

| Niveau | Usage | Public | Entree | Sortie |
|---|---|---|---|---|
| 1 | **Cases** (par module) | Developpeur d'un module | TOML local + script de cas | Validation du module isole |
| 2 | **Prototypage** (transverse) | Chercheur qui explore | Script Python / Jupyter | Objets manipulables en memoire |
| 3 | **Production** (application) | Ingenieur qui deploie | TOML global | Resultats reproductibles sur disque |

Les trois niveaux coexistent. Aucun ne remplace les autres.

**Regle fondamentale** : les objets de la bibliotheque ne connaissent pas l'existence
du launcher ni de `simulation/`. La dependance va dans un seul sens :

```
launcher  -->  simulation  -->  objets metier  <--  scripts utilisateur / cases
```

`simulation/`, les scripts utilisateur et les `cases/` sont au meme niveau :
ils composent les memes objets, juste differemment.

### Un seul package, un seul import

La difference entre prototypage et production n'est **pas dans l'import,
c'est dans l'usage**. Un seul `import hydromodpy`, meme bibliotheque,
memes objets, deux facons de les composer :

```python
import hydromodpy as hmp

# ---- Prototypage : acces direct aux objets ----
workspace  = hmp.Workspace(config=cfg.workspace)
geographic = hmp.Geographic(cfg.geographic, workspace)
modflow    = hmp.Modflow(geographic, ...)
modflow.pre_processing(...)
modflow.processing(...)

# ---- Production : acces au launcher ----
# (ou via CLI : python -m hydromodpy.launchers simulation config.toml)
from hydromodpy.launchers import HydroModPyLauncher
launcher = HydroModPyLauncher("config.toml")
launcher.run()
```

Pas de `import hydromodpy_dev` ni de package separe pour le prototypage.
Les objets (`Modflow`, `Geographic`, `Flow`...) sont utilises par les deux
modes. Creer deux points d'entree pour les memes classes serait de la
duplication d'API sans valeur ajoutee. C'est le pattern standard des
bibliotheques scientifiques (scikit-learn, PyTorch, FloPy) : un seul
package, tout accessible, l'utilisateur choisit son niveau d'orchestration.

---

## 2. Couches architecturales

```
Couche 8 : Points d'entree
  launcher/          CLI et orchestrateur TOML-driven
  examples/          Workflows executables (prototypage et production)

Couche 7 : Orchestration
  simulation/        Planification, execution, adapters, etat

Couche 6 : Post-traitement et analyse
  postprocess/       Timeseries, NetCDF, intermittence
  display/           Visualisation 2D/3D, suites de plots
  calibration/       Moteur d'optimisation (grid, simplex, GP, DA)

Couche 5 : Solveurs
  solver/            Interface abstraite (Solver ABC)
  solver/modflow_nwt/   MODFLOW-NWT, Modpath, MT3DMS
  solver/modflow6/      MODFLOW 6, MF6-GWT

Couche 4 : Processus physiques
  process/flow/         Flow (regime, BC, IC, puits, recharge)
  process/transport/    Transport (concentrations, dispersion)
  process/prototype/    ProcessSpatial (ABC generique)

Couche 3 : Domaine spatial
  geographic/        Delineation de bassin versant, DEM, CRS
  domain/            Maillage, profondeur, zones, surface topographique

Couche 2 : Donnees
  data_managers/     Gestionnaires par variable (hydrometry, piezometry...)
  field/             Parametres spatiaux (FieldParam, discretisation)

Couche 1 : Configuration et utilitaires
  config/            HydroModPyConfig (agregat Pydantic), param_level
  tools/             Logging, utilitaires divers
```

**Regle de dependance** : une couche ne peut importer que des couches
inferieures. Jamais l'inverse.

### 2.1 Interface CLI unifiee (`hmp`)

Toutes les commandes passent par `hmp` (alias de `hydromodpy`), enregistre
dans `pyproject.toml` via `[project.scripts]`. Jamais de `python -m ...`.

```bash
# Initialisation
hmp init                                  # cree ~/hydromodpy/
hmp init --path /mnt/shared/hydrodata     # chemin custom

# Configuration
hmp config config.toml                    # genere un TOML template
hmp config --profile user                 # TOML minimal
hmp config --list-modules                 # modules disponibles

# Tests
hmp test unit                             # tests unitaires
hmp test regression                       # tous les tests de regression
hmp test regression --fast                # regression rapide
hmp test regression example12             # un test specifique
hmp test regression --list                # lister les tests disponibles
hmp test regression --update-goldens      # mettre a jour les references

# Simulation (production)
hmp simulation config.toml                # lance le pipeline complet
hmp simulation config.toml --until data   # s'arrete apres le chargement

# Cases (developpement par module)
hmp case geographic                       # lance geographic/cases/
hmp case field square                     # lance field/cases/square/
hmp case hydrometry                       # lance hydrometry/cases/
hmp case calibration reservoir            # lance calibration/cases/reservoir/
hmp case --list                           # liste les cases disponibles
```

**Etat actuel** : `hmp init`, `hmp config` et `hmp test` sont implementes.
`hmp simulation` et `hmp case` sont a ajouter.

---

## 3. Niveau 1 — Cases (developpement par module)

### 3.1 Principe

Chaque module dispose d'un dossier `cases/` contenant des scripts
autonomes pour developper et valider le module en isolation, sans
lancer le pipeline complet.

```
hydromodpy/
  geographic/
    cases/
      run_geographic_case.py      <- lancer pour bosser sur geographic
      run_geographic_config.toml  <- config isolee, pas le TOML global
      outputs/                    <- resultats locaux
  field/
    cases/
      square/
        run_field_demo.py         <- lancer pour bosser sur field
        field_param_config.toml
  hydrometry/
    cases/
      run_hydrometry_case.py      <- lancer pour bosser sur hydrometry
      run_hydrometry_config.toml
  calibration/
    cases/
      reservoir/                  <- cas scientifique complet
      groundwater_1d/
      recession_brutsaert/
  domain/
    cases/
      run_domain_case.py
  ...
```

### 3.2 Quand utiliser les cases

- **Developper un module** : "je travaille sur geographic, je lance
  `geographic/cases/` pour verifier mes changements"
- **Valider une correction** : le case produit un resultat deterministe
  comparable au golden de reference
- **Comprendre un module** : le case sert de documentation executable
- **CI** : les cases alimentent les tests de regression

### 3.3 Limites des cases

Les cases couvrent le cas **"un module isole"**. Ils ne couvrent pas :

| Situation | Cases ? | Prototypage ? | Launcher ? |
|---|---|---|---|
| Developper geographic seul | Oui | — | — |
| Combiner geographic + climatic + hydrometry | Non | Oui | — |
| Injecter un array numpy custom en recharge | Non | Oui | Via hook |
| Iterer interactivement dans Jupyter | Non | Oui | — |
| Tester un module pas encore integre | Non | Oui | — |
| Workflow reproductible complet | Non | Non | Oui |

### 3.4 Convention de structure

Chaque `cases/` suit la meme convention :

```
module/cases/
  run_<module>_case.py       Script principal executable
  run_<module>_config.toml   Configuration locale
  outputs/                   Resultats (dans .gitignore)
  README.md                  Documentation du cas (optionnel)
```

Execution :

```bash
python hydromodpy/spatial/geographic/cases/run_geographic_case.py
python hydromodpy/spatial/field/cases/square/run_field_demo.py
python hydromodpy/analysis/calibration/cases/reservoir/run_calibration.py
```

---

## 4. Niveau 2 — Prototypage (scripts transverses)

### 4.1 Principe

L'utilisateur combine librement les objets HydroModPy dans un script
Python ou un notebook Jupyter. Chaque objet est **autonome** : il recoit
un config Pydantic et produit un resultat sans connaitre le contexte global.

```python
# Script de prototypage : flow seul, sans launcher
from hydromodpy.core.config import HydroModPyConfig
import hydromodpy as hmp
from hydromodpy.spatial.domain import Domain
from hydromodpy.process import Flow
from hydromodpy.solver.modflow_nwt import (
    Modflow, ModflowPreprocessOptions, ModflowRunOptions, ModflowPostprocessOptions,
)

cfg = HydroModPyConfig.from_toml("config.toml")

# Etape par etape, chaque objet est manipulable
workspace   = hmp.Workspace(config=cfg.workspace)
geographic  = hmp.Geographic(cfg.geographic, workspace)
domain      = Domain(config=cfg.domain, surface_topo=geographic.get_domain_surface_topo())
flow        = Flow(config=cfg.flow)

# Instantiation directe du solveur
modflow = Modflow(
    geographic,
    model_folder=workspace.simulations_folder,
    model_name="mon_test",
    bin_path=workspace.bin_path,
    modflow_config=cfg.modflownwt,
    preprocess_options=ModflowPreprocessOptions(box=True, sink_fill=False),
)

# Workflow explicite
modflow.pre_processing(flow=flow, domain=domain, options=ModflowPreprocessOptions(...))
success = modflow.processing(options=ModflowRunOptions(write_model=True, run_model=True))
if success:
    modflow.post_processing(options=ModflowPostprocessOptions(watertable_elevation=True))

# L'utilisateur a acces a tout : modflow.mf, modflow.heads, etc.
```

### 4.2 Quand utiliser le prototypage

- **Combiner des modules** : geographic + climatic + hydrometry sans modele
- **Injection de donnees calculees** : arrays numpy, DataFrames, etc.
- **Comparaison rapide** : deux solveurs cote a cote en 20 lignes
- **Debugging** : inspecter un objet, modifier un parametre, relancer
- **Notebooks Jupyter** : pedagogie, demonstrations, publications
- **Tester un module en cours de developpement** avant de creer son case

### 4.3 Doit-on appeler directement Modflow() ou passer par un solver generique ?

**En prototypage : appel direct.** L'utilisateur sait quel solveur il veut,
il n'a pas besoin d'indirection.

```python
# OUI - prototypage, explicite
modflow = Modflow(geographic, model_folder=..., modflow_config=cfg.modflownwt, ...)

# OUI aussi - si on veut suivre le config sans if/else
from hydromodpy.solver import SolverEngine
if cfg.solver.solver_engine == SolverEngine.MODFLOW_NWT:
    modflow = Modflow(...)
else:
    modflow = Modflow6(...)
```

**Pas de factory magique en prototypage.** L'utilisateur voit ce qu'il
instancie. La dispatch automatique (adapter registry) est reservee a
`simulation/` car la-bas le TOML decide.

### 4.4 Injection Pydantic depuis Python

L'utilisateur peut court-circuiter le TOML a tout moment :

```python
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

# Config construite en Python, pas depuis un TOML
geo_cfg = GeographicConfig(
    catch_def="from_outlet_coord",
    dem_init_path="data/dem.tif",
    x_outlet=265611.0,
    y_outlet=6784182.0,
    snap_dist=50,
    buff_area=20.0,
    crs_project="EPSG:2154",
)
geographic = hmp.Geographic(geo_cfg, workspace)
```

C'est un usage de premiere classe, pas un hack. Le TOML n'est qu'un
moyen de serialiser un config Pydantic.

### 4.5 Difference entre cases et prototypage

| | Cases (niveau 1) | Prototypage (niveau 2) |
|---|---|---|
| Perimetre | Un seul module | N modules combines |
| Donnees | Fixees, reference | Libres, variables |
| Modifiable | Non (valeur de reference) | Oui (jetable) |
| Emplacement | `module/cases/` (dans le repo) | Script utilisateur (hors du repo) |
| Reproductible | Oui (deterministe) | Non (exploratoire) |
| CI | Oui (alimente les tests) | Non |

Les cases sont **dans le repo** et font partie du code. Les scripts
de prototypage sont **chez l'utilisateur** et sont jetables.

---

## 5. Niveau 3 — Production (Launcher / Simulation)

### 5.1 Principe

Un fichier TOML declare **quoi** executer. Le launcher + `simulation/`
s'occupent du **comment**.

```bash
python -m hydromodpy.launchers simulation config.toml
```

L'utilisateur ne touche pas de Python. Le TOML est la specification
complete du workflow.

### 5.2 Architecture de simulation/

```
simulation/
  planning/
    config.py          SimulationConfig (Pydantic, section [simulation])
    plan.py            ProcessRun, SimulationPlan, RunContext, RunExecutionResult
    planner.py         SimulationPlanner : config -> plan ordonne
  runtime/
    runner.py           SimulationRunner + ProcessContextFactory (inline)
  adapters/
    base.py            SolverAdapter (Protocol)
    registry.py        Registre dynamique {(type, solver) -> adapter}
                       + register_adapter() pour extension
    flow/              ModflowNwtFlowAdapter, Modflow6FlowAdapter
    transport/         ModpathAdapter, Mt3dmsAdapter, Modflow6GwtAdapter
    postprocess/       TimeseriesPostprocessAdapter, NetcdfPostprocessAdapter (stubs)
    display/           FlowDisplayAdapter, TransportDisplayAdapter (stubs)
  state/
    run_state.py       LauncherRunState (3 scopes)
    setup.py           SetupContext
    data.py            LoadedDataContext
    execution.py       ExecutionRegistry
  workspace/
    config.py          WorkspaceConfig
    path_registry.py   WorkspacePathRegistry (frozen)
    workspace.py       Workspace (creation dossiers)
  forcing/
    recharge_chronicle.py  Parsing recharge (observed, synthetic)
  time/
    window.py          Resolution fenetre temporelle + validation couverture
  settings.py          Settings (options preprocessing legacy)
```

### 5.3 Decisions architecturales

**Adapter pattern + registry dynamique** : la meilleure decision architecturale.
Ajouter un solveur = 1 fichier adapter + 1 ligne dans le registre. Le
runner reste generique. Le registre est extensible dynamiquement :

```python
# Registre existant (charge au demarrage)
_ADAPTERS = {
    ("flow", "modflownwt"): ModflowNwtFlowAdapter(),
    ("flow", "modflow6"):   Modflow6FlowAdapter(),
    ("transport", "modpath"):     ModpathTransportAdapter(),
    ("transport", "mt3dms"):      Mt3dmsTransportAdapter(),
    ("transport", "modflow6gwt"): Modflow6GwtTransportAdapter(),
}

# Extension dynamique depuis un module externe
from hydromodpy.simulation.adapters import register_adapter
from hydromodpy.solver.compatibility import register_process_solver

register_process_solver("postprocess", "timeseries")
register_adapter("postprocess", "timeseries", MyTimeseriesAdapter())
```

**Type de process extensible** : `SimulationProcessConfig.type` est un `str`
valide dynamiquement contre le registre `solver/compatibility.py`, plus un
`Literal["flow", "transport"]`. Ajouter un nouveau type (postprocess, display,
etc.) ne necessite aucune modification du code simulation/ existant.

**Trois scopes d'etat** (SetupContext, LoadedDataContext, ExecutionRegistry) :
separation claire entre objets structurels, donnees chargees, et resultats
d'execution. Indispensable pour la calibration (reinitialiser execution
sans recharger les donnees).

**WorkspacePathRegistry** (frozen) : un seul point de verite pour tous les
chemins derives. Elimine les constructions ad-hoc.

**SimulationPlan** comme structure de donnees : la liste ordonnee de
ProcessRun avec `depends_on` explicite supporte les dependances non-lineaires
(transport depend de flow, etc.). Necessaire des qu'on a plus de 2 processus.

**DataManagersPlanner** avec inference : deduire automatiquement les types
de donnees actifs depuis la configuration domain/flow. Reduit le boilerplate
TOML.

**RunContext / RunExecutionResult** dans `planning/plan.py` : contrats
partages entre le runner et les adapters. Co-localises avec ProcessRun et
SimulationPlan pour eviter les dependances circulaires.

**ProcessContextFactory inline dans runner.py** : materialise les objets
process (Flow, Transport) a la demande. Accepte silencieusement les types
inconnus (no-op) pour supporter les nouvelles phases sans modification.

### 5.4 A evoluer

#### Planner : fusionner eventuellement

Le `SimulationPlanner` ne planifie pas (il ne reordonne pas, ne parallelise
pas). Il **valide et aplatit**. Option future : fusionner `planner.py` +
`plan.py` en un seul module (~100 lignes au lieu de 170). Pas prioritaire.

#### settings.py : a deprecer

`Settings` est un vestige pre-Pydantic. Ses champs (`box`, `sink_fill`,
`check_grid`) sont deja modelises dans `FlowConfig` et
`ModflowPreprocessOptions`. Encore utilise par `modflow_common.py` et le
launcher — a migrer progressivement.

### 5.5 Extensibilite

#### Ajouter un nouveau type de process (ex: postprocess)

1. Enregistrer la paire dans la matrice de compatibilite :
   ```python
   from hydromodpy.solver.compatibility import register_process_solver
   register_process_solver("postprocess", "timeseries")
   ```

2. Creer l'adapter :
   ```python
   class TimeseriesPostprocessAdapter:
       process_type = "postprocess"
       solver_name = "timeseries"
       def execute(self, ctx: RunContext) -> RunExecutionResult:
           # wrapper autour de FlowTimeseriesPostprocess...
           return RunExecutionResult(primary_model=result)
   ```

3. Enregistrer l'adapter :
   ```python
   from hydromodpy.simulation.adapters import register_adapter
   register_adapter("postprocess", "timeseries", TimeseriesPostprocessAdapter())
   ```

4. L'utilisateur peut maintenant declarer dans son TOML :
   ```toml
   [[simulation.process]]
   id = "post_ts"
   type = "postprocess"
   solvers = ["timeseries"]
   ```

**Zero modification du code simulation/ existant.**

### 5.6 Hooks lifecycle (optionnel, basse priorite)

Un hook est un point d'insertion ou l'utilisateur glisse du code Python
entre les phases du launcher (ex: `on_after_data`, `on_before_simulation`).

L'ancien launcher avait 10 hooks. Ils ont ete supprimes dans la refonte.

**Decision** : les hooks ne sont **pas prioritaires**. Puisque le
prototypage (niveau 2) est maintenu, un utilisateur qui a besoin de
flexibilite (injecter des donnees, debugger, exporter) ecrit un script
Python directement. Le launcher TOML est reserve aux workflows standards
et reproductibles — la ou justement on ne veut pas de code custom.

Si le besoin se confirme plus tard, on pourra les reintroduire sous cette
forme :

```python
@dataclass
class LauncherCallbacks:
    on_after_setup: Callable[[LauncherRunState], None] | None = None
    on_after_data: Callable[[LauncherRunState], None] | None = None
    on_after_simulation: Callable[[LauncherRunState], None] | None = None
```

Avec auto-decouverte d'un fichier `hooks.py` a cote du TOML.

### 5.7 Workflow partiel

Permettre de n'executer qu'une partie du pipeline depuis le TOML :

```toml
[simulation]
# N'executer que setup + data, pas de modele
phases = ["setup", "data"]
```

Ou via CLI :

```bash
hmp simulation config.toml --until data
```

Cela couvre le cas "je veux juste exporter les donnees climatiques
sans lancer de modele".

---

## 6. Donnees (data_managers/)

### 5.1 Organisation

```
data_managers/
  contracts/         PointRecord, FieldRecord, StationLocation
  common/            BaseStation, BaseStationSet, BaseApiLoader, clients/
  registry/          Catalogue SQLAlchemy (SQLite -> PostgreSQL)
  climatic/          Climatic, SIM2, DRIAS, SAFRAN
  geology/           GeologyField
  hydrometry/        Station, StationSet, discovery, HydrometryManager
  piezometry/        Piezometer, PiezometerSet, discovery, PiezometryManager
  water_quality/     (en cours)
  hydrography/       Hydrography
  intermittency/     Intermittency
  oceanic/           Oceanic
  plan.py            DataLoadPlan
  planner.py         DataManagersPlanner (inference)
  runtime_loader.py  DataManagersRuntimeLoader (chargement)
```

### 5.2 Deux APIs de chargement coexistent

**API legacy (StationSet/PiezometerSet)** : approche du collegue,
classe monolithique qui charge depuis un TOML specifique au module.

```python
stations = StationSet.from_toml("run_hydrometry_config.toml")
```

**API Manager (HydrometryManager/PiezometryManager)** : approche
dev-data, Pydantic-driven, produit des `list[PointRecord]`.

```python
manager = HydrometryManager(config=hydro_cfg, project_period=period)
records: list[PointRecord] = manager.load()
```

**Decision a prendre** : converger vers une seule API. L'API Manager
(PointRecord) est plus flexible et s'integre mieux au contrat standard.
L'API StationSet peut rester comme couche de commodite au-dessus.

### 5.3 Inference des types de donnees

Le `DataManagersPlanner` deduit automatiquement les types actifs :

| Condition dans le TOML | Type infere |
|---|---|
| `domain.zone_ids` contient `"geology"` | `geology` |
| `flow.active_bc` contient `"stream"` | `hydrography` |
| `flow.active_bc` contient `"ocean"` | `oceanic` |

Les types explicites dans `[data].types` ont toujours priorite.
Le mode `inference_mode = "warn"` tolere les sections manquantes,
`"strict"` leve une erreur.

---

## 7. Solveurs (solver/)

### 6.1 Interface abstraite

```python
class Solver(ABC):
    @abstractmethod
    def pre_processing(self, **kwargs) -> None: ...

    @abstractmethod
    def processing(self, **kwargs) -> bool: ...

    @abstractmethod
    def post_processing(self, **kwargs) -> None: ...
```

Chaque solveur concret herite de `Solver` et implemente les 3 phases.

### 6.2 Implementations actuelles

| Solveur | Classe | Processus |
|---|---|---|
| MODFLOW-NWT | `Modflow` | flow |
| MODFLOW 6 | `Modflow6` | flow |
| MODPATH | `Modpath` | transport (particules) |
| MT3DMS | `Mt3dms` | transport (concentration) |
| MF6-GWT | `Modflow6Transport` | transport (concentration) |

### 6.3 Relation Process <-> Solver

Un **Process** (`Flow`, `Transport`) definit la physique (BC, IC, parametres).
Un **Solver** resout les equations avec un backend numerique specifique.

```
Flow (physique)  -->  Modflow ou Modflow6 (numerique)
Transport        -->  Modpath, Mt3dms, ou Modflow6Transport
```

Le processus ne sait pas quel solveur le resoudra. Le solveur recoit
le processus en argument de `pre_processing()`.

### 6.4 Ajouter un nouveau solveur

1. Creer `solver/mon_solveur/` avec une classe heritant de `Solver`
2. Implementer `pre_processing`, `processing`, `post_processing`
3. Creer un adapter dans `simulation/adapters/` (si integration launcher)
4. Ajouter l'entree dans `simulation/adapters/registry.py`
5. Ajouter la config Pydantic dans `config/`

Le code existant ne change pas.

---

## 8. Processus (process/)

### 7.1 Structure

```python
ProcessSpatial (ABC, Generic[TInitialConditions])
  |
  +-- Flow(ProcessSpatial[FlowInitialConditions])
  |     .parameters       : dict[str, FieldParam]   (K, Sy, Ss...)
  |     .boundary_conditions : dict[str, BoundaryCondition]
  |     .sinks_sources    : dict[str, SinkSource]    (wells, recharge)
  |     .flow_regime      : "steady" | "transient"
  |
  +-- Transport(ProcessSpatial[TransportInitialConditions])
        .modpath          : ModpathTransportConfig
        .mt3dms           : Mt3dmsTransportConfig
        .modflow6gwt      : Modflow6GwtTransportConfig
```

### 7.2 Configuration depuis TOML

```toml
[flow]
flow_regime = "transient"
param_list = ["K", "Sy", "Ss"]

[flow.ic]
type = "custom"
value = 12.5

[flow.bc.dirichlet.ocean]
value = 0.0

[flow.sinks_sources.recharge]
first_clim = "mean"
```

### 7.3 Injection en prototypage

En prototypage, l'utilisateur peut modifier les processus apres
creation :

```python
flow = Flow(config=cfg.flow)

# Injection de recharge calculee
import numpy as np
recharge = np.random.uniform(0, 0.005, size=(12,))  # mm/jour par mois
flow.set_recharge(FlowRechargeConfig(values=recharge, first_clim="mean"))

# Modification de BC
flow.boundary_conditions["ocean"].value = -0.5  # override MSL
```

C'est un usage normal, pas un contournement.

---

## 9. Configuration (config/)

### 8.1 Modele Pydantic global

```python
HydroModPyConfig
  workspace:    WorkspaceConfig        # [workspace]
  geographic:   GeographicConfig       # [geographic]
  domain:       DomainConfig           # [domain]
  data:         DataManagersConfig     # [data]
  flow:         FlowConfig             # [flow]
  transport:    TransportConfig        # [transport]
  solver:       SolverConfig           # [solver]
  modflownwt:   ModflowConfig          # [modflownwt]
  modflow6:     Modflow6Config         # [modflow6]
  simulation:   SimulationConfig       # [simulation]
  postprocess:  PostprocessConfig      # [postprocess]
  display:      DisplayConfig          # [display]
```

### 8.2 Chargement

```python
# Depuis un TOML
cfg = HydroModPyConfig.from_toml("config.toml")

# Depuis Python (prototypage)
from hydromodpy.core.workspace.config import WorkspaceConfig
ws_cfg = WorkspaceConfig(catch_name="test", out_dir_path="/tmp/out")
```

### 8.3 Niveaux de parametres (ParamLevel)

Chaque champ Pydantic porte un niveau : `"user"`, `"dev"`, `"expert"`.
Le generateur TOML filtre les champs selon le profil cible :

- `user` : parametres essentiels (chemins, CRS, regime)
- `dev` : parametres avances (taille maille, correction DEM)
- `expert` : parametres internes (tolerances numeriques)

```bash
python -m hydromodpy.core.config --level user    # TOML minimal
python -m hydromodpy.core.config --level expert  # TOML complet
```

### 8.4 Sections optionnelles

Toutes les sections sauf `workspace` et `geographic` sont optionnelles
avec des valeurs par defaut. L'utilisateur n'inclut dans son TOML que
ce dont il a besoin :

```toml
# TOML minimal pour geographic seul
[workspace]
catch_name = "test"
out_dir_path = "/tmp/out"

[geographic]
catch_def = "from_outlet_coord"
dem_init_path = "data/dem.tif"
x_outlet = 265611.0
y_outlet = 6784182.0
snap_dist = 50
buff_area = 20.0
```

Pas besoin de `[flow]`, `[transport]`, `[simulation]` si on ne
lance pas de modele.

---

## 10. Calibration (calibration/)

> Module existant mais hors perimetre pour le moment. Sera documente
> quand il sera stabilise. Voir `hydromodpy/analysis/calibration/` pour le code.

---

## 11. Workflow standard complet

### 10.1 En prototypage (script Python)

```python
import hydromodpy as hmp
from hydromodpy.core.config import HydroModPyConfig
from hydromodpy.spatial.domain import Domain
from hydromodpy.process import Flow, Transport
from hydromodpy.solver.modflow_nwt import Modflow, Modpath, Mt3dms
from hydromodpy.data.climatic import Climatic

cfg = HydroModPyConfig.from_toml("config.toml")

# 1. Setup
workspace  = hmp.Workspace(config=cfg.workspace)
geographic = hmp.Geographic(cfg.geographic, workspace)
domain     = Domain(config=cfg.domain, surface_topo=geographic.get_domain_surface_topo())

# 2. Donnees
climatic = Climatic(out_path=workspace.catch_folder)
climatic.update_recharge_reanalysis(...)

# 3. Processus
flow = Flow(config=cfg.flow)
flow.set_recharge(...)

# 4. Solveur flow
modflow = Modflow(geographic, model_folder=..., modflow_config=cfg.modflownwt, ...)
modflow.pre_processing(flow=flow, domain=domain, ...)
modflow.processing(...)
modflow.post_processing(...)

# 5. Solveur transport (optionnel)
transport = Transport(config=cfg.transport)
modpath = Modpath(domain, transport, modflow, ...)
modpath.pre_processing()
modpath.processing(...)
modpath.post_processing(...)

# 6. Analyse
# L'utilisateur fait ce qu'il veut : plots custom, exports, etc.
```

### 10.2 En production (TOML)

```toml
[workspace]
catch_name = "vilaine"
out_dir_path = "output/"

[geographic]
catch_def = "from_outlet_coord"
dem_init_path = "data/dem.tif"
x_outlet = 265611.0
y_outlet = 6784182.0
snap_dist = 50
buff_area = 20.0

[domain]
zone_ids = ["geology"]

[data]
types = ["geology", "hydrography"]

[flow]
flow_regime = "transient"
param_list = ["K", "Sy"]

[solver]
solver_engine = "modflownwt"

[simulation]
name = "Vilaine flow + transport"

[[simulation.process]]
id = "flow_steady"
type = "flow"
solvers = ["modflownwt"]

[[simulation.process]]
id = "particles"
type = "transport"
solvers = ["modpath"]

[postprocess]
enabled = true
```

```bash
hmp simulation config.toml
```

---

## 12. Regles de conception

### 11.1 Regles absolues

1. **Pas d'import ascendant** : un objet de couche N n'importe jamais
   de la couche N+1. `Flow` n'importe pas `simulation`. `Modflow`
   n'importe pas `launcher`.

2. **Config Pydantic = contrat** : tout parametre utilisateur passe
   par un modele Pydantic valide. Pas de `dict[str, Any]` en entree
   publique.

3. **Objets autonomes** : chaque classe doit etre instanciable et
   utilisable sans le launcher. Si ce n'est pas le cas, c'est un
   bug d'architecture.

4. **Pas de logique metier dans simulation/** : `simulation/` orchestre
   et dispatch. Toute la logique physique, numerique ou de traitement
   est dans les objets metier (process, solver, data_managers...).

5. **Un solveur = un adapter** : l'adapter est la seule couche qui
   importe la classe concrete du solveur. Le runner ne connait que
   le Protocol `SolverAdapter`.

### 11.2 Conventions

- `*_config.py` : modele Pydantic (schema de validation)
- `*_legacy.py` : compatibilite arriere, a migrer
- `prototype/` : classes abstraites de base (ABC)
- `cases/` : tests de validation integres au module
- `common/` : utilitaires partages au sein d'un package

### 11.3 Tests

```bash
# Tests rapides (unitaires)
python -m pytest -m "fast" -q -n auto

# Tests de regression (end-to-end)
python -m pytest -m regression -q -n auto

# Mise a jour des references golden
python -m pytest -m regression -q -n auto --update-goldens
```

Chaque nouveau module doit avoir :
- Au moins un test unitaire dans `tests/unit/`
- Un `cases/` avec golden test si le module produit des sorties deterministes
- Integration dans un test de regression si le module participe au pipeline

---

## 13. Feuille de route architecturale

### Fait

- [x] `ProcessContextFactory` inline dans `runner.py` (suppression de `process_context.py`)
- [x] `runtime_contracts.py` supprime (`RunContext`/`RunExecutionResult` dans `plan.py`)
- [x] `SimulationProcessConfig.type` extensible (`str` valide dynamiquement)
- [x] `register_adapter()` et `register_process_solver()` pour extension dynamique
- [x] Stubs adapters pour `postprocess/` et `display/`
- [x] Matrice de compatibilite etendue (postprocess, display)

### Court terme (a faire)

- [x] Ajouter `hmp simulation config.toml` dans le CLI (remplace `python -m hydromodpy.launchers`)
- [ ] Ajouter `hmp case <module> [sous-cas]` dans le CLI (decouverte auto des cases/)
- [ ] Ajouter `--until <phase>` au CLI launcher
- [ ] Implementer les adapters postprocess (timeseries, netcdf) — wrapping des modules existants
- [ ] Implementer les adapters display (flow, transport)
- [ ] Converger hydrometry/piezometry vers une seule API (Manager + PointRecord)
- [ ] Deprecer `settings.py` au profit de `FlowConfig` + `ModflowPreprocessOptions`
- [x] Nettoyer les marqueurs de conflit dans docs/ et process/ (aucun conflit reel trouve)

### Moyen terme

- [ ] Fusionner `planner.py` + `plan.py` si la taille le justifie
- [ ] Planner avec resolution de DAG (si workflows non-lineaires confirmes)
- [ ] Parallelisation de processus independants dans le runner
- [ ] Support PyHELP comme data manager (recharge calculee)
- [ ] Hooks lifecycle optionnels (~30 lignes, auto-decouverte hooks.py)

### Long terme

- [ ] Nouveaux solveurs (FEFLOW, HGS, ParFlow...)
- [ ] Interface web pour le TOML (generation + monitoring)
- [ ] Catalogue de donnees partage (registry PostgreSQL)
