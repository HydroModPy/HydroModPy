# Audit d'architecture globale — HydroModPy

> **Auditeur** : Architecte logiciel senior (Python scientifique, 15 ans)
> **Périmètre** : arborescence `hydromodpy/`, CLI, API publique, cycle de vie
> **Date** : 2026-04-17
> **Branche** : `dev-database`

Cet audit compare **systématiquement** HydroModPy à quatre références de l'écosystème
scientifique Python : **FloPy** (référence domaine MODFLOW), **xarray** (orchestration
de backends lazy), **scikit-learn** (API fit/transform/predict), **PyGMT** (wrapper
CLI + scientifique). Les jugements sont sans complaisance.

---

## Synthèse exécutive

| Domaine | Note globale | Commentaire |
|---|---|---|
| Découpage en packages | **Acceptable** | Logique mais surdécoupé par rapport à FloPy/xarray |
| Graphe de dépendances | **À améliorer** | `core/` n'est **pas** un noyau sans dépendance, contrairement à ce qu'affirme `CLAUDE.md`. Circuits résolus par imports tardifs. |
| CLI (`hmp`) | **À améliorer** | Absence de `--version`, pas de completion, pas de `-v/-q`, codes de sortie incohérents |
| API publique | **Acceptable** | Lazy import correct mais `_LAZY_IMPORTS` pointe des modules là où il devrait pointer des classes (bug silencieux) |
| Nommage | **Acceptable** | PEP8 respecté. « Launcher » non idiomatique, abréviations `Mt3dms` discutables |
| Cycle de vie TOML → résultat | **Problématique** | 7 « phases » dans `Simulation.__init__`, 18 imports tardifs, accouplement implicite via `WorkflowContext` |
| Anti-patterns | **Problématique** | `try/except: pass` silencieux, God-init, duplication de `SimulationResult`/`Simulation`/`Simulation` (3 classes homonymes) |
| Tests excessifs | **À améliorer** | Trois tiers (unit/regression fast/extensive + validation) sont **sains** ; la machinerie de discovery dans `__main__.py` (200 lignes) est surdimensionnée |

**Verdict global : 5,5/10.** Le projet est **techniquement sérieux** (catalogue DuckDB + Zarr,
adaptateurs solver sous `Protocol`, `Pydantic` partout) mais **surstratifié** pour un outil
de ~100 modules. Les conventions industrielles ne sont pas toujours respectées et
la couche `runners/`/`workflow/`/`simulation/`/`analysis/` empile trois abstractions
d'orchestration pour faire le travail qu'`xarray.open_dataset` ou `sklearn.Pipeline`
accomplissent en une.

---

## 1. Architecture des packages

### 1.1 Inventaire et verdict package par package

| Package | Rôle déclaré (`CLAUDE.md`) | Réalité | Verdict |
|---|---|---|---|
| `core/` | Infra sans dépendance externe | **Importe `spatial.*`, `data.*`, `analysis.postprocess` transitivement** | **Non-conforme** au principe annoncé |
| `data/` | Entrées, managers, cache | Cohérent ; contient `DataManagersPlanner` + sous-paquet `variables/` | Conforme |
| `spatial/` | Domaine spatial | Mélange primitives (4 fichiers racine) et sous-paquets domaine (4) | Acceptable |
| `process/` | Processus physiques | Base ABC + Flow/Transport. Cohérent. | Conforme |
| `solver/` | Interfaces solver | 4 solveurs + `compatibility.py` à la racine | Conforme |
| `simulation/` | Orchestration | `planning/`, `execution/`, `adapters/`, `results/`, `forcing/`, `settings.py` | **Redondant** avec `workflow/` et `results/` |
| `analysis/` | Post-traitement, calibration, batch | 5 sous-paquets ; `capability_gallery.py` orphelin mais utilisé | Acceptable |
| `results/` | Catalogue DuckDB + Zarr | Bon design. Chevauche `simulation/results/`. | À améliorer |
| `workflow/` | Pipelines composables | `pipelines/`, `steps/`, `context.py`. Importé par `project.py` ET par `runners/`. | **Redondant** avec `simulation/execution/` |
| `watershed/` | API « historique » | **Shim legacy** (re-exporte `data.variables.*`, `simulation.settings`). Zéro valeur ajoutée. | **Problématique** (à supprimer) |
| `runners/` | Shells CLI | 5 fichiers de ~15 lignes chacun. Trop fin. | **Surdécoupé** |

### 1.2 Principe « `core/` ne dépend de rien » : **NON respecté**

Le `CLAUDE.md` affirme :

> *"`core/` depends on nothing."*

C'est **faux**. Le `core/__init__.py` importe `core.state.WorkflowContext`, lequel
attend des types venant de `data/`, `spatial/`, `process/`. Le graphe réel montre
que `core/` joue à la fois le rôle de **racine de types** (`Workspace`, `Config`)
et de **racine de contexte d'exécution** (`WorkflowContext` qui connaît tout le reste).

**Comparaison FloPy** : `flopy.utils` ne touche pas aux modèles. `flopy.modflow`
et `flopy.mf6` ne se connaissent pas. HydroModPy a **un** `WorkflowContext`
monolithique traversant toutes les couches.

**Recommandation** :

- Déplacer `WorkflowContext`, `ExecutionRegistry`, `SetupContext`, `LoadedDataContext`
  hors de `core/` vers `simulation/context.py` (ou `runtime/`).
