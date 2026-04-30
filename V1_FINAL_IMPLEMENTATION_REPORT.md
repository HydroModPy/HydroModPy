# Rapport final v1

Date: 2026-05-01

Sources exploitees:

- `v1_final_audit_output/20260430_202122/FINAL_SYNTHESIS.md`
- `v1_final_audit_claude_output/20260430_202517/FINAL_SYNTHESIS.md`
- rapports references sous `v1_final_audit_output/20260430_202122/reports/`
- rapports references sous `v1_final_audit_claude_output/20260430_202517/reports/`

## Ce qui a ete corrige

### Contrats publics et documentation

- La facade publique expose maintenant `run`, `calibrate`, `overview` et `batch` par le meme chemin CLI/runtime.
- Les alias publics `Catalog`, `DataCatalog` et `Run.id` ont ete retires des surfaces canoniques.
- Les commandes `show` et `inspect` utilisent `Run.sim_id`.
- Les quickstarts README, CLI et ReadTheDocs ont ete alignes sur les commandes v1 et les chemins actuels.
- Les sections TOML legacy `[initializing]`, `[modflow]`, `[capability_gallery]` et `[batch]` sont rejetees explicitement.
- Les sections top-level inconnues sont rejetees par `HydroModPyConfig.from_toml`.
- Le placeholder DEM `__DEM_API_BOOTSTRAP__` a ete supprime. Un DEM declare via `[[data.dem.sources]]` autorise temporairement `geographic.dem_init_path = None` pendant le chargement TOML, puis le resolver remplit le chemin avant le runtime geographique.

### Storage, provenance et atomicite

- Le schema DuckDB accepte le statut `partial` et conserve `zarr_packed`.
- Le packaging Zarr est atomique: zip temporaire, validation, promotion par `os.replace`, puis suppression stricte du dossier source.
- La finalisation catalogue ne marque plus un run `completed` avant validation du packaging.
- La provenance conserve `source_type="data_manager"` et rejette les types inconnus.
- Une migration reconstruit les anciennes contraintes `provenance.source_type` qui ne connaissaient pas `data_manager`.
- Une table `_schema_version` enregistre la version du schema catalogue.
- La table `observations` est maintenant alimentee par l'ingestion observationnelle.
- `write_timeseries` accepte un `qflag`, avec `observed` pour les observations.
- Les exports Parquet gardent des metadata de schema et de version.

### Temps, CRS et exports

- Les extracteurs MODFLOW 6, MODFLOW-NWT et Boussinesq ecrivent un axe temps CF dans le Zarr.
- Les exports NetCDF lisent le temps depuis Zarr et corrigent les sous-selections `timesteps=[...]`.
- Les exports GeoTIFF et Shapefile exigent un CRS explicite au lieu d'un EPSG hardcode.
- Les exports GeoTIFF exigent une resolution explicite.
- Les exporters NetCDF, GeoTIFF, Shapefile et VTU savent lire un Zarr packe.
- Les handles Zarr ouverts par `Run`, `RunArrayProvider` et plusieurs extracteurs sont fermes explicitement.

### Post-run et failure modes

- `post_run_results` echoue fort si l'extracteur ou le dossier solver manque.
- Les phases `extract`, `derive`, aggregation catchment et auto-export ne masquent plus les erreurs critiques.
- Les extracteurs lumped, dont GR4J, ne lancent pas d'aggregation spatiale catchment.
- `keep_solver_files` respecte maintenant `results_config.keep_solver_files`.
- La preparation solver echoue si l'ecriture de provenance critique echoue.

### Calibration

- Les objectifs non finis produisent un `failed` explicite au lieu d'un `completed` avec NaN.
- Le cache de calibration stocke et restaure `sim_id`, `objective`, `status` et `components`.
- Les hits cache reutilisent l'objectif fini persiste au lieu de reconstruire un NaN.
- Les metriques unsupported ou sans observations echouent fort.
- Les extracteurs Boussinesq et GR4J ne retournent plus de serie vide silencieuse.
- Les bornes, transforms et priors des parametres sont valides plus strictement.
- La liste des optimiseurs disponibles vient du registry. `grid` devient le defaut core sans dependance optionnelle.
- `optuna`, `cma` et `whitebox-workflows` passent dans des extras optionnels.

