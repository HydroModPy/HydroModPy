# Prompt : intégration complète de la calibration dans l'architecture v0.6

Lance ce prompt dans une nouvelle session Claude Code à la racine de
`/home/bb/Documents/01_Git_Repository/02-HydroModPy-dev`.

---

## Rôle

Tu intègres la calibration à 100 % dans la nouvelle architecture publique
(`Project.calibrate()`, `hmp run`, catalog DuckDB, Pydantic partout) et tu
supprimes `hydromodpy/calibration/benchmark.py` une fois les validation
cases portées.

## Lectures obligatoires avant de coder

Dans cet ordre :

1. `BENCHMARK_PY_ANALYSIS.md` (cartographie factuelle du problème)
2. `LEGACY_REMAINING.md` section 1 (raisons de conservation actuelles)
3. `CLAUDE.md` (conventions projet, Pydantic, catalog, tests)
4. `hydromodpy/calibration/benchmark.py` (source à supprimer)
5. `hydromodpy/calibration/cli.py` + `engine.py` + `config.py` + `parameters.py` + `objective.py` + `persistence.py` + `optimizer.py` + `adapters/*` (cible)
6. `hydromodpy/project.py` méthode `calibrate` (ligne 636)
7. `validation_cases/calibration/shared/runtime.py` (consommateur legacy)
8. `tests/validation/calibration/test_twin_*.py` (tests à préserver)

## Règles absolues

- **Pas de push.** Jamais. Commits locaux seulement. L'utilisateur pousse lui-même.
- **Commits sans co-author.** Titre seul, pas de body, pas de `Co-Authored-By`.
- **Format de commit : `[zone] - short english description`**
  - Zones autorisées : `calibration`, `config`, `adapters`, `parameters`, `objective`, `project`, `persistence`, `cli`, `validation`, `tests`, `docs`, `cleanup`
  - English simple, phrases courtes, pas de tiret long (em-dash)
  - Exemples :
    - `[config] - add calib output and objective block models`
    - `[adapters] - add cma adapter`
    - `[validation] - port dupuit fixed head twin case`
    - `[cleanup] - remove benchmark legacy module`
- **Style code** : anglais simple, phrases courtes, pas de tiret long, pas de commentaires inutiles (par défaut aucun). Quand un commentaire est nécessaire, expliquer **pourquoi**, pas **quoi**.
- **Pas de backwards-compat shims** pour du code interne. Pour le schéma TOML `[model_calibration]` user-facing, ajouter un warning de déprécation dans `detect_workflow` qui auto-convertit vers `[calibration]` (retrait après 1 release).
- **Goldens intouchables.** Si un golden diverge après portage, diagnostiquer avant de modifier. Divergence = bug, pas feature.
- **Pas de mock DB** dans les tests d'intégration.
- **TaskCreate** pour suivre les 10 phases, marquer `in_progress` / `completed` au fur et à mesure.

## Subagents

Utilise des subagents `model: "opus"` (Opus 4.7) pour paralléliser.
Batche plusieurs `Agent` calls dans un seul message dès que possible.

Parallélisables :
- Phase 1, 2, 3 (indépendantes sur `config`, `parameters`, `objective`)
- Phase 4 adapters (1 subagent par adapter à créer ou rework)
- Phase 9 cas validation (1 subagent par cas après portage des shared helpers)

Séquentielles :
- Phase 5 après 3
- Phase 6 après 5
- Phase 7 et 8 après 6
- Phase 9 après 8
- Phase 10 après 9

---

## Objectif final

- `hydromodpy/calibration/benchmark.py` supprimé
- `grep -rn "from hydromodpy.calibration.benchmark" .` renvoie 0 ligne
- `Project.calibrate()` fonctionne avec ET sans TOML
- `hmp run calibration.toml` accepte le schéma enrichi
- Tous les tests verts : `hmp test unit`, `hmp test regression --fast`, `pytest tests/validation/calibration/ -v`
- Goldens scientifiques inchangés
- `LEGACY_REMAINING.md` n'a plus que 3 entrées (CatchmentDelineation, DataStore.workspace_root, docstrings)