- Renommer `core/` en `config/` (car c'est son rôle principal) ou en `foundation/`.
- Conserver `core/units/`, `core/time/`, `core/tools/` comme véritables briques basses.

### 1.3 `hydromodpy/watershed/` : dette pure

```text
hydromodpy/watershed/__init__.py
    from hydromodpy.data.variables.geology.config import GeologyConfig
    from hydromodpy.data.variables.hydrography.result import HydrographyResult as Hydrography
    from hydromodpy.data.variables.intermittency.manager import IntermittencyManager
    from hydromodpy.simulation.settings import Settings
    from hydromodpy.watershed.hydraulic import Hydraulic
    from hydromodpy.watershed.watershed import Watershed
```

Le module ne fait que **re-exporter** des symboles. Il ajoute confusion en plaçant
`Watershed` dans un paquet de nom identique. À supprimer ; les deux fichiers utiles
(`hydraulic.py`, `watershed.py`) doivent rejoindre `analysis/` ou `spatial/geographic/`.

**Verdict** : **Dead-code shim** à éliminer lors du prochain major.

### 1.4 `simulation/` vs `workflow/` vs `runners/` : triple orchestration

Trois paquets d'orchestration coexistent :

| Paquet | Contenu | Question |
|---|---|---|
| `runners/` | 5 fonctions `run(config_path)` de 10 lignes | Pourquoi un paquet pour 5 dispatchs ? |
| `workflow/pipelines/` | `SimulationLauncher`, `MeshCatchmentLauncher`, `DataOverviewLauncher` | Anciens launchers renommés |
| `simulation/execution/` | `SimulationRunner`, `ProcessCallbacks` | Moteur d'exécution bas-niveau |
| `simulation/planning/` | `SimulationPlanner`, `SimulationPlan` | Construction immutable du plan |

**Diagnostic** : l'équipe a fait *deux* refactorisations successives (extraction
en `workflow/`, puis extraction en `runners/`) sans **supprimer** les couches
précédentes. Résultat : `hmp run config.toml` traverse
`__main__._cmd_run` → `runners/simulation.run` → `project.Simulation` →
`workflow.pipelines.simulation.prepare_simulation_runtime` →
`simulation.SimulationRunner` → `simulation.adapters.*`. **6 niveaux d'indirection**
pour une tâche linéaire.

**Comparaison scikit-learn** :

```python
pipe = Pipeline([("scaler", StandardScaler()), ("clf", SVC())])
pipe.fit(X, y)
```

Deux niveaux, fin. PyGMT, xarray : idem.

**Recommandation** :
- Fusionner `runners/` dans `__main__.py` (cinq `elif workflow == "x"` suffisent).
- Supprimer `workflow/pipelines/` ; déplacer son contenu dans `simulation/pipelines/`.
- Conserver `simulation/planning/` + `simulation/execution/` comme moteur.

### 1.5 `results/` et `simulation/results/` : chevauchement

- `hydromodpy/results/` : **stockage** (catalogue DuckDB, Zarr, exporters).
- `hydromodpy/simulation/results/` : **extraction** post-exécution depuis les
  solveurs, écriture vers le catalogue.

Le second dépend du premier (`simulation/results/` écrit dans `SimulationCatalog`).
C'est un sens correct, mais la dénomination est **trompeuse** (un utilisateur
cherchant « où sont gérés les résultats » aura à lire les deux).

**Recommandation** : renommer `simulation/results/` en `simulation/extractors/`
(aligné avec `simulation/adapters/`).

### 1.6 Tableau récapitulatif

| Découpage | Verdict | Justification | Recommandation |
|---|---|---|---|
| 12 paquets pour ~100 modules | **À améliorer** | Surdécoupé ; xarray fait avec 6, scikit-learn avec ~15 pour 10× plus de code | Fusionner `runners/` + `workflow/pipelines/` dans `simulation/` |
| `core/` prétend sans dépendance | **Non-conforme** | Importe depuis `state/` qui connaît le reste | Déplacer `state/` hors de `core/` |
| `watershed/` existe | **Problématique** | Pur shim legacy | Supprimer |
| `results/` + `simulation/results/` | **À améliorer** | Noms trop proches | Renommer le second en `extractors/` |

---

## 2. Interface en ligne de commande (CLI)

### 2.1 Points positifs

- **Sous-commandes claires** (`init`, `new`, `config`, `run`, `display`, `list`, `export`, `test`).
  Structure argparse standard.
- **Double entrée** `hmp` + `hydromodpy` (bonne pratique, cf. `pip`+`pip3`).
- **Dispatch TOML** (`detect_workflow`) élégant : une seule commande `run` qui
  détecte le type de workflow depuis les sections présentes. Aligné avec
  `docker compose up` / `kubectl apply`.
- **`hmp config --profile user|dev|expert`** : niveaux de visibilité bien pensés,
  inspirés de `rustup toolchain`.

### 2.2 Problèmes

