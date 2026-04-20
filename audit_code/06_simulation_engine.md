# Audit — Moteur de simulation (`simulation/`, `workflow/`, `project.py`)

**Auditeur** : expert design patterns & orchestration scientifique
**Branche** : `dev-database` (HEAD `74b62878`, post-merge `dev-refact`)
**Scope** :

- `hydromodpy/simulation/` (adapters, execution, planning, results, forcing, settings)
- `hydromodpy/workflow/` (pipelines, steps, context)
- `hydromodpy/project.py`

**Volumétrie globale** (`wc -l`) :

| Paquet | Lignes | Fichiers |
|---|---:|---:|
| `simulation/adapters/` (flow+transport+stubs+base+registry) | ~960 | 16 |
| `simulation/planning/` | ~505 | 4 |
| `simulation/execution/runner.py` | 240 | 1 |
| `simulation/results/` (post_run, calibration_bridge) | ~415 | 3 |
| `simulation/results/extractors/` | ~1862 | 9 |
| `simulation/forcing/`, `settings.py`, `__init__.py` | ~93 | 3 |
| `workflow/` (pipelines+steps+context) | ~1597 | 14 |
| `project.py` | 705 | 1 |
| **Total audité** | **~5 377** | **51** |

> Contexte merge : le refactor `dev-refact` a introduit `process/contracts.py`,
> `solver/contracts.py`, l'adaptateur `flow/legacy_compat.py`, les runtimes
> Boussinesq restructurés et les nouveaux diagnostics MF6 (`modflow6/diagnostics.py`,
> `postprocess.py`, `flow_to_modflow_adapter.py`). Dev-database a ensuite supprimé
> la couche `launchers/` ressuscitée par le merge (cf. section « 11. Nettoyage »).

---

## Synthèse exécutive

| Aspect | Verdict | Commentaire 1-ligne |
|---|---|---|
| Pattern Adapter (`SolverAdapter`) | **acceptable** | Vrai `Protocol`, registre statique ; `register_adapter()` jamais appelé |
| Registre de dispatch | **à améliorer** | Deux registres parallèles (exec + extract) non synchronisés |
| `SimulationPlan` (frozen dataclass) | **conforme** | Frozen + tuples ; sérialisation custom manquante |
| `SimulationRunner` | **acceptable** | Callbacks OK ; pas de try/except autour des runs, pas de cleanup garanti |
| Workflow steps | **acceptable** | Fonctions pures sur `WorkflowContext`, mais DAG implicite (ordre codé en dur) |
| Extracteurs | **à améliorer** | Duplication massive (NWT↔MF6), dtype conversions répétitives, I/O non vectorisé |
| `derived.py` | **problématique** | 581 lignes, heuristiques de sentinelles fragiles, helper géotiff laborieux |
| `Simulation` (project.py) | **problématique** | God class, duplique `step_open_store`, override path bypasse `SimulationPlanner` |
| Orchestration comparée à Prefect/Airflow | **non-standard** | DAG implicite, pas de task memoization, pas de retries, pas de persistence d'état |
| Gestion d'erreurs | **à améliorer** | `except Exception: pass`/`logger.debug` généralisé masque des bugs |
| Gestion de ressources | **problématique** | `head_file.close()` non protégé par `with` ; fuite si exception |

**Verdict global** : architecture **correctement découpée** mais **implémentation
irrégulière**. Le squelette Planner/Runner/Adapter est solide et documenté ;
les extracteurs et le code « derived » montrent des signes de développement
opportuniste (heuristiques en dur, fallbacks silencieux, duplications). La
classe `Simulation` détruit une partie du bénéfice architectural en
ré-implémentant la moitié du pipeline en parallèle.

---

## 1. Pattern Adapter — `SolverAdapter` (`adapters/base.py`, `adapters/registry.py`)

### 1.1 Est-ce un vrai Protocol structurel ?

Oui. `adapters/base.py:29` :

```python
class SolverAdapter(Protocol):
    process_type: str
    solver_name: str
    def execute(self, ctx: RunContext) -> RunExecutionResult: ...
```

C'est un `typing.Protocol` pur, structural subtyping correct. Les adaptateurs
concrets (`ModflowNwtFlowAdapter`, `Modflow6FlowAdapter`, `BoussinesqFlowAdapter`,
`ModpathTransportAdapter`, `Mt3dmsTransportAdapter`, `Modflow6GwtTransportAdapter`)
n'héritent pas de `SolverAdapter` — ils sont seulement duck-typés. C'est
conforme PEP 544.

| Critère | Verdict | Justification |
|---|---|---|
| Protocol vs ABC | **conforme** | Vrai structural typing, pas de pseudo-ABC avec `@abstractmethod` |
| Attributs de classe `process_type`/`solver_name` | **acceptable** | Redondants avec la clé du registre (voir 1.2), mais utiles au debug |
| Méthodes optionnelles documentées (`validate`, `cleanup`) | **à améliorer** | Documentées dans le docstring mais jamais appelées par le runner (cf. section 3) |

**Comparaison scikit-learn/FloPy** :

- scikit-learn n'utilise pas Protocol (Python < 3.8) mais un duck-typing
  documenté (`fit`/`predict`/`transform`). L'équivalent moderne est exactement
  ce qu'implémente HydroModPy.
- FloPy n'a pas ce niveau d'abstraction : les solveurs sont des classes
  concrètes. HydroModPy fait mieux ici.

**Recommandation** : ajouter `validate(ctx)` et `cleanup(ctx)` aux adaptateurs
concrets qui en ont besoin, puis les faire appeler par le runner via
`hasattr`. Sinon, supprimer la mention dans le docstring de `base.py` — elle
est actuellement **code mort documentaire**.

### 1.2 Le registre — `adapters/registry.py`

```python
_ADAPTERS: dict[tuple[str, str], SolverAdapter] = {
    ("flow", "modflownwt"): ModflowNwtFlowAdapter(),
    ...
}

def register_adapter(process_type, solver_name, adapter) -> None: ...
def get_solver_adapter(process_type, solver_name) -> SolverAdapter: ...
```

