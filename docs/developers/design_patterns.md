# Patterns de conception

La plupart des features non triviales du codebase reposent sur l'un des
patterns ci-dessous. Les connaître rend le code prévisible.

Liens : [glossary.md](glossary.md),
[simulation_catalog_architecture.md](simulation_catalog_architecture.md),
[frontend_hooks.md](frontend_hooks.md).

## 1. Protocol SolverAdapter

Emplacement : `hydromodpy/simulation/adapters/base.py`, adapters concrets
à côté de chaque backend sous `hydromodpy/solver/<backend>/adapters/`
(`solver/modflow_nwt/adapters/flow.py`, `solver/modflow6/adapters/flow.py`,
`solver/boussinesq/adapters/flow.py`, helpers partagés dans
`solver/modflow_common/flow_adapter_helpers.py`).

Un `SolverAdapter` est un Protocol qui lie une paire
`(process_type, solver_name)` à un solveur concret. Il prend un process
de domaine (`Flow`, `Transport`) et pilote la machinerie FloPy, PETSc ou
scipy sous-jacente.

```python
class SolverAdapter(Protocol):
    process_type: ClassVar[str]
    solver_name: ClassVar[str]
    def build(self, plan: ProcessRun, state: WorkflowContext) -> SolveResult: ...
```

Enregistrement dans `solver/base/registry.py`. Le planner résout
l'adapter au moment de la construction du plan ; le runner ne voit que
le Protocol.

Raison : découple le domaine (Flow, Transport) des spécificités du
solveur. Ajouter un solveur revient à écrire une classe d'adapter et une
ligne dans le registre.

## 2. Pipeline Step

Emplacement : `hydromodpy/workflow/steps/`, base dans
`hydromodpy/pipeline/step.py`.

Un step est une fonction pure `(WorkflowContext) -> WorkflowContext` (ou
un sous-contexte restreint). Chaque step met à jour exactement une scope
du contexte : setup, data-loading, mesh, solve, extract, derive, export.

```python
def resolve_support_configs(ctx: SetupContext) -> SetupContext:
    ...
```

Les steps vivent dans des fichiers courts, nommés selon leur concern, et
n'importent jamais `Project` ni le runner. La composition du pipeline est
déclarée ailleurs (`hydromodpy/workflow/pipelines/`), ce qui rend les
steps réutilisables en test.

Raison : testabilité. Chaque step est une fonction pure avec des entrées
et sorties explicites. Un nouveau workflow assemble des steps sans
forker l'orchestration.

## 3. Figure (suites d'affichage)

Emplacement : `hydromodpy/display/figure.py`, figures concrètes dans
`hydromodpy/display/figures/`.

Chaque figure nommée implémente le Protocol `Figure` :

```python
class Figure(Protocol):
    name: ClassVar[str]
    def plot(self, sim: Run, *, save_path: Path | None) -> None: ...
```

Les figures sont enregistrées par nom. Côté utilisateur :
`run.plot("watertable_map")` ou `hmp.display.get("watertable_map")`.
L'appelant décide de l'affichage ou de l'écriture ; le module display ne
l'impose pas.

Raison : rendu à la demande, cohérent entre suites, piloté par la
config `[display]` (`DisplayConfig` dans
`hydromodpy/display/config.py`) plutôt que des variables d'environnement.

## 4. Backend de délinéation

Emplacement : `hydromodpy/spatial/delineation/`.

La délinéation est agnostique du backend. Les backends integrés sont
`whitebox_workflows` et `synthetic`; les autres implementations passent
par `register_backend()` puis `get_backend()`. `DelineationBackend`
(`base.py`) decrit le contrat minimal consomme par les steps d'analyse
de flux.

```python
backend = get_backend("whitebox_workflows")
backend.flow.breach_depressions(input_dem, output_dem)
```

Raison : ajouter un backend au runtime sans publier de placeholder public.

## 5. Data Manager

Emplacement : `hydromodpy/data/base_manager.py`,
`hydromodpy/data/variables/<variable>/`.

Chaque variable d'entrée (hydrométrie, piézométrie, géologie,
hydrographie, climat) dispose d'une sous-classe de
`BaseVariableManager` :

```python
class HydrometryManager(BaseVariableManager):
    def load(self) -> LoadResult: ...
```

`LoadResult` encapsule les données fetchées et un fingerprint utilisé
pour la provenance. `DataManagersPlanner`
(`hydromodpy/data/planner.py`) résout la config explicite et les besoins
inférés en un `DataLoadPlan` immuable.

