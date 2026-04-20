# Audit architectural — HydroModPy

**Auditeur** : architecte logiciel senior, toolboxes scientifiques Python
**Branche analysée** : `dev-database` (post-merge `dev-refact`, HEAD `74b62878`)
**Date** : 2026-04-17
**Portée** : architecture globale, CLI, API publique, nommage, cycle de vie, anti-patterns

---

## 0. TL;DR — verdict d'ensemble

| Dimension | Note | Synthèse |
|---|---|---|
| Découpage des packages | **À améliorer** | 10 packages avec des rôles globalement lisibles, mais règle « core ne dépend de rien » **violée en pratique** (core importe spatial/data/analysis/process/simulation/solver en haut de `hydromodpy_config.py`). |
| CLI `hmp` | **Acceptable** | Sous-commandes cohérentes, mais `__main__.py` = 1223 lignes (God module), mélange argparse + logique métier + helpers regression. Pas de completion shell, pas de `--version`. |
| API publique | **Acceptable** | Lazy imports propres dans `hydromodpy/__init__.py`. Mais `Simulation` dans `hydromodpy/project.py` au lieu de `hydromodpy/simulation/` est un piège de nommage grave. |
| Nommage | **Problématique** | `project.py` pour la classe `Simulation`, `watershed` pour un façade legacy, `process` ambigu (processus métier vs processus système), `launchers/templates/` dans `runners/`. |
| Cycle de vie TOML → résultat | **À améliorer** | Pipeline `Simulation.__init__` = 7 phases quasi-impératives inlinées, couplages cachés via `WorkflowContext`. Pas d'objet `Plan` explicite côté API haut niveau. |
| Anti-patterns | **Problématique** | God modules (jusqu'à 3409 lignes), exception hierarchy morte (0 usage sur 5 classes déclarées), `__getattr__` de `process/__init__.py` qui ne peut jamais se déclencher, duplication `flow_to_modflow_adapter.py` entre `solver/modflow6/` et `solver/modflow_nwt/`. |

L'architecture **annoncée** (CLAUDE.md, docstrings) est propre. L'architecture **réelle** souffre d'un centre de gravité inversé : le `core` devrait être feuille du DAG mais attire tout par son aggrégateur Pydantic. Le projet est dans une phase de refactor tardive et les vestiges de trois générations (Watershed legacy → launchers → runners/workflow/project) cohabitent.

---

## 1. Architecture des packages

### 1.1 Arbre de dépendances réel (produit par AST walk)

```
   ┌───────────────────────────────────────────────────────────┐
   │                    __main__  (CLI entry)                  │
   │                1223 lignes — God module                    │
   └─────────┬───────────────────────┬─────────────────────────┘
             │                       │
             ▼                       ▼
    ┌─────────────┐          ┌────────────────┐
    │  runners/   │          │   project.py   │ ◄─── API publique haut niveau
    │  (~15 l)    │────────► │  (Simulation)  │      (mal placée — voir §4)
    └─────┬───────┘          └────┬───────────┘
          │                       │
          ▼                       ▼
   ┌─────────────────────────────────────────────────────────┐
   │                     workflow/                            │
   │        (pipelines, steps, WorkflowContext)               │
   └─────────┬───────────────────────────────────────────────┘
             │
   ┌─────────┴───────────┬──────────────┬──────────────┬──────┐
   ▼                     ▼              ▼              ▼      ▼
┌─────────┐       ┌─────────────┐   ┌────────┐   ┌────────┐ ┌─────┐
│analysis │       │ simulation  │   │results/│   │ solver │ │ ... │
│         │       │(adapters,…) │   │catalog │   │3 moteurs│ │     │
└───┬─────┘       └────┬────────┘   └───┬────┘   └───┬────┘ └──┬──┘
    │                  │                │            │         │
    ▼                  ▼                ▼            ▼         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 process  (Flow, Transport, contracts)            │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                  spatial  (geographic, domain, field, mesh)     │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│   data  (managers, variables, registry, contracts)               │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  core  (config, state, time, tools, workspace, backends)        │
│           [devrait être feuille — ne l'est PAS]                 │
└─────────────────────────────────────────────────────────────────┘

LEGACY / COMPAT
┌──────────┐
│watershed/│  (façade historique Watershed — lazy imports uniquement)
└──────────┘
```

### 1.2 Edges inter-packages (compte d'imports extraits par AST)

| Source → Cible | Nb fichiers | Acceptable ? |
|---|---:|---|
| `analysis → core, data, process, project, results, simulation, solver, spatial` | — | Oui (couche haute légitime). |
| `core → analysis` | 7 | **NON** — `hydromodpy_config.py`, `generate_toml.py`. Fait monter `core` d'un niveau. |
| `core → data` | 5 | **NON** — aggrégation Pydantic en haut de module. |
| `core → process` | 6 | **NON** — idem. |
| `core → simulation` | 3 | **NON** — idem. |
| `core → solver` | 9 | **NON** — idem (+ `core/state/setup.py` en `TYPE_CHECKING` OK). |
| `core → spatial` | 11 | **NON** — idem. |
| `core → watershed` | 1 | **NON** — `core/tools/io_utils.py` appelle `from hydromodpy.watershed import Watershed` depuis une helper. Cela dit, il est dans une fonction (lazy), et la helper relève de la compat Watershed. |
| `data → analysis` | 1 | **NON** — `data/climatic/sim2.py` importe `NetcdfWriter` depuis `analysis.postprocess`. Inversion de couche. |
| `solver → process` | 11 | Acceptable (les solveurs consomment les contrats Flow/Transport). |
| `spatial → solver` | 9 | **Contestable** — `spatial/mesh/config.py`, `spatial/mesh/runtime.py` tirent des utilitaires gmsh depuis `solver/utils/`. Les utilitaires mesh gmsh ne devraient pas vivre dans `solver/`. |
| `spatial → data` | 4 | Acceptable (geology_field lit des LoadResult). |
| `runners → analysis, core, project, workflow` | — | OK. |
| `watershed → analysis, core, data, process, spatial` | — | OK (façade legacy). |

### 1.3 Verdict package par package

| Package | Rôle affiché | Réalité | Verdict |
|---|---|---|---|
| `core/` | Infrastructure feuille | **Aggrégateur transverse** : `hydromodpy_config.py` importe 13 modules de 7 packages différents. Cycle latent masqué par le fait que Python tolère les imports fils → parent tant que l'init du parent est terminé. | **Problématique** — la règle énoncée dans CLAUDE.md est fausse. |
| `data/` | Entrées (managers, cache) | Cohérent, bien nommé. Sous-packages `variables/<type>/{manager,config,result,apis,cases}` répétés 15+ fois. | **Conforme** (avec duplication structurelle signalée §6). |
| `spatial/` | Domaine géographique | Mélange geographic + mesh + field + domain + catchment_zones_field.py flottant au top. `spatial/mesh` importe `solver/utils/mesh/` — mauvaise direction. | **À améliorer** — sortir la génération gmsh de `solver/` vers `spatial/mesh/`. |
| `process/` | Physique (flow, transport) | Bon découpage. Mais `process/hydrology/` et `process/forcing/` sont en limite avec `data/` et `solver/`. Contrats centralisés dans `contracts.py` — bien. | **Conforme**. |
| `solver/` | Adaptateurs solveurs | Trois moteurs + `modflow_common/` + `utils/` qui déborde sur le maillage. `solver/utils/mesh/gmsh_grid/` ne relève pas du solveur. | **À améliorer**. |
| `simulation/` | Plan + exécution | Adapters / execution / planning / results / forcing. Le dossier `results/` ici DOUBLONNE sémantiquement `hydromodpy/results/` (catalogue). Confusion garantie. | **À améliorer** — renommer `simulation/results/` en `simulation/extraction/` ou `simulation/postrun/`. |
| `results/` | Catalogue DuckDB + Zarr | Cohérent, bien bordé, un point d'entrée clair (`SimulationCatalog`). | **Conforme** (point fort du projet). |
| `analysis/` | Post-traitement, calibration, batch, comparison, display | Très hétérogène : `calibration/engine/session.py` = 3409 l., `comparison/runtime.py` = 2061 l., `batch/runtime.py` = 1828 l. | **Problématique** (obésité, voir §6). |
| `workflow/` | Pipelines composables | Sert de glue entre `project.py` et les packages métier. Rôle légitime mais on croise `workflow/pipelines/` + `runners/` + `project.py` — trois lieux qui se partagent l'orchestration. | **À améliorer** — clarifier : qui orchestre quoi ? |
| `runners/` | Thin CLI shells (~15 l) | Respecte parfaitement la règle annoncée (12–29 l.). | **Conforme**. |
| `watershed/` | Façade historique Watershed | Bien fait pour une compat layer : pure lazy, `__getattr__`, pas d'effet de bord. | **Conforme** (mais à tuer à terme — voir §6). |

### 1.4 Comparaison avec les références du domaine

| Aspect | HydroModPy | FloPy | xarray | scikit-learn | pandas |
|---|---|---|---|---|---|
| Top-level `__init__.py` | Lazy via `__getattr__` PEP 562 | Eager re-export explicite | Eager + `__all__` strict | Eager sauf `_base` | Eager massif |
| Profondeur max (niveaux) | 6 (`solver/utils/mesh/gmsh_grid/cases/...`) | 3–4 | 3 | 3 | 3 |
| Fichier le plus gros | 3409 l. (`calibration/engine/session.py`) | 2700 l. (`modflow/mf.py`) | ~2000 l. | rare > 1500 | rare > 2000 |
| Nombre de sous-packages | 10 top + 50+ mid | 8 top | 5 top | 15 top (plats) | 10 top |
| Point d'entrée CLI | argparse monolithique | absent | absent | absent | absent |

**Observation critique** : HydroModPy imite la profondeur de FloPy mais sans son aplatissement final (FloPy pose `flopy.modflow.ModflowDis` en 2 niveaux — ici `hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning` à 6 niveaux). Les chemins d'import longs **trahissent un DAG mal factorisé**.

**Recommandation** — aplatir :
- `solver/utils/mesh/gmsh_grid/` → `spatial/mesh/gmsh/`
- `solver/utils/temporal/` → `core/time/` (ou `simulation/time/`)
- Supprimer `cases/` des sous-packages runtime (les mettre dans `validation_cases/` au niveau racine, où ils sont déjà).

---

## 2. CLI `hmp` / `hydromodpy`

### 2.1 Structure argparse

Sous-commandes : `init`, `new`, `config`, `run`, `display`, `list`, `export`, `test`.
Double binaire : `hmp` et `hydromodpy` pointent sur `__main__:main`.

| Aspect | Verdict | Détail |
|---|---|---|
| Découpage en sous-commandes | **Conforme** | Style `git`-like, comme `poetry`, `ruff`, `httpie`. |
| Longueur `__main__.py` | **Problématique** | 1223 lignes. Mélange : parsing argparse, dispatch, helpers pytest, regex regression, PROJ_DATA env, exit codes. Devrait être ≤ 300 lignes. |
| Séparation parseur / handler | **À améliorer** | Parseur et handlers co-habitent dans le même fichier. Standard : `cli/` ou `commands/` avec un fichier par sous-commande. Cf. `poetry/console/commands/`, `httpie/cli/`. |
| `--version` | **Absent** | Aucun flag `--version`. Standard absolu : `hmp --version` doit afficher `__version__`. |
| `-h` / `--help` | Conforme | argparse génère l'aide. Mais l'aide est pauvre : pas de « Examples », pas d'epilog. |
| Completion shell | **Absente** | Pas de `argcomplete`, `click.shell_completion`, ou intégration `$SHELL`. Standard : `hmp --generate-completion bash`. `poetry completions`, `ruff generate-shell-completion` en sont les exemples. |
| Exit codes | **Incohérent** | `sys.exit(1)` dans 9 endroits, `sys.exit(2)` dans 6 endroits (pour arguments incompatibles), `sys.exit(result.returncode)` pour subprocess. Pas de code 0 explicite — implicite seulement. Standard POSIX : 0 = ok, 1 = erreur générique, 2 = misuse. C'est RESPECTÉ par hasard, mais pas documenté. |
| Sous-parser par défaut | Conforme | `parser.print_help()` si aucune commande — bon. |
| Dispatch `hmp run` | Conforme | Auto-détection via `detect_workflow()` — intelligent, mais opaque pour l'utilisateur qui se demande pourquoi son TOML fait « overview » et pas « simulation ». Ajouter `--workflow` explicite. |
| Messages d'erreur stderr | Partiellement conforme | Tous les logs vont sur stderr (`file=sys.stderr`), bien. Mais mélange `print()` et `logger.info()`. |
| Subprocess pour scripts `.py` | Contestable | `hmp run script.py` lance un `subprocess.run(python script.py)` — c'est `python script.py`. Ajoute du coût pour rien. Alternative : `runpy.run_path()`. |

### 2.2 Comparaison avec les CLI de référence

| Feature | `hmp` | `poetry` | `ruff` | `httpie` | `pytest` |
|---|---|---|---|---|---|
| `--version` | ✗ | ✓ | ✓ | ✓ | ✓ |
| Completion shell | ✗ | ✓ (plugin) | ✓ | ✓ | ✓ (via plugin) |
| Help avec exemples | ✗ | ✓ | ✓ | ✓ | ✓ |
| Couleurs ANSI | ✗ | ✓ | ✓ | ✓ | ✓ |
| Sous-commandes | ✓ | ✓ | ✓ | — | — |
| Configuration via fichier | ✓ (TOML) | ✓ | ✓ | ✓ | ✓ |
| Fichier entrée ≤ 300 l. | ✗ (1223) | ✓ (~50 l. + dispatch) | ✓ (Rust) | ✓ | ✓ |
| Dry-run | ✗ | ✓ | ✓ (`--check`) | ✓ | ✓ (`--collect-only`) |

**Verdict CLI** : **Acceptable mais amateur**. Utilisable mais ne respire pas l'outil moderne. À faire :

1. Découper `__main__.py` en `cli/__init__.py` (parser), `cli/commands/<verb>.py` (un fichier par sous-commande).
2. Ajouter `hmp --version` (1 ligne).
3. Ajouter `argcomplete` (2 lignes : `# PYTHON_ARGCOMPLETE_OK` + appel).
4. Normaliser exit codes : 0 ok, 1 runtime, 2 usage, 3 config, 4 solver (permet d'automatiser).
5. Ajouter un epilog sur le parseur principal avec 3–4 exemples.

### 2.3 `hmp test` — sur-complexité

La sous-commande `hmp test` contient sa propre machinerie (`_discover_regression_tests`, `_append_regression_name_selection`, `_RE_REGRESSION`, `_append_marker_filter`) qui **dupliquent ce que pytest fait déjà**. Pytest gère déjà la collection par répertoire, les markers `-m`, la parallélisation via `-n`. La réinvention en 300 lignes :

- **Non standard** : les scientifiques ne s'attendent pas à une CLI pour lancer `pytest`. On tape `pytest tests/regression/fast/`.
- **Fragile** : `_RE_REGRESSION` parse les noms de fichiers — plusieurs conditions `_s_short`, `_new`, `_npy_` — ce genre de logique métier dans du regex sur les noms de fichiers est un *smell* majeur.
- **Dupliqué** avec les markers pytest (`@pytest.mark.fast`, `@pytest.mark.nwt`). On choisit par nom de fichier ET par marker.

**Recommandation** : supprimer `hmp test`, documenter les commandes pytest natives dans le README. Gain : ~300 lignes mortes, ~10 tests unitaires devenus inutiles (`tests/unit/test_hmp_regression_cli.py`).

---

## 3. API publique (`hydromodpy/__init__.py`)

### 3.1 Lazy imports

**Implémentation** : PEP 562 (`__getattr__` au niveau module) avec deux dictionnaires : `_MODULE_EXPORTS` (packages) et `_LAZY_IMPORTS` (classes/fonctions). Le pattern est **correct et bien fait** :

- Cache dans `globals()` après premier accès (évite de ré-importer).
- `__all__` couvre les clefs — `dir(hydromodpy)` fonctionnera pour l'introspection.
- Pas d'eager import des dépendances lourdes (matplotlib, rasterio, flopy) au chargement du package racine.

**Verdict** : **Conforme aux standards**. C'est le même pattern que `scipy.linalg` (PEP 562), `sklearn`, `xarray`. Deux bugs mineurs :

1. L'import eager de `LogManager` ligne 243 est exécuté à chaque import de `hydromodpy`, avec création d'un fichier log. Effet de bord à l'import — anti-pattern. Devrait être lazy.
2. La logique PROJ_DATA (lignes 20–227) représente **207 lignes d'infra** exécutées systématiquement à l'import. Cela pollue l'environnement (mutation de `os.environ`). À extraire dans `core.tools.proj_env` et appeler explicitement au premier besoin (dans `Geographic.__init__` par exemple).

### 3.2 Cohérence de l'API exposée

**Exposé au top-level** : `Geographic`, `Workspace`, `Modflow`, `Modpath`, `Mt3dms`, `Simulation`, `SimulationResult`, `SimulationCatalog`, `HydroModPyConfig`, `WorkspaceConfig`, `GeographicConfig`, `Hydrometry`, `Piezometry`, `Subbasin`, `HydrographyConfig`, `HydrographyManager`, `HydrographyResult`, `IntermittencyConfig`, `IntermittencyManager`, `OceanicConfig`, `OceanicManager`, `open`.

| Classe | Lisibilité pour hydrogéologue | Commentaire |
|---|---|---|
| `Geographic` | **Conforme** | Objet central clair. |
| `Workspace` | **Conforme** | OK. |
| `Simulation` | **Conforme** sémantiquement | Mais vit dans `hydromodpy/project.py` — voir §4. |
| `Modflow`, `Modpath`, `Mt3dms` | **Acceptable** | Héritage FloPy, reconnaissable. Mais pourquoi `Modflow` (= NWT) et pas `Modflow6` exposé au top ? Asymétrie non documentée. |
| `Hydrometry`, `Piezometry` | **Conforme** | Vocabulaire hydrogéo. |
| `SimulationCatalog` | **Conforme** | Bien nommé. |
| `open(workspace_path)` | **Conforme** | Mimique `xarray.open_dataset`, `pandas.read_csv`. Bon. |
| `HydrographyConfig`, `HydrographyManager`, `HydrographyResult`, `IntermittencyConfig`, `IntermittencyManager`, `OceanicConfig`, `OceanicManager`, `HydrographyManager` | **Problématique** | 7 classes d'une même variable exposées au top — pollution de l'espace de noms. Un hydrogéologue ne veut pas choisir entre `HydrographyConfig` vs `HydrographyManager`. Alternative : n'exposer que `hydromodpy.data.hydrography` en sous-module. |
| `Subbasin` | **Acceptable** | Une classe top-level isolée (aucune autre entité spatiale à ce niveau) — incohérence. |

**Recommandation API publique minimale** — ne garder que :
`Workspace`, `Geographic`, `Simulation`, `SimulationResult`, `SimulationCatalog`, `HydroModPyConfig`, `Modflow`, `Modflow6`, `Modpath`, `Mt3dms`, `Boussinesq`, `open`, sous-modules (`hmp.data.hydrometry`, `hmp.data.piezometry`, etc.).

**Absence notable** : `Boussinesq` n'est PAS exposé au top-level alors que `Modflow` l'est. Asymétrie grave pour un solveur de première classe du projet.

---

## 4. Nommage

| Nom actuel | Emplacement | Problème | Proposition |
|---|---|---|---|
| `hydromodpy/project.py` contient la classe `Simulation` | Racine du package | **Dissonance flagrante** : le fichier s'appelle `project`, la classe `Simulation`, et les attributs internes l'appellent `self._project_name`. Le code dans `runners/simulation.py` écrit `with Simulation(config_path) as project`. Quatre mots (project, simulation, run, catalog) se recouvrent. | Renommer fichier en `hydromodpy/simulation.py` ET déplacer dans `hydromodpy/simulation/` (déjà existant), probablement `hydromodpy/simulation/__init__.py` ou `hydromodpy/simulation/api.py`. Aligner : le fichier, la classe, les usages. |
| `hydromodpy/watershed/` | Top-level | Façade historique d'un workflow mort (« Watershed » pré-refactor). Induit un débutant en erreur (« dois-je commencer par `Watershed` ou `Geographic` ? »). Le merge vient de tuer la couche `launchers/` — même traitement pour `watershed/`. | Marquer `DeprecationWarning` sur chaque import. Planifier suppression. |
| `hydromodpy/process/` | Top-level | Polysémie : en Python, « process » évoque `multiprocessing`. Dans HydroModPy c'est « processus physique » (flow, transport). | Garder `process` si on assume le vocabulaire scientifique, OU renommer `physics/`. Le vocabulaire DSL / domaine-driven design pointe vers `physics/`. |
| `runners/templates/model_calibration.py` | `runners/` | Contradiction : `runners/` est censé être des « thin CLI shells ≤ 30 lignes ». `templates/` dedans ? Template pour quoi ? C'est un vestige de la migration `launchers/` → `runners/`. | Déplacer `runners/templates/` vers `analysis/calibration/templates/` (contenu métier, pas CLI). |
| `hydromodpy/results/` vs `hydromodpy/simulation/results/` | Deux packages `results/` | Confusion certaine. Le premier est le catalogue DuckDB+Zarr, le second contient des extracteurs post-run. | Renommer `simulation/results/` → `simulation/extraction/` (ce sont des `extractors`). |
| `simulation/adapters/` et `solver/modflow6/flow_to_modflow_adapter.py`, `solver/modflow_nwt/flow_to_modflow_adapter.py` | Plusieurs « adapter » | Deux notions d'adapter : l'un relie `(Process, Solver)`, l'autre convertit `Flow → MODFLOW`. Homonymie dangereuse. | Renommer les seconds `flow_to_modflow_translator.py` (ce sont des traducteurs de schéma). |
| `hydromodpy/core/backends/` | `core/` | Ne contient que le backend Whitebox. Le mot « backends » au pluriel promet plusieurs, alors qu'on en a un seul. | Renommer `core/whitebox/` OU `core/dem_backends/`. |
| `capability_gallery.py` au top de `analysis/` | `analysis/` | Nom non standard, marketing plutôt que technique. Que fait-il ? Un modèle Pydantic pour une gallerie d'exemples. Ça devrait être dans `docs/` ou `tools/doc_gallery/`. | Déplacer en `tools/doc_gallery/config.py`. |
| `SinkSource` (classe) | `process.contracts` | Non PEP 8 conforme (concept flou). Alternative : `SourceTerm` (standard en PDE). | Renommer `SourceTerm`. |
| `_derive_run_id_from_filename` | `__main__.py` et `core/config/hydromodpy_config.py` | **Duplicata strict** du même nom (fonction dupliquée dans deux modules). | Factoriser dans `core/tools/run_id.py`. |
| `_ensure_simulation_block` | `project.py` | Méthode privée qui mute la config. Nom révélateur d'un kludge (« au cas où y'a pas de section, on en fabrique une »). | Gérer la synthèse en amont dans `SimulationConfig.ensure_defaults()`. |

### 4.1 Modules `*_config.py` et `*_manager.py`

Le projet a posé la convention (CLAUDE.md) : `foo_config.py` pour le modèle Pydantic, `foo_manager.py` pour le `BaseVariableManager`. **Bien respectée** dans `data/variables/*/`.

Petit défaut : `hydromodpy_config.py` n'a pas de préfixe de package (il s'appelle `hydromodpy_config.py` dans `core/config/`). Suivre la convention donnerait `aggregate_config.py` ou `root_config.py`.

