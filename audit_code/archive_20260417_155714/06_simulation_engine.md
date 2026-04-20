# Audit critique — Moteur d'orchestration `simulation/` + `workflow/` + `project.py`

**Auditeur** : Expert design patterns & orchestration de workflows scientifiques (références : Prefect 2, Airflow 2, Luigi, Dask Delayed, scikit-learn Estimators, FloPy).
**Périmètre** : `hydromodpy/simulation/**`, `hydromodpy/workflow/**`, `hydromodpy/project.py` — 3 799 lignes de Python.
**Date** : 2026-04-17.

---

## 0. Synthèse exécutive — Verdict global

| Axe | Verdict |
|-----|---------|
| Pattern Adapter / registre solveurs | **Acceptable** (protocole vrai, registre simpliste) |
| Plan immutable / planification | **Conforme aux standards** (borderline exemplaire) |
| Runner + callbacks | **À améliorer** (robustesse erreurs, hooks trop pauvres) |
| Workflow steps | **Non-standard, sous-ingénieré** (imperatif, pas de DAG) |
| Extracteurs binaires MODFLOW | **À améliorer** (duplication massive, try/except avalés) |
| Derived variables | **Acceptable physiquement**, **problématique** sur mailles irrégulières |
| Classe `Simulation` (project.py) | **Problématique — God class** (705 LOC, 7 responsabilités, code dupliqué avec `workflow/steps/`) |

**Dette technique la plus criante** : la classe `Simulation` réécrit à la main une dizaine d'étapes déjà factorisées dans `workflow/steps/store_lifecycle.py`, `result_ingestion.py`, `pipelines/simulation.py`. Elle fabrique même un faux `ctx` avec `type("_Ctx", (), {...})()` (project.py:490‑495) au lieu d'appeler l'étape canonique.

**Points forts (à préserver)** :
- `SolverAdapter` est un vrai `typing.Protocol` (structural subtyping) — c'est rare et bien fait.
- `SimulationPlan`, `ProcessRun`, `RunContext`, `RunExecutionResult` sont tous `@dataclass(frozen=True)` — standard industriel.
- `SimulationPlanner` isole la validation de la planification de l'exécution — bon découplage.

---

## 1. PATTERN ADAPTER — `SolverAdapter` Protocol + registre

### 1.1 Le Protocol est-il un *vrai* Protocol ?

`hydromodpy/simulation/adapters/base.py:29-36` :

```python
class SolverAdapter(Protocol):
    process_type: str
    solver_name: str
    def execute(self, ctx: RunContext) -> RunExecutionResult: ...
```

| Critère | Constat | Verdict |
|---|---|---|
| Utilise `typing.Protocol` (PEP 544) | Oui — pas un ABC déguisé | **Conforme** |
| `@runtime_checkable` absent | Oui, mais pas utilisé | Non pertinent (pas de `isinstance()` nulle part) |
| Duck-typing réel dans le registre | Les 6 adaptateurs **n'héritent pas** de `SolverAdapter` — ils implémentent la forme | **Conforme, exemplaire** |
| `ctx: RunContext` typé, `ctx.state: Any` | `state` est typé `Any` — on perd toute vérification statique | **À améliorer** |

**Comparaison avec scikit-learn** : `BaseEstimator` est un ABC avec `fit/predict` (héritage dur). scikit-learn l'a **choisi** parce qu'il fournit `get_params`/`set_params`/`clone` automatiquement. Ici, rien de tel n'est partagé entre adaptateurs, donc `Protocol` est le bon choix — **préférer structural subtyping quand on n'a pas de comportement à mutualiser**.

### 1.2 Interface « étendue » fantôme

`base.py:12-19` documente :

> Adapters **may** also implement `validate(ctx)` and `cleanup(ctx)`. The runner will call them when present (via `hasattr` checks).

**Vérification par grep** : aucun `hasattr(adapter, 'validate')` ni `hasattr(adapter, 'cleanup')` n'existe dans le code. Donc cette docstring est **mensongère** — **documentation morte depuis au moins une refonte**.

**Recommandation** : soit les hooks sont ajoutés au runner (utile pour Boussinesq qui a un `post_processing` manuel), soit la docstring est supprimée. Laisser une promesse d'API non tenue est pire qu'une limitation assumée.

### 1.3 Registre : `dict` littéral vs plugin system

`hydromodpy/simulation/adapters/registry.py:17-24` :

```python
_ADAPTERS: dict[tuple[str, str], SolverAdapter] = {
    ("flow", "modflownwt"): ModflowNwtFlowAdapter(),
    ("flow", "modflow6"):    Modflow6FlowAdapter(),
    ...
}
```

| Critère | Constat | Verdict |
|---|---|---|
| Dispatch via `dict[tuple]` | Simple, lisible, performant | **Acceptable** |
| Adaptateurs instanciés à l'import | `BoussinesqFlowAdapter()` etc. — pas de lazy init | **Acceptable** (adaptateurs sans état au moment de `__init__`, imports stdlib) |
| `register_adapter()` pour extension externe | Disponible, testé dans `ARCHITECTURE.md` | **Conforme** |
| Entry points (`importlib.metadata.entry_points`) | Absent | **À améliorer pour un vrai écosystème plugin** |
| Conflit de clé | Lève `ValueError` si clé existe — pas d'override possible | **Acceptable** (mieux : warning + override explicite) |

**Comparaison industrie** :
- Prefect utilise `@task` decorator + registre implicite via import.
- Airflow utilise les entry points `apache_airflow_providers` pour découverte plugin.
- FloPy charge ses packages via une fabrique explicite `Mfusg(*packages)`.

**Verdict** : pour 6 adaptateurs, le `dict` est parfaitement adapté. L'over-engineering (entry points) n'apporterait rien tant que tous les solveurs vivent dans le même dépôt. `register_adapter()` est la bonne porte d'extension.

### 1.4 Code mort — stubs d'adaptateurs

`adapters/display/stub.py` et `adapters/postprocess/stub.py` définissent 4 classes qui lèvent `NotImplementedError`, **jamais référencées** dans le code (grep confirme : seul `ARCHITECTURE.md` les évoque).

**Recommandation** : supprimer les 4 stubs (72 LOC), ou inscrire explicitement le TODO dans un issue tracker. Conserver des `NotImplementedError` orphelins pollue la surface API et trompe l'extension (`get_solver_adapter("display", "flow")` renvoie `ValueError` alors que la classe existe).

### 1.5 Récapitulatif

