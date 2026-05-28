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
- Migration de l'index d'archives BD ALTI vers
  `hydromodpy/data/variables/dem/apis/_bdalti_archive_index.py`.
- Conservation des helpers `BDALTI_25M_ASC_ARCHIVES`, `_extract_7z`,
  `_find_asc_files` et `_request_hash_str` comme details internes utilises par
  `ign_dem_fr`.
- Retrait de l'index BD ALTI de l'export paresseux du package
  `hydromodpy.data.variables.dem.apis`; il reste un detail interne importe
  directement par le client et ses tests.
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
- Retrait de l'index BD ALTI interne de `hydromodpy.data.variables.dem.apis.__all__`.
- Scan strict hors `_dev_notes`: les seules occurrences restantes de
  `ign_bdalti` sont les tests de rejet.

## Lot complementaire - clarification de cloture

- Le provider public `ign_geoplateforme_dem` n'expose plus que
  `dataset = "bd-alti"` dans le schema utilisateur. Le chemin d'assemblage
  raster supporte explicitement BD ALTI 25 m ASC.
- RGE ALTI reste disponible uniquement dans le helper de telechargement brut
  (`tools/download_dem_fr`) et dans les fonctions de discovery/download bas
  niveau. Il n'est pas expose comme raster assemble par le data manager V1.
- Le fallback sur l'index interne des archives BD ALTI est documente comme
  resilience interne du client Geoplateforme, pas comme provider legacy.
- Le module interne a ete renomme en `_bdalti_archive_index.py` et le flag de
  metadonnees du cache adopte s'appelle maintenant `adopted_unversioned_cache`.
- La resolution DEM des workflows `site_selection` a ete factorisee pour
  eviter de dupliquer le fallback `DataDemConfig.ign_geoplateforme_dem(...)`.
- La reference de configuration, le schema JSON, l'OpenAPI wrapper, l'index de
  recherche config et les diagrammes ont ete regeneres apres resserrement du
  schema.

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
- Validation du lot de clarification:
  `python -m ruff check` sur les fichiers DEM/site-selection/tests touches: OK.
- `python -m pytest -q tests/unit/config/test_discriminated_unions.py tests/unit/data_managers/test_variable_managers_smoke.py tests/unit/data_managers/test_dem_manager.py tests/unit/data_managers/test_geoplateforme_dem_downloader.py -o addopts=""`: 137 passed.
- `python -m pytest -q tests/unit/test_docs_config_consistency.py tests/unit/tools/test_verify_docs_refresh_outputs.py -o addopts=""`: 29 passed.
- `python -m pytest -q tests/unit/site_selection -o addopts=""`: 153 passed.

## Etat de cloture

Le chantier legacy `ign_bdalti` peut etre cloture.

Nettoyage de cloture 2026-05-28:

- Le plan d'implementation Geoplateforme est marque comme archive historique
  et ne sert plus de backlog courant.
- L'audit national ne presente plus `ign_bdalti` comme source DEM active.
- Le grep actif reste borne aux tests anti-retour et aux details internes
  BD ALTI du provider Geoplateforme.
- Validations ciblees relancees:
  Ruff sur les perimetres DEM/TMesh et tests cibles: OK;
  discriminated-unions + smoke managers: 114 passed;
  `test_dem_manager.py`: 2 passed;
  `test_geoplateforme_dem_downloader.py`: 21 passed.

Les points suivants ne bloquent pas la cloture; ils relevent d'un suivi
Geoplateforme/RGE ALTI separe:

1. Valider periodiquement un vrai test reseau/download/assembly Geoplateforme
   avec les variables d'environnement explicites.
2. Suivre l'evolution de la discovery Geoplateforme BD ALTI; le fallback interne
   pourra etre retire si le service devient suffisamment stable et complet.
3. Ouvrir un chantier dedie si RGE ALTI doit devenir un raster assemble par le
   data manager, avec garde-fous de volume, fragments d'archives et cache.
4. Nettoyer optionnellement les notes `_dev_notes` historiques si l'objectif
   devient un grep strict sans aucune mention de `ign_bdalti` dans tout le repo.