| Critère | Verdict | Justification |
|---|---|---|
| Dispatch dict avec clé `(process_type, solver_name)` | **conforme** | Pattern Strategy canonique |
| Instanciation à l'import | **acceptable** | Adaptateurs stateless, pas de problème ; conteneurs d'état (cache MF6) placés dans `state.setup` |
| `register_adapter` public | **problématique** | **Jamais appelé nulle part** (cf. `grep`). API d'extensibilité morte |
| Entry-points setuptools / plugin | **non** | Non implémenté ; extensibilité par inheritance interne uniquement |

**Comparaison industrie** :

- scikit-learn utilise une « factory + registry » via `__init_subclass__` ou
  une liste statique. Même approche.
- Prefect/Luigi utilisent des entry-points setuptools pour l'extensibilité de
  plugins. Ce n'est pas essentiel dans un projet scientifique in-house.

**Duplication notable** : il existe **un second registre parallèle** dans
`results/post_run.py:21` (`_ADAPTER_REGISTRY`) qui mappe `solver_name` →
`(module_path, class_name)` pour les extracteurs. Les deux registres ne
partagent ni leur clé (1-uplet vs 2-uplet) ni leur API (instance vs lazy
import). Un solveur ajouté dans l'un sans l'autre cause un extraction silently
skipped (`logger.debug`).

**Recommandation** :

- Supprimer `register_adapter()` ou l'utiliser (ex. pour charger les stubs
  `display`/`postprocess`).
- Fusionner les deux registres sous un seul (ou au moins un seul point
  d'entrée de découverte via entry-points `hydromodpy.solver_adapter` +
  `hydromodpy.output_adapter`).

### 1.3 Stubs `display` et `postprocess`

`adapters/display/stub.py` et `adapters/postprocess/stub.py` déclarent 4
classes qui lèvent `NotImplementedError`. **Elles ne sont jamais référencées
ailleurs** (cf. `grep`) et **ne sont pas enregistrées** dans `_ADAPTERS`.

**Verdict** : **dead code**. Le process-type `display` / `postprocess` n'existe
pas dans `known_process_types()` (cf. `planning/config.py` `_validate_type`) ;
les stubs sont donc inaccessibles même en théorie. À supprimer ou à
implémenter.

---

## 2. Plan immuable — `SimulationPlan` (`planning/plan.py`)

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

### 2.1 Immutabilité réelle ?

| Critère | Verdict | Justification |
|---|---|---|
| `frozen=True` | **conforme** | Protections shallow correctes |
| Collections immuables (`tuple`) | **conforme** | `runs` et `depends_on` sont des `tuple`, pas des `list` |
| Pas de référence mutable cachée | **partiellement** | `ProcessRun` ne contient que des `str`/`tuple[str]` — OK. Mais `RunContext.state: Any` est **une back-door massive** (cf. 2.2) |
| `__eq__`/`__hash__` | **conforme** | Hérité automatiquement de `frozen=True` |

### 2.2 Mutations cachées — `RunContext.state`

```python
@dataclass(frozen=True)
class RunContext:
    plan: SimulationPlan
    run: ProcessRun
    state: Any
    dependency_models: tuple[Any, ...] = ()
```

`state: Any` est le `WorkflowContext` qui est **intégralement mutable**
(setup/loaded_data/execution sont des dataclasses non-frozen). Le plan est
immutable **en apparence** mais le runner et les adaptateurs mutent
librement `state.execution.models_by_run_id`, `state.setup.flow`,
`state.setup.mesh_bundle`, etc.

De plus, `BoussinesqFlowAdapter._resolve_planar_mesh` fait
`setattr(setup_state, "mesh_planar", mesh)` (cache latéral via setattr) ce qui
est un anti-pattern : on mute un attribut de dataclass non déclaré comme tel.

**Recommandation** : renommer le docstring pour indiquer que le plan est
*déclaratif et immutable* mais que `RunContext.state` reste **mutable par
design** pour permettre le chaînage de modèles. Éliminer les `setattr` au
profit de champs explicitement déclarés dans `SetupContext`.

### 2.3 Sérialisation / reproductibilité

**Non implémentée**. `SimulationPlan` est un dataclass trivial, mais il
n'existe pas de méthode `to_json()`/`from_json()`. Un plan ne peut pas être
persisté, diff, ni re-exécuté.

`dataclasses.asdict(plan)` fonctionne implicitement puisque tous les champs
sont des `str`/`tuple[str]` : le plan est **sérialisable par accident**, pas
par contrat.

**Comparaison Prefect/Airflow** : chaque DAG est sérialisable (JSON/pickle)
pour inspection, replay, distribution. Ici c'est **partiel**.

**Recommandation** : exposer `SimulationPlan.to_dict() / from_dict()` ; écrire
le plan dans `_config_snapshot.toml` ou dans un champ DuckDB
`simulations.plan_json` pour traçabilité.

### 2.4 Planner — `planning/planner.py`

| Critère | Verdict | Justification |
|---|---|---|
| Préserve l'ordre TOML déclaré | **conforme** | Choix documenté, no topological re-sort |
| Unicité process_id et run_id vérifiée | **conforme** | `seen_process_ids`/`seen_run_ids` guards |
| Résolution `required_bindings` backward-only | **conforme** | Interdit le dépassement de dépendance |
| Message d'erreur | **acceptable** | Explicite mais formatting redondant |
| Complexité | **O(n·m)** avec n=process, m=solvers — trivial |

**Point positif** : le planner est **court (115 lignes)**, testable,
déterministe. Meilleure partie du paquet.

---

## 3. Exécution — `SimulationRunner` (`execution/runner.py`)

### 3.1 Structure

```python
@dataclass(frozen=True)
class ProcessCallbacks:
    before_process: Callable[[str], None] | None = None
    after_process: Callable[[str], None] | None = None
    after_run: Callable[[ProcessRun, RunExecutionResult, Any], None] | None = None

class SimulationRunner:
    def execute(self, plan, state) -> None: ...
```

| Critère | Verdict | Justification |
|---|---|---|
| Callbacks vs Observer/Event-bus | **acceptable** | Callbacks frozen suffisent pour un pipeline linéaire. Un event-bus (pub/sub) serait overkill |
| Granularité des callbacks | **acceptable** | 3 hooks (before/after_process, after_run) — bien pensé |
| `before_run` callback | **manquant** | Asymétrie : il existe `after_run` mais pas `before_run`. Utile pour logging, metrics |

