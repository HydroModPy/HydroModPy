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

Dans cette premiere phase, les spellings historiques restaient acceptes
temporairement:

- `[[testbed.variant]]`;
- `[[testbed.variant_from_catalog]]`.

Cette compatibilite d'entree a ete retiree au lot 10.

### Lot 3 - sorties compatibles mais orientees `case`

Les artefacts generiques ecrivent maintenant les champs canoniques:

- `case_id`;
- `case_label`;
- `case_count`;
- `case_from_catalog`.

Dans cette premiere phase, les champs historiques restaient presents pour
compatibilite aval:

- `variant_id`;
- `variant_label`;
- `variant_count`;
- `variant_from_catalog`.

Cette compatibilite de sortie a ete retiree au lot 9.

### Lot 4 - migration des exemples TOML et des tests inline

Les TOML publics des exemples testbed ont ete migres vers le vocabulaire
canonique:

- `examples/projects/10_testbed_workflow/**/*.toml`;
- `examples/projects/18_site_selection_to_testbed/**/*.toml`.

Les TOML inline de `tests/unit/launchers/test_testbed_launcher.py` utilisent
maintenant `[[testbed.case]]` et `[[testbed.case_from_catalog]]`. Les tests
dedies au legacy verifient le rejet de:

- `[[testbed.variant]]`;
- `[[testbed.variant_from_catalog]]`;
- `[[testbed.variants]]` et
  `[[testbed.catalog_variant]]`;
- un TOML qui melange `case` et `variant`.

### Lot 5 - reference de configuration generee

Les champs Pydantic publics du `TestbedConfig` ont ete renommes:

- `variants` -> `case`;
- `catalog_variants` -> `case_from_catalog`.

Les proprietes Python canoniques restent disponibles:

- `cases`;
- `catalog_cases`;

Le validateur Pydantic rejette une construction Python directe avec les anciens
noms `variants` et `catalog_variants`. La reference generee expose donc
maintenant:

- `testbed.case`;
- `testbed.case_from_catalog`.

Le generateur `tools/doc_config` a aussi ete corrige pour afficher les
`tuple[BaseModel, ...]` comme des arrays of tables TOML `[[...]]`, au meme titre
que les `list[BaseModel]`. Cette correction touche aussi les tables
`analysis.batch.cluster_rules` et `analysis.batch.recipes`, qui etaient rendues
avec un seul crochet dans la reference.

### Lot 6 - politique de deprecation runtime

Pendant la phase de transition, les spellings historiques emettaient un
`DeprecationWarning` lorsqu'ils sont utilises comme entree:

- `[[testbed.variant]]` -> `[[testbed.case]]`;
- `[[testbed.variant_from_catalog]]` -> `[[testbed.case_from_catalog]]`;
- `TestbedConfig(variants=...)` -> `TestbedConfig(case=...)`;
- `TestbedConfig(catalog_variants=...)` ->
  `TestbedConfig(case_from_catalog=...)`.

Cette politique a ete remplacee par le retrait effectif du lot 10.

### Lot 7 - publication de la deprecation

La deprecation est maintenant visible dans les surfaces publiques:

- `CHANGELOG.md` a d'abord ajoute une entree `Deprecated` dans `[Unreleased]`;
- `docs/source/user_guide/workflows/testbed.rst` utilise `case` dans les
  exemples et documente la compatibilite legacy `variant`;
- la page workflow renvoie les nouveaux TOML vers `[[testbed.case]]` et
  `[[testbed.case_from_catalog]]`.

Cette publication a ete transformee en entree `Removed` au lot 10.

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

### Lot 9 - retrait des sorties `variant_*`

Les artefacts generiques testbed n'ecrivent plus les cles de compatibilite:

- `variant_id`;
- `variant_label`;
- `variant_count`;
- `variant_from_catalog`.

Les sorties canoniques restantes sont:

- `case_id`;
- `case_label`;
- `case_count`;
- `case_from_catalog`.

Les consommateurs aval cibles ont ete migres:

- tests launcher et regional-lab;
- rapport HTML testbed generique;
- rapport HTML NWT flux testbed;
- changelog `[Unreleased]`.

Les spellings d'entree legacy restaient separes de cette decision jusqu'au
lot 10.

### Lot 10 - retrait des entrees legacy

Le parser generique rejette maintenant les entrees historiques:

- `[[testbed.variant]]`;
- `[[testbed.variant_from_catalog]]`.

La construction Python directe rejette aussi:

- `TestbedConfig(variants=...)`;
- `TestbedConfig(catalog_variants=...)`.

Les proprietes legacy `cfg.variants` et `cfg.catalog_variants` ont ete
retirees. Les consommateurs Python doivent utiliser `cfg.cases`,
`cfg.catalog_cases`, `cfg.case` ou `cfg.case_from_catalog`.

Le changelog `[Unreleased]` decrit maintenant ces retraits dans la section
`Removed`.

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
- `docs/source/user_guide/workflows/regional_lab.rst`
- `docs/source/user_guide/workflows/testbed.rst`
- `docs/source/user_guide/config_reference/testbed.rst`
- `docs/source/user_guide/config_reference/config_index.rst`
- `docs/source/user_guide/config_reference/complete_toml.rst`
- `docs/source/_static/hmp-config-search.json`
- `docs/source/_static/hydromodpy-schema.json`
- `docs/source/_static/hydromodpy-openapi.json`
- `tests/unit/analysis/test_testbed_web_report.py`
- `tests/unit/launchers/test_testbed_launcher.py`
- `tests/unit/launchers/test_boussinesq_petsc_vi_regression_testbed.py`
- `tests/unit/launchers/test_regional_lab_launcher.py`
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

Validation apres lot 9:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py tests\unit\launchers\test_site_selection_bridge_examples.py tests\unit\launchers\test_boussinesq_petsc_vi_regression_testbed.py tests\unit\launchers\test_regional_lab_launcher.py
python -m pytest tests\unit\analysis\test_testbed_web_report.py
```

Resultats:

- `53 passed` pour launcher testbed, bridge site-selection, regression PETSc et
  regional-lab;
- `1 passed` pour le rapport web testbed.

Validation apres lot 10:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py tests\unit\launchers\test_site_selection_bridge_examples.py tests\unit\launchers\test_boussinesq_petsc_vi_regression_testbed.py tests\unit\launchers\test_regional_lab_launcher.py
python -m pytest tests\unit\analysis\test_testbed_web_report.py
```

Resultats:

- `53 passed` pour launcher testbed, bridge site-selection, regression PETSc et
  regional-lab;
- `1 passed` pour le rapport web testbed.

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

Le contrat historique n'est plus supporte:

```toml
[[testbed.variant]]
id = "low_k"

[[testbed.variant_from_catalog]]
id_template = "{case_id}"
```

Les sorties CSV/JSON ne sont plus redondantes: les consommateurs doivent lire
`case_id` / `case_label` et `case_count` / `case_from_catalog`.

## Dette restante

1. Quelques noms internes Python restent centres sur `variant` pour
   compatibilite ou dette locale: `catalog_variants.py`, le champ interne
   `TestbedPlannedCase.variant`, et l'alias `expand_catalog_variants`.
2. Certains scripts de demonstration hors runtime generique conservent
   `variant` lorsqu'il designe un vrai axe scientifique ou une famille de cas.
3. Les aliases Python de type `TestbedVariantConfig` et
   `TestbedCatalogVariantConfig` restent disponibles pour compatibilite
   d'import, meme si la reference publique expose les noms `Case`.
4. Les documents generes ou historiques hors perimetre peuvent encore citer
   `variant`; ces occurrences doivent etre traitees par familles, pas par
   remplacement global.

## Risques

- Renommer les modeles Pydantic directement risque de modifier la reference de
  configuration generee et des imports publics.
- Les artefacts historiques qui contiennent seulement `variant_*` doivent etre
  regeneres ou convertis avant lecture par les nouveaux rapports.
- `variant` peut rester legitime dans d'autres domaines du depot, notamment
  les sensibilites scientifiques, les solveurs et la galerie. Le nettoyage doit
  rester borne au contrat testbed generique.

## Prochaine etape recommandee

Lot 11: isoler les derniers noms internes legacy.

Objectif: reduire la dette interne sans toucher aux vrais variants
scientifiques hors testbed generique.

Actions proposees:

1. Ajouter un module canonique `catalog_cases.py` et garder
   `catalog_variants.py` comme shim d'import.
2. Renommer le champ interne `TestbedPlannedCase.variant` en `case_config` si
   le churn reste local.
3. Decider si les aliases de type `TestbedVariantConfig` et
   `TestbedCatalogVariantConfig` restent exports ou passent par un shim.
4. Laisser `variant` intact dans les exemples ou rapports ou il designe un vrai
   axe scientifique.

Validation minimale attendue apres lot 11:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py
```
