# DEM IGN legacy cleanup report

Date: 2026-05-27

## Objectif

Supprimer la surface publique legacy `ign_bdalti` et faire de
`ign_geoplateforme_dem` le seul provider IGN DEM configure par les utilisateurs.
Le chemin BD ALTI 25 m reste disponible, mais comme implementation interne du
client Geoplateforme.

## Etat

Lot 2 termine cote code, exemples, tests cibles et documentation publiee.

`ign_bdalti` n'est plus accepte dans les schemas Pydantic actifs, n'est plus
exporte par `hydromodpy`, et n'est plus reference dans les exemples ou la
documentation utilisateur generee. Les seules references restantes sont les
tests anti-retour ajoutes explicitement et les notes `_dev_notes` historiques.

## Changements runtime

- Suppression de `IgnBdaltiDemSource` et de `DemConfig.ign_bdalti()`.
- Union DEM reduite a `custom | ign_geoplateforme_dem`.
- Suppression de l'export lazy `IgnBdaltiDemSource`.
- Suppression du dispatch `DemManager._fetch_ign_bdalti`.
- Suppression du bootstrap resolver `ign_bdalti`.
- Migration des metadonnees statiques BD ALTI vers
  `hydromodpy/data/variables/dem/apis/bdalti_static.py`.
- Conservation des helpers `_BDALTI_ARCHIVES`, `_extract_7z`,
  `_find_asc_files` et `_request_hash_str` comme details internes utilises par
  `ign_dem_fr`.
- Retrait de `bdalti_static` de l'export paresseux du package
  `hydromodpy.data.variables.dem.apis`; le module reste importable directement
  par les tests et le client interne qui en ont besoin.
- `site_selection` et `site_selection_data` construisent maintenant
  `DataDemConfig.ign_geoplateforme_dem(...)` quand une source DEM publique IGN
  est declaree.

## Changements exemples et docs

- Les TOML Bretagne site-selection utilisent `source = "ign_geoplateforme_dem"`
  avec `dataset = "bd-alti"` et `resolution_m = 25.0`.
- Les exemples overview Nancon et commentaires de projets remplacent l'ancien
  nom de source par le provider Geoplateforme.
- La page utilisateur DEM ne liste plus `ign_bdalti`.
- La matrice des providers data et les assets associes ont ete regeneres.
- La reference de configuration Pydantic, le schema JSON, l'OpenAPI wrapper et
  l'index de recherche config ont ete regeneres.
- Les deux pages de galerie Nancon data-overview ont ete regenerees pour
  afficher le provider DEM courant.
- `docs/source/user_guide/config_reference/_diagrams/data.svg` a ete supprime:
  l'environnement local ne dispose pas de `erdantic`, et le generateur gardait
  sinon un vieux diagramme contenant `IgnBdaltiDemSource`.

## Lot complementaire - garde anti-retour

- Ajout de tests explicites qui rejettent `source = "ign_bdalti"` au niveau
  `DemSourceConfig` et `DemConfig`.
- Retrait de `bdalti_static` de `hydromodpy.data.variables.dem.apis.__all__`;
  le module reste un detail importable directement par `ign_dem_fr` et ses
  tests.
- Scan strict hors `_dev_notes`: les seules occurrences restantes de
  `ign_bdalti` sont les tests de rejet.

## Validations

- `python -m ruff check ...` sur les modules DEM, workflows touches, tests
  cibles et generateur data-doc: OK.
- `python -m pytest -q tests/unit/data_managers/test_geoplateforme_dem_downloader.py tests/unit/data_managers/test_dem_manager.py tests/unit/data_managers/test_variable_managers_smoke.py tests/unit/config/test_discriminated_unions.py tests/unit/site_selection/test_config.py tests/unit/site_selection/test_example_configs.py`: 162 passed.
- `python -m pytest -q tests/unit/test_docs_config_consistency.py tests/unit/tools/test_verify_docs_refresh_outputs.py -o addopts=""`: 29 passed.
- `python -m tools.doc_gallery --check --only geographic_nancon_identity_card --only geographic_nancon_observed_timeseries`: OK.
- `python -m pytest -q tests/integration/test_geoplateforme_dem_network.py -o addopts=""`: 3 skipped par garde reseau.
- Scan final runtime/docs publics:
  `rg "ign_bdalti|IgnBdalti|fetch_bdalti" hydromodpy examples tools docs/source`
  ne retourne plus de reference.

## Residuel avant cloture complete

1. Ajouter un vrai test reseau/CLI Geoplateforme sur une petite emprise ou un
   departement unique, a lancer seulement quand l'environnement reseau est
   explicitement active.
2. Durcir le client Geoplateforme: retry HTTP, messages d'erreur sur URL
   manquante, nettoyage d'archives partielles et verification cache plus
   explicite.
3. Decider le niveau de support RGE ALTI: discovery seulement, assemblage
   borne par garde-fous, ou report explicite apres V1.
4. Ajouter `erdantic` dans l'environnement docs si les diagrammes ER doivent
   rester publies et regenerables.
5. Nettoyer optionnellement les notes `_dev_notes` historiques si l'objectif
   devient un grep strict sans aucune mention de `ign_bdalti` dans tout le repo.