**Comparaison Prefect** : Prefect utilise des tasks et un orchestrateur avec
états (`Pending`, `Running`, `Failed`, `Cached`). Ici l'exécution est **tout
ou rien** : pas d'état persisté, pas de retry, pas de resume. C'est acceptable
pour un outil scientifique batch, mais à documenter comme limitation.

### 3.2 Gestion d'erreurs

```python
def _run_process_run(self, plan, state, run) -> None:
    dependency_models = self._resolve_dependency_models(state, run)
    adapter = get_solver_adapter(run.process_type, run.solver)
    result = adapter.execute(RunContext(...))
    self._record_run_output(state, run, result)
    self._call_after_run(run, result, state)
```

| Critère | Verdict | Justification |
|---|---|---|
| `try/except` autour de `adapter.execute` | **absent** | Si un solver lève, aucune garantie de cleanup |
| `try/finally` pour `after_process` | **partiellement** | Pas de finalisation du block de process type en cas d'exception mi-parcours |
| Rollback du `models_by_run_id` | **absent** | Un modèle partiellement exécuté peut laisser une entrée dans le registre |
| Propagation d'erreur | **OK** | Exception remonte à l'appelant (`Simulation.run` / `execute_simulation`) qui fait le cleanup store |

**Problèmes concrets** :

1. Si `BoussinesqFlowAdapter.execute` raise après avoir écrit `.npz` sur
   disque mais avant `post_processing()`, les fichiers solver restent orphelins.
   Le cleanup en fin de pipeline (`shutil.rmtree(scratch)`) les supprime, mais
   seulement si `keep_solver_files=False`. Sinon, fuite.
2. Le `head_file.close()` dans `modflow6.py:88` **n'est pas dans un `with`** —
   si `store.write_field()` raise, le handle reste ouvert (fuite sur Windows
   qui empêchera de supprimer le .hds).
3. `execute_simulation` a un `except BaseException` qui tente de finaliser le
   store en `"failed"` : bien. Mais il **ne nettoie pas** les fichiers scratch.

**Recommandation** :

- Envelopper les écritures/lectures binaires des extracteurs dans `with
  bf.HeadFile(path) as f:` (pas sûr que FloPy supporte le context manager, à
  vérifier) ou `try/finally`.
- Wrapping explicite `try/except` autour de `adapter.execute()` dans
  `_run_process_run` avec un hook `on_run_failed` dans `ProcessCallbacks`.
- Documenter que le runner n'offre pas de guarantees transactionnelles
  cross-runs.

### 3.3 `ensure_process_context` et helpers free-function

```python
_REQUIRED_COMPONENTS_BY_PROCESS = {"flow": ("flow",), "transport": ("flow", "transport")}
_COMPONENT_ENSURERS = {"flow": ensure_flow, "transport": ensure_transport}
```

Deux registres parallèles pour mapper `process_type` → composants requis +
facteurs pour les créer. OK pour 2 entrées, mais **ne scale pas** :

- `postprocess`, `display`, `optimization` ne peuvent pas être ajoutés sans
  éditer ce fichier.
- Pas de mapping entre `known_process_types()` (dans
  `solver.compatibility`) et `_REQUIRED_COMPONENTS_BY_PROCESS` — divergence
  possible silencieuse.

**Recommandation** : déplacer `_REQUIRED_COMPONENTS_BY_PROCESS` dans
`solver/contracts.py` (unique source de vérité pour les process-types).

### 3.4 Reuse solver model (MF6 only) — asymétrie

Seul `Modflow6FlowAdapter` implémente un cache `_flow_solver_runtime_cache` en
mutant `state.setup`. `ModflowNwtFlowAdapter` et `BoussinesqFlowAdapter`
n'ont pas cette optimisation.

**Verdict** : **à améliorer**. Soit factorisé dans `modflow_common.py`, soit
supprimé (si ce n'est utile qu'à un scénario particulier de calibration). La
duplication silencieuse entre solveurs est un risque de maintenance.

---

## 4. Workflow steps et pipelines — `workflow/`

### 4.1 Steps

Chaque step est une fonction pure prenant un `WorkflowContext` :

- `step_setup`, `step_spatial_supports`, `step_data_loading`, `step_mesh`,
  `step_mesh_input` — préparation
- `step_open_store`, `step_finalize_store` — lifecycle DuckDB
- `step_ingest_run_results`, `step_write_provenance`, `step_persist_forcings`,
  `step_save_run_artifacts` — post-run

| Critère | Verdict | Justification |
|---|---|---|
| Signature uniforme `step(ctx, **kwargs)` | **conforme** | Très bien |
| Mutabilité du context | **acceptable** | Explicite, assumé dans le docstring |
| Composabilité | **acceptable** | Fonctions libres importables unitairement |
| DAG explicite | **absent** | L'ordre d'exécution est codé en dur dans `prepare_simulation_runtime()` et `execute_simulation()` |
| Tests unitaires par step | **partiel** | Existent pour certains (test_process_context_factory) |

**Comparaison Prefect/Airflow** : un DAG Prefect expose les dépendances sous
forme de graphe (`step_data_loading.depends_on = [step_setup]`). Ici les
dépendances sont **implicites** dans l'ordre d'appel. Un test ne détectera pas
si on inverse deux appels.

**Comparaison scikit-learn Pipeline** : un `Pipeline([('scaler', …), ('est', …)])`
est **explicite** et sérialisable ; ici le pipeline est un script.

**Recommandation** : ce n'est pas grave pour l'usage actuel (pipeline linéaire,
pas de fork), mais pour l'avenir (multi-process, calibration branchée),
introduire une classe `Pipeline(steps=[...])` qui accepte une liste de steps
+ dépendances implicites. Ne pas introduire Prefect tant que ce n'est pas
nécessaire — le coût d'adoption est réel.

### 4.2 Pipelines

| Fichier | Lignes | Rôle | Verdict |
|---|---:|---|---|
| `pipelines/simulation.py` | 161 | `prepare_simulation_runtime` + `execute_simulation` | **conforme** |
| `pipelines/mesh.py` | 169 | Launcher `MeshCatchmentLauncher` | **acceptable** (code launcher legacy) |
| `pipelines/overview.py` | 215 | Launcher `DataOverviewLauncher` | **à améliorer** (4 méthodes statiques, 1 instance method, cohabitation illogique) |
| `pipelines/process_simulation.py` | 33 | Re-exports seulement | **dead code** / façade faible |