---

## Plan (10 phases)

### Phase 1 — enrichir `CalibrationConfig`

Fichier : `hydromodpy/calibration/config.py`

Étendre `CalibParameterDecl` avec :
- `target: str | None` (alias lisible de `path`)
- `mode: Literal["replace", "scale"] = "replace"` (USER)
- `parameterization: str = "global_value"` (DEV)
- `property: str | None` (DEV)
- `lithology_key: str | None` (DEV)

Nouveaux modèles Pydantic (`ConfigDict(extra="forbid")`, `ParamLevel`, `description=`) :

```python
class CalibOutputDecl(BaseModel):
    name: str
    variable: str
    support: Literal["point", "boundary", "cell"]
    x: Length | None = None
    y: Length | None = None
    boundary_id: str | None = None
    time: Literal["all", "last", "first"] | list[str] = "all"
    reducer: Literal["mean", "sum", "last", "none"] = "none"
    observed_values: list[float] | None = None

class CalibObjectiveBlockDecl(BaseModel):
    name: str
    metric: str = "rmse"
    weight: float = 1.0
    uses_outputs: list[str]
    normalize_cost: bool = False
    transform: Literal["identity", "log", "inverse"] = "identity"
```

Ajouter à `CalibrationConfig` :
- `outputs: dict[str, CalibOutputDecl] = {}`
- `objective_blocks: list[CalibObjectiveBlockDecl] = []`
- `persist_iteration_detail: Literal["none", "summary", "full"] = "summary"`
- `persist_model_distribution: bool = False`
- `resume_session: str | None = None`
- `rerun_best_with_outputs: bool = False`
- `materialize_candidates: bool = False`
- `candidates_root: Path | None = None`

Validator : si `objective_blocks` vide, construire un bloc implicite depuis `(objective, variable)`.

Tests : `tests/unit/calibration/test_config_enrichment.py`
- round-trip TOML riche
- extra field rejeté
- bloc implicite OK

Commits :
- `[config] - add calib output and objective block models`
- `[config] - extend calib parameter decl with mode and target`

---

### Phase 2 — modes `replace` / `scale`

Fichiers : `hydromodpy/calibration/parameters.py`, `hydromodpy/simulation/execution/trial.py`

- `CalibParameter` gagne `mode: str`, `target: str | None`
- `ParameterSpace.from_toml_mapping` hydrate ces champs
- Nouveau helper `apply_parameter_to_config(cfg, param, value)` dans `parameters.py` : résout dotted-path, applique `replace` ou `scale`
- `run_trial_light` utilise ce helper (plus de `_override_paths` brut)

Tests : `tests/unit/calibration/test_parameter_apply.py` (deux modes, erreur si path invalide).

Commit : `[parameters] - support replace and scale modes`

---

### Phase 3 — composite objective builder

Fichiers : `hydromodpy/calibration/objective.py`, `hydromodpy/calibration/metrics.py`

Nouveau :

```python
def build_objective_from_config(cfg: CalibrationConfig) -> Objective
```

- Lit `cfg.outputs` + `cfg.objective_blocks`
- Construit un `ScalarObjective` par bloc
- Assemble en `CompositeObjective` (ou retourne un seul `ScalarObjective` si un seul bloc)

Étendre `build_metric_extractor` :
- Accepte `cfg.outputs` pour extraction multi-observables
- Support `point` (head at x/y/layer) porté depuis `benchmark.py:800`
- Support `boundary` (DRAIN discharge par `boundary_id`) porté depuis `benchmark.py`
- Si `output.observed_values` fourni, l'utiliser comme `ObservationSet.values` directement

Tests : `tests/unit/calibration/test_composite_objective.py` (2 blocs pondérés, normalize_cost, transform).

Commit : `[objective] - build composite objective from config`

---

### Phase 4 — adapters unifiés (supprimer les 7 `_driver_*`)

Fichier : `hydromodpy/calibration/adapters/`