### Architecture et validation

- Le coupling `results -> solver` pour determiner `solver_category` a ete retire.
- Les chemins `sys.path.append` de production identifies ont ete retires.
- Le layer matrix et son test ont ete durcis sur les nouveaux contrats.
- `describe_grid()` preserve les espacements `delr` et `delc` non uniformes.
- Les validation loaders n'utilisent plus de fallback `.npy` quand un store et un `sim_id` sont fournis. Le mode `.npy` reste possible seulement sans contexte store.

## Tests lances

Commandes lancees dans l'environnement `hmp_refact`:

```bash
mamba run -n hmp_refact ruff check --fix .
mamba run -n hmp_refact ruff format .
mamba run -n hmp_refact pytest -n auto tests/unit/test_pipeline_state_types.py tests/unit/calibration/test_cli_composite_routing.py tests/unit/test_trial_primitive.py tests/integration/test_results_post_run.py tests/unit/simulation/test_results_exporters.py tests/unit/test_storage_catalog.py tests/unit/test_api_public.py tests/integration/test_public_api_workflow.py tests/unit/test_calibration_cache.py tests/unit/calibration/test_engine.py tests/unit/calibration/test_metrics_extractors.py tests/unit/solver/modflow_nwt/test_modflow_config.py tests/unit/solver/test_modflow_grid_mapping.py tests/unit/calibration/test_cli_dispatch.py tests/unit/calibration/test_schemas.py tests/unit/calibration/test_build_objective_from_config.py tests/unit/config/test_toml_loader.py tests/unit/simulation/test_observation_ingest.py tests/unit/geographic/test_geographic_config.py tests/unit/architecture/test_layer_matrix.py
```

Resultat:

- Ruff check: OK
- Ruff format: OK
- Tests cibles parallelises avec 16 workers: `264 passed in 9.00s`

## Ressources mobilisees

- Plusieurs subagents de lecture ont ete utilises pour repartir l'audit et verifier les contradictions.
- Maxwell a effectue la relecture finale du diff courant et a remonte trois blocages critiques, tous corriges dans ce passage.
- Les tests ont ete lances avec `pytest -n auto` pour exploiter le parallelisme disponible.

## Ce qui reste a faire

Ces sujets restent hors de ce commit car ils changent des contrats larges, necessitent des solveurs reels, ou demandent une decision de release:

- Remplacer la reprise par checkpoint de contexte vivant par un `ResolvedRunManifest` immuable, puis tester `--resume` sur un vrai run solver.
- Construire un lockfile input complet avec SHA-256 pour tous les artefacts, et faire appliquer le mode `--frozen` aux loaders.
- Ajouter des foreign keys ou une strategie transactionnelle documentee pour les relations DuckDB qui restent sans contrainte moteur.
- Finaliser la gouvernance des observations: table `observations`, series `_obs`, stations et qualite doivent avoir un contrat utilisateur unique.
- Remplacer les anciens fixtures TOML qui declarent encore `[postprocess]` par les sections v1 equivalentes.
- Faire passer les validation cases completes par l'API publique et le catalogue, sans acces prive ni artefact `.npy` implicite.
- Couvrir les cas scientifiques lourds: Theis via API publique, MMS Boussinesq assemblee, drainage Boussinesq vs DRN MODFLOW, transport MT3DMS grand volume.
- Clarifier l'usage operationnel de `prior` dans les optimiseurs: il est valide, mais pas encore consomme uniformement par tous les samplers.
- Materialiser et recharger les overlays de calibration sur tous les chemins Python, TOML et objet Pydantic avec tests E2E.
- Rendre le registry delineation pleinement extensible et sortir les placeholders backend restants.
- Declarer ou archiver les gros outils non testes sous `tools/investigate_*.py`.
- Executer la suite complete CI, les tests integration avec binaires MODFLOW, et les validation cases avant tag v1.