**`process_simulation.py`** re-exporte 4 noms depuis `workflow/steps/*.py`
avec `# noqa: F401`. Commentaire :

> The ``HydroModPyLauncher`` class that used to live here has been removed

**Verdict** : **dead code**. Le fichier ne contient plus rien de substantiel.
`_build_data_plan` local duplique celui de `workflow/steps/data_loading.py`
(lignes quasi-identiques).

**Recommandation** : supprimer `workflow/pipelines/process_simulation.py` et
rediriger les imports vers `workflow/steps/*`.

### 4.3 `execute_simulation` — contrôle du cleanup

```python
try:
    SimulationRunner(...).execute(plan, ctx)
    step_save_run_artifacts(ctx, wall_seconds)
    if not results_cfg.keep_solver_files:
        shutil.rmtree(scratch, ignore_errors=True)  # <-- dans le try
    ...
    step_finalize_store(ctx, wall_seconds)
except BaseException:
    if ctx.store is not None:
        ctx.store.finalize(ctx.sim_id, status="failed", duration_s=...)
        ctx.store.close()
    raise
```

| Critère | Verdict | Justification |
|---|---|---|
| Fonction + finally | **à améliorer** | Le `shutil.rmtree(scratch)` devrait être dans `finally`, sinon fuite scratch en cas d'erreur |
| `store.finalize` toujours appelé | **conforme** | Géré par les deux branches |
| Cleanup geographic en cas d'échec | **non** | `cleanup_stable_folder` seulement dans la branche success |
| Attraper `BaseException` | **à améliorer** | Trop large (absorbe `KeyboardInterrupt`, `SystemExit`). `Exception` suffit. |

**Recommandation** : restructurer en try/except/finally explicite avec
`KeyboardInterrupt` correctement propagé.

---

## 5. Extracteurs — `simulation/results/extractors/`

### 5.1 Uniformité de l'interface

| Extracteur | Signature `extract` | Signature `derive` | Verdict |
|---|---|---|---|
| `Modflow6OutputAdapter` | `(sim_id, solver_output_dir, store, *, model_name=None, budget_spatial_fields=False)` | `(sim_id, store, config=None)` | OK |
| `ModflowNwtOutputAdapter` | `(sim_id, solver_output_dir, store, *, model_name=None, budget_spatial_fields=False, hdry=-100, hnoflo=-9999)` | `(sim_id, store, config=None)` | **Divergence** des kwargs (hdry/hnoflo hardcodés) |
| `BoussinesqOutputAdapter` | `(sim_id, solver_output_dir, store)` — pas de `budget_spatial_fields` | idem | **Divergence** |
| `Mt3dmsOutputAdapter` | `(sim_id, solver_output_dir, store, *, model_name=None)` | idem | OK |
| `ModpathOutputAdapter` | `(sim_id, solver_output_dir, store, *, model_name=None)` | `(…) → pass` | OK |
| `GR4JOutputAdapter` | `(sim_id, solver_output_dir, store) → pass` + `extract_from_memory(…)` | `(…) → pass` | OK |

Le protocole `OutputAdapter` dans `extractors/base.py` ne déclare **pas** les
kwargs (`budget_spatial_fields`, etc.) — ils sont passés dynamiquement par
`post_run.py` avec un `try/except TypeError` :

```python
try:
    adapter.extract(..., **extract_kwargs)
except TypeError:
    adapter.extract(..., store)
```

**Verdict** : **problématique**. Le fallback sur `TypeError` est un
anti-pattern : il masque les vrais `TypeError` dans le code de l'extracteur.
Préférer l'introspection `inspect.signature(adapter.extract).parameters`.

**Recommandation** : formaliser `ExtractOptions` comme une dataclass et la
passer à tous les extracteurs uniformément.

### 5.2 Duplication extracteurs MF6 ↔ NWT

Les deux fichiers `modflow6.py` (284 l) et `modflownwt.py` (240 l) **dupliquent
à ~70 %** :

| Section | MF6 | NWT | Duplication |
|---|---|---|---|
| Détection `model_name` depuis `.hds` | lignes 35-42 | lignes 37-41 | ~identique |
| `HeadFile` + `get_times` + `get_kstpkper` | 44-48 | 46-49 | identique |
| Boucle `for t, time in enumerate(times)` avec reshape + sentinel masking | 65-74 | 64-73 | différence : MF6 masque `|h|>1e20`, NWT masque `hdry`/`hnoflo` |
| `_extract_budget` | 93-153 | 93-153 | 90 % identique — divergence : MF6 utilise `full3D=True` implicite + handling recarray, NWT `full3D=True` explicite |
| `_extract_mass_balance` | via `Mf6ListBudget` | via `MfListBudget` | structure identique |
| `_write_surface_elevation` | via `MfGrdFile` | via `flopy.modflow.Modflow.load` | logique différente |

**Recommandation** : extraire une classe de base `_ModflowLikeOutputAdapter`
partagée :

```python
class _BinaryHeadExtractor:
    def _read_heads(self, path, mask_fn): ...
    def _read_budget(self, path, times, kstpkpers, reshape_fn): ...
```

Gain estimé : **-200 lignes** et 1 source unique de vérité pour les bugs
(ex. le `np.isclose(values, hdry, atol=1.0)` de NWT est-il correct pour MF6 ?).

### 5.3 Correctness des formats binaires MODFLOW

Tous les extracteurs **délèguent à FloPy** (`bf.HeadFile`, `bf.CellBudgetFile`,
`bf.UcnFile`, `PathlineFile`, `EndpointFile`, `MfGrdFile`). FloPy gère
correctement :

- endianness (little-endian natif, malgré le nom "big-endian" parfois évoqué
  dans la doc MODFLOW)