| Lacune | Standard industrie | Impact |
|---|---|---|
| **Absence de `--version`** | `ruff --version`, `poetry --version`, `pip --version` | L'utilisateur doit importer le module. Bloquant en support. |
| **Aucune auto-complétion** | `argcomplete` (httpie, aws-cli) ou `click` | UX dégradée en shell |
| **Pas de `-v/--verbose` ni `-q/--quiet`** | Tout CLI sérieux | Verbosité contrôlée uniquement par `HYDROMODPY_NO_DISPLAY=1` |
| **Codes de sortie incohérents** | 0 succès, 1 erreur applicative, 2 mésusage (POSIX) | `_cmd_new` l.342 renvoie 1 pour un workspace absent ; `_append_marker_filter` l.126 renvoie 2 pour une incompatibilité de flags. Bon début, mais `_cmd_run_toml` l.401 renvoie 1 pour fichier absent au lieu de **66** (EX_NOINPUT) ou 2. |
| **`display compare` en sous-commande cachée** | `git branch --list` vs `git branch list` | `hmp display compare` est détecté par une comparaison de string `subcommand == "compare"` au lieu d'un vrai `subparsers` imbriqué (l.606). Fragile. |
| **`hmp run script.py` lance un sous-processus** | À proscrire si évitable | `_cmd_run_script` l.447-454 : `subprocess.run([sys.executable, script])`. Perd le contexte et empêche `ctrl-C` propre. Utiliser `runpy.run_path`. |
| **Découverte de tests (_RE_REGRESSION) de 200 lignes dans `__main__.py`** | Discovery déléguée à pytest | Mélange CLI et logique métier de test. À extraire dans `tools/test_discovery.py`. |
| **`hmp export` : flags non-orthogonaux** | `--format csv,netcdf` | 4 flags booléens `--csv --netcdf --geotiff --vtu` + logique "si aucun, csv par défaut" (l.830). Préférer `--format` multivalué. |

### 2.3 Comparaison avec les CLI de référence

| Critère | `ruff` | `poetry` | `httpie` | `hmp` |
|---|---|---|---|---|
| `--version` | OUI | OUI | OUI | **NON** |
| Completion shell | OUI | OUI | OUI | **NON** |
| `-v/-q` | OUI | OUI | OUI | **NON** |
| Codes POSIX | OUI | OUI | OUI | Partiel |
| Sous-commandes imbriquées | OUI | OUI | N/A | Mal fait |

**Verdict** : **À améliorer**. Aucun défaut rédhibitoire mais standards industriels
manquants.

### 2.4 Recommandations concrètes

```python
# hydromodpy/__main__.py
parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
parser.add_argument("-v", "--verbose", action="count", default=0)
parser.add_argument("-q", "--quiet", action="store_true")
```

Ajouter dans `pyproject.toml` :

```toml
[project.scripts]
hmp = "hydromodpy.__main__:main"
# Enable argcomplete
```

Et documenter `eval "$(register-python-argcomplete hmp)"`.

---

## 3. API publique (`hydromodpy/__init__.py`)

### 3.1 Lazy import : bon pattern, **mauvaise implémentation**

Le pattern `__getattr__` (PEP 562) est **le standard** pour API scientifique avec
dépendances lourdes (cf. scikit-learn 1.3+, xarray). C'est le bon choix.

**Mais** : l'implémentation a un bug silencieux latent dans `_LAZY_IMPORTS` :

```python
# __init__.py l.276-278
"Modflow": "hydromodpy.solver.modflow_nwt",
"Modpath": "hydromodpy.solver.modflow_nwt",
"Mt3dms": "hydromodpy.solver.modflow_nwt",
```

Le `__getattr__` fait `getattr(module, name)` l.294. Si le module `solver.modflow_nwt`
expose effectivement les classes `Modflow`, `Modpath`, `Mt3dms` dans son
`__init__.py`, ça fonctionne. Mais la lecture est ambiguë : le dictionnaire devrait
référencer le **module qui définit** la classe, pas son alias module.

**Également problématique** :

```python
"OceanicManager": "hydromodpy.data.variables.oceanic",
"OceanicConfig": "hydromodpy.data.variables.oceanic",
```

Les deux pointent vers le paquet, pas vers `oceanic.manager` et `oceanic.config`.
Fonctionne si le `__init__.py` du paquet les ré-exporte, sinon **AttributeError**.

### 3.2 `__all__` incohérent

```python
__all__ = [
    "analysis", "core", "data", "log_manager", "open",
    "process", "simulation", "solver", "spatial", "watershed",
    "__version__",
    *_LAZY_IMPORTS,   # <-- itère les CLÉS du dict
]
```

`_LAZY_IMPORTS` est un dict ; itérer dessus donne les clés (correct), mais
le comportement est implicite. **Standard** : définir explicitement
`__all__ = [...]` ou `__all__ = tuple(sorted(_EXPORTS))`.

De plus, `log_manager` est exposé dans `__all__` mais pas dans `_LAZY_IMPORTS` :
il est chargé au premier import du package (`__init__.py` l.242-243), contredisant
l'objectif lazy.

### 3.3 Initialisation PROJ (lignes 20-227) : surdimensionnée

**200 lignes** pour gérer les inconsistances de `PROJ_DATA` entre `pyproj`,
`rasterio`, systèmes Linux. C'est une **rustine**, pas un design.

**Comparaison** : `pyproj` lui-même gère cela dans sa propre base. `rasterio`
fait un check simple au premier appel. HydroModPy bootstrape `pyproj` à
l'import, lit `proj.db` en SQLite, modifie `os.environ` — effet de bord
majeur à l'import.

**Verdict** : **Problématique**. Effet de bord sur `os.environ` à l'import,
scan disque, exceptions silencieuses. À extraire vers un `hydromodpy.proj_bootstrap`
appelable explicitement ou, mieux, à supprimer en imposant une version
minimale de `pyproj` dans `pyproject.toml`.

### 3.4 API de haut niveau : `hmp.open(path)` et `hmp.Simulation(toml)`

Cette double entrée (fonction `open` comme `xr.open_dataset`, classe `Simulation`
comme `sklearn.Pipeline`) est **cohérente** et bien pensée pour un hydrogéologue :

- `hmp.open(workspace)` → `SimulationCatalog` (analogie `xr.open_dataset`).
- `hmp.Simulation("config.toml")` → objet Python runnable (analogie `gensim.Model`).

