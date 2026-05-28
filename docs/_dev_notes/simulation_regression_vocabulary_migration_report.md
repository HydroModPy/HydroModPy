# Simulation regression vocabulary migration report

Date: 2026-05-27

## Objectif

Demarrer la suppression de l'heritage `launcher_simulation` en remplacant le
vocabulaire actif des regressions par `simulation_regression`.

MT3DMS et MODPATH sont volontairement hors perimetre de ce lot.

## Changements appliques

- Renommage des fixtures:
  `tests/regression/fixtures/projects/launcher_simulation/` ->
  `tests/regression/fixtures/projects/simulation_regression/`.
- Renommage du helper:
  `tests/regression/launcher_simulation_helpers.py` ->
  `tests/regression/simulation_regression_helpers.py`.
- Renommage des tests fast/extensive et des goldens associes vers le prefixe
  `simulation_regression_*`.
- Renommage des assets suivis de capability gallery:
  `examples/projects/09_capability_gallery/launcher_simulation/` ->
  `examples/projects/09_capability_gallery/simulation_regression/`.
- Mise a jour des references actives dans les tests, docs source, specs de
  generation de gallery, `.gitignore` et valeur par defaut
  `CapabilityGalleryConfig.case_slug`.
- Correction de la decouverte CLI des regressions: le parser prend maintenant
  le suffixe final `_regression`, ce qui permet aux noms contenant
  `simulation_regression` de rester adressables par `hmp test regression`.
- Ajout d'un test unitaire qui verrouille ce cas.

## Validation

Commandes executees:

```powershell
python -m ruff check hydromodpy/cli/commands/test.py hydromodpy/analysis/capability_gallery.py tests/unit/test_hmp_regression_cli.py tests/regression/simulation_regression_helpers.py tests/regression/fast/test_simulation_regression_fast_boussinesq_regression.py tests/regression/fast/test_simulation_regression_fast_boussinesq_divide_regression.py tests/regression/fast/test_simulation_regression_fast_mf6_regression.py tests/regression/fast/test_simulation_regression_fast_nwt_regression.py tests/regression/extensive/test_simulation_regression_extensive_mf6_regression.py tests/regression/extensive/test_simulation_regression_extensive_nwt_regression.py tests/e2e/test_workflow_from_scratch.py tests/integration/test_export_import_roundtrip.py tests/unit/config/test_toml_loader.py tests/unit/regression/test_golden_utils.py tests/validation/numerical/steady/test_boussinesq_headwater_100km2_petsc.py tools/doc_gallery/gallery_simulation_specs.py tools/investigate_surface_interaction_hillslope.py tools/investigate_surface_interaction_hillslope_transient.py
python -m hydromodpy test regression --list --fast
python -m pytest -q tests/unit/test_hmp_regression_cli.py::test_regression_discovery_keeps_embedded_regression_vocab tests/unit/config/test_toml_loader.py::test_simulation_regression_example_config_inheritance_keeps_only_relevant_data_types tests/unit/config/test_toml_loader.py::test_simulation_regression_mf6_precomputed_mesh_input_config_uses_runtime_mesh tests/unit/config/test_toml_loader.py::test_simulation_regression_mf6_mesh_catchment_config_embeds_mesh_generation tests/unit/regression/test_golden_utils.py -o addopts=""
git grep -n -I "launcher_simulation" -- . ':!docs/_dev_notes/**' ':!docs/source/_static/**' ':!docs/_internal/legacy_notebooks/**'
```

Resultats:

- Ruff: aucun probleme sur le perimetre touche.
- CLI: `simulation_regression_fast_boussinesq_divide`,
  `simulation_regression_fast_boussinesq`, `simulation_regression_fast_mf6` et
  `simulation_regression_fast_nwt` sont bien listes.
- Pytest cible: `12 passed`.
- Grep actif hors notes historiques, artefacts `_static` generes et notebooks
  legacy: aucune occurrence restante de `launcher_simulation`.

## Restes hors lot

- `docs/source/_static/capability_gallery/**` contient encore des chemins
  `launcher_simulation`, des chemins absolus locaux et des references
  `_postprocess/*.npy`. Ce sont des artefacts generes: il faut les regenerer ou
  filtrer les chemins source dans le generateur.
- Les notes historiques `_dev_notes` conservent volontairement les anciennes
  occurrences pour tracer les migrations.
- Les helpers validation `.npy` legacy restent a traiter dans un lot separe
  catalog-only.

## Etape suivante proposee

Traiter la regeneration/filtration documentaire avant d'ajouter le garde
anti-retour global:

1. Regenerer les summaries de capability gallery depuis les manifests sous
   `examples/projects/09_capability_gallery/simulation_regression/`.
