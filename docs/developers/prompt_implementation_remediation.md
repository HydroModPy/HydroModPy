# Prompt : Implementation du plan de remediation Simulation Catalog

## Contexte

Tu travailles sur HydroModPy, un toolbox Python pour la modelisation
hydrologique. Le Simulation Catalog (DuckDB + Zarr) a un schema complet
(12 tables) mais le pipeline d'execution ne remplit que 4 tables sur 12.
Un audit a identifie les corrections necessaires.

## Documents de reference

- Plan de remediation complet : `docs/developers/remediation_plan_catalog.md`
- Architecture cible du schema : `docs/developers/simulation_catalog_architecture.md`
- Instructions projet : `CLAUDE.md` (racine du repo)

Lis ces trois documents avant de commencer.

## Base DuckDB existante (examples/)

La base `examples/hydromodpy.duckdb` contient 3 simulations du projet
`04_nancon`. Les Zarr associes sont dans `examples/simulations/`.
Utilise-les pour tester tes modifications.

## Fichiers a modifier — coordonnees exactes

### Catalog schema et API

| Fichier | Element | Ligne |
|---|---|---|
| `hydromodpy/results/catalog_schema.py` | `PER_SIM_TABLE_NAMES` (ajouter geographic_*) | 226 |
| `hydromodpy/results/catalog.py` | `register_simulation()` | 61 |
| `hydromodpy/results/catalog.py` | `write_budget()` (ajouter `write_budgets()` batch) | 192 |
| `hydromodpy/results/catalog.py` | `write_mass_balance()` (ajouter `write_mass_balances()` batch) | 211 |
| `hydromodpy/results/catalog.py` | `import_simulation()` (wrapper transaction) | 756 |
| `hydromodpy/results/catalog.py` | `delete()` (wrapper transaction) | 835 |

### Pipeline d'ingestion (call sites de register_simulation)

| Fichier | Element | Ligne |
|---|---|---|
| `hydromodpy/workflow/steps/store_lifecycle.py` | `step_open_store()` — appel `register_simulation()` | 38 |
| `hydromodpy/workflow/steps/store_lifecycle.py` | `step_finalize_store()` — appel `finalize()` | 70 |
| `hydromodpy/project.py` | appel `register_simulation()` | 415 |
| `hydromodpy/project.py` | appel `finalize()` | 465 |

### Extracteurs (adapter aux batch writes)

| Fichier | Element | Ligne |
|---|---|---|
| `hydromodpy/simulation/results/extractors/modflownwt.py` | boucle `write_budget()` | 132 |
| `hydromodpy/simulation/results/extractors/modflow6.py` | boucle `write_budget()` | 129 |
| `hydromodpy/simulation/results/extractors/catchment_aggregation.py` | `write_timeseries()` (ajouter unites) | 71, 222 |
| `hydromodpy/simulation/results/extractors/derived.py` | `compute_derived()` | 44 |

### Post-run et ingestion

| Fichier | Element | Ligne |
|---|---|---|
| `hydromodpy/simulation/results/post_run.py` | `post_run_results()` | 53 |
| `hydromodpy/workflow/steps/result_ingestion.py` | step d'ingestion (ajouter provenance) | 15 |

### Objets du contexte runtime (lecture seule, ne pas modifier)

| Fichier | Element | Ligne |
|---|---|---|
| `hydromodpy/core/state/run_state.py` | `WorkflowContext` (ctx) | 35 |
| `hydromodpy/core/state/setup.py` | `SetupContext` (ctx.setup) | 26 |
| `hydromodpy/process/flow/flow.py` | `Flow.parameters` (dict de FieldParam) | 136 |
| `hydromodpy/core/config/hydromodpy_config.py` | `HydroModPyConfig` (ctx.cfg) | 62 |

### Zarr et geographic

| Fichier | Element | Ligne |
|---|---|---|
| `hydromodpy/results/zarr_store.py` | `SimulationZarr.write_mesh()` | 58 |
| `hydromodpy/spatial/geographic/store_ingestion.py` | `persist_geographic_to_store()` | 40 |