**Verdict** : **Conforme** aux standards.

### 3.5 Tableau récapitulatif

| Élément | Verdict | Justification | Recommandation |
|---|---|---|---|
| Lazy import PEP 562 | Acceptable | Bon pattern, mais chemins d'import ambigus | Référencer les modules qui **définissent** les classes |
| `__all__` | À améliorer | Généré implicitement par itération de dict | Définir explicitement |
| Bootstrap PROJ | Problématique | 200 lignes, effet de bord à l'import | Supprimer ou isoler |
| `hmp.open()` / `hmp.Simulation()` | Conforme | Aligné xarray/sklearn | Conserver |
| `SimulationResult` exporté | À améliorer | Confusion avec `Simulation` de `results/simulation.py` | Renommer ou fusionner |

---

## 4. Nommage

### 4.1 PEP8 : globalement respecté

| Élément | Constat | Verdict |
|---|---|---|
| Classes | PascalCase (`SimulationCatalog`, `HydroModPyConfig`, `FieldParam`) | Conforme |
| Modules | snake_case (`catalog.py`, `zarr_store.py`) | Conforme |
| Constantes | UPPER_SNAKE (`_MIN_PROJ_LAYOUT_MINOR`, `_REGRESSION_TIERS`) | Conforme |
| Fonctions privées | `_leading_underscore` | Conforme |

### 4.2 Problèmes de nommage

| Nom actuel | Problème | Proposition | Justification |
|---|---|---|---|
| `Modflow`, `Modpath`, `Mt3dms` | Abréviations PascalCase inhabituelles | `ModflowNwt`, `Modpath7`, `Mt3dms` ou `MODFLOW_NWT`, `MODPATH7` | FloPy utilise `Modflow`, `Mt3dms` — l'existant est **aligné FloPy**, donc conservable, mais `Mt3dms` reste peu lisible |
| `ModelCalibrationLauncher`, `RegionalLabLauncher`, `DataOverviewLauncher`, `MeshCatchmentLauncher` | « Launcher » n'est pas idiomatique Python | `Calibrator`, `RegionalBatch`, `WatershedIdentityCard`, `MeshBuilder` | Java-ism. scikit-learn dirait `Calibrator`, xarray `Builder` |
| `Simulation` (3 classes homonymes : `project.Simulation`, `results.simulation.Simulation`, `simulation.planning.SimulationConfig`) | **Collision sémantique grave** | `Project` (ou `SimulationSession`), `SimulationRecord`, `SimulationConfig` | Un utilisateur Python ne sait pas de quel `Simulation` on parle |
| `SimulationCatalog` + `SimulationGroup` + `Simulation` | Trois niveaux de granularité non distingués dans les noms | OK tel quel mais documenter | Analogie `pandas` : `Index`/`Series`/`DataFrame` |
| `project.py` + classe `Simulation` | Le fichier devrait s'appeler `simulation.py` mais ce nom est pris par le paquet | Renommer la classe en `Project` (cohérent avec le nom du fichier ET la CLI `hmp new <project>`) | Lève la collision, cohérent CLI |
| `runners/` | Très ambigu avec `simulation/execution/runner.py` | `cli_dispatch/` ou absorption dans `__main__.py` | |
| `watershed/` | Shim legacy | À supprimer | |
| `hydromodpy_config.py` | Préfixe redondant avec le package | `config.py` | cf. `sklearn.base`, pas `sklearn.sklearn_base` |
| `data_managers.py`, `data_managers_config.py` | Préfixe redondant dans `data/` | `managers.py`, `managers_config.py` ou `planner_config.py` | |
| `structure_binders.py` (plusieurs exemplaires) | Jargon interne peu parlant | `bindings.py` ou intégration dans les classes concernées | |
| `capability_gallery.py` | Nom obscur | `figure_gallery_export.py` | |
| `posthoc.py`, `posthoc_orchestration.py` | `posthoc` est en un mot depuis 30 ans | `post_hoc_orchestration.py` ou `replay.py` | Ambiguïté stats vs. replay |

### 4.3 Collision la plus grave : trois `Simulation`

```
hydromodpy.project.Simulation           # classe user-facing (run-many)
hydromodpy.results.simulation.Simulation # vue en lecture d'une ligne du catalogue
hydromodpy.simulation.SimulationPlan    # plan d'exécution frozen
hydromodpy.simulation.SimulationConfig  # config Pydantic
```

Plus un **paquet** `hydromodpy.simulation` qui n'est pas la classe.

**Verdict** : **Problématique**. À résoudre en renommant :

- `project.Simulation` → `Project` (aligné CLI `hmp new <project>`)
- `results.simulation.Simulation` → `SimulationRecord` ou `StoredSimulation`
- `simulation.SimulationConfig` → `SimulationSpec` (Pydantic — une *spec* du run)

### 4.4 Tableau récapitulatif

| Convention | Verdict | Action |
|---|---|---|
| Classes PascalCase | Conforme | — |
| Modules snake_case | Conforme | — |
| « Launcher » | Non standard | Renommer en `*Engine` / `*Builder` / `*Session` |
| Collision `Simulation` | Problématique | Renommer 2 des 3 classes |
| Noms à préfixe redondant | À améliorer | `data_managers.py` → `managers.py` |

---

## 5. Cycle de vie : de la config TOML au résultat

### 5.1 Flux réel (trace `hmp run config.toml`)