| Élément | Verdict | Justification | Recommandation |
|---|---|---|---|
| `SolverAdapter` (Protocol) | Conforme | Structural subtyping propre, pas d'ABC | Supprimer la docstring sur `validate`/`cleanup` fantômes |
| Registre `_ADAPTERS` | Acceptable | 6 entrées en dur + `register_adapter` | OK tel quel |
| Stubs display/postprocess | À supprimer | Code mort (0 import) | `rm -rf adapters/display adapters/postprocess` ou implémenter |
| Typage `state: Any` dans `RunContext` | À améliorer | Casse la vérification mypy/pyright | Typer via un `Protocol` `RuntimeState` minimal |

---

## 2. PLAN IMMUTABLE — `SimulationPlan`, `ProcessRun`, `RunContext`

### 2.1 Immutabilité réelle ?

`simulation/planning/plan.py` :

```python
@dataclass(frozen=True)
class ProcessRun:
    id: str
    process_id: str
    process_type: str
    solver: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)

@dataclass(frozen=True)
class SimulationPlan:
    name: str
    description: str
    runs: tuple[ProcessRun, ...] = field(default_factory=tuple)
```

| Critère | Analyse |
|---|---|
| `frozen=True` empêche `setattr` | ✅ |
| `runs: tuple` et `depends_on: tuple` | ✅ (pas de `list` mutable) |
| Types des champs tous primitifs/immutables | ✅ — `str`, `tuple[str, ...]` |

**Verdict** : **immuable au sens strict**. Le plan est purement descriptif, aucune référence vers un objet Python mutable.

### 2.2 Immutabilité de `RunContext` — la faille

```python
@dataclass(frozen=True)
class RunContext:
    plan: SimulationPlan
    run: ProcessRun
    state: Any               # <── mutable !
    dependency_models: tuple[Any, ...] = ()
```

`state` est typé `Any` et désigne en pratique `WorkflowContext` qui est **massivement mutable** (voir `core/state/run_state.py` — dataclass non-frozen). Les adaptateurs mutent librement `state.setup.flow`, `state.execution.models_by_run_id`, etc.

**Conséquence** : `RunContext.state` casse la garantie d'immutabilité apportée par `frozen=True`. C'est un **trompe-l'œil** — l'utilisateur croit manipuler un plan « figé » alors que l'exécution dépend d'un état partagé mutable global.

**Verdict** : **Acceptable dans ce cadre** (le runner a besoin de muter `models_by_run_id`), mais la documentation devrait le nommer explicitement. Sinon on se retrouve à l'étonnement classique du `@dataclass(frozen=True)` avec un `list` à l'intérieur (cf. PEP 557 note « immutable façade »).

### 2.3 Sérialisation / reproductibilité

Questions-test :

| Question | Réponse | Verdict |
|---|---|---|
| `pickle.dumps(plan)` fonctionne ? | Oui (types primitifs seulement) | Conforme |
| `json.dumps(asdict(plan))` fonctionne ? | Oui | Conforme |
| Le plan suffit-il à rejouer une simulation ? | **Non** — il manque la config, le workspace, les forcings | À améliorer |
| Existe-t-il un `SimulationPlan.to_toml()` / `from_toml()` ? | Non | À améliorer |

**Comparaison** : Prefect stocke un `FlowRun` avec serialization complète (cadre + inputs). Ici, le plan est une vue minimale de l'ordre d'exécution ; il faut lire `cfg` (HydroModPyConfig) pour rejouer. C'est cohérent avec la philosophie du projet, mais à **documenter**.

### 2.4 Planner — logique simple et bien isolée

`SimulationPlanner.build()` (planner.py:28‑115) :

- Preserve l'ordre utilisateur (pas de tri topologique).
- Expanse `process × solvers` → `ProcessRun`.
- Valide unicité des ids (TOML + concrets).
- Résout `depends_on` en **backward-looking** (un run ne peut dépendre que d'un run déjà planifié).

**Qualité** : 115 lignes, 1 seule méthode, 4 responsabilités listées dans la docstring — **exemplaire**. Équivalent du « static DAG compiler » de Luigi, sans la complexité d'un vrai ordonnanceur (parce qu'il n'y en a pas besoin ici).

**Un seul regret** : la ligne 109 — `runs_by_capability.setdefault(...).append(run)` — mute un dict dans une boucle. Pas de bug, mais un `defaultdict(list)` serait plus idiomatique.

### 2.5 Récapitulatif

| Élément | Verdict | Justification | Recommandation |
|---|---|---|---|
| `@dataclass(frozen=True)` + `tuple` | Conforme | Immutabilité réelle du plan | Maintenir |
| `RunContext.state: Any` | Acceptable mais ambigu | État mutable derrière façade « frozen » | Documenter explicitement ou séparer `ImmutableContext` / `MutableState` |
| Sérialisation | Acceptable | Plan JSON-compatible | Ajouter `SimulationPlan.to_dict()` explicite pour ML/audit |
| `SimulationPlanner` | Conforme (borderline exemplaire) | Code clair, validations explicites | Remplacer `setdefault().append()` par `defaultdict(list)` |

---

## 3. EXECUTION — `SimulationRunner` + `ProcessCallbacks`

### 3.1 Pattern callbacks — bon choix ?

`execution/runner.py:91-107` :

```python
@dataclass(frozen=True)
class ProcessCallbacks:
    before_process: Callable[[str], None] | None = None
    after_process: Callable[[str], None] | None = None
    after_run:     Callable[[ProcessRun, RunExecutionResult, Any], None] | None = None
```

| Critère | Constat | Verdict |
|---|---|---|
| Hook pattern cohérent | 3 hooks, signatures claires | Acceptable |
| `before_run` absent | ⚠️ | À améliorer |
| `on_error` absent | ⚠️ | **Problématique** |
| `on_cancel` absent | ⚠️ | À améliorer |
| Structure = dataclass `frozen=True` | Idiomatique | Conforme |

**Comparaison** :
- **Keras** : `Callback` avec 15+ hooks (`on_train_begin`, `on_epoch_end`, `on_batch_end`, etc.).
- **scikit-learn** : pas de callbacks (parti pris différent).
- **PyTorch Lightning** : `Callback` avec hooks granulaires + lifecycle `on_exception`.
- **Prefect 2** : pas de callbacks, mais `@flow.on_completion`/`@flow.on_failure`.

**Verdict** : 3 hooks sont **sous-dimensionnés** pour un moteur scientifique. Ajouter `on_run_error(run, exc, state)` au minimum, pour permettre à la pipeline d'écrire un statut `failed` dans le SimulationCatalog **par run** (actuellement c'est fait globalement dans `pipelines/simulation.py:152-161`).

### 3.2 Robustesse aux erreurs solveur

`_run_process_run` (runner.py:189-208) :