2. Filtrer les chemins absolus et les chemins `_postprocess/*.npy` des CSV/JSON
   publies si ces donnees ne doivent pas faire partie du contrat public.
3. Ajouter ensuite un test d'architecture `no_legacy_surface` qui interdit
   `launcher_simulation` hors `_dev_notes`, `_static` regenere et notebooks
   explicitement archives.

## Lot 2 - artefacts gallery et validation

Date: 2026-05-28

Objectif: finir la suppression de `launcher_simulation` dans les artefacts
documentaires suivis, sans traiter les chemins historiques MT3DMS/MODPATH.

Changements:

- regeneration ciblee des deux pages de simulation declarees dans
  `tools/doc_gallery/gallery_simulation_specs.py`;
- synchronisation textuelle des summaries simulation conserves, notamment
  `nancon_transient_nwt_summary.json`;
- synchronisation des snapshots `simulation_comparison` publies sous
  `docs/source/_static/capability_gallery/simulation_comparison/`;
- synchronisation des summaries de validation generes sous
  `docs/source/_static/capability_gallery/validation/`, ou le champ
  `metadata.case_metadata.launcher` vaut maintenant `simulation_regression`;
- ajout d'une normalisation dans
  `tools/doc_gallery/import_simulation_comparison.py` pour eviter qu'un futur
  import de bundle de comparaison ne repousse l'ancien vocabulaire dans les
  JSON/TOML publies;
- ajout d'une assertion unitaire sur l'importeur pour couvrir cette
  normalisation;
- documentation du comportement dans `tools/doc_gallery/README.md`.

Validation:

```powershell
python -m ruff check tools/doc_gallery/import_simulation_comparison.py tests/unit/tools/test_doc_gallery_extensions.py
python -m tools.doc_gallery --check --only modflow6_gmsh_mesh_catchment --only headwater_100km2_outlet_2_mf6_transient_reference
git grep -n -I "launcher_simulation" -- . ':!docs/_dev_notes/**' ':!docs/_internal/legacy_notebooks/**'
```

Resultats:

- `ruff`: OK;
- check cible capability gallery: OK;
- grep strict hors notes `_dev_notes` et notebooks legacy: aucune occurrence
  restante de `launcher_simulation`.

Commandes non conclusives:

- `python -m tools.doc_gallery --category simulation_comparison` a depasse le
  timeout local de 5 minutes; les artefacts de comparaison touches ici ont donc
  ete synchronises comme snapshots texte suivis, pas regeneres depuis les runs;
- un pytest cible sur l'importeur n'a pas rendu la main dans l'environnement
  local, alors que `ruff` et le check gallery ciblent correctement le code
  modifie. Un processus `python -m pytest` existait encore en arriere-plan et
  n'a pas ete arrete pour ne pas interrompre un travail utilisateur possible.

Residuel:

- les CSV de `simulation_comparison` contiennent encore des chemins
  `_postprocess/*.npy`, maintenant sous `simulation_regression`. Ce n'est plus
  un residu de vocabulaire legacy, mais une decision de contrat documentaire:
  soit on assume que ces colonnes sont des traces de provenance internes, soit
  on publie une version compacte/filtrée des observables.

Etape suivante proposee:

1. Modifier l'export/import `simulation_comparison` pour publier un
   `observables.csv` compact sans chemins de workspace ni chemins
   `_postprocess/*.npy`.
2. Regenerer les bundles de comparaison depuis cette regle compacte quand les
   sources de resultats sont disponibles.
3. Ajouter ensuite un garde `no_legacy_surface` qui interdit
   `launcher_simulation` hors `_dev_notes` et notebooks archives.

## Lot 3 - contrat public compact pour observables

Date: 2026-05-28

Objectif: retirer les chemins internes `_postprocess/*.npy` des artefacts
publics `simulation_comparison`, tout en conservant les chemins complets dans
le CSV runtime local utilise par les workflows de comparaison.

Changements:

- ajout de `write_public_observables_csv()` dans
  `hydromodpy.analysis.comparison.runtime.observables`;
- conservation de `write_observables_csv()` comme export runtime complet avec
  `source_path` et `run_folder`;
- branchement de `tools.doc_gallery.update_gallery` sur le writer public pour
  les artefacts `docs/source/_static/capability_gallery/simulation_comparison/*_observables.csv`;
- retrait des colonnes `source_path` et `run_folder` des six CSV
  `*_observables.csv` deja suivis dans la galerie;
- ajout d'une assertion dans le smoke test de generation
  `simulation_comparison` pour garantir que les CSV publics ne republient pas
  ces colonnes;
- ajout du garde `tests/unit/test_no_legacy_surface.py`, qui interdit le retour
  de `launcher_simulation` hors `_dev_notes` et notebooks archives;