```
user
  └─ hmp run config.toml
       ├─ __main__._cmd_run                             (parse argparse)
       │    └─ __main__._cmd_run_toml
       │         ├─ tomllib.load
       │         ├─ runners.detect_workflow             (dispatch par clé TOML)
       │         └─ runners.simulation.run              (shell 15 lignes)
       │              └─ project.Simulation(config_path) as project
       │                   ├─ __init__ : 7 phases     [PROBLÉMATIQUE]
       │                   │    1. Config Pydantic
       │                   │    2. Time grid
       │                   │    3. Mesh section detection
       │                   │    4. Spatial supports
       │                   │    5. Data plan
       │                   │    6. WorkflowContext + prepare_simulation_runtime
       │                   │    7. Postprocess runner
       │                   └─ project.run()
       │                        ├─ register_simulation        (DuckDB)
       │                        ├─ _write_flow_parameters
       │                        ├─ write_mesh                (Zarr)
       │                        ├─ persist_geographic_to_store
       │                        ├─ step_persist_forcings
       │                        ├─ SimulationRunner.execute   (<- moteur)
       │                        │    └─ adapters (NWT/MF6/Boussinesq)
       │                        └─ store.finalize
```

**7 phases** enchaînées dans `__init__`. C'est **trop**. Un `__init__` doit être
déterministe et rapide. Ici, `Simulation(cfg)` **charge les données** (phase 5),
**prépare le mesh** (phase 6), **instancie le PostprocessRunner** (phase 7) — bien
plus que de l'initialisation.

### 5.2 Accouplement caché : `WorkflowContext`

`project.Simulation` construit un `WorkflowContext` (`self._ctx`, l.276) et le passe
à travers 12+ fonctions (`collect_requested_support_ids`, `resolve_support_configs`,
`prepare_simulation_runtime`, `_write_flow_parameters`, `step_persist_forcings`...).

Chaque étape **mute** le contexte :

```python
self._ctx.data_plan = data_plan           # l.281
self._ctx.setup.time_grid = self._time_grid  # l.282
self._ctx.postprocess_runner = self._postprocess_runner  # l.292
self._ctx.setup.flow_runtime_overrides = ...  # l.406
self._ctx.setup.run_id = name             # l.608
self._ctx.execution.simulation_plan = plan  # l.609
```

**C'est un God-object d'état mutable**, anti-pattern classique. Un lecteur ne peut
pas savoir quels champs sont renseignés à quelle étape. Chaque bug de « champ None »
sera traqué par bisection.

**Référence xarray** : pas de contexte mutable ; chaque opération renvoie un nouveau
`Dataset` immutable. Ou `Dataset.close()` comme context manager.

### 5.3 Hack de contexte pour `step_persist_forcings` (l.489-496)

```python
_tmp_ctx = type("_Ctx", (), {
    "store": self._store,
    "sim_id": sim_id,
    "loaded_data": self._ctx.loaded_data,
    "setup": self._ctx.setup,
})()
step_persist_forcings(_tmp_ctx)
```

Construction d'un **faux** objet de type anonyme par `type()`. C'est un aveu que
`step_persist_forcings` attend un `WorkflowContext` complet mais n'en a pas besoin :
l'API de la fonction est mal pensée. **À corriger** : accepter les 4 paramètres
nécessaires au lieu d'un contexte.

### 5.4 Double entrée en planification (l.397-402)

```python
if overrides or thickness is not None or first_clim is not None:
    plan = self._run_with_overrides(name, overrides, thickness=thickness, first_clim=first_clim)
else:
    plan = self._run_from_plan(name)
```

Deux chemins pour construire un `SimulationPlan` selon la présence d'overrides.
Or `_run_with_overrides` crée **toujours** un plan mono-flow en hard-codé, tandis
que `_run_from_plan` passe par `SimulationPlanner`. Si l'utilisateur a configuré
un multi-processus (flow + transport) et passe `Sy=0.05`, il perd silencieusement
la partie transport.

**Verdict** : **Problématique**. Surprise utilisateur. Documenter ou unifier.

### 5.5 Tableau récapitulatif

| Étape | Verdict | Problème |
|---|---|---|
| Parsing CLI + dispatch TOML | Conforme | Clair |
| `Simulation.__init__` à 7 phases | Problématique | Trop lourd, imports tardifs, effet de bord |
| `WorkflowContext` mutable | Problématique | God-object d'état |
| `_tmp_ctx = type(...)()` hack | Problématique | API mal conçue en amont |
| Double planification `_run_with_overrides` vs `_run_from_plan` | À améliorer | Surprise silencieuse |
| Exécution via `SimulationRunner` + adapters | Conforme | Bon pattern Protocol |

---

## 6. Anti-patterns détectés

### 6.1 Liste des anti-patterns identifiés

| Anti-pattern | Localisation | Sévérité |
|---|---|---|
| **God-init** (`Simulation.__init__` à 7 phases, 130 lignes) | `project.py:168-311` | Haute |
| **God-context** (`WorkflowContext` muté en 6 endroits) | `project.py:276-299, 406-411, 460, 490-496, 598-599` | Haute |
| **Bare `except Exception: pass`** (essai silencieux) | `project.py:420-421`, `__main__.py:459, 495, 844-845, 858-859, 866-868`, 5 fichiers `analysis/display/` | Haute |
| **Import dans méthode** (18 imports dans `Simulation.__init__`) | `project.py:175-200` | Moyenne |
| **Construction d'objet par `type()` anonyme** | `project.py:489-496` | Moyenne |
| **3 classes homonymes `Simulation`** | Voir §4.3 | Haute |
| **Double ré-export** : `core/__init__.py` ET `simulation/__init__.py` exportent `WorkflowContext`, `SetupContext`, `LoadedDataContext`, `ExecutionRegistry` | `core/__init__.py:10-15`, `simulation/__init__.py:18-23` | Basse |
| **Shim package** `watershed/` sans valeur | `watershed/__init__.py` | Moyenne |
| **Effet de bord à l'import** (PROJ env mutation) | `__init__.py:226-227` | Haute |
| **Sous-processus pour exécuter un script Python** | `__main__.py:452-454` | Basse |
| **Logique métier dans `__main__.py`** (200 lignes de découverte regression) | `__main__.py:87-300` | Moyenne |
| **Feature envy** : `project.run()` connaît les détails internes du mesh, du time_grid, du domaine, de la Zarr, de DuckDB, des structure_binders | `project.py:414-548` | Haute |
| **Dispatch par string** dans `_cmd_display` (`subcommand == "compare"`) | `__main__.py:608` | Basse |