```python
def _run_process_run(self, plan, state, run):
    dependency_models = self._resolve_dependency_models(state, run)
    adapter = get_solver_adapter(run.process_type, run.solver)
    result = adapter.execute(RunContext(...))   # <── AUCUN try/except
    self._record_run_output(state, run, result)
    self._call_after_run(run, result, state)
```

| Scénario | Comportement actuel |
|---|---|
| MF6 crash avec `RuntimeError` | L'exception remonte au pipeline ; `_call_after_run` pas appelé → **pas d'ingestion dans le catalog pour ce run** |
| Fichier `.hds` manquant après run « réussi » | `adapter.execute` renvoie `RunExecutionResult`, puis `post_run_results` log `exception` et **continue** silencieusement |
| Solveur bloque (timeout) | **Aucun mécanisme de timeout** |
| KeyboardInterrupt en plein run | `BaseException` attrapé dans `pipelines/simulation.py:152` → `store.finalize(sim_id, status="failed")` puis `raise` — **correct** |
| Adapter lève `ValueError` | Idem — store finalisé `failed`, re-raise |

**Points positifs** :
- `pipelines/simulation.py:152` utilise `except BaseException` et ferme le store proprement. C'est **la bonne pratique** pour un moteur scientifique (KeyboardInterrupt est une `BaseException`).
- `cleanup_solver_files` est rappelé dans `post_run_results` (mais **jamais** en cas d'exception).

**Points négatifs** :
- Pas de `try/finally` autour de `adapter.execute` — si l'adaptateur crée des fichiers temporaires (Boussinesq écrit `_boussinesq_state_history.npz`) et crash, ils restent sur disque.
- Pas de timeout.
- Pas de retry.
- `_resolve_dependency_models` peut lever si l'upstream a crashé, mais on n'a pas de message clair indiquant *pourquoi* l'upstream est absent.

**Comparaison** : Dask Delayed gère les timeouts/retries via `dask.distributed.Worker`. Airflow a `retry_delay`/`execution_timeout` au niveau de chaque `Task`. Ici, pour un moteur de simulation **locale et longue**, pas de retry/timeout natif est **défendable** mais devrait être **documenté**.

### 3.3 Cleanup — état du terrain

| Ressource | Qui nettoie | Quand | Problème |
|---|---|---|---|
| `solver_scratch_folder` | `pipelines/simulation.py:133-136` | Après `execute()` si `!keep_solver_files` | Pas nettoyé en cas d'exception (pas dans un `finally`) |
| Fichiers `.hds`/`.cbc`/etc. | `post_run_results` → `cleanup_solver_files` | Après extraction | OK |
| `cache.duckdb` | Géré par `DataCatalogDuckDB` (hors scope) | — | — |
| `hydromodpy.duckdb` | `step_finalize_store` → `ctx.store.close()` | Dans `pipelines/simulation.py:151` + `except` branche 159 | **OK** (try/except couvre le close) |
| `_ctx.setup.flow_runtime_overrides` | `project.py:543` | `finally` branche du `run()` | OK |
| Fichiers temporaires whitebox (derived.py:399) | `tempfile.TemporaryDirectory` context manager | À la sortie du `with` | OK |
| Modèles flopy en mémoire | Jamais libérés explicitement | — | Acceptable (GC Python) |

**Principal manquement** : l'exécution de `adapter.execute()` **n'est pas dans un `try/finally`**. Si un run échoue, le scratch n'est pas nettoyé (le `rmtree` ligne 136 n'est jamais atteint parce que `execute()` a re-raisé). Mineur mais à corriger.

### 3.4 Récapitulatif

| Élément | Verdict | Justification | Recommandation |
|---|---|---|---|
| `ProcessCallbacks` dataclass | Acceptable | Pattern clair, mais pauvre | Ajouter `on_run_error(run, exc, state)` |
| Gestion d'exceptions | À améliorer | Pas de try/finally autour de `adapter.execute` | Wrap avec finally; appeler `cleanup_solver_files` en cas d'échec |
| Timeout / retry | Absent | Pas critique mais à documenter | Ajouter un hint dans la docstring sur la stratégie actuelle (fail-fast) |
| Cleanup store | Conforme | `BaseException` capturé en pipeline | Maintenir |
| Cleanup scratch si échec | À améliorer | Pas nettoyé | Déplacer `rmtree` dans un `finally` |

---

## 4. WORKFLOW STEPS — Composabilité et pipeline

### 4.1 Les steps sont-ils composables ?

`workflow/steps/*.py` — 7 fichiers, signatures :

```python
step_setup(ctx, *, requested_spatial_support_ids, requested_domain_supports)
step_spatial_supports(ctx, *, phase, requested_domain_supports, registry)
step_data_loading(ctx)
step_mesh(ctx, *, mesh_section_data, constraints_mode)
step_mesh_input(ctx, *, external_mesh_input)
step_open_store(ctx)
step_ingest_run_results(ctx, run, result)
step_persist_forcings(ctx)
step_write_provenance(ctx)
step_save_run_artifacts(ctx, wall_seconds)
step_finalize_store(ctx, *, wall_seconds)
```