### Simulation API (rerun)

| Fichier | Element | Ligne |
|---|---|---|
| `hydromodpy/results/simulation.py` | classe `Simulation` (ajouter `rerun()`) | 20 |
| `hydromodpy/results/simulation_group.py` | classe `SimulationGroup` | 14 |

## Phases d'implementation

Implementer dans cet ordre. Chaque phase est un ensemble coherent
testable independamment.

### Phase 1 — Corrections critiques (pas de changement d'API)

1. `catalog_schema.py:226` : ajouter `"geographic_features"` et
   `"geographic_metadata"` a `PER_SIM_TABLE_NAMES`
2. `catalog.py:835` : wrapper `delete()` dans `BEGIN/COMMIT/ROLLBACK`
3. `catalog.py:756` : wrapper `import_simulation()` dans une transaction
4. `store_lifecycle.py:57` et `project.py:465` : appeler
   `finalize(status='failed')` dans un `except` autour de l'execution

### Phase 2 — Pipeline d'ingestion complet

1. Enrichir les deux appels `register_simulation()` :
   - `store_lifecycle.py:38` : passer `flow_regime`, `n_cells`,
     `n_layers`, `n_timesteps`, `bbox`, `crs`, `period_start`,
     `period_end`, `time_unit`, `config` (via `ctx.cfg.model_dump(mode="json")`),
     `mesh_type`, `mesh_hash`
   - `project.py:415` : meme enrichissement
   - Source des valeurs : `ctx.setup.domain.mesh`, `ctx.setup.geographic`,
     `ctx.cfg.flow.flow_regime`, `ctx.setup.time_grid`
2. Ecrire les parametres hydrauliques apres registration :
   - Source : `ctx.setup.flow.parameters` (dict de `FieldParam`)
   - Chaque FieldParam a `.identifier`, `.value`, `.unit`, `.kind`,
     `.values_by_key`
   - Appeler `store.write_parameters(sim_id, params_list)`
3. Appeler `store.write_mesh()` avec vertices et connectivity depuis
   `ctx.setup.domain.mesh`
4. Ajouter les unites dans `catchment_aggregation.py`

### Phase 3 — Batch writes

1. Ajouter `write_budgets(sim_id, records: list[dict])` dans `catalog.py`
   (pattern identique a `write_timeseries()` : DataFrame → INSERT SELECT)
2. Ajouter `write_mass_balances(sim_id, records: list[dict])` pareil
3. Adapter `modflownwt.py:132` et `modflow6.py:129` : accumuler les
   records dans une liste puis appeler la methode batch

### Phase 4 — Provenance et nettoyage Zarr

1. Ajouter un step `write_provenance()` dans le workflow apres le
   data loading
2. Dans `store_ingestion.py:40`, filtrer les rasters ecrits dans le
   Zarr : ne garder que `dem`, `geology`, `fill` (pas les intermediaires
   `buff_direc`, `buff_dem`, etc.)
3. Logger en WARNING (pas DEBUG) quand `_extract_mass_balance()` echoue

### Phase 5 — rerun()

1. Ajouter `HydroModPyConfig.from_snapshot(snapshot, **overrides)` dans
   `core/config/hydromodpy_config.py`
2. Ajouter `Simulation.rerun(**overrides)` dans `simulation.py`
3. Passer `parent_sim_id` dans les call sites de `register_simulation()`
   quand le workflow est declenche par `rerun()`

## Regles

- Repondre en francais
- Pas de commit git, l'utilisateur gere son historique
- Pas de bandeaux decoratifs (===, ---), commentaires simples en anglais technique
- Lancer les tests avec `pytest -n auto`
- Lire chaque fichier avant de le modifier
- Ne pas modifier les fichiers marques "lecture seule" dans le tableau
- Verifier que les tests existants passent apres chaque phase :
  `pytest tests/unit/ -n auto -v`