---

## 5. Cycle de vie TOML → résultat

### 5.1 Pipeline observé dans `project.py`

```
1. Charger TOML (HydroModPyConfig.from_toml + raw dict)
2. Détecter solveur (via section présente ou [[simulation.process]])
3. Ensure simulation block (synthèse si absent)
4. Appliquer time window aux tgrids (apply_explicit_time_window_to_tgrids)
5. Résoudre les sections mesh optionnelles
6. Construire registry de spatial supports
7. Planifier les data managers (DataManagersPlanner)
8. Instancier WorkflowContext
9. Construire PostprocessRunner
10. prepare_simulation_runtime(ctx, ...) ← pipeline cachée
11. Ouvrir SimulationCatalog
12. run() ← construit plan, lance SimulationRunner, écrit Zarr/DuckDB
```

**Verdict** : **Pipeline spaghetti déguisé en procédure**.

### 5.2 Anti-patterns observés

1. **God constructor** : `Simulation.__init__` (lignes 168–311) fait 140 lignes. Sept phases inlinées. Nom de paramètre `headless` muter des attributs en cascade (`cfg.display.enabled`, `cfg.display.show`, `cfg.display.save`, `cfg.postprocess.enabled`) : c'est une mutation de config au post-chargement, surprise.

2. **Mutations cachées** : `prepare_geographic_config_for_meshing(...)` réécrit `self.cfg.geographic`. `apply_explicit_time_window_to_tgrids(self.cfg)` mute la config sur place. Pour un modèle Pydantic `extra="forbid"`, on s'attendrait à l'immutabilité (`model_copy(update=...)`) — ici on mute.

