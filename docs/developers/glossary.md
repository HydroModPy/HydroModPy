# Glossaire

Vocabulaire canonique HydroModPy. Ce document fait foi en cas de conflit
de nommage. Les alias listés sont interdits dans du code nouveau.

Liens : [design_patterns.md](design_patterns.md),
[simulation_catalog_architecture.md](simulation_catalog_architecture.md).

## Objets principaux

### Workspace

Répertoire racine contenant `hydromodpy.duckdb`, `data/`, `simulations/`
et `projects/`. Un workspace est mutable, représenté par la classe
`Workspace` (`hydromodpy.core.workspace.workspace.Workspace`). Résolu via
`[workspace] root` dans le TOML, la variable `HYDROMODPY_WORKSPACE`, ou
le layout scaffold.

### Project

Nom canonique : `Project`. Module :
`hydromodpy.project.Project`, exposé comme `hmp.Project`.

Façade programmatique : construite depuis un TOML, exécute via
`.run(**overrides)` et persiste le résultat dans le catalogue. Retourne
un `Run`.

Alias interdits : `Simulation`, `SimulationRunner`, `Launcher`,
`Pipeline` (ce dernier désigne un autre objet, voir plus bas).

### Run

Nom canonique : `Run`. Module : `hydromodpy.results.run.Run`, exposé
comme `hmp.Run`.

Handle en lecture seule retourné par `project.run(...)`, `catalog[sim_id]`,
`catalog.best(...)` ou l'itération sur `SimulationGroup`. Expose champs,
séries temporelles, métadonnées et `.plot(...)`.

Alias interdits : `SimulationView`, `SimulationResult`, `RunOutput`.

### Catalog

Le terme recouvre deux rôles distincts. Toujours désambiguïser.

- `SimulationCatalog` : catalogue de sortie adossé à
  `workspace/hydromodpy.duckdb`. Module
  `hydromodpy.results.catalog.SimulationCatalog`. Alias interdits :
  `ResultsCatalog`, `Catalog`, `SimulationStore`.
- `DataCatalogDuckDB` : cache d'entrée adossé à
  `workspace/data/cache.duckdb`. Module
  `hydromodpy.data.registry.catalog_duckdb.DataCatalogDuckDB`. Alias
  interdits : `DataCatalog`, `CacheCatalog`, `InputCatalog`.

### Plan (immuable)

- `SimulationPlan` : plan gelé pour une simulation. Module
  `hydromodpy.simulation.planning.plan.SimulationPlan`. Alias interdits :
  `RunPlan`, `ExecutionPlan`.
- `DataLoadPlan` : plan gelé décrivant les managers de données à invoquer.
  Module `hydromodpy.data.plan.DataLoadPlan`. Alias interdits :
  `DataPlan`, `LoadPlan`.
- `ProcessRun` : entrée d'un `SimulationPlan`. Module
  `hydromodpy.simulation.planning.plan.ProcessRun`. Alias interdits :
  `RunSpec`, `TaskSpec`.

### Pipeline et Step

- `Pipeline` : séquence ordonnée de `PipelineStep`. Module
  `hydromodpy.pipeline.pipeline.Pipeline`. Orchestration de bout en bout
  d'une simulation. Alias interdits : `Workflow`, `Runner`, `Driver`.
  Le mot *workflow* est réservé à l'auto-dispatch CLI
  (voir [CLI.md](CLI.md)).
- `PipelineStep` : unité exécutable du pipeline. Module
  `hydromodpy.pipeline.step`. Protocol paramétré en entrée/sortie
  (`PipelineStep[TIn, TOut]`). Un step n'est pas un process
  (`Flow`, `Transport`) : c'est une étape comme `MeshBuildStep`,
  `SolveStep`, `ExtractStep`.

### SolverAdapter

Interface Protocol qui lie une paire `(process_type, solver_name)` à un
solveur concret. Module : `hydromodpy.simulation.adapters.base`. Le
renommage vers `SolverRunner` est planifié mais non effectué. Le nom
`SolverAdapter` reste la référence courante.

### Backend

Moteur d'implémentation choisi au runtime. Toujours qualifier :

- Backend de solveur : moteur concret derrière un `SolverAdapter`
  (flopy, scipy, petsc).
- Backend de délinéation : `WhiteboxCLIBackend` versus
  `WhiteboxWorkflowsBackend`. Module
  `hydromodpy.spatial.delineation/`.
- Backend d'affichage : matplotlib ou pyvista, sélectionné dans
  `[display]`.