### 6.2 Focus : `Simulation.run()` est une God-method

La méthode `run()` de `project.py` (l.342-548) fait **200 lignes** et enchaîne :

1. Incrémentation compteur + génération UUID
2. Séparation overrides spéciaux (thickness, first_clim, properties)
3. Construction du plan (2 chemins)
4. Injection de propriétés spatiales
5. Construction de `reg_kwargs` avec mesh, CRS, time_grid
6. `register_simulation` dans DuckDB
7. `_write_flow_parameters`
8. `write_mesh` en Zarr
9. `persist_geographic_to_store`
10. `step_persist_forcings` (via ctx bricolé)
11. Wire store dans `PostprocessRunner`
12. Construction de `ResultsConfig`
13. Définition de callbacks `_after_run`, `_after_process`
14. `SimulationRunner.execute`
15. `finalize`

**Recommandation** : extraire chaque étape dans sa méthode. Ou mieux : déplacer
`register_simulation`, `write_mesh`, `persist_geographic` dans une méthode
`_open_simulation(sim_id)` séparée de `_execute(plan)` et `_close_simulation`.

### 6.3 Leaky abstraction du `SimulationCatalog`

Extraits de `project.run()` :

```python
self._store.register_simulation(sim_id, project=..., solver=..., **reg_kwargs)
self._store.write_mesh(sim_id, vertices=..., face_node_connectivity=..., z_interfaces=...)
```

Le `SimulationCatalog` expose **trop de méthodes ciblées** (`register_simulation`,
`write_mesh`, `_write_flow_parameters`, `write_geographic`...). L'utilisateur doit
connaître la **séquence** d'appels.

**Meilleure abstraction** : un `SimulationWriter(sim_id)` en context manager :

```python
with catalog.open_writer(sim_id, metadata=...) as w:
    w.write_mesh(...)
    w.write_parameters(...)
    w.write_geographic(...)
    # exception => status=failed ; sinon completed automatique
```

---

## 7. Diagramme de dépendances (ASCII)

Dépendances **internes** déclarées (imports `from hydromodpy.X`). Flèches = « importe ».

```
                                +─────────────+
                                │   __init__  │
                                │   __main__  │
                                +──────┬──────+
                                       │
                                       v
                                +─────────────+
                                │  runners/   │ <───── dispatch TOML
                                +─────┬───────+
                                      │
                 +────────────────────┼────────────────────+
                 v                    v                    v
         +──────────────+    +──────────────+    +──────────────+
         │  project.py  │    │  workflow/   │    │  analysis/   │
         │  Simulation  │    │  pipelines/  │    │  calibration │
         │  (God-init)  │    │  steps/      │    │  batch/      │
         +──────┬───────+    +──────┬───────+    │  display/    │
                │                   │            │  postprocess/│
                +──────────┬────────+            +──────┬───────+
                           │                            │
                           v                            │
                  +──────────────+                      │
                  │  simulation/ │ <────────────────────+
                  │  planning/   │
                  │  execution/  │
                  │  adapters/   │
                  │  results/    │ (extraction vers catalogue)
                  +──┬────┬──────+
                     │    │
          +──────────+    +───────────+
          v                            v
   +─────────────+              +─────────────+
   │   process/  │              │   solver/   │
   │  flow/      │              │ modflow_nwt │
   │  transport/ │              │ modflow6    │
   │  hydrology/ │              │ boussinesq  │
   │  forcing/   │              │ modflow_common│
   +──────┬──────+              +──────┬──────+
          │                            │
          +──────────────┬─────────────+
                         v
                  +─────────────+
                  │   spatial/  │
                  │  geographic │
                  │  domain     │
                  │  mesh       │
                  │  field      │
                  +──────┬──────+
                         │
                         v
                  +─────────────+
                  │    data/    │
                  │  variables/ │
                  │  planner    │
                  │  registry/  │
                  +──────┬──────+
                         │
                         v
                  +─────────────+
                  │    core/    │
                  │  config     │
                  │  state      │ <── ❌ importé par TOUT le monde
                  │  time       │    (WorkflowContext God-object)
                  │  tools      │
                  │  units      │
                  │  workspace  │
                  +──────┬──────+
                         │
                         v
                  +─────────────+
                  │   results/  │ <── importé par project.py,
                  │   catalog   │     simulation/results/,
                  │   zarr_store│     analysis/display/, runners/
                  │   exporters +
                  +─────────────+

                  +─────────────+
                  │  watershed/ │ <── ⚠️ SHIM LEGACY
                  │  (à retirer)│     re-exporte data.variables, simulation.settings
                  +─────────────+
```

**Lecture** : l'ordre vertical approxime la **hauteur dans la hiérarchie**.

### 7.1 Anomalies visibles sur le graphe