3. **Couplages cachés via WorkflowContext** : `self._ctx.setup.workspace`, `self._ctx.setup.time_grid`, `self._ctx.postprocess_runner`, `self._ctx.execution.simulation_plan`, `self._ctx.setup.flow_runtime_overrides`, ... **15+ attributs** attachés dynamiquement à un dataclass. C'est un **bus de données** déguisé. Signe que la segmentation `SetupContext` / `LoadedDataContext` / `ExecutionRegistry` ne tient pas face à la réalité.

4. **Double chemin d'exécution dans `run()`** : `_run_with_overrides` vs `_run_from_plan`. Ils font deux choses similaires, mais les overrides construisent un plan minimal *ad hoc* (un seul `ProcessRun`). Les deux chemins synchronisent manuellement le même ensemble d'attributs (`self._ctx.setup.run_id`, `self._ctx.execution.simulation_plan`, etc.). Duplication fragile.

5. **Contexte temporaire fabriqué** : lignes 490–496, construction d'un `_tmp_ctx` artificiel via `type("_Ctx", (), {...})()` pour passer à `step_persist_forcings`. **Smell** : la signature de `step_persist_forcings` est mal choisie — elle devrait prendre les paramètres explicitement.

6. **Gestion d'exceptions minimaliste** : `try/except Exception: pass` dans le calcul du `mesh_hash` (ligne 432–436) et dans le dump de la config (ligne 418–421). Suppression silencieuse d'erreurs, anti-pattern classique.