Actions parallèles (1 subagent par item, batch les Agent calls) :

1. Créer `cma_adapter.py` avec `CmaEsAdapter(space, *, sigma0, popsize, max_evaluations, normalize, seed)` utilisant le package `cma`. Le signature doit matcher `_driver_cma_es` pour préserver le comportement numérique.
2. Enregistrer `random_search` comme alias Optuna `RandomSampler` dans le registry de `optimizer.py`.
3. Aligner les noms de méthodes sur le legacy : `grid_search`, `random_search`, `simplex`, `cma_es`, `nelder_mead`, `gp_mapping`, `da_mh_gp`. Mettre à jour `CalibrationConfig.method` Literal.
4. Tests unitaires pour chaque adapter : bounds respectées, seed reproductible, `ask`/`tell` retourne les bonnes formes.

Commits (un par adapter ou groupe logique) :
- `[adapters] - add cma adapter`
- `[adapters] - register random search as optuna alias`
- `[adapters] - align method names with legacy schema`
- `[tests] - add adapter unit tests`

---

### Phase 5 — `materialize_candidate` public

Fichier : nouveau `hydromodpy/calibration/materialize.py`

API :

```python
def materialize_candidate(
    base_config: Path | HydroModPyConfig,
    params: dict[str, float],
    space: ParameterSpace,
    out_dir: Path,
) -> Path:
    """Write a self-contained TOML overlay for one candidate."""
```

Port de `benchmark.py:856` (`actualize_candidate`). Le TOML produit est
rechargeable via `Project(path)` (paths absolus ou relatifs à un
`base_dir` explicite).

Intégration : si `cfg.materialize_candidates=True`, `on_iteration` écrit
un overlay sous `cfg.candidates_root / iter_XXXX / config.toml`. Le
chemin est attaché aux `metadata` de `EvaluationResult`.

Export dans `hydromodpy/calibration/__init__.py`.

Tests : TOML produit rechargeable + valeurs appliquées correctement.

Commit : `[calibration] - add public materialize candidate helper`

---

### Phase 6 — `Project.calibrate` mode Python

Fichier : `hydromodpy/project.py`, `hydromodpy/calibration/cli.py`, `hydromodpy/calibration/report.py`

Refactor : extraire le cœur de `run_calibration_cli` en

```python
def _run_calibration(cfg: CalibrationConfig, trial_ctx, *, workspace, project_label, objective=None, metric_fn=None) -> CalibrationReport
```

Deux shells autour :
- `run_calibration_cli(path, ...)` : charge TOML puis appelle `_run_calibration`
- `run_calibration_programmatic(cfg, project, ...)` : pas de TOML

Étendre `Project.calibrate` :

```python
def calibrate(
    self,
    *,
    config_path: str | Path | None = None,
    parameters: dict[str, dict] | None = None,
    outputs: dict[str, dict] | None = None,
    objective_blocks: list[dict] | None = None,
    method: str = "optuna",
    max_iter: int = 50,
    save_runs: str = "none",
    **kw,
) -> CalibrationReport
```

- Si `config_path` fourni, délègue à `run_calibration_cli`
- Sinon construit un `CalibrationConfig` en mémoire et appelle `run_calibration_programmatic`

Nouveau type retour `CalibrationReport` (dataclass dans `report.py`) :
- `session_id, method, n_iterations, best_objective, best_sim_id, duration_s, save_runs, promoted`
- `.iterations` → DataFrame depuis catalog
- `.best` → `Run` (via `catalog[best_sim_id]`)
- `.plot(name, **kw)` → délègue au rendering existant
- `.to_dict()` pour compat CLI

`run_calibration_cli` retourne `CalibrationReport.to_dict()` pour préserver la signature publique.

Tests : `tests/unit/calibration/test_project_calibrate_python.py` (bout-en-bout, pas de TOML).

Commits :
- `[calibration] - add calibration report dataclass`
- `[project] - enable python mode on project calibrate`

---

### Phase 7 — CLI dispatch