| Critère | Constat | Verdict |
|---|---|---|
| Une signature uniforme `step_*(ctx, ...) -> None` | Presque — kwargs variables | Acceptable |
| Les steps ont-ils des entrées/sorties **explicites** ? | Non — tous mutent `ctx` par effet de bord | **Non-standard** |
| Dépendances entre steps exprimées ? | **Implicites uniquement** (ordre d'appel dans `pipelines/simulation.py:63-86`) | **À améliorer** |
| Exécution parallèle possible ? | Non (tout passe par `ctx` unique) | Acceptable vu le domaine |
| Réutilisation hors pipeline | Peu — chaque step suppose `ctx.setup`, `ctx.loaded_data` pré-remplis | À améliorer |

**Comparaison** :

- **scikit-learn Pipeline** : `Pipeline([('step1', Transformer1()), ('step2', Transformer2())])`. Chaque étape a `fit()/transform()` — **entrées et sorties explicites**, tableau d'échange (numpy array). Dépendances claires par ordre.
- **Prefect `@flow`** : `@task` avec arguments typés. Le DAG est construit automatiquement par dépendance sur les futures. Parallélisme possible.
- **Luigi** : `requires()` retourne les upstream tasks. DAG déclaratif.
- **Dask Delayed** : même principe, lazy evaluation.

**Ici** : les steps sont des **fonctions impératives qui mutent un objet god-context**. Aucune déclaration `requires=[step_setup]`, aucun typage des « artefacts » produits. Conceptuellement plus proche d'une **fonction shell script** qu'un DAG.

### 4.2 Monolithique ou atomique ?

Taille des steps :
- `step_setup` → `run_setup` : **63 lignes** (setup.py:257-327) — fait 6 choses (workspace, geographic, features, domain, zones, flow/transport). **Monolithique**.
- `step_persist_forcings` : **147 lignes** (result_ingestion.py:105-251) — fait 3 shapes (LoadResult, GeologyField, HydrographyResult). Énorme `for` avec `if hasattr(...)`.
- `step_save_run_artifacts` : 31 lignes, fait 2 choses (snapshot + gallery) → OK.

**Verdict** : les petits steps (`step_data_loading`, `step_ingest_run_results`) sont corrects. Les gros (`step_setup`, `step_persist_forcings`) sont des **procédures monolithiques**.

### 4.3 Pipeline `simulation.py` — lisibilité

`pipelines/simulation.py:40-87` (`prepare_simulation_runtime`) :

```python
step_setup(ctx, ...)
step_spatial_supports(ctx, phase="setup", ...)
step_data_loading(ctx)
step_spatial_supports(ctx, phase="data", ...)   # ← appelé deux fois !
step_mesh(ctx, ...)
step_mesh_input(ctx, ...)
```

**Problèmes** :
1. `step_spatial_supports` appelé **deux fois** avec un param `phase=...` — ça sent la mauvaise factorisation. Un DAG exprimerait ça avec deux nœuds différents liés à `setup` et `data_loading`.
2. `step_mesh` et `step_mesh_input` sont exclusifs (l'un est no-op si l'autre s'applique), mais c'est encodé dans chaque step par un `if x is None: return` — pas dans le pipeline.
3. Aucun step n'exprime quelle partie de `ctx` il **lit** ni **écrit** → impossible de détecter une corruption d'état.

**Recommandation** : **ne pas** réécrire en Prefect (overkill), mais introduire un mini-protocole :

```python
class WorkflowStep(Protocol):
    reads: tuple[str, ...]     # noms des attributs ctx lus
    writes: tuple[str, ...]    # noms des attributs ctx écrits
    def run(self, ctx: WorkflowContext, **params) -> None: ...
```

Cela permet de détecter en test qu'un step écrit hors de son contrat.

### 4.4 Récapitulatif

| Élément | Verdict | Justification | Recommandation |
|---|---|---|---|
| Composabilité | Non-standard | Effets de bord sur ctx, pas de DAG | Documenter « ce n'est PAS un DAG, c'est une sequence impérative » |
| `step_setup` | À améliorer (monolithique) | 6 responsabilités mélangées | Découper en `step_workspace`, `step_geographic`, `step_domain`, `step_process_ensure` |
| `step_persist_forcings` | À améliorer | Dispatch manuel par `hasattr` | Extraire une stratégie par type (`ForcingPersister.for(obj)`) |
| `step_spatial_supports` appelé 2× | Acceptable | Encodé explicitement via `phase` param | OK tel quel |
| Documentation flux | À améliorer | `prepare_simulation_runtime` docstring minimale | Ajouter diagramme de séquence |

---

## 5. EXTRACTORS — MF6 / NWT / Boussinesq / MT3DMS / MODPATH

### 5.1 Interface uniforme ?

Protocol `OutputAdapter` (extractors/base.py:10-23) :

```python
class OutputAdapter(Protocol):
    def extract(self, sim_id, solver_output_dir, store) -> None: ...
    def derive(self, sim_id, store, config=None) -> None: ...
```

| Adapter | `extract` respecte la signature ? | `derive` présent ? |
|---|---|---|
| `ModflowNwtOutputAdapter` | Kwargs en plus (`model_name`, `budget_spatial_fields`, `hdry`, `hnoflo`) | ✅ |
| `Modflow6OutputAdapter` | Kwargs en plus (`model_name`, `budget_spatial_fields`) | ✅ |
| `BoussinesqOutputAdapter` | Signature stricte | ✅ |
| `Mt3dmsOutputAdapter` | Kwarg `model_name` en plus | ✅ |
| `ModpathOutputAdapter` | Kwarg `model_name` en plus | ✅ (no-op) |
| `GR4JOutputAdapter` | **Méthode custom `extract_from_memory`** | ✅ (no-op) |

**Problème** : `post_run_results` (post_run.py:91-105) gère l'hétérogénéité des signatures avec un hack :

```python
try:
    adapter.extract(sim_id, solver_output_dir, store, **extract_kwargs)
except TypeError:
    # Adapter doesn't accept extra kwargs (Boussinesq, GR4J, etc.)
    try:
        adapter.extract(sim_id, solver_output_dir, store)
    except Exception:
        logger.exception(...)
except Exception:
    logger.exception(...)
```

**Verdict** : **problématique**. Intercepter un `TypeError` pour deviner la signature est un anti-pattern. Soit tous les adaptateurs acceptent `**kwargs`, soit on dispatche sur la présence d'un attribut `supports_budget_spatial = True`.

### 5.2 Duplication code — audit impitoyable

#### 5.2.1 `_write_surface_elevation` en 3 copies

| Fichier | Lignes | Contenu |
|---|---|---|
| `extractors/modflownwt.py:184-225` | 41 | Charge `.dis`, extrait `top`/`botm`, écrit `mesh/surface_top` + `z_interfaces` |
| `extractors/modflow6.py:225-272` | 47 | Idem mais via `MfGrdFile` |
| `extractors/boussinesq.py:92-125` | 33 | Idem mais via `_boussinesq_summary.json` |

Les trois finissent par écrire **exactement les mêmes clés dans Zarr** :

```python
mesh.create_array("z_interfaces", data=z_flat, overwrite=True)
mesh.create_array("surface_top", data=top, overwrite=True)
mesh.attrs["n_cells"] = int(n_cells)
mesh.attrs["n_layers"] = int(nlay)
```

**Factorisation évidente** : `extractors/mesh_ingest.py::write_surface_elevation(store, sim_id, top, z_interfaces, nlay)` consommé par les 3 extracteurs. Chaque extracteur fournit juste `top` et `z_interfaces`.

#### 5.2.2 Recherche du clef `drn` dans `derived.py`

6 occurrences du même bloc (derived.py:316-320, 454-458, 529-533) :

```python
drn_key = None
for candidate in ("drn", "drain", "drains", "DRN", "DRAINS"):
    if candidate in budget_grp:
        drn_key = candidate
        break
```

**Factoriser** en `_find_budget_key(budget_grp, "drn")` (déjà mentionné par un commentaire line 32 de `catchment_aggregation.py`, mais non implémenté).

#### 5.2.3 Boucle extract head — quasi-copy-paste

`modflownwt.py:64-73` vs `modflow6.py:65-74` : la boucle d'itération sur les timesteps, reshape, cast `float64`, masquage sentinelle est **95% identique**. Les seules différences :
- MF-NWT : `hdry`/`hnoflo` en paramètre, `isclose(..., atol=1.0)`.
- MF6 : `values[np.abs(values) > 1e20] = np.nan`.

**Factorisation** : `_extract_head_timeseries(head_file, store, sim_id, mask_sentinel_fn)` — réduit 20 LOC à 5.

#### 5.2.4 `_extract_mass_balance` — même armature, API flopy différente

MF-NWT utilise `MfListBudget.get_budget_from_list()` ; MF6 utilise `Mf6ListBudget.get_budget()`. Les dtypes de records diffèrent légèrement. Le reste (boucle d'écriture dans le store) est identique.

**Factorisation difficile** (APIs flopy différentes) — **acceptable de garder 2 copies**.

#### 5.2.5 Quantification

| Type | Occurrences | LOC dupliquées estimées |
|---|---|---|
| `_write_surface_elevation` | 3 | ~120 |
| `drn_key` candidate loop | 6 | ~30 |
| head extract loop | 2 | ~20 |
| `_extract_mass_balance` armature | 2 | ~20 |
| **Total gain potentiel** | — | **~190 LOC** sur 1 600 LOC d'extracteurs (~12%) |

### 5.3 Formats binaires MODFLOW — correctement lus ?

| Aspect | Constat | Verdict |
|---|---|---|
| Endianness | Déléguée à `flopy.utils.binaryfile` | Conforme (flopy gère big/little selon la précision) |
| Précision `single` vs `double` | MF6 tente `bf.CellBudgetFile(str(cbc_path))` puis fallback `precision="double"` | Acceptable (flopy auto-détecte quand il peut) |
| Record markers | Gérés par flopy | Conforme |
| Gestion DRY cells | NWT → `hdry=-100`, `hnoflo=-9999` avec `isclose(..., atol=1.0)` ; MF6 → `abs(values) > 1e20` | **Acceptable** mais hétérogène (MF6 utilise `1e30` stricto sensu, pas `1e20`) |
| MF6 stress packages (recarrays) | `_recarray_to_grid` scatter `node/q` → `(nlay, n_cells)` | **Conforme** — implémentation correcte du 1-based → 0-based |
| HDRY threshold en MF-NWT | `atol=1.0` pour `-100.0` et `-9999.0` | **Douteux** : `atol=1.0` masque aussi des charges **légitimes** proches de ces valeurs. Si un modèle a une charge vraie à `-99.3 m NGF`, elle deviendra NaN |

**Recommandation pour la sentinelle NWT** : utiliser le vrai `hdry`/`hnoflo` du listing file au lieu de constantes magiques `-100.0` / `-9999.0`. FloPy expose `m.get_package("BAS6").hnoflo`.

### 5.4 Lecture `full3D=True` en NWT — pourquoi pas en MF6 ?

MF-NWT utilise `cbb.get_data(..., full3D=True)` (ligne 122) pour obtenir un array dense. MF6 n'utilise PAS `full3D=True` (ligne 118) et doit ensuite appeler `_recarray_to_grid` manuellement pour les stress packages.

**Vérification** : `full3D=True` existe-t-il dans l'API MF6 ? Oui — FloPy `CellBudgetFile.get_data(full3D=True)` fonctionne aussi sur MF6. L'utiliser supprimerait entièrement `_recarray_to_grid`.

**Recommandation** : passer `full3D=True` en MF6 aussi, puis supprimer `_recarray_to_grid` (29 LOC en moins).

### 5.5 Try/except avalés

Grep sommaire dans `extractors/` :

```
modflow6.py:    except Exception:   (6 occurrences)
modflownwt.py:  except Exception:   (4)
boussinesq.py:  except Exception:   (4)
derived.py:     except Exception:   (2) + try:/except:…return (frequent)
post_run.py:    except Exception:   (8)
```

**Constat** : ~24 blocs `except Exception: logger.debug(...)` ou pire `except Exception: pass`. C'est de la **programmation défensive paranoïaque** — chaque bug devient silencieux.

**Cas réel problématique** : mt3dms.py:49 — `except (EOFError, Exception)` — `Exception` couvre déjà `EOFError`, donc le tuple est redondant ET le bloc avale n'importe quoi.

**Recommandation** :
- Remplacer `except Exception:` par `except (KeyError, IndexError, ValueError):` avec la liste des causes légitimes.
- Conserver `except Exception` uniquement avec `logger.exception(...)` (pas `logger.debug`) pour que les erreurs imprévues soient visibles.
- En phase de test (CI), activer un flag `HYDROMODPY_STRICT=1` qui re-raise.

### 5.6 Récapitulatif

| Élément | Verdict | Justification | Recommandation |
|---|---|---|---|
| Protocol `OutputAdapter` | Acceptable | Deux méthodes, sémantique claire | Harmoniser signatures pour supprimer le `except TypeError` de post_run.py |
| `_write_surface_elevation` ×3 | **Problématique (duplication)** | 120 LOC de triplicata | Factoriser dans `_mesh_ingest.py` |
| `drn_key` candidate loop ×6 | À améliorer | 30 LOC dupliquées | Créer `_find_budget_key(grp, kind)` |
| `full3D=True` en MF6 | À améliorer | `_recarray_to_grid` devient inutile | Passer `full3D=True` partout |
| Sentinelle NWT `atol=1.0` | À améliorer | Masque des charges légitimes | Lire `hnoflo/hdry` du .bas/.lst |
| `except Exception` partout | **Problématique** | 24 blocs silencieux | Typer les exceptions, `logger.exception` obligatoire |
| Conformité CF / UGRID | Absente | Zarr custom avec attrs partiels | Viser UGRID pour `mesh` group |

---

## 6. DERIVED VARIABLES — `compute_derived()`

### 6.1 Extensibilité

Mécanisme : un dict `DERIVED_VARIABLES` de flags bool (derived.py:31-41) + un grand `if flags.get(...): _compute_XXX(...)` (lignes 77-102).

| Critère | Constat | Verdict |
|---|---|---|
| Ajouter une nouvelle variable dérivée = ? | Ajouter entrée dans `DERIVED_VARIABLES` + fonction `_compute_X` + une ligne `if flags.get("X")` | Acceptable mais répétitif |
| Registry pattern dict[nom→fn] | Absent — structure hard-codée | À améliorer |
| Dépendances entre variables (seepage dépend de watertable_elevation) | Implicites (re-lecture `store.query_field(..., "watertable_elevation", t)`) | **Problématique** |
| Ordre d'exécution | Hard-codé, pas déclaratif | À améliorer |

**Recommandation** : registre explicite

```python
DERIVED_REGISTRY: dict[str, DerivedVariable] = {
    "watertable_elevation": DerivedVariable(compute=_compute_wte, depends=[]),
    "watertable_depth":     DerivedVariable(compute=_compute_wtd, depends=["watertable_elevation"]),
    "seepage_areas":        DerivedVariable(compute=_compute_seepage, depends=["watertable_elevation"]),
    ...
}
```

Permet d'exécuter en ordre topologique, de lever une erreur claire si une dépendance est désactivée, et d'autoriser les plugins.

### 6.2 Correction physique

| Variable | Définition | Audit |
|---|---|---|
| `watertable_elevation` | `flopy.utils.postprocessing.get_water_table()` — charge à la plus haute couche saturée | **Correct** |
| Fallback 1 couche | `head[0]` | **Correct** |
| Sentinelle « legacy_floor » (derived.py:123-130) | Fenêtre `min(-50, p1 - 200)` | **Douteux mais pragmatique** — ajoute un garde-fou pour stores legacy sans NaN masking. Risque : un site en dépression (Pays-Bas, altitude -4 m) ne déclencherait pas `legacy_floor` mais passe dans le `finite_heads > -50` → OK |
| `watertable_depth` | `max(top - wt, 0)` | **Correct** |
| `seepage_areas` | `(wt >= top_elev)` en float64 | **Correct physiquement**, conforme à la définition hydrogéologique |
| `groundwater_flux` | `sqrt(sum(flow_*_face²))` magnitude inter-cellule | **Correct** pour grille structurée ; **incorrect** en DISV (MF6 unstructured) où `flow-ja-face` est indexé par face, pas par direction |
| `accumulation_flux` | Routage whitebox D8 sur `surface_top` reshape(nrow,ncol) | **Correct sur grille régulière**, **problématique sur maille irrégulière/gmsh** |
| `outflow_drain` | `drn.sum(axis=0)` en gardant le signe | Correct |
| `concentration_seepage` | `conc * seepage` avec NaN hors seepage | Correct |
| `mass_seepage` | `conc_seepage * abs(drn)` | **Douteux** — dimensionnellement `[conc] × [m3/s]` = `[mg/s]` mais la docstring dit « mass flux ». OK si `conc` est en `mg/m3`, mais aucune vérification |
| `mass_accumulated` | `cumsum(mass_seepage)` | Correct |

### 6.3 Gestion des NaN / nodata

**Strengths** : extraction NWT masque `hdry`/`hnoflo` → NaN dès l'entrée.

**Faiblesses** :
- `legacy_floor` (derived.py:127) est une rustine pour stores legacy non-masqués — devrait disparaître une fois la migration confirmée.
- `mesh["surface_top"]` est filtré par `(top > -9000)` (catchment_aggregation.py:258) avec valeur magique.
- Pas de convention unique pour « no data » — parfois `NaN`, parfois `-9999`, parfois `-99999`.

**Recommandation** : adopter une constante unique `HMP_NODATA = np.nan` et nommer les sentinelles historiques dans un seul endroit (`results/constants.py`).

### 6.4 Grilles régulières vs irrégulières

**Problème majeur** — `_accumulation_flux_routed` (derived.py:355-435) :

```python
grid_shape = (nrow, ncol)
if nrow * ncol != n_cells:
    side = int(np.sqrt(n_cells))
    if side * side == n_cells:
        grid_shape = (side, side)
    else:
        raise ValueError(...)
```

**Conséquence** : sur une grille gmsh (n_cells=9341 non carré), **ça lève immédiatement**. Le fallback « simple abs(drn) » prend alors le relai (lignes 340-350), donc pas de crash, mais `accumulation_flux` devient **incorrect sur mailles irrégulières**.

**Recommandation** : désactiver `accumulation_flux` par défaut sur DISV/gmsh et documenter que le routage whitebox est pour DIS seulement.

### 6.5 Récapitulatif

| Élément | Verdict | Justification | Recommandation |
|---|---|---|---|
| `compute_derived` dispatch | Acceptable | Dict de flags + if/elif | Passer à un registre `DerivedVariable` avec dépendances |
| Ordre d'exécution | À améliorer | Hard-codé, dépendances implicites | Topological sort |
| Convention nodata | À améliorer | 3 valeurs (`-9000`, `-9999`, `NaN`) mélangées | Unifier |
| Correction physique | Acceptable | watertable, seepage OK ; flux magnitude fragile en DISV | Renommer `groundwater_flux` en `groundwater_flux_cartesian` pour clarifier |
| `accumulation_flux` sur DISV | Problématique | Fallback silencieux vers `abs(drn)` | Désactiver par défaut + warning explicite |

---

## 7. CLASSE `Simulation` (`project.py`) — God class ?

### 7.1 Métriques

| Métrique | Valeur | Référence industrie |
|---|---|---|
| Lignes totales | 705 | >500 suspect |
| Lignes dans `__init__` | ~130 (lignes 168-311) | >50 suspect |
| Responsabilités assumées | **≥7** | >3 = God class |
| Méthodes publiques | 5 (`run`, `close`, `__enter__`, `__exit__`, `__repr__`) + 5 properties | Raisonnable |
| Imports dans `__init__` | 16 (lignes 175-200) | >5 = code smell |
| Imports dans `run()` | 11 (lignes 363-385) | >5 = code smell |

### 7.2 Inventaire des responsabilités

1. **Chargement config TOML** (phase 1, lignes 204-210)
2. **Détection/forcing du solveur** (`_detect_solver`, `_ensure_simulation_block`)
3. **Résolution time grid** (phase 2)
4. **Détection/validation section mesh** (phase 3, 30 lignes)
5. **Résolution spatial supports** (phase 4)
6. **Planification data loading** (phase 5)
7. **Construction WorkflowContext** (phase 6, appelle `prepare_simulation_runtime`)
8. **Postprocess runner lifecycle** (phase 7)
9. **Ouverture SimulationCatalog** (lignes 304-308)
10. **Méthode `run()`** qui duplique `step_open_store`, `step_persist_forcings`, `post_run_results` (200 LOC)
11. **`_run_with_overrides`** — construction d'un plan à la main (duplication `SimulationPlanner`)
12. **`_rebuild_domain`** — réimplémentation partielle de `Domain` setup

**Verdict** : **7 responsabilités ≠ Single Responsibility Principle**. Classe **God**.

### 7.3 Le context manager est-il correct ?

```python
def __enter__(self): return self
def __exit__(self, *exc): self.close()
```

| Critère | Constat | Verdict |
|---|---|---|
| Signature `__exit__` | `*exc` ignore `exc_type`, `exc_val`, `exc_tb` | **Douteux** — correct (retourne None = re-raise) mais perd l'info de debug |
| `close()` appelé même si exception | Oui (via `__exit__`) | Conforme |
| `close()` idempotent | `if self._store is not None: ...` | Conforme |
| `close()` nettoie scratch ? | **Non** — seul `store.close()` + `cleanup_stable_folder(geographic)` | À améliorer |
| `close()` nettoie `solver_scratch_folder` ? | **Non** — au contraire, `run()` avec `keep_solver_files=True` laisse tout sur disque | **Problématique** |
| Ferme postprocess runner ? | Non | À améliorer |

**Bug latent** : dans `run()` ligne 504-514, `ResultsConfig(keep_solver_files=True)` est **hard-codé**. Tous les runs de `Simulation.run()` laissent des fichiers solveur sur disque, **contrairement** au chemin `hmp run config.toml` qui respecte la config. Cette asymétrie n'est documentée nulle part.

### 7.4 Duplication avec `workflow/steps/`

Comparaison `Simulation.run()` ↔ `pipelines/simulation.py::execute_simulation` :

| Logique | `Simulation.run` | `execute_simulation` |
|---|---|---|
| Open store | Lignes 453-457 | `step_open_store` |
| Write mesh | Lignes 464-479 | Dans `step_open_store` |
| Persist forcings | Lignes 488-496 avec **faux ctx** (`type("_Ctx", (), {...})()`) | `step_persist_forcings(ctx)` |
| Write parameters | Import direct de `_write_flow_parameters` (fonction **privée** !) | Appelée dans `step_open_store` |
| Run plan | `SimulationRunner().execute()` | Idem |
| Finalize | `store.finalize(sim_id, status="completed")` | `step_finalize_store` |
| Scratch cleanup | **Absent** (`keep_solver_files=True` forcé) | `rmtree(scratch)` conditionnel |

**Ligne 460** :
```python
from hydromodpy.workflow.steps.store_lifecycle import _write_flow_parameters
```

Importer une fonction **préfixée underscore** d'un autre module = signal clair que la séparation a été violée. Soit on rend la fonction publique (`write_flow_parameters`), soit `Simulation.run()` appelle le step entier.

**Recommandation radicale** : `Simulation.run()` devrait être :

```python
def run(self, *, name=None, **overrides) -> SimulationResult:
    plan = self._build_plan(name, overrides)
    self._ctx.execution.simulation_plan = plan
    execute_simulation(self._ctx, after_process=self._postprocess_runner.after_process)
    return SimulationResult(sim_id=self._ctx.sim_id, name=name, store=self._store)
```

~10 lignes au lieu de 200. Gain : ~180 LOC et **suppression de tous les bugs de désynchronisation** entre les deux chemins.

### 7.5 Le piège `_tmp_ctx`

Lignes 490-496 :

```python
_tmp_ctx = type("_Ctx", (), {
    "store": self._store,
    "sim_id": sim_id,
    "loaded_data": self._ctx.loaded_data,
    "setup": self._ctx.setup,
})()
step_persist_forcings(_tmp_ctx)
```

Fabrication **ad-hoc** d'une classe anonyme pour piper un objet dans une fonction qui attend `WorkflowContext`. C'est un **contournement de typage** et une **relation de couplage fragile** : si `step_persist_forcings` commence à lire `ctx.cfg`, ce hack casse silencieusement.

**Verdict** : **Problématique** — à réécrire en mutant le vrai `self._ctx`. Le seul vrai obstacle est que `self._ctx.sim_id` doit être transient par run (pas de `for each run` dans la vie d'une `Simulation` dans le chemin `WorkflowContext` actuel). Ce n'est **pas** un obstacle insurmontable.

### 7.6 Récapitulatif

| Élément | Verdict | Justification | Recommandation |
|---|---|---|---|
| Taille de la classe | **Problématique** | 705 LOC, 7 responsabilités | Décomposer `Simulation` en `ProjectLoader` (config) + `Simulation` (run-only) |
| Context manager | Acceptable | `__enter__/__exit__` basique | Signaler via docstring que cleanup solver n'est PAS fait |
| Duplication avec `workflow/steps/` | **Problématique** | 200 LOC dupliquées, import `_private` | Refactorer `Simulation.run` en 10 LOC via `execute_simulation` |
| `_tmp_ctx` fabriqué | **Problématique** | Type anonyme + couplage fragile | Utiliser `self._ctx` directement |
| `keep_solver_files=True` hard-codé | À améliorer | Silencieux, inverse du comportement CLI | Déléguer à `self.cfg.simulation.results.keep_solver_files` |
| Imports dans les méthodes | À améliorer | 11+ imports dans `run()` | Hisser au top-level si lazy pas crucial |

---

## 8. DIAGRAMME DE SÉQUENCE — TOML → Export

### 8.1 Chemin TOML (`hmp run config.toml`)

```
┌───────────┐   ┌────────────────┐   ┌─────────────────────────┐   ┌──────────────────┐
│ config.toml│──▶│ HydroModPyConfig│──▶│ prepare_simulation_runtime│──▶│ execute_simulation│
└───────────┘   └────────────────┘   │ (Setup → Data → Mesh)    │   └────────┬─────────┘
                                     └─────────────────────────┘            │
                                                                            ▼
                                                              ┌───────────────────────┐
                                                              │ SimulationPlanner.build│
                                                              └───────────┬────────────┘
                                                                          │
                                                                          ▼
                                                              ┌───────────────────────┐
                                                              │ step_open_store (Cat.) │
                                                              └───────────┬────────────┘
                                                                          │
                                                                          ▼
   ┌─────────────────────────┐   ┌────────────────────────┐   ┌────────────────────────┐
   │ SimulationRunner.execute │──▶│ get_solver_adapter(...)│──▶│ Adapter.execute(ctx)   │
   │  (for each ProcessRun)   │   └────────────────────────┘   │  → RunExecutionResult  │
   └─────────────┬────────────┘                                └───────────┬────────────┘
                 │                                                         │
                 │        after_run callback                               │
                 ▼                                                         ▼
   ┌─────────────────────────┐   ┌───────────────────────┐   ┌────────────────────────┐
   │ step_ingest_run_results  │──▶│ post_run_results      │──▶│ adapter.extract(...) + │
   │  (invoked par callback)  │   └───────────────────────┘   │ adapter.derive(...) +  │
   └─────────────────────────┘                                │ aggregate_catchment +  │
                                                              │ _auto_export +         │
                                                              │ cleanup_solver_files   │
                                                              └────────────────────────┘
                                                                          │
                                                                          ▼
   ┌─────────────────────────┐   ┌───────────────────────┐   ┌────────────────────────┐
   │ step_save_run_artifacts │──▶│ step_finalize_store   │──▶│ SimulationCatalog closed│
   └─────────────────────────┘   └───────────────────────┘   └────────────────────────┘
```

### 8.2 Chemin programmatique (`hmp.Simulation(...).run(...)`)

```
hmp.Simulation("x.toml")
 ├── __init__: phases 1-7 (config, mesh, data plan, ctx, postprocess)
 ├──   → prepare_simulation_runtime(ctx, ...)    # identique au chemin TOML
 └── .run(Sy=0.05)
      ├── _run_from_plan OU _run_with_overrides
      ├── self._store.register_simulation(...)    # duplique step_open_store
      ├── _write_flow_parameters(...)             # duplique step_open_store
      ├── self._store.write_mesh(...)             # duplique step_open_store
      ├── persist_geographic_to_store(...)        # duplique step_open_store
      ├── step_persist_forcings(_tmp_ctx)         # via un faux ctx
      ├── SimulationRunner().execute(plan, ctx)   # commun
      │    └── after_run: post_run_results(...)    # commun
      └── self._store.finalize(...)               # duplique step_finalize_store
```

**Constat graphique** : le chemin `Simulation` emprunte **~60%** des steps du pipeline, avec les mêmes effets mais en copiant les appels au lieu d'appeler `execute_simulation`. Aucune raison technique ne justifie cette duplication.

---

## 9. OPTIMISATIONS IDENTIFIÉES

| # | Emplacement | Problème | Gain potentiel |
|---|---|---|---|
| 1 | `derived.py:131-157` | Boucle Python sur chaque timestep pour `watertable_elevation` | Vectorisation `get_water_table` en 1 call → **O(n_timesteps) I/O évités** |
| 2 | `derived.py:282-294` | Boucle Python pour `groundwater_flux` avec `**2` et `sqrt` | `np.einsum` ou `np.linalg.norm(..., axis=0)` sur la pile complète |
| 3 | `modflow6.py:65-74` et `modflownwt.py:64-73` | Un `store.write_field` par timestep | Batch : écrire `head[:]` en un seul `write_field` avec chunking Zarr |
| 4 | `post_run.py:90-105` | `try/except TypeError` pour deviner la signature | Signature uniforme + disparition du hack |
| 5 | `catchment_aggregation.py:129-138` | Boucle `for t in range(n_timesteps)` avec `np.asarray(arr[t], ...)` | Lire `arr[:]` une fois puis reducer vectorisé |
| 6 | `result_ingestion.py:205-247` | Deux boucles `for rec in points/fields` écrivent un par un en Zarr | Batcher les appels |
| 7 | `project.py:433-434` | `mesh.points_xy.tobytes() + mesh.connectivity.tobytes()` alloue 2 copies | `hashlib.sha256(...); h.update(points_xy); h.update(connectivity)` évite copie |

---

## 10. CODE MORT ET VERBOSITÉ

| Élément | Statut | Action |
|---|---|---|
| `adapters/display/stub.py` (36 LOC) | Jamais appelé | **Supprimer** |
| `adapters/postprocess/stub.py` (36 LOC) | Jamais appelé | **Supprimer** |
| `simulation/settings.py` — classe `Settings` | Jamais importée par `simulation/**` (seulement `watershed/` et doc audit) | Déplacer vers `watershed/` (son unique consommateur) |
| `_COMPONENT_ENSURERS` + `ensure_process_context` (runner.py:54-83) | Abstraction pour 2 entrées (`flow`, `transport`) | Simplifier : `if process_type in ("flow", "transport"): ensure_flow(state); if process_type == "transport": ensure_transport(state)` → 5 LOC |
| Docstring « Adapters may also implement validate / cleanup » (base.py:12-19) | Contrat jamais tenu | Supprimer ou implémenter |
| `MeshCatchmentLauncher`, `DataOverviewLauncher` (pipelines/mesh.py, overview.py) | Alias transitionnels | Noter dans audit architecture globale (déjà fait en section 01) |
| `process_simulation.py` (32 LOC) | Ne contient plus que des re-exports `# noqa: F401` | **Candidat à suppression** après vérification des importateurs |

---

## 11. RECOMMANDATIONS PRIORISÉES

### 11.1 Critique (à faire en priorité)

1. **Refactorer `Simulation.run()`** pour déléguer à `execute_simulation(ctx)` — supprime ~180 LOC de duplication et un faux `ctx`.
2. **Factoriser `_write_surface_elevation`** dans un helper partagé (gagne ~100 LOC).
3. **Remplacer `try/except TypeError`** dans `post_run.py:90-105` par une signature uniforme.
4. **Ajouter `on_run_error` callback** dans `ProcessCallbacks` pour tracer les échecs par run dans le catalog.
5. **Supprimer les stubs display/postprocess** (72 LOC dead).

### 11.2 Important (à faire rapidement)

6. Typer `except Exception` en exceptions spécifiques dans extractors (~24 blocs).
7. Passer `full3D=True` en MF6 ; supprimer `_recarray_to_grid` (29 LOC).
8. Unifier constantes nodata (`HMP_NODATA`).
9. Ajouter `finally: cleanup_solver_files(...)` autour de `adapter.execute`.
10. Documenter explicitement dans `Simulation.close()` ce qui N'est PAS nettoyé (scratch solveur).

### 11.3 Souhaitable (dette moyen terme)

11. Passer `compute_derived` à un registre `DerivedVariable` avec dépendances topologiques.
12. Introduire un `Protocol WorkflowStep` avec `reads`/`writes` pour typer les steps.
13. Ajouter `SimulationPlan.to_dict()` / `from_dict()` pour reproductibilité.
14. `register_adapter()` via entry points pour un écosystème plugin (optionnel, faible ROI).

---

## 12. VERDICT FINAL PAR SECTION

| Section | Verdict |
|---|---|
| 1. Pattern Adapter | **Acceptable** — Protocol propre, registre minimal mais suffisant, stubs morts |
| 2. Plan immutable | **Conforme** — frozen dataclasses exemplaires, un bémol sur `state: Any` |
| 3. Exécution (Runner) | **À améliorer** — callbacks pauvres, pas de `finally` cleanup |
| 4. Workflow steps | **Non-standard, imperatif** — pas un DAG, mais cohérent si documenté |
| 5. Extracteurs | **À améliorer** — duplication lourde, except trop permissifs |
| 6. Derived variables | **Acceptable** physiquement, **problématique** sur maille irrégulière |
| 7. Classe `Simulation` | **Problématique** — God class, duplique workflow/steps |
| 8. Diagramme | Deux chemins parallèles mal alignés — convergence à opérer |

**Dette technique totale estimée** : ~500 LOC de duplication + 24 except trop larges + 1 God class. **Refactoring ciblé de ~3 jours** permettrait de revenir à un code conforme aux standards de l'industrie sans changer la sémantique externe.

---

*Fin de l'audit — `06_simulation_engine.md`.*