### 5.3 Flux bout-en-bout

```
   TOML file
      │
      ▼
┌────────────────────────────┐
│ HydroModPyConfig           │◄─── Pydantic aggregator
│  .from_toml()              │     (importe 13 modules d'autres packages)
└──────┬─────────────────────┘
       │
       ▼
┌────────────────────────────┐
│ Simulation.__init__        │  7 phases inlinées
│  (project.py, 140 lignes)  │  mute self.cfg au passage
└──────┬─────────────────────┘
       │   (WorkflowContext bus)
       ▼
┌────────────────────────────┐
│ DataManagersPlanner.build  │  construit DataLoadPlan
└──────┬─────────────────────┘
       │
       ▼
┌────────────────────────────┐
│ prepare_simulation_runtime │  ← étape opaque depuis workflow/pipelines
└──────┬─────────────────────┘
       │
       ▼
┌────────────────────────────┐
│ Simulation.run(**overrides)│
│   _run_with_overrides      │  ← ou _run_from_plan — duplication
│                            │
│   register_simulation()    │  ← SQL DuckDB
│   write_mesh()             │  ← Zarr
│   persist_geographic()     │
│   step_persist_forcings()  │  (via _tmp_ctx synthétique)
│                            │
│   SimulationRunner.execute │  ← boucle sur plan.runs
│     callback after_run     │
│     callback after_process │
│                            │
│   store.finalize()         │
└──────┬─────────────────────┘
       │
       ▼
   SimulationResult (lazy views)
      │
      ▼
   DuckDB tables + Zarr arrays
```