1. `core/state` est à la fois **bas** (dans `core/`) et **omniprésent** (tout le monde
   le passe autour). C'est un **God-context mal placé**.
2. `results/` est référencé par `project.py` (haut), par `simulation/results/` (milieu)
   et par `analysis/display/` (milieu). **Chevauchement**.
3. `watershed/` est déconnecté : rien ne l'appelle sauf `__init__.py` principal.
4. Pas de cycle direct observé, mais les cycles **logiques** (project ↔ workflow ↔
   simulation) sont seulement brisés par des imports tardifs (`import` dans méthode).

---

## 8. Optimisation, duplication, verbosité, dead code

### 8.1 Optimisation

| Fichier / ligne | Problème | Gain attendu |
|---|---|---|
| `__init__.py:20-227` | Lecture SQLite PROJ à chaque import du paquet | 20-50 ms d'import time économisables si contournable via `importlib.resources` |
| `__main__.py:180-190` | `rglob("test_*regression*.py")` à chaque appel CLI | Moindre (une fois par run) mais scan disque inutile |
| `project.py:432-436` | Calcul SHA-256 sur `mesh.points_xy.tobytes() + mesh.connectivity.tobytes()` à chaque run | Hasher une fois dans l'objet `HydroMesh` et cacher |
| `_build_pytest_runtime_env` (`__main__.py:65-80`) | Crée 4 directories à chaque `hmp test` | Négligeable |
| `project.py:497-509` | Callback `_after_run` capture `sim_id`, `name` par closure — recrée à chaque run | Négligeable mais lisibilité faible |

**Verdict** : pas de problème **critique** de performance dans les fichiers d'architecture.
Les vrais gains d'optimisation sont à chercher dans `data/variables/`, `spatial/mesh/`,
`simulation/execution/` (hors périmètre de ce rapport).

### 8.2 Duplication

| Duplication | Fichiers | Action |
|---|---|---|
| `load_toml_with_base_config(config_path)` appelé 2 fois dans `Simulation.__init__` (l.206 puis l.644 via `_detect_solver`) | `project.py` | Cacher le résultat dans un attribut |
| Ré-export de `WorkflowContext`, `SetupContext`, `LoadedDataContext`, `ExecutionRegistry` | `core/__init__.py:10-15` ET `simulation/__init__.py:18-23` | N'exporter qu'une fois (`core/` ou `simulation/`) |
| `apply_*_to_*` (9 fonctions `structure_binders`) dans `process/flow/structure_binders.py` ET `spatial/geographic/structure_binders.py` | Multiples | Vérifier signatures ; si pattern répété, introduire un protocole `Binder` |
| Dispatch `if args.raster/feature/sim` dans `_cmd_export` (l.764-871) | `__main__.py` | Factoriser en fonctions séparées par format |
| 5 runners shell quasi-identiques (`simulation.py`, `overview.py`, `mesh.py`, `calibration.py`, `batch.py`) | `runners/` | Supprimer le paquet, dispatcher dans `__main__._cmd_run` |

### 8.3 Verbosité

| Élément | Verbosité inutile | Action |
|---|---|---|
| `hydromodpy/runners/` | 5 fichiers `def run(path): return Launcher(path).run()` | Remplacer par un dict `{"simulation": "...path.module"}` dans `__main__.py` |
| `hydromodpy/watershed/__init__.py` | Re-exporte depuis 4 modules | Supprimer |
| `hydromodpy/exceptions.py` | 5 classes, toutes avec une seule ligne `pass` | Acceptable, mais aucune n'est utilisée en vérification dans le code (grep nécessaire) — vérifier l'usage |
| `__main__.py:87-300` | 200 lignes de discovery regression dans le CLI | Extraire dans `hydromodpy/core/tools/test_discovery.py` |
| `core/__init__.py` | Importe 11 symboles de 4 sous-paquets. Typique du « fichier parapluie » | Réduire à 3-4 exports canoniques |

### 8.4 Dead code potentiel

| Élément | Statut | Confidence |
|---|---|---|
| `hydromodpy/watershed/` | Shim legacy | Haute |
| `hydromodpy/solver/compatibility.py` | À la racine de `solver/`, pas exporté dans `__init__.py` | Moyenne (vérifier imports) |
| `hydromodpy/analysis/capability_gallery.py` | Utilisé par 2 endroits | **Pas dead code** |
| `hydromodpy/simulation/settings.py` | `Settings` re-exporté par `watershed/` | Pourrait être dead code si `watershed/` disparaît |
| `launchers/` au niveau repo | **N'existe pas dans le repo** (CLAUDE.md ment sur ce point) | Confirmé absent |
| `hydromodpy/exceptions.py` : `ConfigError`, `SolverError`, `DataError`, `MeshError` | Aucune n'est levée dans le code (`raise ValueError` utilisé à la place, cf. `project.py:222, 564, 667`) | **Haute : dead classes** |

**Vérification critique** : une recherche `grep -r "raise ConfigError"` doit être faite
pour confirmer. À première vue, **le module `exceptions.py` est du code mort**, ce qui
est commun pour les projets qui ont défini une hiérarchie « au cas où » sans jamais
l'utiliser. La question : soit l'adopter partout, soit supprimer.

### 8.5 Tests excessifs ?