Fichier : `hydromodpy/_cli/workflows.py`, `hydromodpy/runners/__init__.py`

- Vérifier que `detect_workflow` route `[calibration]` enrichi correctement
- S'il existe une branche `[model_calibration]` dans le dispatch, la supprimer et la remplacer par un warning de déprécation qui auto-convertit vers `[calibration]`
- `hmp config <out>.toml --profile user|dev|expert` doit exporter le nouveau schéma (ParamLevel gère la vue)

Test : `tests/unit/cli/test_calibration_dispatch.py` sur un TOML riche minimal.

Commit : `[cli] - dispatch enriched calibration schema`

---

### Phase 8 — persistence enrichie

Fichiers : `hydromodpy/calibration/persistence.py`, `hydromodpy/results/catalog.py`

- `append_iteration` écrit `block_costs` dans `metrics: JSON` si `persist_iteration_detail="full"`
- Nouveau `catalog.export_calibration_session(session_id, out_dir)` :
  - Produit `iteration_history.jsonl` au format legacy (shim compat)
  - Produit `session_manifest.json`
  - Produit `model_distribution.json` si demandé
- Catalog expose :
  - `catalog.calibration_sessions` (DataFrame)
  - `catalog.calibration_iterations(session_id)` (DataFrame)

Tests : export jsonl identique au legacy sur un fixture simple.

Commit : `[persistence] - export session in legacy jsonl format`

---

### Phase 9 — port des validation cases

Fichiers : `validation_cases/calibration/shared/runtime.py`, `validation_cases/calibration/shared/definitions.py`, tous les `run_case.py` sous `validation_cases/calibration/`, tous les `test_twin_*.py` sous `tests/validation/calibration/`.

#### 9.1 — shared helpers (séquentiel, base commune)

- `definitions.py` : ajouter `build_payload(definition) -> dict` qui émet le nouveau schéma `[calibration]` enrichi
- `runtime.py:synthesize_truth_observations` : remplacer
  - `ModelCalibrationLauncher(truth_config)` → `Project(truth_config)`
  - `actualize_candidate(...)` → `materialize_candidate(...)`
  - `select_candidate_outputs(...)` → nouveau helper `extract_outputs(run, outputs_cfg)` basé sur `Run.timeseries` / `Run.field`
- `runtime.py:run_twin_benchmark_case` : utiliser `Project(calib_config).calibrate()` et assembler `TwinMethodBenchmarkResult` depuis `CalibrationReport`
- `plotting.py` et `run_benchmarks.py` : lire `catalog.calibration_iterations(session_id)` au lieu du `.jsonl`

Commit : `[validation] - port shared calibration runtime to project api`

#### 9.2 — porter UN cas et valider le golden

Cas pilote : `twin/steady/dupuit_fixed_head_1d/`

- Porter `experiment.py` + `run_case.py` sur la nouvelle API
- Run : `pytest tests/validation/calibration/test_twin_dupuit_fixed_head_modflow6.py -v`
- Golden diverge ? STOP. NE PAS MODIFIER LE GOLDEN. Enregistrer la séquence d'évaluations (params, seed, ask/tell) avant et après port, diff-er, diagnostiquer. Les causes probables :
  - seed propagé différemment dans le nouvel adapter
  - ordre d'injection des paramètres (`replace` vs `scale`)
  - initialisation LHS / grid différente
- Fix le bug, pas le golden.

Commit : `[validation] - port dupuit fixed head twin case`

#### 9.3 — porter les autres cas twin (parallélisable, 1 subagent par cas)

Une fois 9.2 vert, batcher des subagents Opus 4.7 pour porter en parallèle :

- `twin/steady/boussinesq_fixed_head_piecewise_k_1d/` → test `test_twin_boussinesq_fixed_head_piecewise_k_modflow6.py`
- `twin/transient/linearized_unconfined_recharge_step_1d/` → test `test_twin_linearized_recharge_step_flux_only_noisy_modflow6.py`
- test_twin_dupuit_fixed_head_noisy_modflow6.py
- test_twin_dupuit_fixed_head_mesh_perturbed_modflow6.py
- test_twin_dupuit_fixed_head_posterior_modflow6.py