**Verdict cycle de vie** : **lisible à 70 %**. Les noms de méthodes sont bons, mais trois couches d'orchestration (`project.py`, `workflow/pipelines/`, `runners/`) font le même travail sous des formes différentes. Recommandation : **un seul orchestrateur par workflow**, documenté et testé comme tel.

---

## 6. Anti-patterns détectés

### 6.1 God modules (LOC > 1500)

| Fichier | Lignes | Gravité | Action |
|---|---:|---|---|
| `analysis/calibration/engine/session.py` | **3409** | Critique | Découper en `session_state.py`, `session_orchestration.py`, `session_io.py`, `session_reports.py`. |
| `solver/modflow6/modflow6.py` | **2900** | Critique | Découper par phase : `discretization.py`, `packages.py`, `output.py` déjà existent en voisinage — les utiliser. |
| `analysis/comparison/runtime.py` | **2061** | Majeure | Découper par type de comparaison. |
| `analysis/comparison/visuals.py` | **1997** | Majeure | Découper par planche de figures. |
| `analysis/batch/runtime.py` | **1828** | Majeure | Découper. |
| `solver/boussinesq/boussinesq.py` | **1667** | Majeure | Moins critique : beaucoup a déjà été extrait post-merge (voir `assembly/`, `drivers/`, `runtimes/`). |
| `solver/modflow_nwt/modflow/flow_to_modflow_adapter.py` | 1392 | Modérée | Partage code avec `solver/modflow6/flow_to_modflow_adapter.py` — factoriser dans `solver/modflow_common/`. |
| `analysis/display/export_vtuvtk.py` | 1258 | Modérée | Fichier de fonctions exportant VTK — candidat à découpe fonctionnelle. |
| `hydromodpy/__main__.py` | **1223** | Critique | §2. |
| `analysis/calibration/engine/output_selection.py` | 1177 | Modérée | Selon hypothèse : sélection de sorties par objectif. À découper. |

