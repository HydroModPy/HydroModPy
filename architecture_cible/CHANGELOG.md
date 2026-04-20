# Architecture cible — Changelog post-review

**Date** : 2026-04-20
**Contexte** : revue par l'utilisateur des 14 documents d'architecture. Les décisions ci-dessous sont appliquées comme **OVERRIDES** en tête de chaque fichier concerné (les blocs historiques restent visibles pour référence, mais les OVERRIDES prévalent).

---

## `01_structure_packages.md`
- **whitebox retiré de `core/`**. `core/backends/whitebox_backend.py` et `core/backends/whitebox_workflows_backend.py` migrés vers **`spatial/delineation/`**.
- Nouveau package `spatial/delineation/` multi-backend : `base.py` (Protocol `DelineationBackend`), `whitebox_cli_backend.py`, `whitebox_workflows_backend.py`, `pysheds_backend.py` (stub), `synthetic_backend.py` (BV auto-générés), `registry.py`.
- Tableau de migration mis à jour : dossier `core/backends/` **supprimé** de l'arbre cible, shim temporaire en P05, nettoyé en P13.

## `02_config_pydantic.md`
- **pydantic-pint adopté en P03** (section « Ce qu'on ne fait pas » nettoyée).
- Nouvelle section **§12 Unités via pydantic-pint** : `hydromodpy/core/units/` avec `registry.py` + `types.py`. Types annotés `HydraulicConductivity`, `SpecificYield`, `Length`, `FlowRate`, etc. Remplace `normalize_m_per_s_unit` et `units/conversions.py`.
- TOML accepte `k_aquifer = 1e-4` OU `k_aquifer = "0.0001 m/s"` (conversion auto via pint).
- Rejets conservés : Hydra/OmegaConf, runtime overrides CLI, multi-environnement, schéma SQL séparé.

## `03_data_contracts.md`
- Ajout d'une section OVERRIDES en tête : **formats utilisateur = CSV / SHP / GeoTIFF / ASC / GeoJSON / GPKG**.
- **Parquet / GeoParquet restent internes** (pivot), jamais exposés à l'utilisateur.
- Adapters d'ingestion créés en P04 : `csv_to_parquet.py`, `shp_to_geoparquet.py`, `asc_to_geotiff.py`.

## `04_storage_ideal.md`
- **Clean slate — pas de migration DB.** `_schema_version`, `MIGRATIONS[]`, `SchemaTooNewError` **retirés** du scope initial. Principes de migration pour évolutions **futures** documentés dans `docs/developers/schema_evolution.md` (post-P13).
- Principe #9 barré (ANNULÉ) dans le tableau directeur.
- **Nouveau cache geographic content-addressable** : `workspace/geographic/<fingerprint>/` (fingerprint = SHA-256 des inputs : DEM+géologie+bbox+résolution+CRS).
- `SimulationZarr` stocke uniquement `geographic_fingerprint` en attribut ; plus de duplication des rasters.
- Matérialisation au `.hmp` export (reste portable) ; dé-matérialisation à l'import.
- Gain calibration : 200 itérations même BV → 1 build geographic au lieu de 200 (~99 % d'économie disque sur les rasters).

## `07_calibration.md`
- **Optuna** devient l'adapter principal (NOUVEAU — actuellement uniquement scipy.optimize + simplex custom).
- **PEST++ via pyemu** retiré du scope initial. Reporté post-P13 comme adapter plugin optionnel si besoin concret identifié.
- **TOML `[calibration.parameters]` simplifié** : `{ bounds, transform }` suffisent, le `path`, `prior`, `distribution` sont dérivés automatiquement des annotations Pydantic `Calibrable()`.
- Nouveaux **modes `save_runs`** :
  - `"none"` (défaut) : metadata uniquement dans `calibration_iterations`, **aucun Zarr par itération**.
  - `"best_n"` : les N meilleures itérations promues en vraies simulations complètes après la boucle.
  - `"all"` : comportement lourd historique (1 Zarr par itération), opt-in.
- **Cache content-addressable** par `params_hash` (SHA-256 des paramètres résolus). Combiné au `geographic_fingerprint`, 200 itérations = 1 build geographic + 1 mesh + 200 runs solver seulement.

## `11_frontend_ready.md`
- **FastAPI, uvicorn, WebSockets retirés du scope.** Le projet reste pur Python, zéro dépendance web.
- Tout le document devient une **référence externe** pour développeurs tiers ; aucun serveur n'est créé dans HydroModPy.
- Livrables réels de **P11** :
  1. CLI `hmp schema export` → `config.json` + `config_meta.json` + `field_validators.json`.
  2. Annotations Pydantic riches (`widget_type`, `unit`, `display_name_fr`, `help_text_fr`).
  3. Partial field validator `validate_field(path, value, context)` < 50 ms.
  4. Documentation `docs/developers/frontend_hooks.md` + exemple `docs/examples/streamlit_app.py`.
- Consommateurs cibles : Streamlit local, Angular externe (repo séparé), React, etc.

## `12_input_data_rethink.md`
- **API SIM2 Météo-France préservée.** Pas de migration vers `meteo.data.gouv.fr/api/v1/edr/...`. Refacto cosmétique uniquement : déplacement de `hydromodpy/data/climatic/sim2_API.py` vers `hydromodpy/data/common/clients/sim2_meteofrance.py`, endpoint identique.
- **Drag-and-drop avant CLI** : flow principal = déposer dans `~/hydromodpy/{variable}_custom/`, auto-scan mtime-based au `hmp run`. `hmp data add` reste disponible mais secondaire (power-user).
- Formats utilisateur : CSV, SHP, GeoJSON, GeoTIFF, ASC. Parquet / GeoParquet restent internes.
- Ligne 201 du tableau des APIs mise à jour (endpoint SIM2 Météo-France via geosas.fr, pas rate-limited, pas de clé).

## `14_plan_migration.md`
- **Un seul script `run_migration.sh`** à la racine du repo orchestre les 13 phases. Remplace les `run_migration_Pxx.sh` individuels.
- Gestion automatique : rate limits Claude (6h max), reprise après crash (état persistant `migration/phases/*.done`), commits atomiques `[Pxx] - ...`, zéro push, garde-fous branche.
- **Phases retirées** : migration DB (clean slate), PEST++ adapter, FastAPI serveur.
- Ordre canonique P01–P13 documenté en OVERRIDES au-dessus du plan historique (conservé à titre de référence).

---

## Fichiers non modifiés

- `05_solver_contracts.md` : aucun override (pas de changement de décision par l'utilisateur).
- `06_pipeline_execution.md` : aucun override (le checkpointing proposé est retenu tel quel).
- `08_postprocess_display.md` : aucun override.
- `09_tests_ideaux.md` : aucun override.
- `10_ux_cli_api.md` : aucun override (les décisions CLI/API sont retenues telles quelles).
- `13_coherence_globale.md` : aucun override (la vérification de cohérence reste pertinente pour le nouveau design).

---

## Comment lire ces documents maintenant

1. **Toujours commencer par la section `OVERRIDES`** en tête de chaque fichier modifié — c'est la décision actuelle.
2. Le reste du document reste valide sauf indication contraire dans les OVERRIDES.
3. Les conflits explicites sont signalés avec des marqueurs `~~barré~~` ou `**ANNULÉ**`.