Les trois tiers (unit / regression fast / regression extensive / validation) sont
**sains** et alignés avec les standards scientifiques (FloPy a unit + regression ;
xarray a unit + integration ; scikit-learn a unit + tests d'invariants).

Le **problème** n'est **pas** le nombre de tests mais :

1. La **logique de découverte** dans `__main__.py` (200 lignes, regex complexe
   `_RE_REGRESSION`). À externaliser.
2. Le parallélisme par `pytest-xdist` correctement offert (`-j auto`).
3. La gestion du scratch root (`/tmp/hydromodpy_tests/`, `HYDROMODPY_TEST_SCRATCH_ROOT`)
   est propre.

**Verdict** : **Conforme**. Pas de tests inutiles détectables depuis l'architecture.

---

## 9. Comparaison finale avec les références

| Critère | FloPy | xarray | scikit-learn | PyGMT | **HydroModPy** |
|---|---|---|---|---|---|
| Paquets top-level | 8 | 6 | 20 | 9 | **12** (trop pour la taille) |
| `core/` sans dépendance | N/A | `core/` vrai noyau | `base.py` seul | `__init__` plat | **Non respecté** |
| Lazy import PEP 562 | Partiel | OUI | OUI (depuis 1.3) | NON | OUI (bon) |
| CLI scriptable | NON | NON | NON | NON | OUI (`hmp`) |
| CLI `--version` | N/A | N/A | N/A | N/A | **NON** (manque) |
| Completion shell | — | — | — | — | **NON** |
| God-context mutable | NON | NON | NON | NON | **OUI** (`WorkflowContext`) |
| Dualité API/CLI | — | — | — | OUI | OUI |
| Adapters par Protocol | NON | OUI | NON (héritage) | NON | **OUI** (bon) |
| Hiérarchie d'exceptions dédiée | `FloPyException` | OUI | OUI | OUI | OUI mais **jamais levée** |
| Format stockage | binaires natifs | Zarr/NetCDF/HDF5 | joblib/pickle | — | **Zarr + DuckDB** (excellent) |
| Conventions mesh | MODFLOW DIS/DISV/DISU | UGRID (via xugrid) | N/A | GMT grid | **Maison** (meshio-compatible, pas UGRID) |

---

## 10. Plan d'action priorisé (recommandations)

### Priorité HAUTE (dette qui sabote la maintenance)

1. **Supprimer `hydromodpy/watershed/`** et déplacer `Hydraulic` + `Watershed` dans
   `analysis/` ou `spatial/geographic/`.
2. **Résoudre la collision `Simulation`** : renommer la classe de `project.py` en
   `Project` (aligné CLI), renommer `results.simulation.Simulation` en
   `SimulationRecord`.
3. **Refactorer `Simulation.__init__`** (project.py:168-311) :
   séparer en `Project.__init__(toml)` (config seulement) + `project.prepare()`
   (data/mesh/plan). Bonne pratique FloPy et scikit-learn.
4. **Supprimer les `try/except Exception: pass`** silencieux (`project.py:420`,
   `__main__.py:459, 858-868`). Au minimum ajouter un `logger.debug`.
5. **Extraire le bootstrap PROJ** hors de `__init__.py` dans
   `hydromodpy.proj_bootstrap` appelable explicitement.

### Priorité MOYENNE (qualité perçue)

6. **Ajouter `--version`, `-v/-q`, argcomplete** au CLI.
7. **Supprimer le paquet `runners/`** et fusionner dans `__main__._cmd_run` :

   ```python
   DISPATCH = {
       "simulation": "hydromodpy.project:Simulation",
       "overview":   "hydromodpy.workflow.pipelines.overview:DataOverviewLauncher",
       ...
   }
   ```
8. **Unifier `simulation/execution/` et `workflow/pipelines/`** : un seul paquet
   `simulation/` avec `planner`, `runner`, `adapters`, `pipelines`.
9. **Remplacer `WorkflowContext` mutable** par un `SimulationSession` immutable avec
   méthodes `with_data(...)`, `with_mesh(...)` (builder pattern).
10. **Valider ou supprimer `hydromodpy/exceptions.py`** : soit remplacer les
    `raise ValueError(...)` du code par `raise ConfigError`, soit supprimer la
    hiérarchie.

### Priorité BASSE (cosmétique)

11. Renommer `data/data_managers.py` → `data/managers.py`.
12. Renommer `*Launcher` → `*Engine` ou `*Session`.
13. Extraire la discovery des tests régression hors de `__main__.py`.

---

## 11. Verdict final

HydroModPy est un projet **scientifiquement mûr** (catalogue DuckDB + Zarr, adapters
Protocol, Pydantic bien typé, stratégie de tests multi-tier) mais **architecturalement
jeune** : trop de couches d'orchestration, un `WorkflowContext` God-object, une
collision de nommage `Simulation`×3, des shims legacy non nettoyés, des effets de bord
à l'import.

**Un hydrogéologue débutant comprendra `hmp.open(workspace)`, `hmp.Simulation(toml)`,
`result.field("head", t=12)` — c'est là que le design est le plus réussi**. En
revanche, un contributeur qui tente de suivre le flux `__main__ → runners → project →
workflow → simulation → solver` se perdra dans 6 niveaux.

**Score global : 5,5/10**. Le projet est **bien au-dessus** des bibliothèques
scientifiques maison (qui sont souvent à 3/10), mais **en-dessous** des références
industrielles (xarray ≈ 9/10, FloPy ≈ 7/10, scikit-learn ≈ 9/10).

Les corrections proposées (priorité HAUTE) amèneraient HydroModPy à **7,5/10** sans
toucher à la logique métier. Les changements de priorité MOYENNE le porteraient à
**8/10**.

---

*Fin du rapport d'architecture globale. Les audits suivants traiteront en détail :
(02) couche données, (03) couche spatiale, (04) moteur d'exécution et adapters,
(05) catalogue de résultats, (06) tests et CI, (07) documentation.*