### 6.2 Exception hierarchy morte

`hydromodpy/exceptions.py` déclare `HydroModPyError`, `ConfigError`, `SolverError`, `DataError`, `MeshError`.

**Zéro** `raise` de ces classes dans le code (`grep -rn "raise HydroModPyError\|raise ConfigError\|raise SolverError\|raise DataError\|raise MeshError"` → 0 résultats). **Zéro** import de ce module dans `hydromodpy/` (hors définition elle-même).

En revanche : **~1900** `raise ValueError` / `raise RuntimeError` dans le projet.

**Verdict** : code mort à 100 %. Soit le fichier est supprimé, soit on introduit réellement la hiérarchie. Standard scikit-learn : `NotFittedError`, `ConvergenceWarning`, `DataConversionWarning` **sont réellement raisées**.

### 6.3 `__getattr__` de `process/__init__.py` inopérant

```python
from hydromodpy.process.base import (
    BoundaryCondition, InitialCondition, Process, ProcessSpatial,
    ProcessSpatialConfig, SinkSource,
)
...
def __getattr__(name: str):
    if name in _LEGACY_CONTRACT_NAMES:
        warnings.warn(..., DeprecationWarning, stacklevel=2)
        return getattr(contracts, name)
    raise AttributeError(...)
```

`BoundaryCondition` etc. sont **eager-importées** au top. Python n'appelle `__getattr__` que quand la lookup normale échoue. Donc `import hydromodpy.process as p; p.BoundaryCondition` **ne déclenchera jamais** le warning. Le code de deprecation est fonctionnellement mort.

**Fix** : soit supprimer les eager imports de ces noms (et laisser `__getattr__` faire son travail), soit supprimer `__getattr__`.

### 6.4 Duplications majeures

| Duplication | Fichiers concernés | Recommandation |
|---|---|---|
| `flow_to_modflow_adapter.py` | `solver/modflow6/` (1 f.) + `solver/modflow_nwt/` (1 f.) | Factoriser le tronc commun dans `solver/modflow_common/flow_translator.py`. |
| `_derive_run_id_from_filename` | `__main__.py` + `core/config/hydromodpy_config.py` | Extraire `core/tools/run_id.py`. |
| Structure `variables/<type>/{manager,config,result,apis,cases}` | 15+ fois dans `data/variables/` et dans `data/{hydrometry,geology,oceanic,piezometry}/` | Il existe DEUX chemins (anciens `data/hydrometry/` et nouveaux `data/variables/hydrometry/`). Confirmer, puis supprimer l'ancien. |
| `cases/` dans packages runtime | 10 packages (`spatial/`, `data/*`, `solver/utils/*`, etc.) | Déplacer vers `validation_cases/` ou `examples/` au niveau racine — pas dans le package publiable. |
| `runtime_*.py` et `*_runtime.py` | `spatial/mesh/runtime*.py`, `solver/boussinesq/runtime_*.py` | Convention incohérente. Choisir un suffixe (`_runtime.py`) et s'y tenir. |