- documentation du contrat public compact dans `tools/doc_gallery/README.md`.

Validation:

```powershell
python -m ruff check hydromodpy/analysis/comparison/runtime/observables.py hydromodpy/analysis/comparison/runtime/__init__.py tools/doc_gallery/update_gallery.py tools/doc_gallery/import_simulation_comparison.py tests/unit/tools/test_doc_gallery_extensions.py tests/unit/test_no_legacy_surface.py
python -m pytest -q tests/unit/test_no_legacy_surface.py -o addopts=""
python -m pytest -q tests/unit/tools/test_doc_gallery_extensions.py::test_generate_simulation_comparison_case_smoke -o addopts=""
python -m tools.doc_gallery --check --only modflow6_gmsh_mesh_catchment --only headwater_100km2_outlet_2_mf6_transient_reference
git grep -n -I "_postprocess" -- docs/source/_static/capability_gallery/simulation_comparison docs/source/_static/capability_gallery/simulation
git grep -n -I "launcher_simulation" -- . ':!docs/_dev_notes/**' ':!docs/_internal/legacy_notebooks/**'
```

Resultats:

- `ruff`: OK;
- garde anti-retour: `1 passed`;
- smoke test generation `simulation_comparison`: `1 passed`;
- check cible capability gallery simulation: OK;
- aucun `_postprocess` restant dans les artefacts publics
  `simulation`/`simulation_comparison`;
- aucune occurrence active restante de `launcher_simulation` hors notes et
  notebooks archives.

Etape suivante proposee:

1. Elargir la regeneration/check de `simulation_comparison` quand les bundles
   sources sont disponibles, pour remplacer la synchronisation de snapshots par
   une regeneration complete.
2. Traiter le dernier sujet explicitement laisse hors lot: decider le statut
   des chemins historiques MT3DMS/MODPATH, ou confirmer qu'ils restent hors
   migration V1.
3. Nettoyer les notes `_dev_notes` seulement si l'objectif devient un grep
   strict sur tout le depot, historique compris.

## Lot 4 - regeneration ciblee simulation_comparison

Date: 2026-05-28

Objectif: remplacer la synchronisation manuelle des snapshots
`simulation_comparison` par une regeneration ciblee via le generateur de
gallery, quand les artefacts sources suivis sont disponibles. Les chemins et
decisions historiques MT3DMS/MODPATH restent hors perimetre et n'ont pas ete
modifies.

Changements:

- execution de `python -m tools.doc_gallery` sur les 8 pages
  `simulation_comparison` actuellement declarees;
- regeneration des summaries `simulation_comparison` devenus obsoletes apres
  compactage des CSV publics;
- conservation du contrat public compact: les `*_observables.csv` regeneres
  n'exposent pas `source_path`, `run_folder` ni de chemins `_postprocess`;
- aucun changement applique au code ou aux documents MT3DMS/MODPATH.

Validation:

```powershell
python -m tools.doc_gallery --check --only example12_map_simulation_comparison --only ex12_mf6_nwt_moderate_same_s60 --only ex12_mf6_nwt_moderate --only example12_mf6_vs_nwt_different_meshes_demonstrative --only ex12_multi_simulation_moderate --only ex12_multi_simulation_moderate_causes --only site_03_natural_n1_10km2_mf6_bouss --only site_08_natural_n1_10km2_mf6_bouss
python -m ruff check hydromodpy/analysis/comparison/runtime/observables.py hydromodpy/analysis/comparison/runtime/__init__.py tools/doc_gallery/update_gallery.py tools/doc_gallery/import_simulation_comparison.py tests/unit/tools/test_doc_gallery_extensions.py tests/unit/test_no_legacy_surface.py
python -m pytest -q tests/unit/test_no_legacy_surface.py -o addopts=""
git grep -n -I "_postprocess" -- docs/source/_static/capability_gallery/simulation_comparison docs/source/_static/capability_gallery/simulation
git grep -n -I "launcher_simulation" -- . ':!docs/_dev_notes/**' ':!docs/_internal/legacy_notebooks/**'
rg -n "modpath|mt3dms|MT3DMS|MODPATH" tools/doc_gallery hydromodpy/analysis/comparison docs/source/_static/capability_gallery/simulation_comparison tests/unit/tools/test_doc_gallery_extensions.py docs/source/capability_gallery/cases docs/_dev_notes/simulation_regression_vocabulary_migration_report.md
```

Resultats:

- check cible `simulation_comparison`: OK apres regeneration;
- `ruff`: OK;
- garde anti-retour: `1 passed`;
- aucun `_postprocess` restant dans les artefacts publics
  `simulation`/`simulation_comparison`;
- aucune occurrence active restante de `launcher_simulation` hors notes et
  notebooks archives;
