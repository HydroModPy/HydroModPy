# Testbed case vocabulary migration report

Date: 2026-05-27

## Objectif

Stabiliser `case` comme vocabulaire public canonique du testbed generique.

Motivation:

- le runtime materialise deja des `TestbedPlannedCase`;
- l'artefact principal s'appelle deja `testbed_cases.csv`;
- le profil `regional_lab` expose deja `case_id`;
- `variant` reste utile comme axe de sensibilite scientifique, mais il est
  ambigu comme unite executable.

## Lots appliques

### Lot 1 - retrait des alias parser non documentes

Les alias TOML suivants ne sont plus acceptes par le parser generique:

- `[[testbed.variants]]`;
- `[[testbed.catalog_variant]]`.

Les tests de rejet couvrent explicitement ces deux spellings pour eviter leur
retour silencieux.

### Lot 2 - introduction du contrat public `case`

Le parser accepte maintenant les spellings canoniques:

- `[[testbed.case]]`;
- `[[testbed.case_from_catalog]]`.

Les spellings historiques restent acceptes temporairement:

- `[[testbed.variant]]`;
- `[[testbed.variant_from_catalog]]`.

Un TOML qui melange la forme canonique `case` et la forme historique `variant`
dans la meme section est rejete. Cela evite une matrice ambigue dans laquelle
deux vocabulaires decrivent les memes executions.

### Lot 3 - sorties compatibles mais orientees `case`

Les artefacts generiques ecrivent maintenant les champs canoniques:

- `case_id`;
- `case_label`;
- `case_count`;
- `case_from_catalog`.

Les champs historiques restent presents pour compatibilite aval:

- `variant_id`;
- `variant_label`;
- `variant_count`;
- `variant_from_catalog`.

Les rapports testbed lisent prioritairement `case_*` puis retombent sur
`variant_*` pour les runs existants.

### Lot 4 - migration des exemples TOML et des tests inline

Les TOML publics des exemples testbed ont ete migres vers le vocabulaire
canonique:

- `examples/projects/10_testbed_workflow/**/*.toml`;
- `examples/projects/18_site_selection_to_testbed/**/*.toml`.

Les TOML inline de `tests/unit/launchers/test_testbed_launcher.py` utilisent
maintenant `[[testbed.case]]` et `[[testbed.case_from_catalog]]`, sauf les tests
dedies a la compatibilite legacy:

- acceptation temporaire de `[[testbed.variant]]`;
- acceptation temporaire de `[[testbed.variant_from_catalog]]`;
- rejet des alias retires `[[testbed.variants]]` et
  `[[testbed.catalog_variant]]`;
- rejet d'un TOML qui melange `case` et `variant`.

### Lot 5 - reference de configuration generee

Les champs Pydantic publics du `TestbedConfig` ont ete renommes:

- `variants` -> `case`;
- `catalog_variants` -> `case_from_catalog`.

Les proprietes Python de compatibilite restent disponibles:

- `cases`;
- `catalog_cases`;
- `variants`;
- `catalog_variants`.

Le validateur Pydantic accepte encore une construction Python directe avec les
anciens noms `variants` et `catalog_variants`, mais les normalise vers les
champs canoniques. La reference generee expose donc maintenant:

- `testbed.case`;
- `testbed.case_from_catalog`.

Le generateur `tools/doc_config` a aussi ete corrige pour afficher les
`tuple[BaseModel, ...]` comme des arrays of tables TOML `[[...]]`, au meme titre
que les `list[BaseModel]`. Cette correction touche aussi les tables
`analysis.batch.cluster_rules` et `analysis.batch.recipes`, qui etaient rendues
avec un seul crochet dans la reference.

### Lot 6 - politique de deprecation runtime

Les spellings historiques encore supportes emettent maintenant un
`DeprecationWarning` lorsqu'ils sont utilises comme entree:

- `[[testbed.variant]]` -> `[[testbed.case]]`;
- `[[testbed.variant_from_catalog]]` -> `[[testbed.case_from_catalog]]`;
- `TestbedConfig(variants=...)` -> `TestbedConfig(case=...)`;
- `TestbedConfig(catalog_variants=...)` ->
  `TestbedConfig(case_from_catalog=...)`.