### 6.5 Leaky abstractions

- **`ProcessCallbacks`** dans `SimulationRunner` : `after_run`, `after_process` avec paramètres typés vaguement (`run, result, state`, `process_type`). Pas de contrat explicite. Le consommateur (`project.py:516`) doit savoir ce qui est passé.
- **`_store` duck-typé** : `simulation/results/extractors/*.py` acceptent un `store` « duck-typed ». Au moins documenté dans CLAUDE.md, mais sans protocol typing formel → piège à régression silencieuse. Introduire un `Protocol` typé.
- **`self._ctx.setup.flow_runtime_overrides`** : dictionnaire anonyme `{"source": str, "properties": dict}`. Pas de schéma, pas de type. Utilisé par la calibration pour injecter des params spatiaux.

### 6.6 Feature envy

- `project.py:Simulation._run_with_overrides` manipule intensivement `flow.parameters[key].value = ...`, `flow.sinks_sources["recharge"].first_clim = ...`. Ces mutations appartiennent à `Flow` lui-même (méthode `Flow.with_overrides(...)`). La classe `Simulation` connaît trop les internes de `Flow`.

### 6.7 Over-engineering

- `WorkflowContext` triple-niveau (`SetupContext`, `LoadedDataContext`, `ExecutionRegistry`) : la frontière entre les trois est floue, et les attributs circulent entre eux. Un unique `RunContext` plat serait plus honnête.
- `ensure_flow`, `ensure_process_context`, `ensure_transport` exposés au top-level `simulation` : des helpers impératifs déguisés en API — odeur de procédural.
- Le `data_managers_config.py` + `data_managers.py` + `planner.py` + `plan.py` : quatre modules pour orchestrer 15 variables. `DataLoadPlan` est un dataclass de 5 champs. À consolider.

### 6.8 Under-engineering

- Typage `Any` massif dans `project.py` (`store: Any`). Alors que `SimulationCatalog` est connu.
- **Aucun `Protocol`** pour `Store`. Typing via duck-typing bloque mypy/pyright.
- Pas de tests unitaires sur `Simulation` en tant que classe (voir `tests/unit/simulation/`) — ils testent les helpers mais pas la classe publique top-level.

### 6.9 Code mort détecté

| Élément | Localisation | Preuve |
|---|---|---|
| `hydromodpy/exceptions.py` | — | 0 usage. |
| `__getattr__` deprecation de `process/__init__.py` | — | Noms eager-importés → jamais déclenché. |
| `display_parser --save` flag | `__main__.py:1029` | Jamais lu dans `_cmd_display` — option fantôme. |
| `--normal` flag (alias `--fast`) | `__main__.py:1151` | Marqué « deprecated » dans l'aide mais toujours présent. |

---

## 7. Récapitulatif par thème

### 7.1 Tableau synthétique

| # | Thème | État | Action prioritaire |
|---|---|---|---|
| 1 | Découpage des packages | À améliorer | Retirer les imports `hydromodpy_config.py → {solver, spatial, data, analysis, process, simulation}` (TYPE_CHECKING ou lazy factories). |
| 2 | CLI | Acceptable | Découper `__main__.py` en `cli/`, ajouter `--version`, `argcomplete`. Supprimer `hmp test`. |
| 3 | API publique | Acceptable | Déplacer `project.py` → `simulation/api.py`. Exposer `Boussinesq` au top-level. Retirer les `Config/Manager/Result` des variables du top-level. |
| 4 | Nommage | Problématique | 10 renommages listés §4. Priorité : `project.py` → `simulation.py`. |
| 5 | Cycle de vie | À améliorer | Factoriser `_run_with_overrides` et `_run_from_plan`. Sortir les mutations de config de `Simulation.__init__`. Retirer `_tmp_ctx` kludge. |
| 6 | Anti-patterns | Problématique | Supprimer `exceptions.py` OU l'utiliser. Fixer `__getattr__` `process/__init__.py`. Découper les 10 God modules. Factoriser les 2 adapters `flow_to_modflow_adapter.py`. |
| 7 | Dépendances inter-packages | Problématique | `core` doit devenir feuille. Dépendance `spatial → solver` à inverser (`spatial/mesh/gmsh/`). Dépendance `data → analysis` à casser. |

### 7.2 Conformité aux standards