- le scan MT3DMS/MODPATH ne retourne que les mentions de hors-perimetre dans ce
  rapport.

Etape suivante proposee:

1. Stabiliser ce lot en commit separe, car il combine des renommages de surface,
   des artefacts docs volumineux et un garde anti-retour.
2. Lancer ensuite une passe specifique sur les notes `_dev_notes` si un grep
   strict historique est souhaite.
3. Ouvrir un ticket distinct pour MT3DMS/MODPATH seulement si la decision de
   perimetre change; pour l'instant ils restent explicitement exclus.

## Lot 5 - manifests publics sans chemins de workspace

Date: 2026-05-28

Objectif: terminer le nettoyage des artefacts locaux publies par
`simulation_comparison`. Les CSV publics etaient deja compacts, mais les
`*_comparison_manifest.json` conservaient encore des chemins de workspace,
notamment `run_folder`, `config_path`, les chemins de figures, les configs
generees et certains extraits stdout/stderr. MT3DMS/MODPATH restent hors
perimetre et n'ont pas ete modifies.

Changements:

- ajout de `tools.doc_gallery.public_artifacts` pour centraliser la
  normalisation publique des artefacts de galerie;
- filtrage des manifests lors de l'import de bundles
  `tools/doc_gallery/import_simulation_comparison.py`;
- filtrage des manifests lors de la generation directe
  `simulation_comparison_case`;
- filtrage aussi dans le chemin de preservation `copy_assets`/fallback, pour
  les pages publiees depuis bundles compacts quand les observables complets ne
  sont pas disponibles localement;
- regeneration ciblee des 8 pages `simulation_comparison`;
- extension du garde `tests/unit/test_no_legacy_surface.py` pour refuser les
  champs de chemins locaux dans les manifests publics suivis;
- documentation du contrat public dans `tools/doc_gallery/README.md`.

Validation:

```powershell
python -m tools.doc_gallery --only example12_map_simulation_comparison --only ex12_mf6_nwt_moderate_same_s60 --only ex12_mf6_nwt_moderate --only example12_mf6_vs_nwt_different_meshes_demonstrative --only ex12_multi_simulation_moderate --only ex12_multi_simulation_moderate_causes --only site_03_natural_n1_10km2_mf6_bouss --only site_08_natural_n1_10km2_mf6_bouss
python -m tools.doc_gallery --check --only example12_map_simulation_comparison --only ex12_mf6_nwt_moderate_same_s60 --only ex12_mf6_nwt_moderate --only example12_mf6_vs_nwt_different_meshes_demonstrative --only ex12_multi_simulation_moderate --only ex12_multi_simulation_moderate_causes --only site_03_natural_n1_10km2_mf6_bouss --only site_08_natural_n1_10km2_mf6_bouss
python -m pytest -q tests/unit/tools/test_doc_gallery_extensions.py::test_import_simulation_comparison_publishes_bundle tests/unit/tools/test_doc_gallery_extensions.py::test_generate_simulation_comparison_case_smoke tests/unit/test_no_legacy_surface.py -o addopts=""
python -m ruff check tools/doc_gallery/public_artifacts.py tools/doc_gallery/import_simulation_comparison.py tools/doc_gallery/update_gallery.py tests/unit/tools/test_doc_gallery_extensions.py tests/unit/test_no_legacy_surface.py
git grep -n -I "launcher_simulation" -- . ':!docs/_dev_notes/**' ':!docs/_internal/legacy_notebooks/**'
git grep -n -I "_postprocess" -- docs/source/_static/capability_gallery/simulation_comparison docs/source/_static/capability_gallery/simulation
rg -n "run_folder|config_path|comparison_root|C:\\\\|_postprocess|examples/projects/10_testbed_workflow/outputs|generated_config_paths|stdout_tail|stderr_tail|manifest_path" docs/source/_static/capability_gallery/simulation_comparison -g "*_comparison_manifest.json"
```

Resultats:

- regeneration ciblee: OK;
- check cible `simulation_comparison`: OK;
- tests cibles: `4 passed`;
- `ruff`: OK;
- aucune occurrence active de `launcher_simulation` hors notes et notebooks
  archives;
- aucun `_postprocess` dans les artefacts publics `simulation` et
  `simulation_comparison`;
- aucun champ/chemin de workspace detecte dans les manifests publics
  `simulation_comparison` suivis.

Etape suivante proposee:

1. Stabiliser ce lot en commit separe avec les fichiers code/tests/docs et les
   artefacts generes associes.
2. Lancer ensuite une passe separee de nettoyage des notes `_dev_notes` si un
   grep strict historique est souhaite.
3. Garder MT3DMS/MODPATH hors migration tant qu'un ticket distinct ne change
   pas explicitement le perimetre.
