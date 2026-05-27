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

## Fichiers principaux touches

- `hydromodpy/analysis/testbed/config.py`
- `hydromodpy/analysis/testbed/pipeline.py`
- `hydromodpy/analysis/testbed/runtime.py`
- `hydromodpy/analysis/testbed/catalog_variants.py`
- `hydromodpy/analysis/testbed/README.md`
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

Le contrat historique reste supporte mais doit etre considere comme legacy:

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

1. La reference de configuration generee expose encore les champs Pydantic
   internes `testbed.variants` et `testbed.catalog_variants`.
2. Les noms internes Python restent centres sur `variant`:
   `TestbedVariantConfig`, `TestbedCatalogVariantConfig`,
   `catalog_variants.py`, `expand_catalog_variants`.
3. Certains scripts et rapports aval conservent des variables locales
   `variant_id` meme lorsqu'ils lisent maintenant `case_id`.
4. La politique de deprecation n'est pas encore fixee: aucune date ou version
   de retrait n'est associee aux spellings TOML historiques ni aux colonnes
   `variant_*`.
5. Les documents generes ou historiques hors perimetre peuvent encore citer
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

Lot 5: traiter la reference de configuration generee.

Objectif: la documentation publique de configuration doit exposer `testbed.case`
et `testbed.case_from_catalog`, pas `testbed.variants` /
`testbed.catalog_variants`.

Deux strategies possibles:

1. Renommer les champs Pydantic internes vers `cases` et `catalog_cases`, avec
   aliases de compatibilite Python si necessaire.
2. Adapter le generateur de reference pour mapper les noms internes legacy vers
   le vocabulaire public `case`, sans renommer encore les classes et attributs.

Approche recommandee: commencer par auditer le generateur de reference et les
tests associes, puis choisir l'option qui minimise le churn public.

Validation attendue apres lot 5:

```powershell
python -m pytest tests\unit\launchers\test_testbed_launcher.py
python -m pytest tests\unit\launchers\test_site_selection_bridge_examples.py tests\unit\launchers\test_boussinesq_petsc_vi_regression_testbed.py
python -m pytest tests\unit\config tests\unit\schema
```