| Standard | Respect | Preuve |
|---|---|---|
| PEP 8 (naming) | 80 % | `SinkSource`, `HydroModPyConfig` (MixedCase conforme). Quelques modules au nom discutable. |
| PEP 257 (docstrings) | 70 % | Docstrings présentes sur les classes publiques, variables. Beaucoup de fonctions internes sans docstring. |
| PEP 561 (typing) | 60 % | Typings présents, mais `Any` fréquent (`store: Any`, `**overrides`). Pas de `py.typed` marker. |
| PEP 562 (`__getattr__` module) | ✓ | Utilisé correctement en 5 endroits. Un bug inopérant (process). |
| Ruff/black | N/A | CLAUDE.md dit « No linting or formatting tools configured. Do not attempt to run them. » — Choix assumé mais **non standard** pour un projet scientifique moderne (xarray, sklearn, pandas utilisent ruff/black). |
| SemVer | 0.3.5 | Format OK. Pas de changelog structuré visible. |
| CF Conventions (NetCDF) | Partielle | Export NetCDF présent. Conformité CF-1.x non garantie (à auditer dans un autre rapport). |
| UGRID (maillages non structurés) | Non documentée | Zarr `mesh/` contient `vertices`, `face_node_connectivity`, `z_interfaces`. Le vocabulaire correspond à UGRID-1.0 — mais nulle part les attributs CF (`cf_role = "mesh_topology"`, `topology_dimension = 2`, etc.) ne sont visibles. **À vérifier**. |
| MODFLOW-6 DISV / DIS | Conforme (via FloPy) | L'adaptateur `flow_to_modflow_adapter.py` utilise les conventions FloPy — OK pour les maillages structurés. Pour DISV (non structuré), vérifier ordering des nœuds (sens trigonométrique). |
| `pyproject.toml` PEP 621 | Conforme | `[project]`, `[project.scripts]`, `[tool.setuptools]` bien structurés. |

---

## 8. Recommandations priorisées

### Priorité 1 — fondations (1–2 semaines)

1. **Découpler `core/config/hydromodpy_config.py`** : passer en imports lazy (`from hydromodpy.spatial.domain.domain_config import DomainConfig` dans une fabrique). Permet de restaurer « core ne dépend de rien ».
2. **Renommer `hydromodpy/project.py` → `hydromodpy/simulation/api.py`** et dé-exposer `Simulation` de `hydromodpy.project`. Laisser une re-export avec DeprecationWarning pendant une version.
3. **Supprimer `hydromodpy/exceptions.py`** (fichier mort) OU commencer à l'utiliser dans les endroits les plus critiques (`ConfigError` pour Pydantic validation, `SolverError` pour échecs MODFLOW).
4. **Fixer `process/__init__.py`** : soit supprimer les eager imports des noms legacy, soit supprimer le `__getattr__` hypocrite.
5. **Découper `__main__.py`** en `hydromodpy/cli/` avec un fichier par sous-commande.

### Priorité 2 — réduire la surface (2–4 semaines)

6. **Supprimer `hmp test`** (~300 l. de CLI + 10 tests). Remplacer par doc pytest.
7. **Tuer `launchers/templates/` dans `runners/`** : déplacer en `analysis/calibration/templates/`.
8. **Déplacer `solver/utils/mesh/gmsh_grid/` → `spatial/mesh/gmsh/`** : inverse la dépendance `spatial → solver`.
9. **Consolider `data/hydrometry/`, `data/oceanic/`, `data/piezometry/`** avec `data/variables/<type>/` (post-merge incohérence).
10. **Enlever tous les `cases/` des packages runtime** — ils appartiennent à `validation_cases/` ou `examples/`.

### Priorité 3 — confort industriel (mois)

11. **Ajouter `hmp --version`, completion shell, exit codes documentés**.
12. **Factoriser les God modules** (`session.py` 3409 l., `modflow6.py` 2900 l., `comparison/runtime.py` 2061 l.).
13. **Remplacer `Any` par `Protocol`** pour `store`, pour les `ProcessCallbacks`, pour `flow_runtime_overrides`.
14. **Introduire `ruff` en CI** (check-only, pas de reformat obligatoire). Beaucoup de projets scientifiques modernes le font ; CLAUDE.md interdit mais c'est un choix à reconsidérer.
15. **Déprécier puis supprimer `watershed/`** (pair avec la mort de `launchers/`).

---

## 9. Points forts (à préserver)

Tout n'est pas à jeter. Éléments solides :

- **`SimulationCatalog` + Zarr par simulation** : architecture stockage excellente. Séparation claire (DuckDB pour métadonnées/timeseries, Zarr pour champs spatiaux). Compression BLOSC-ZSTD par défaut.
- **Lazy imports au top-level `__init__.py`** : PEP 562 propre, `__all__` cohérent.
- **Protocol-based solver adapters** : `SolverAdapter` dans `simulation/adapters/base.py` — bonne abstraction, extensibilité pour de nouveaux solveurs.
- **Immutable `SimulationPlan` / `ProcessRun`** : `@dataclass(frozen=True)` — discipline respectée.
- **`runners/` thin shells** : 12–29 lignes chacun, exactement le cahier des charges.
- **Tests bien découpés** : unit/regression (fast, extensive)/validation, markers pytest cohérents.
- **Registre de backends Whitebox** : `core/backends/` avec cache — bon pattern pour des dépendances lourdes.

---

## 10. Fin

**Jugement final** : projet scientifique **de maturité moyenne**, avec une direction architecturale ambitieuse (Simulation Catalog, WorkflowContext, Protocol adapters) mais une **exécution partiellement aboutie**. Le merge récent `dev-refact → dev-database` a introduit 487 fichiers neufs — beaucoup de code *transitionnel* coexiste avec du code *cible*. La règle énoncée « core ne dépend de rien » est *aspirationnelle*, pas observée.

Les trois priorités d'attaque : **(1)** découpler `core` en le rendant feuille du DAG, **(2)** renommer `project.py` + déplacer `Simulation` au bon endroit, **(3)** trancher le code mort (`exceptions.py`, `watershed/`, `__getattr__` de `process`).

Sans ces trois chantiers, les audits ultérieurs trouveront toujours le même code vieux à côté du code neuf.
