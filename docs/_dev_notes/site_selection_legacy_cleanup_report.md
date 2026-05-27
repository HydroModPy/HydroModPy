# Site selection - rapport de suppression legacy

Date: 2026-05-27

## Perimetre

Ce lot traite uniquement la legacy `site_selection`, hors source DEM
`ign_bdalti`. Le but est de supprimer les anciens chemins de rapport, les
aliases de domaine sans logique propre et le doublon de sortie
`selection_decisions.jsonl`.

## Changements appliques

- Suppression finalisee de `reports/legacy_review.py` et retrait de l'export
  public `render_selection_report`.
- Suppression des aliases de domaine `domain/candidates.py` et
  `domain/catchments.py`; les imports canoniques sont respectivement
  `candidates.outlets.CandidateOutlet` et
  `hydrology.delineation.DelineatedCatchment`.
- Renommage de `decisions/adapters.py` en `decisions/records.py`.
  Le module de decisions ne parle plus de modele legacy: il construit des
  `DecisionRecord` normalises a partir du resultat de selection courant.
- Suppression de l'ecriture de `selection_decisions.jsonl`.
  La sortie canonique est maintenant `site_selection_decisions.jsonl`, completee
  par `site_selection_decisions.csv` pour la synthese par bassin.
- Mise a jour du manifest: `site_selection_decisions_jsonl` devient une sortie
  requise a la place de `selection_decisions_jsonl`.
- Mise a jour du rapport HTML: il lit les decisions normalisees et retrouve la
  decision finale via les enregistrements `criterion_id = "final_selection"`.
- Mise a jour des tests et de la documentation de contrat.

## Validation

Commandes executees:

```powershell
python -m pytest -q tests/unit/site_selection -m fast -o addopts=""
python -m pytest -q tests/unit/site_selection/test_exports.py tests/unit/site_selection/test_manifest_report.py tests/unit/site_selection/test_decision_records.py -m fast -o addopts=""
python -m ruff check hydromodpy/spatial/site_selection hydromodpy/schema/site_selection_manifest.py tests/unit/site_selection
```

Resultats:

- `142 passed` sur les tests rapides `site_selection`;
- `23 passed` sur les tests de contrat export/manifest/decision;
- `ruff`: aucun probleme.

## Etat apres lot 1

Le contrat `site_selection` n'expose plus:

- `reports/legacy_review.py`;
- `render_selection_report`;
- `decisions.adapters`;
- `selection_decisions.jsonl`;
- `selection_decisions_jsonl`.

Le coeur d'audit canonique est:

- `site_selection_manifest.json`;
- `criteria_components.jsonl`;
- `site_selection_decisions.jsonl`;
- `site_selection_decisions.csv`;
- `site_selection_evidence.jsonl` quand des preuves normalisees existent.

## Suite

Le lot 2 DEM a ete traite dans
`docs/_dev_notes/dem_ign_legacy_cleanup_report.md`.

## Lot 3 - aliases aval

Les aliases de configuration aval `site_selection_output` et
`site_selection_output_key` ont ete retires du resolver de catalogue
`hydromodpy.analysis.testbed.site_selection_catalog`. Le contrat conserve est:

- `from_site_selection_manifest` pour pointer vers le manifest;
- `output` pour choisir une cle explicite du manifest;
- `regional_lab_sites_csv` comme cle par defaut si `output` est absent.

Validation associee:

```powershell
python -m pytest tests/unit/analysis/test_site_selection_catalog.py -q
python -m pytest tests/unit/launchers/test_testbed_launcher.py tests/unit/launchers/test_regional_lab_launcher.py -q
python -m pytest tests/unit/launchers/test_site_selection_bridge_examples.py -q
python -m pytest tests/unit/site_selection -q
```

Resultats:

- `7 passed` pour le resolver de catalogue site-selection;
- `41 passed` pour les launchers testbed/regional-lab;
- `2 passed` pour les exemples de bridge site-selection;
- `142 passed` pour les tests unitaires `site_selection`.

Restent hors perimetre site-selection:

1. Verifier le chemin Geoplateforme en test reseau/CLI controle.
2. Decider le niveau de support RGE ALTI avant de declarer le chantier DEM
   completement clos.
3. Les compatibilites workflow declarees comme legacy (`workflow_dispatch`,
   hooks testbed et colonne historique de heartbeat) ont ete traitees dans
   `docs/_dev_notes/workflow_legacy_cleanup_report.md`.

## Lot 4 - contrat de configuration strict

Ce lot retire la compatibilite restante dans le contrat executable
`site_selection`:

- suppression de l'alias de mode de critere `report` vers `report_only`;
- retrait des profils de strategie non supportes `dem_only` et
  `multicriteria`;
- retrait des modes candidats non branches `dem_area_light` et
  `imported_points` dans `strategy.candidate_mode` / `outlets.candidate_mode`;
- retrait des modes de territoire non branches `site_catalog_extent` et
  `geoparquet_filter`;
- retrait de `same_mainstem_policy`;
- retrait des options de sortie non executees `write_candidates` et
  `write_report_md`;
- suppression du helper public `candidate_outlets_from_rows`, qui ne servait
  plus qu'un chemin d'import manuel non branche;
- obligation de declarer explicitement
  `profile = "gauged_downstream_station"` pour les runs
  `principle = "observation_led"`;
- suppression du mode implicite `site_selection.input.mode = "auto"`;
- obligation de declarer explicitement `profile = "area_only"` pour les runs
  `site_selection.input.mode = "dem_area_light"`; `effective_profile` ne deduit
  plus ce profil depuis le mode d'entree.

Les contrats et rapports courants ont ete alignes. Le plan long
`legacy/site_selection_tool_implementation_plan.md` est archive comme document
historique et peut encore citer les anciennes options, mais elles ne sont plus
supportees par les modeles Pydantic.

L'audit des duplications potentielles est documente dans
`docs/_dev_notes/site_selection_duplication_audit.md`.

Decision de perimetre 2026-05-27: `generated_candidates` est conserve comme
capacite experimentale testee. Il ne fait pas partie du contrat metier court
terme stabilise, mais il n'est pas supprime comme legacy morte.

Validation associee:

```powershell
python -m pytest tests/unit/site_selection -q
python -m ruff check hydromodpy/spatial/site_selection hydromodpy/workflow/site_selection.py hydromodpy/cli/commands/site_selection.py tests/unit/site_selection
```

Resultats:

- `151 passed` pour les tests unitaires `site_selection`;
- `ruff`: aucun probleme.

Validation exemples executee depuis le checkout local:

```powershell
python -m hydromodpy run examples/projects/17_site_selection_workflow/configs/calvados_dem_area_light_100km2_fast.toml
python -m hydromodpy run examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small_bdtopage.toml
```

Resultats:

- Calvados DEM-light: 26 candidats, 10 selectionnes, 16 rejetes;
- Bretagne hydrometrie BD Topage: 6 candidats, 6 selectionnes, 0 rejete.