Les alias de lecture Python (`cfg.variants`, `cfg.catalog_variants`) restent
silencieux pour ne pas casser les consommateurs existants. Les colonnes et cles
de sortie `variant_*` restent egalement silencieuses: ce sont des sorties de
compatibilite, pas le canal recommande pour les nouveaux consommateurs.

Politique retenue: conserver ces entrees legacy jusqu'a une prochaine phase de
compatibilite cassante explicitement annoncee dans une note de release ou un
changelog. Les nouveaux TOML, la reference de configuration et les nouveaux
consommateurs doivent utiliser `case`.

### Lot 7 - publication de la deprecation

La deprecation est maintenant visible dans les surfaces publiques:

- `CHANGELOG.md` ajoute une entree `Deprecated` dans `[Unreleased]`;
- `docs/source/user_guide/workflows/testbed.rst` utilise `case` dans les
  exemples et documente la compatibilite legacy `variant`;
- la page workflow renvoie les nouveaux TOML vers `[[testbed.case]]` et
  `[[testbed.case_from_catalog]]`.

Le jalon de suppression reste exprime comme une future release cassante, sans
numero de version fixe. C'est volontaire tant que la ligne de release cible
n'est pas decidee.

### Lot 8 - nettoyage interne borne

Les noms Pydantic publics sont maintenant canoniques:

- `TestbedCaseConfig`;
- `TestbedCatalogCaseConfig`.

Les anciens imports restent compatibles par alias:

- `TestbedVariantConfig = TestbedCaseConfig`;
- `TestbedCatalogVariantConfig = TestbedCatalogCaseConfig`.

La reference generee expose donc `tuple[TestbedCaseConfig, ...]` pour
`testbed.case` et `tuple[TestbedCatalogCaseConfig, ...]` pour
`testbed.case_from_catalog`.

Le chemin d'expansion catalogue a aussi recu un nom canonique:

- `expand_catalog_cases(...)`.

L'ancien `expand_catalog_variants(...)` reste un alias de compatibilite pour
les tests et consommateurs existants.

Enfin, les champs de catalogue par defaut sont maintenant `case_id` et
`case_label`. Une lecture fallback de `variant_id` / `variant_label` reste
presente lorsque les nouveaux champs par defaut ne sont pas trouves, afin de ne
pas casser les catalogues historiques sans `id_field` explicite.

## Fichiers principaux touches

- `CHANGELOG.md`
- `hydromodpy/analysis/testbed/catalog_variants.py`
- `hydromodpy/analysis/testbed/config.py`
- `hydromodpy/analysis/testbed/contracts.py`
- `hydromodpy/analysis/testbed/pipeline.py`
- `hydromodpy/analysis/testbed/regional_lab_adapter.py`
- `hydromodpy/analysis/testbed/runtime.py`
- `hydromodpy/analysis/testbed/README.md`
- `tools/doc_config/generate.py`
- `docs/source/architecture/simulation/testbed-workflow-architecture.rst`
- `docs/source/user_guide/workflows/testbed.rst`
- `docs/source/user_guide/config_reference/testbed.rst`
- `docs/source/user_guide/config_reference/config_index.rst`
- `docs/source/user_guide/config_reference/complete_toml.rst`
- `docs/source/_static/hmp-config-search.json`
- `docs/source/_static/hydromodpy-schema.json`
- `docs/source/_static/hydromodpy-openapi.json`
- `tests/unit/launchers/test_testbed_launcher.py`
- `examples/projects/10_testbed_workflow/**/*.toml`
- `examples/projects/18_site_selection_to_testbed/**/*.toml`
- `examples/projects/10_testbed_workflow/reporting/generate_testbed_web_report.py`
- `examples/projects/10_testbed_workflow/generate_nwt_flux_testbed_web_report.py`

## Validation

Commandes executees:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py
python -m pytest tests\unit\analysis\test_testbed_web_report.py
python -m pytest tests\unit\launchers\test_site_selection_bridge_examples.py tests\unit\launchers\test_boussinesq_petsc_vi_regression_testbed.py
```

Resultats:

- `21 passed` pour le launcher testbed generique avant le lot 4;
- `1 passed` pour le rapport web testbed;
- `5 passed` pour le bridge site-selection et le testbed de regression PETSc.

Validation apres lot 4:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py
python -m pytest tests\unit\launchers\test_site_selection_bridge_examples.py tests\unit\launchers\test_boussinesq_petsc_vi_regression_testbed.py
```

Resultats:

- `24 passed` pour le launcher testbed generique;
- `5 passed` pour le bridge site-selection et le testbed de regression PETSc.

Validation apres lot 5:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py
python -m pytest tests\unit\launchers\test_site_selection_bridge_examples.py tests\unit\launchers\test_boussinesq_petsc_vi_regression_testbed.py
python -m pytest tests\unit\config\test_schema_export.py tests\unit\config\test_schema_profile_filter.py tests\unit\config\test_field_metadata.py
python -m pytest tests\unit\test_schema_export.py tests\unit\test_schema_annotations.py
```

Resultats:

- `24 passed` pour le launcher testbed generique;
- `5 passed` pour le bridge site-selection et le testbed de regression PETSc;
- `25 passed` pour les tests config/schema cibles;
- `14 passed` pour les tests schema globaux cibles.

Validation apres lot 6:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py
```

Resultat:

- `24 passed` pour le launcher testbed generique avec capture explicite des
  `DeprecationWarning` legacy.

Validation apres lot 7:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py
```

Resultat:

- `24 passed` pour le launcher testbed generique apres publication changelog et
  migration de la page utilisateur workflow.

Validation apres lot 8:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py tests\unit\launchers\test_site_selection_bridge_examples.py tests\unit\launchers\test_boussinesq_petsc_vi_regression_testbed.py
python -m pytest tests\unit\config\test_schema_export.py tests\unit\config\test_schema_profile_filter.py tests\unit\config\test_field_metadata.py tests\unit\test_schema_export.py tests\unit\test_schema_annotations.py
```

Resultats:

- `30 passed` pour launcher testbed, bridge site-selection et regression PETSc;
- `39 passed` pour les tests config/schema cibles et globaux.

## Etat courant

Le contrat public prefere est:

```toml
[[testbed.case]]
id = "low_k"
axis = "hydraulic_conductivity"

[testbed.case.overlay.flow.param.K.field]
value = "5e-6 m/s"

[[testbed.case_from_catalog]]
id_template = "{case_id}"
```

Le contrat historique reste supporte mais emet un `DeprecationWarning`:

```toml
[[testbed.variant]]
id = "low_k"

[[testbed.variant_from_catalog]]
id_template = "{variant_id}"
```

Les sorties CSV/JSON sont volontairement redondantes pendant la migration. Les
nouveaux consommateurs doivent lire `case_id` / `case_label`; les anciens
consommateurs peuvent continuer a lire `variant_id` / `variant_label`.

## Dette restante

1. Quelques noms internes Python restent centres sur `variant` pour
   compatibilite ou dette locale: `catalog_variants.py`, le champ interne
   `TestbedPlannedCase.variant`, et l'alias `expand_catalog_variants`.
2. Certains scripts et rapports aval conservent des variables locales
   `variant_id` meme lorsqu'ils lisent maintenant `case_id`.
3. Le jalon exact de retrait doit encore etre rattache a une version. La
   deprecation est publiee, mais le calendrier de suppression reste volontairement
   generique.
4. Les documents generes ou historiques hors perimetre peuvent encore citer
   `variant`; ces occurrences doivent etre traitees par familles, pas par
   remplacement global.

## Risques

- Renommer les modeles Pydantic directement risque de modifier la reference de
  configuration generee et des imports publics.
- Supprimer trop vite `variant_id` casserait les rapports existants et certains
  artefacts deja produits.
- `variant` peut rester legitime dans d'autres domaines du depot, notamment
  les sensibilites scientifiques, les solveurs et la galerie. Le nettoyage doit
  rester borne au contrat testbed generique.

## Prochaine etape recommandee

Lot 9: auditer les consommateurs aval et les sorties legacy.

Objectif: decider si les champs de sortie `variant_*` et les variables locales
aval restent des alias de compatibilite longue duree ou deviennent une dette a
supprimer au prochain jalon cassant.

Actions proposees:

1. Auditer les scripts de reporting qui lisent encore `variant_id` /
   `variant_label`.
2. Distinguer les vrais variants scientifiques (par exemple low/high K) des
   identifiants d'unite executable testbed.
3. Fixer si `variant_*` reste dans les CSV/JSON au-dela du prochain jalon
   cassant.
4. Eventuellement isoler le module `catalog_variants.py` derriere un nouveau
   module `catalog_cases.py`, avec import legacy.

Validation minimale attendue apres lot 9:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py
```