Chaque subagent : même stratégie que 9.2 (goldens intouchables).

Commits (un par cas) :
- `[validation] - port boussinesq piecewise k twin case`
- `[validation] - port linearized recharge step twin case`
- `[validation] - port noisy dupuit twin case`
- `[validation] - port mesh perturbed dupuit twin case`
- `[validation] - port posterior dupuit twin case`

#### 9.4 — autres cas non-twin

Vérifier : `validation_cases/calibration/groundwater_1d/`, `recession_brutsaert/`, `reservoir/`. Ils passent probablement aussi par `shared/runtime.py` donc sont portés en 9.1. Sinon, mêmes étapes.

Tests à vérifier :
- `tests/validation/calibration/test_groundwater_1d.py`
- `tests/validation/calibration/test_recession_brutsaert.py`
- `tests/validation/calibration/test_reservoir.py`

Commits si fichiers modifiés :
- `[validation] - port groundwater 1d case`
- `[validation] - port recession brutsaert case`
- `[validation] - port reservoir case`

---

### Phase 10 — suppression `benchmark.py`

Pré-requis :

```bash
grep -rn "from hydromodpy.calibration.benchmark" .    # 0 lignes
grep -rn "import hydromodpy.calibration.benchmark" .  # 0 lignes
pytest tests/validation/calibration/ -v               # vert
hmp test unit                                         # vert
hmp test regression --fast                            # vert
```

Actions :

1. `rm hydromodpy/calibration/benchmark.py`
2. Éditer `LEGACY_REMAINING.md` : supprimer la section 1 et renuméroter
3. Déplacer `BENCHMARK_PY_ANALYSIS.md` dans `docs/archive/` (ou `rm` si l'utilisateur le valide — par défaut archive pour trace)
4. Vérifier `hydromodpy/calibration/__init__.py` exporte :
   - `CalibrationReport`
   - `materialize_candidate`
   - `CalibOutputDecl`, `CalibObjectiveBlockDecl`
   - `build_objective_from_config`

Commits :
- `[cleanup] - remove benchmark legacy module`
- `[docs] - archive benchmark analysis and legacy entry`

---

## Vérification finale (à runner avant de t'arrêter)

```bash
grep -rn "benchmark" hydromodpy/calibration/
grep -rn "from hydromodpy.calibration.benchmark" .
grep -rn "ModelCalibrationLauncher\|ModelCalibrationObjectiveEvaluator\|actualize_candidate\|select_candidate_outputs" .
hmp test unit
hmp test regression --fast
pytest tests/validation/calibration/ -v
hmp config /tmp/calib_test.toml --profile user
```

Tous les greps doivent être vides (ou uniquement dans docs/archive/).
Tous les tests doivent passer.
`hmp config` doit produire un TOML avec les nouveaux champs.

---

## Ce que tu ne fais JAMAIS

- `git push`
- `git commit --amend`
- `git commit --no-verify`
- `git reset --hard`
- Modifier un golden scientifique sans diagnostic
- Ajouter `Co-Authored-By` à un commit
- Ajouter un body / description à un commit
- Utiliser un tiret long (em-dash) dans un commit ou du code
- Mocker la DB dans un test d'intégration
- Créer des shims legacy pour du code interne
- Toucher `CatchmentDelineation`, `DataStore.workspace_root` ou les docstrings "Ported from legacy X" (hors périmètre, cf LEGACY_REMAINING.md)

## Tu peux, en revanche

- Lancer autant de subagents Opus 4.7 que nécessaire
- Batcher plusieurs `Agent` calls dans un seul message
- Utiliser `TaskCreate` pour suivre les 10 phases
- Interrompre une phase et demander confirmation à l'utilisateur si un golden diverge et que tu ne comprends pas pourquoi après 2 tentatives de diagnostic

Bonne intégration.