- precision (single/double, auto-detect avec fallback `precision="double"` en
  cas d'échec — présent dans `modflow6.py:108-111`)
- record markers Fortran

**Verdict** : **conforme**. Le projet ne réinvente pas la roue, c'est le bon
choix.

**Point de vigilance** : le pattern `try: CellBudgetFile(path) except: CellBudgetFile(path, precision="double")` est **seulement dans MF6** (pas dans NWT).
Si un `.cbc` NWT est en double précision, on a un bug latent. Vérifier avec
tests d'intégration.

### 5.4 `_recarray_to_grid` (MF6) — physique

```python
lay = idx // n_cells
cell = idx % n_cells
```

Cette formule suppose **un layout MF6 avec `DISV`** où `node = (layer-1)*n_cells + cell_id`.
Pour `DIS` : `node = (layer-1)*nrow*ncol + (row-1)*ncol + col`, soit aussi
`lay = (node-1) // (nrow*ncol)`, donc OK si `n_cells = nrow*ncol`.

**Verdict** : **conforme pour DIS et DISV**, mais non testé pour `DISU`
(unstructured). Documenter la limitation.

### 5.5 Extracteur Boussinesq

```python
npz_path = solver_output_dir / "_boussinesq_state_history.npz"
with np.load(npz_path) as payload:
    head_history = payload.get("head_history_m")
    ...
```

| Critère | Verdict | Justification |
|---|---|---|
| Format `.npz` (maison) | **acceptable** | Format natif NumPy, interopérable |
| `_persist_state_history` copie tout en Zarr | **à améliorer** | Double stockage (disque .npz + Zarr) pendant la durée de vie du run |
| `_write_surface_elevation` ne gère que `z_top` uniforme | **à améliorer** | Boussinesq 2D avec topo variable n'est pas exploité |

**Recommandation** : écrire directement en Zarr depuis le solveur Boussinesq,
supprimer le détour `.npz`.

### 5.6 I/O non-vectorisé — optimisations

Dans tous les extracteurs :

```python
for t, time in enumerate(times):
    head = head_file.get_data(totim=time)
    values = head.reshape(nlay, n_cells).astype("float64")
    values[np.isclose(values, hdry, atol=1.0)] = np.nan
    store.write_field(sim_id, "head", t, values, ...)
```

**Une écriture Zarr par timestep**. Pour un run de 3650 jours, c'est 3650
appels `write_field`, chacun vérifiant le schema + ouvrant le fichier +
compressant un chunk.

**Comparaison xarray** : `ds.to_zarr(append_dim='time')` accepte un
Dataset entier et gère le buffering. Le store HydroModPy devrait exposer
`write_field_batch(...)`.

**Verdict** : **à améliorer**. Impact perfs potentiellement x2-x5 sur les
grosses simulations.

### 5.7 `catchment_aggregation.py` — 290 lignes

```python
_AGGREGATION_SPEC: list[tuple[str, str, str]] = [
    ("watertable_depth", "watertable_depth", "mean_active"),
    ...
    ("drains|drn|drain", "outflow_drain", "qspe"),
    ...
]
```

| Critère | Verdict | Justification |
|---|---|---|
| Spec déclarative | **conforme** | Bien pensé, facile à étendre |
| Fallback dialectal `drains|drn|drain` | **acceptable** | Compromis pragmatique pour la diversité des solveurs |
| `_reduce` : dispatch string-based | **à améliorer** | Pourrait être un `dict[str, Callable]` au lieu de if/elif |
| Détection stress-period par heuristique `n_head % n_per == 0` | **problématique** | `for n_per in [12, 6, 4, 3, 2, 1]:` est une **devinette** qui échoue dès qu'on a 7 périodes (premier nombre premier > 1) |

**Bug probable** ligne 209 : si `n_head = 7` (7 mois), aucun `n_per ∈ [12, 6, 4, 3, 2, 1]` ne divise ; on tombe dans le `else` qui met `nstp=1, n_per = n_head`, ce qui masque le vrai nombre de périodes.

**Recommandation** : lire le nombre de stress periods depuis `simulations.n_timesteps` (DuckDB) + `time.substeps_per_period`. Ne pas deviner.

---

## 6. Derived variables — `extractors/derived.py` (581 l)

### 6.1 Physique

| Variable | Formule | Conformité |
|---|---|---|
| `watertable_elevation` | head @ uppermost saturated layer via `flopy.get_water_table` | **conforme** |
| `watertable_depth` | `max(top - wt, 0)` | **conforme** |
| `seepage_areas` | `wt >= top_elev` (0/1) | **conforme** (binaire) |
| `groundwater_flux` | `sqrt(sum(face_flow²))` | **acceptable** (norm L2 sur flux sur faces — approximation raisonnable, mais pas la vraie magnitude car les faces ne sont pas orthogonales en DISV) |
| `accumulation_flux` | D8 routing via whitebox, fallback `abs(drn)` | **conforme** |
| `outflow_drain` | `drn` avec signe | **conforme** |
| `concentration_seepage` | `conc * seepage` | **conforme** |
| `mass_seepage` | `conc_seep * abs(drn)` | **conforme** |
| `mass_accumulated` | `cumsum(mass_seepage)` sans pondération temporelle | **problématique** : pas de multiplication par `dt` |

**Critique `mass_accumulated`** : pour une masse accumulée, on veut
`∫ flux dt`, pas `Σ flux`. Si les timesteps ne sont pas uniformes, le résultat
est faux dimensionnellement. Le champ s'appelle « cumulative mass_seepage over
time » ce qui est ambigu.

### 6.2 Gestion des NaN/nodata

`_compute_watertable_elevation` contient une **heuristique de sentinelles en
cascade** (lignes 119-131) :

```python
_SENTINEL_THRESHOLD = -50.0
head_sample = head_arr[:].ravel()  # <-- charge TOUT le head array en mémoire
finite_heads = head_sample[np.isfinite(head_sample)]
if finite_heads.size > 0:
    p01 = float(np.nanpercentile(finite_heads[finite_heads > _SENTINEL_THRESHOLD], 1)) if ... else 0.0
    legacy_floor = min(_SENTINEL_THRESHOLD, p01 - 200.0)
```

| Critère | Verdict | Justification |
|---|---|---|
| Charge tout le tableau head en mémoire | **problématique** | `head_arr[:]` sur 3650 timesteps × 10k cells = 300 Mo ; utiliser streaming |
| Magic number `-50.0` | **problématique** | Dépend de l'altitude du bassin versant. Un DEM négatif (ex. bassin côtier Pays-Bas) casse cette heuristique |
| `p01 - 200.0` | **arbitraire** | Documentation absente |

**Verdict** : **problématique**. Les extracteurs doivent avoir **déjà
mis NaN** les sentinelles. Cette double-protection masque les bugs en amont.

**Recommandation** : supprimer cette rustine. Documenter clairement que
l'extracteur amont **doit** nettoyer les sentinelles.

### 6.3 Helper `_write_bare_tif` — duplication interne

Lignes 13-27 : helper local pour écrire un `.tif` avec CRS factice
`EPSG:32631`.

**Verdict** : **problématique** multiples.

1. Le CRS est hardcodé à UTM 31N (ouest de la France). Un bassin en UTM 32
   ou Lambert-93 aura des pixels déformés par whitebox.
2. La fonction est répétée partout où on a besoin de whitebox (cf.
   duplications dans `spatial/` à vérifier).
3. `transform = from_bounds(0, 0, ncol, nrow, ncol, nrow)` : le pixel size
   est 1 unité (pas 1 m). Pour D8 routing, OK (relatif), mais ça reste
   fragile.

**Recommandation** : déplacer dans un `core/backends/geotiff.py`, accepter
CRS et pixel_size en paramètres.

### 6.4 Extensibilité de `compute_derived`

```python
DERIVED_VARIABLES = {
    "watertable_elevation": True,
    ...
}
...
if flags.get("watertable_elevation"):
    _compute_watertable_elevation(...)
if flags.get("watertable_depth"):
    _compute_watertable_depth(...)
...
```

9 `if flags.get(...)` successifs. Pas de registre de computers.

**Verdict** : **à améliorer**. Un dict `{name: callable}` serait plus
idiomatique et permettrait l'extension sans éditer ce fichier :

```python
_DERIVED_COMPUTERS = {
    "watertable_elevation": _compute_watertable_elevation,
    "watertable_depth": _compute_watertable_depth,
    ...
}
for name, computer in _DERIVED_COMPUTERS.items():
    if flags.get(name):
        try:
            computer(sim_id, store, head_arr, n_timesteps, n_layers, n_cells)
        except Exception:
            logger.exception("Derived %s failed", name)
```

---

## 7. Classe `Simulation` (`project.py`, 705 l)

### 7.1 God class ?

**Oui.** Recensement des responsabilités (ligne 132-705) :

1. Chargement TOML + validation Pydantic
2. Détection du solveur par inspection TOML
3. Synthèse d'un `[simulation]` block si absent
4. Résolution mesh (embedded vs external)
5. Spatial-support registry bootstrap
6. Data plan building + inference
7. WorkflowContext instanciation
8. Postprocess runner lifecycle
9. `prepare_simulation_runtime` invocation
10. **SimulationCatalog ouverture/fermeture** (duplicate avec `step_open_store`)
11. `run()` avec deux branches : avec/sans overrides
12. Injection manuelle des `flow_runtime_overrides` pour calibration
13. Enregistrement simulation + mesh + geographic + forcings dans le store
14. Exécution via `SimulationRunner`
15. Finalisation / gestion d'erreurs
16. `_rebuild_domain(thickness)` — mini-pipeline de reconstruction de domaine
17. Context manager (`__enter__`/`__exit__`)

**Verdict** : **problématique**. ~16 responsabilités dans **une seule classe**.
Le score de responsabilité cyclomatique de `run()` est probablement > 15.

### 7.2 Duplication massive avec `step_open_store` / `execute_simulation`

`Simulation.run()` (lignes 342-548, 207 lignes) **ré-implémente** :

- `_collect_registration_kwargs` → ligne 415-456 dans `run()` (copié-collé)
- `_write_flow_parameters` → importé en interne depuis `store_lifecycle`
- `store.write_mesh(...)` → ligne 465-479 (re-duplication de `step_open_store`)
- `persist_geographic_to_store(...)` → ligne 483-486 (re-duplication)
- `step_persist_forcings(...)` → invoqué avec un **`_tmp_ctx` ad-hoc**
  fabriqué avec `type("_Ctx", (), {...})()` (ligne 490)
- `SimulationRunner(...).execute(plan, self._ctx)` → exécution
- Configuration `ResultsConfig` hardcodée (lignes 504-514)

**Verdict** : **problématique**. La classe `Simulation` contourne
`execute_simulation()` et ré-écrit le pipeline sous une forme légèrement
différente. Cette divergence est **un nid à bugs** : toute amélioration de
`execute_simulation()` doit être répliquée manuellement dans
`Simulation.run()`.

**Recommandation** : faire de `Simulation.run(**overrides)` un **wrapper
mince** :

```python
def run(self, *, name=None, **overrides):
    self._apply_overrides(overrides)
    ctx = self._ctx
    ctx.setup.run_id = name or f"run_{self._run_counter:04d}"
    ctx.execution.simulation_plan = self._plan_for(overrides)
    execute_simulation(ctx)
    return SimulationResult(ctx.sim_id, name, ctx.store)
```

Et placer toute la logique store/registration dans `execute_simulation()`.

### 7.3 Bypass du `SimulationPlanner`

```python
def _run_with_overrides(self, name, overrides, ...):
    ...
    run_entry = ProcessRun(id=f"flow_main::{self._solver}", ...)
    plan = SimulationPlan(name=name, description=name, runs=(run_entry,))
    ...
```

**Verdict** : **problématique**. La méthode **construit un `SimulationPlan`
à la main** sans passer par `SimulationPlanner.build()`. Conséquence : les
validations (unicité des IDs, dépendances, `required_bindings`) sont
contournées. Pour un simple cas flow-only, ça marche ; pour des cas multi-
process avec overrides, ça ne fonctionnera pas.

**Recommandation** : overrides agissent sur `ctx.setup.flow.parameters` et
sur `ctx.setup.domain`, pas sur la structure du plan. Le plan doit toujours
venir du planner.

### 7.4 Context manager

```python
def __enter__(self): return self
def __exit__(self, *exc): self.close()

def close(self):
    cleanup_stable_folder(self.geographic)  # <-- peut raise
    if self._store is not None:
        self._store.close()
        self._store = None
```

| Critère | Verdict | Justification |
|---|---|---|
| `__enter__`/`__exit__` présents | **conforme** | |
| `__exit__` ignore les exceptions | **acceptable** | `*exc` ignoré, `close()` tourné |
| Cleanup garanti | **à améliorer** | `cleanup_stable_folder` avant `store.close` : si le premier raise, `store` n'est jamais fermé |
| Support ré-entrée | **non** | Si on ré-entre après `close()`, on obtient un état indéfini (self._store = None mais self.cfg/ctx toujours utilisés par les properties) |
| Support "déjà fermé" | **partiel** | `self._store = None` check dans `close()` mais pas dans `run()` |

**Recommandation** :

```python
def close(self):
    errors = []
    if self._store is not None:
        try:
            self._store.close()
        except Exception as e:
            errors.append(e)
        self._store = None
    try:
        cleanup_stable_folder(self.geographic)
    except Exception as e:
        errors.append(e)
    if errors:
        raise ExceptionGroup("close errors", errors)
```

### 7.5 `_ensure_simulation_block` — infer time window depuis recharge

```python
start = getattr(recharge_cfg, "date_start", None) if recharge_cfg else None
end = getattr(recharge_cfg, "date_end", None) if recharge_cfg else None
```

**Verdict** : **à améliorer**. La time window doit venir de
`[simulation.time]` ou être construite par l'utilisateur. Inférer depuis
`[data.recharge]` est pratique mais couple fortement `Simulation` à la
nature hydrogéologique de la config. Pour un `Transport`-only run, ce code
échoue à trouver date_start/date_end dans recharge.

---

## 8. Diagramme de séquence : TOML → Config → Plan → Run → Extract → Derive → Export

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. TOML  → HydroModPyConfig.from_toml()                                    │
│              (core/config/hydromodpy_config.py)                             │
│              → validation Pydantic (extra="forbid"), ParamLevel             │
│              → cfg.simulation (SimulationConfig)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  2. Config → SimulationPlanner.build(cfg.simulation) → SimulationPlan       │
│              (frozen dataclass, tuple[ProcessRun, ...])                     │
│              • vérifie unicité ids                                          │
│              • résout dépendances via required_bindings()                   │
│              • préserve l'ordre TOML                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  3. WorkflowContext ← prepare_simulation_runtime(ctx, ...)                  │
│              step_setup → step_spatial_supports → step_data_loading         │
│              → step_mesh → step_mesh_input                                  │
│     [mutation explicite de ctx.setup, ctx.loaded_data]                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  4. Open store: step_open_store(ctx)                                        │
│              • uuid4() → ctx.sim_id                                         │
│              • SimulationCatalog(workspace_root) → ctx.store                │
│              • register_simulation + write_mesh + write_parameters          │
│              • step_write_provenance + step_persist_forcings                │
├─────────────────────────────────────────────────────────────────────────────┤
│  5. Run: SimulationRunner(callbacks).execute(plan, ctx)                     │
│              for run in plan.runs:                                          │
│                  ensure_process_context(state, run.process_type)            │
│                  [before_process callback]                                  │
│                  adapter = get_solver_adapter(run.process_type, run.solver) │
│                  result = adapter.execute(RunContext(plan, run, state, ...))│
│                  state.execution.models_by_run_id[run.id] = result.primary  │
│                  [after_run callback → step_ingest_run_results]             │
│                  [after_process callback → postprocess_runner]              │
├─────────────────────────────────────────────────────────────────────────────┤
│  6. Extract (dans after_run → post_run_results):                            │
│              adapter = _get_output_adapter(solver_name)                     │
│              adapter.extract(sim_id, solver_output_dir, store, **kwargs)    │
│                 [lit .hds/.cbc/.lst/.npz, écrit Zarr]                       │
│              adapter.derive(sim_id, store, derived_flags)                   │
│                 [compute_derived: watertable_*, seepage, …]                 │
│              aggregate_catchment_timeseries(sim_id, store)                  │
│                 [scalaires catchment-wide → DuckDB]                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  7. Export (dans _auto_export si export.any_enabled()):                     │
│              store.export(sim_id, var, fmt, path, ...)                      │
│              csv / netcdf / vtu / geotiff / shapefile                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  8. Finalize: step_finalize_store(ctx, wall_seconds)                        │
│              store.finalize(sim_id, status="completed", duration_s=...)     │
│              store.close()                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Anomalies observées sur ce diagramme** :

- **Étape 4 / 6** : le store est ouvert **avant** la boucle de runs, mais
  les runs écrivent DEDANS pendant l'exécution. Si une exception arrive à
  mi-parcours, le sim est partiellement peuplé avec `status != completed`.
  OK (documenté par `finalize(status="failed")`).
- **Étape 5** : `ensure_process_context` est appelé lors du **changement** de
  `process_type`, pas avant chaque run. Si une init échoue, seuls les runs
  suivants sont affectés.
- **Étape 6 et 7 mélangées** : `_auto_export` est appelé **à chaque
  after_run** (cf. `post_run.py:124`). Pour un plan avec 3 runs
  (flow + 2 transports), on exporte 3 fois. Probablement **inefficace**.
  L'export devrait être appelé une seule fois en fin de pipeline.

---

## 9. Duplications et dead code — récapitulatif

| Localisation | Type | Sévérité | Action |
|---|---|---|---|
| `simulation/results/extractors/modflow6.py` vs `modflownwt.py` (~70 %) | Code dupliqué | **élevée** | Extraire base `_BinaryHeadExtractor` |
| Deux registres (`adapters/registry.py`, `results/post_run.py`) non synchronisés | Code dupliqué | **moyenne** | Fusionner ou cross-reference |
| `Simulation.run()` vs `execute_simulation()` vs `step_open_store` | Logique dupliquée | **élevée** | Refactorer `Simulation` en wrapper |
| `_collect_registration_kwargs` dupliqué entre `store_lifecycle.py` et `project.py` | Code dupliqué | **moyenne** | Import canonique depuis `store_lifecycle` |
| `workflow/pipelines/process_simulation.py` (33 l, re-exports uniquement) | Dead code | **basse** | Supprimer |
| `simulation/adapters/display/stub.py` + `postprocess/stub.py` (72 l) | Dead code (jamais enregistré) | **basse** | Supprimer ou implémenter |
| `simulation/adapters/registry.py::register_adapter` | API morte (jamais appelée) | **basse** | Supprimer ou utiliser |
| `simulation/adapters/flow/legacy_compat.py` | Rarement appelé (opt-in) | **basse** | Documenter suppression future |
| `simulation/settings.py` (16 l, `DeprecationWarning`) | Alias deprecated | **basse** | Supprimer dans N+1 release |
| `simulation/forcing/__init__.py` (31 l, re-exports) | Façade faible | **basse** | Vérifier usage, supprimer si inutile |
| `Modflow6FlowAdapter._solver_runtime_cache` | Optim asymétrique (MF6 only) | **moyenne** | Factoriser dans `modflow_common` ou supprimer |
| `_write_bare_tif` (derived.py) avec CRS hardcodé EPSG:32631 | Anti-pattern | **moyenne** | Paramétrer ou déplacer |
| `for n_per in [12, 6, 4, 3, 2, 1]` (catchment_aggregation.py) | Heuristique bugguée | **élevée** | Lire n_periods depuis DuckDB |

---

## 10. Gestion d'erreurs — récapitulatif

| Pattern trouvé | Occurrences (approx.) | Verdict |
|---|---:|---|
| `except Exception:` + `logger.debug(...)` | ~18 | **problématique** — masque des bugs |
| `except Exception:` + `logger.exception(...)` | ~9 | **acceptable** — trace stack mais continue |
| `except Exception:` + `pass` | 3 | **problématique** — silence total |
| `except (EOFError, Exception):` | 1 (mt3dms.py:49) | **non-standard** — `Exception` englobe déjà `EOFError` |
| `except BaseException:` | 1 (simulation.py:152) | **à améliorer** — absorbe `KeyboardInterrupt` |
| `try/finally` pour ressource | ~2 | **insuffisant** |
| Context manager `with` | ~5 | **à augmenter** |

**Recommandation globale** : passer tous les `except Exception: logger.debug`
en `except SpecificError: logger.debug` + `except Exception: logger.exception`.
Les extracteurs en particulier mangent toutes les exceptions sans indication,
ce qui rend le debugging catastrophique.

---

## 11. Optimisations potentielles

1. **Écritures Zarr par batch** (sections 5.6) : 2-5× plus rapide.
2. **Lecture FloPy streaming** : `HeadFile.get_data(totim=t)` relit le header
   à chaque appel ; `get_alldata()` serait plus efficace si mémoire permet.
3. **Vectorisation des reducers catchment** (`_reduce`) : boucle Python sur
   timesteps alors que les fields sont numpy arrays. Un `np.nanmean(arr,
   axis=1)` sur l'ensemble épargne 100 itérations Python.
4. **`head_sample = head_arr[:].ravel()` puis `np.isfinite`** : chargement
   full-array en RAM. Remplacer par un `np.min`/`np.max` en streaming.
5. **`compute_derived`** : les appels sont tous séquentiels et disjoints ;
   parallélisables (ThreadPoolExecutor, I/O-bound sur Zarr).

---

## 12. Comparaison standards industrie

| Aspect | HydroModPy | Prefect | Airflow | scikit-learn Pipeline | Verdict |
|---|---|---|---|---|---|
| DAG explicite | Non (ordre script) | Oui | Oui | Oui (steps list) | **à améliorer** |
| Retries auto | Non | Oui | Oui | N/A | **acceptable** (batch scientifique) |
| State persistence entre runs | Partielle (DuckDB) | Oui (backend) | Oui | N/A | **acceptable** |
| Sérialisation plan | Par accident (dataclass) | Oui | Oui | `joblib` | **à améliorer** |
| Observer/Event | Callbacks | Events + hooks | Signals | `set_params` | **acceptable** |
| Plugin system | Registry manuel | Entry-points | Plugins | N/A | **acceptable** |
| Tests de composabilité | ?  | Oui | Oui | Oui | **à vérifier** |

---

## 13. Verdict final par section

| Section | Verdict | Priorité fix |
|---|---|---|
| 1. Adapter pattern | Acceptable | P3 |
| 2. SimulationPlan immuable | Conforme | — |
| 3. SimulationRunner | Acceptable (erreurs à durcir) | **P1** |
| 4. Workflow steps | Acceptable | P3 |
| 5. Extractors uniformity | À améliorer (duplication MF6↔NWT) | **P1** |
| 5.7 catchment_aggregation | À améliorer (bug heuristique) | **P1** |
| 6. Derived variables | Problématique (heuristiques) | **P2** |
| 7. Simulation class | Problématique (God class, duplication) | **P1** |
| 8. Orchestration séquence | Acceptable | P3 |

**P1 = à corriger dans les 2 prochaines PR.**
**P2 = à corriger dans le trimestre.**
**P3 = à noter pour refactor long terme.**

---

## 14. Actions recommandées — top 10

1. **Fusionner `Simulation.run()` avec `execute_simulation()`** — éliminer la
   duplication store/register/persist (≈ -150 lignes).
2. **Extraire `_BinaryHeadExtractor`** commun MF6/NWT — éliminer ≈ 200 lignes.
3. **Remplacer la devinette `n_per ∈ [12,6,4,...]`** par lecture DuckDB —
   corrige bug sur 7/11/13 périodes.
4. **Envelopper les I/O FloPy** (`HeadFile`, `CellBudgetFile`) dans
   `try/finally` ou context manager explicites — corrige fuites handle.
5. **Supprimer `register_adapter` inutilisé** ou enregistrer réellement les
   stubs display/postprocess.
6. **Fusionner les registres** `adapters/registry.py` et
   `post_run._ADAPTER_REGISTRY` sous un unique point d'entrée.
7. **Exporter une seule fois** (`_auto_export`) en fin de plan, pas après
   chaque run.
8. **Éliminer `_SENTINEL_THRESHOLD = -50.0`** dans `derived.py` — le cleanup
   doit être fait au niveau extracteur uniquement.
9. **Rendre `compute_derived` extensible** via un `dict[name, computer]`
   enregistrable depuis l'extérieur.
10. **Tous les `except Exception: logger.debug`** → `except SpecificError:
    logger.debug` + `except Exception: logger.exception`.

---

## 15. Verdict global — en une phrase

Le squelette Planner/Runner/Adapter est **bien pensé et documenté**, mais les
extracteurs et la classe `Simulation` trahissent un développement en
accrétion (duplication, heuristiques fragiles, gestion d'erreur laxiste) qui
réduit significativement la qualité perçue d'ensemble ; un effort de
factorisation ciblé (top 10 ci-dessus) ramènerait l'ensemble au niveau
attendu pour un outil scientifique de production.