Raison : un récit uniforme fetch / cache / verify pour des sources
hétérogènes (Hubeau, BD Topage, SIM2, synthétique, custom). Ajouter une
variable revient à écrire un manager et l'enregistrer.

## 6. Config Pydantic avec Annotated

Emplacement : `hydromodpy/master_config/` et chaque `*_config.py`.

Toute la configuration est exprimée en modèles Pydantic avec
`ConfigDict(extra="forbid")`. Les champs porteurs de quantités physiques
utilisent des alias `Annotated` de `hydromodpy/core/units/` :
`Length`, `Time`, `FlowRate`, `HydraulicConductivity`, `SpecificStorage`,
`SpecificYield`, `Area`, `Volume`, `Dimensionless`. L'utilisateur peut
écrire `"50 m"` ou `"0.1 km"`.

`Profile` (`hydromodpy.core.config_kit.profile.Profile`, un `IntEnum`)
contrôle la visibilité des champs dans les TOML générés.

```python
class DomainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone_ids: list[str]
    depth_model: DepthModelConfig = Field(default_factory=...)
```

Raison : un parseur unique pour TOML, CLI et dictionnaires Python ;
export JSON Schema automatique pour les frontaux ; unités gérées en un
seul endroit.

## 7. Adaptateurs de calibration

Emplacement : `hydromodpy/calibration/adapters/`.

Un adapter de calibration branche un optimiseur concret sur le moteur.
Les adapters disponibles :

- `scipy_adapter.py` : routines scipy (Nelder-Mead, differential
  evolution).
- `optuna_adapter.py` : moteur Bayesian d'Optuna.
- `grid_adapter.py` : balayage grille.
- `gp_mapping_adapter.py` : surrogate GP, mapping paramètres.
- `da_mh_gp_adapter.py` : data-assimilation Metropolis-Hastings sur GP.

Chaque adapter expose une interface commune avec l'`engine` pour
exposer paramètres, métriques et clé de cache sans coupler l'engine au
runtime.

Raison : l'engine reste générique. Chaque stratégie d'optimisation se
branche via un adapter fin.

## 8. Objective

Emplacement : `hydromodpy/calibration/objective.py`.

Un `Objective` agrège une ou plusieurs `Metric` pondérées en une perte
scalaire. Les objectifs sont déclaratifs (configurés depuis le TOML) et
stateless : ils prennent un dict `Metrics` et retournent un float.

```python
class Objective:
    def __call__(self, metrics: Metrics) -> float: ...
```

Raison : permuter la cible de calibration (NSE débit, perte jointe
piézo-débit, moyenne multi-site) sans toucher à l'engine.

## 9. Metric

Emplacement : `hydromodpy/core/metrics/` (canon : NSE, KGE, RMSE, MAE,
log-NSE, bias, pbias, correlation), `hydromodpy/calibration/metrics.py`
(extracteur trial-side `build_metric_extractor`).

Une `Metric` est un callable qui compare une série simulée à une série
observée :

```python
class Metric(Protocol):
    name: ClassVar[str]
    def __call__(self, sim, obs) -> float: ...
```

Métriques canoniques : `nse`, `kge`, `rmse`, `mae`. Persistées dans la
table `metrics` du catalogue avec la PK `(sim_id, station_id, metric_name)`.

Raison : vocabulaire unique de noms de métriques pour calibration,
affichage, export et catalogue.

## 10. Hooks frontaux via Pydantic + JSON Schema

Emplacement : `hydromodpy/schema/`.

Tout objet destiné à piloter un widget d'UI (sélecteur de figures,
formulaire de paramètres, panneau de métriques) expose un contrat
JSON-compatible. Le paquet `schema` expose des helpers pour dumper les
modèles Pydantic en JSON Schema (CLI `hmp schema export`) et valider
partiellement un TOML édité, afin qu'un frontal puisse remonter des
erreurs champ par champ sans lever d'exception dès la première faute.

Raison : le codebase sert aussi de backend à des frontaux externes.
Garder le contrat déclaratif (Pydantic plus export schema) évite de
dupliquer la structure côté UI.

## Voir aussi

- [simulation_catalog_architecture.md](simulation_catalog_architecture.md) : couche de stockage.
- [frontend_hooks.md](frontend_hooks.md) : intégration des frontaux externes.
- [glossary.md](glossary.md) : conventions de nommage.