### Variable

Quantité d'entrée nommée et typée : piézométrie, hydrographie, géologie,
climat, DEM. Chaque variable dispose :

- d'un modèle Pydantic `*_config.py`,
- d'un manager `*_manager.py` sous-classant `BaseVariableManager`, avec
  une méthode `load() -> LoadResult`.

Les variables vivent dans `hydromodpy/data/variables/`.

### Manager

Sous-classe de `BaseVariableManager` responsable du chargement d'une
variable depuis ses `DataSource` configurées et de la production d'un
`LoadResult` normalisé. Une variable par manager. Les managers sont
stateless au-delà de leur config et de l'`DataCatalogDuckDB` injecté.

### Source

Implémentation du Protocol `DataSource` qui récupère un type de donnée
depuis un fournisseur : `HubEauPiezometrySource`, `SIM2Source`,
`CustomFileSource`. Enregistrement via
`@register_source(provider=..., variable=...)` dans
`hydromodpy/data/sources/`. Un manager peut interroger plusieurs sources,
une source peut nourrir plusieurs managers.

## Identifiants

### sim_id

UUID v5 déterministe :
`uuid5(HYDROMODPY_NAMESPACE, run_fingerprint)` où
`run_fingerprint = sha256(canonical_config_json + inputs_fingerprints)`.
Config identique plus entrées identiques donnent le même `sim_id`, ce qui
permet la déduplication.

### run_id

ULID de 26 caractères, triable lexicographiquement, généré à la
soumission. Plusieurs runs peuvent partager un même `sim_id`.

## Infrastructure pipeline

### PipelineState

Module : `hydromodpy.pipeline.state.PipelineState`. Dataclass frozen,
slotted, porteuse de `run_id`, `step_index`, `step_name`, `elapsed_ms` et
d'un mapping `data` non typé. C'est la seule valeur qui circule entre
étapes. Les étapes ne mutent pas : elles produisent un successeur via
`state.advance(...)`.

### CheckpointStore

Module : `hydromodpy.pipeline.checkpoint.CheckpointStore`. Persiste les
snapshots `PipelineState` à
`<workspace>/.hmp/checkpoints/<run_id>/<step_index>_<step_name>.pkl.zst`,
permettant la reprise après crash. Fallback pickle si `zstandard`
indisponible. Alias interdits : `Snapshot`, `StateCheckpoint`.

### StepsLedger

Module : `hydromodpy.pipeline.ledger.StepsLedger`. Journal DuckDB des
exécutions d'étapes, une ligne par `(run_id, step_index)` avec statut,
timestamps, durée, message d'échec. Stocké à
`<workspace>/.hmp/checkpoints/steps_ledger.duckdb`. Alias interdits :
`StepLog`, `ExecutionLog`.

### DerivedRegistry

Module : `hydromodpy.pipeline.derived.DerivedRegistry`. Registre ordonné
de `DerivedComputation` évalué par l'étape de dérivation. Résout les
dépendances via `ordered_names()` pour que les champs dérivés aval voient
leurs prérequis déjà écrits.

### ParamsHashCache

Module : `hydromodpy.calibration.cache.ParamsHashCache`. Mémoïsation
fingerprint pour dédupliquer l'évaluation de vecteurs de paramètres
identiques au sein d'une session de calibration.

## Visibilité de configuration

### Profile

Nom canonique : `Profile` (IntEnum). Module :
`hydromodpy.core.config.profile.Profile`. Trois niveaux :

- `Profile.USER` (1) : champs physiques et projet.
- `Profile.DEV` (2) : tolérances, backends, cache.
- `Profile.EXPERT` (3) : internes solveurs.

Un champ est inclus dans un TOML généré si son profil est inférieur ou
égal au profil demandé. Déclaration via `Annotated[T, Profile.X]`.

### ParamLevel (shim)

Module : `hydromodpy.core.config.param_level.ParamLevel`. Alias dataclass
legacy (`ParamLevel("user" | "dev" | "expert")`) maintenu en v0.6 pour la
compatibilité. Nouveau code : `Profile`. Retrait prévu en v0.7.

## Hygiène de nommage

- Ne pas introduire de nouvel alias pour un concept déjà listé.
- Tout nouveau nom doit d'abord figurer ici avec sa définition courte.
- Les renommages connus en cours (par exemple `SolverAdapter`
  vers `SolverRunner`) sont signalés dans cette section dès qu'ils sont
  planifiés.
