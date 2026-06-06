# Site selection - audit des duplications potentielles

Date: 2026-05-27

## Synthese

Le volume de `site_selection` vient surtout du fait que le package porte le
contrat d'audit complet: configuration typee, candidats, delimitation,
preuves, criteres, decisions, exports vectoriels/tabulaires, manifest et
rapport HTML. La plus grande partie n'est pas une duplication directe d'autres
modules: `site_selection` orchestre des primitives existantes et ajoute les
artefacts metier necessaires pour expliquer chaque decision.

Les vraies duplications a reduire sont principalement des helpers d'export
vectoriel et de rendu HTML, pas les algorithmes hydrologiques.

## Pas une duplication a supprimer maintenant

- `hydrology/flow_products.py` est un adaptateur fin autour de
  `hydromodpy.spatial.geographic.core.flow_products.build_regional_flow_products`.
  Il ajoute un contrat local et des chemins d'artefacts pour le manifest; il ne
  reimplemente pas le calcul D8/accumulation.
- `hydrology/delineation.py` delegue a
  `hydromodpy.spatial.geographic.core.catchment_from_point.extract_catchment_from_point`.
  La couche locale transforme le resultat en `DelineatedCatchment`, gere les
  echecs auditables, le snap de reference et les surfaces.
- `outputs/manifest.py` complete
  `hydromodpy.schema.site_selection_manifest`: le schema central definit les
  constantes et la resolution aval, tandis que le module spatial construit et
  valide le manifest d'un run concret.
- `outputs/tabular.py` produit `regional_lab_sites.csv`; le resolver
  `hydromodpy.analysis.testbed.site_selection_catalog` le consomme ensuite via
  le manifest. C'est une frontiere producteur/consommateur, pas un doublon.

## Duplications reelles

- `outputs/geojson.py` et `outputs/geospatial.py` dupliquent
  `_repair_geometry_for_export` et `_observation_location`.
- `outputs/geospatial.py`, `evidence/influence.py` et `evidence/context.py`
  dupliquent des helpers comme `_single_crs`, `_clean_value` et l'ecriture
  `GeoDataFrame.to_file(..., driver="GPKG")`.
- `candidates/generation.py` et `outputs/geospatial.py` dupliquent le nettoyage
  de proprietes JSON/GeoJSON via `_clean_properties` et `_clean_value`.
- Les rapports `site_selection/reports/*` ont leurs propres helpers HTML alors
  que `hydromodpy.results.html_helpers` et
  `hydromodpy.reporting.comparison.html_utils` fournissent deja `safe_html` et
  `link_relative`.

## Refactor conseille

Priorite 1: extraire les helpers d'export vectoriel dans un petit module
partage, d'abord interne a `site_selection` pour limiter le risque:

- `repair_geometry_for_export`;
- `observation_location`;
- `clean_value` / `clean_properties`;
- `single_crs`;
- `write_gpkg_layer`.

Priorite 2: si d'autres packages en ont besoin, promouvoir ce module vers
`hydromodpy.core.io.geospatial`, sur le modele de
`hydromodpy.core.io.geoparquet.write_geoparquet_atomic`.

Priorite 3: remplacer progressivement les helpers HTML locaux par
`hydromodpy.results.html_helpers.safe_html` et `link_relative`, uniquement si
cela ne force pas une refonte du rapport. Le layout du rapport reste metier et
doit rester dans `site_selection/reports`.

## Hors refactor immediat

- La generation automatique `dem_network_sampling` reste experimentale mais
  elle est testee et couvre un chemin fonctionnel distinct; elle ne doit pas
  etre supprimee comme legacy sans decision produit separee.
- Les adaptateurs hydrologiques doivent rester proches du workflow: les
  fusionner avec `spatial.geographic.core` ferait perdre le contrat d'audit
  propre a `site_selection`.
