# Maillage conforme gmsh

Note d'architecture : trois concepts coopèrent pour produire un maillage
2D conforme aux zones géologiques et au réseau hydrographique.

1. Extraction du réseau hydrographique depuis le DEM (backend whitebox).
2. Exposition d'une trace rivière en mémoire pour le mailleur.
3. Génération gmsh conforme aux interfaces.

Liens : [glossary.md](glossary.md),
[unified_mesh_pivot_architecture.md](unified_mesh_pivot_architecture.md),
[gmsh_mesh_integration_note.md](gmsh_mesh_integration_note.md).

## 1. Extraction du réseau hydrographique

Module : `hydromodpy/spatial/geographic/core/river_network.py`.

Déclenchement : `geographic.river_network.enabled = true`. Le pipeline
géographique produit alors les fichiers canoniques suivants dans
`results_stable/geographic/` :

- `river_streams.tif` : raster des cellules de cours d'eau.
- `river_streams_pruned.tif` : idem, après élagage optionnel.
- `river_stream_order_strahler.tif` : ordre de Strahler.
- `river_stream_link_id.tif` : identifiant de tronçon.
- `river_network.shp` : version vectorielle clippée au bassin versant.
- `river_network_summary.json` : métriques de reproductibilité.

Entrées requises :

- DEM (corrigé via `fill` ou `breach`).
- Exutoire, snap à l'accumulation.
- Direction et accumulation D8.

Backend : `WhiteboxWorkflowsBackend`
(`hydromodpy/spatial/delineation/whitebox_workflows_backend.py`) pour la
version wheel, `WhiteboxCLIBackend` pour le binaire standalone. Le
choix se fait via `get_whitebox_backend(preferred=...)`.

Paramètres TOML :

```toml
[geographic.river_network]
enabled = true
threshold_mode = "area_km2"      # ou "cells"
threshold_area_km2 = 0.5
prune_short_streams = false
min_stream_length_m = 0.0
compute_strahler_order = true
compute_stream_links = true
```

Conversion interne : `threshold_cells = threshold_area_km2 * 1e6 / dem_res_m**2`.

## 2. Trace rivière en mémoire

Classe : `RiverMeshTrace`
(`hydromodpy/spatial/geographic/core/river_mesh_trace.py`).

Exposée comme attribut de `DomainGeographicContext.river_mesh_trace`. La
trace est déjà reprojetée dans le CRS du domaine et clippée au bassin
versant. Aucune relecture disque ne survient au moment du maillage.

Champs :

- `source_kind` : `geographic_generated`, `hydrography_loaded`, `file`.
- `crs_wkt` : CRS cible.
- `lines` : tuple de `LineString` Shapely.
- `segment_count` et `total_length_m` : métriques de contrôle.

Règle de structuration : le réseau hydrographique n'est pas une zone du
domaine. La génération du maillage reste dans `zone_meshing`, la logique
métier du domaine reste dans `spatial/domain/`.

## 3. Génération gmsh conforme

Module : `hydromodpy/spatial/mesh/gmsh_grid/zone_meshing/`.

Point d'entrée principal : `conformal.py`. Pipeline :

1. Chargement des polygones de zones et du domaine.
2. Nettoyage géométrique (`_geometry_cleaning.py`, `_polygon_cleaning.py`) :
   `make_valid`, simplification, snapping, élimination des slivers.
3. Partition planaire non chevauchante (`_partition_builder.py`,
   `_partition_split.py`), avec résolution d'éventuels recouvrements
   par champ de priorité.
4. Traduction en géométrie OCC gmsh (`_gmsh_occ.py`), avec points,
   courbes, boucles et surfaces.
5. Champs de taille (`_gmsh_fields.py`) : global, raffinement autour des
   interfaces, autour des petites zones, autour des rivières.
6. Export `.msh` (`_gmsh_export.py`) et sidecar de métadonnées
   (`_summary_sidecar.py`).

Groupes physiques créés :

- `zone::<zone_key>` sur les surfaces.
- `interface::<zone_a>::<zone_b>` sur les lignes internes.
- `boundary::<name>` sur les contours externes.

Modes disponibles :

- `river_only` : conformité au réseau hydrographique, pas de contrainte
  lithologique.
- `river_plus_lithology` : conformité simultanée aux interfaces
  lithologiques et aux rivières.

## 4. Contrat TOML de maillage

```toml
[mesh]
enabled = true
backend = "gmsh"
mode = "river_conformal"          # ou "river_lithology_conformal"

[mesh.domain]
kind = "vector"                    # "bbox" | "polygon" | "vector"
path = "..."
id_field = "domain_id"
selected_id = "main"

[mesh.river.source]
origin = "geographic_generated"    # "hydrography_loaded" | "file"
path = null                        # requis si origin="file"

[mesh.gmsh]
algorithm = "delaunay"
global_size = 250.0
min_size = 80.0
max_size = 500.0

[mesh.gmsh.river_refinement]
enabled = true
river_size = 60.0
river_distance = 400.0
river_sampling = 96

[mesh.runtime]
use_in_memory_river_trace = true
persist_mesh_inputs = false

[mesh.lithology]
enabled = false
source_mode = "geology_data_manager"
```

## 5. Lecture et projection

Le maillage produit reste lu via `GmshPlanarMesh2D.from_file(...)`. La
projection de `Field` et `FieldParam` reste dans les modules existants
(`Field.on_mesh`, `FieldParam.to_mesh_field`). Sur un maillage conforme,
le nombre de cellules mixtes chute nettement ; la logique de projection
reste cependant inchangée pour couvrir les supports non strictement
conformes.

## 6. Critères qualité

Sortie `*_summary.json` avec :

- Conformité rivière : fraction de longueur de rivière coïncidente avec
  des arêtes du maillage.
- Gradient de raffinement : taille médiane dans un buffer proche rivière
  comparée à la taille hors buffer.
- Couverture du domaine : `|aire_maillage - aire_domaine|` sous
  tolérance.
- Stabilité numérique : nombre total de cellules dans la plage attendue.
- Conformité lithologique si activée : chute du nombre de cellules
  mixtes.
- Reproductibilité : signature stable entre runs identiques.

## 7. Validation et tests

Tests de non-régression :

- `tests/unit/backends/test_whitebox_workflows_backend.py` pour
  `extract_streams`, `raster_streams_to_vector`,
  `strahler_stream_order`, `stream_link_identifier`, `remove_short_streams`.
- `tests/unit/geographic/test_river_network_*.py` pour la couche core
  et le golden de signatures.
- `tests/regression/extensive/` pour les cas de bout en bout.

Helper déterministe : `tests/support/whitebox.py::configure_whitebox_single_thread`
pour stabiliser les runs CI.

## 8. Décisions structurantes

- Le réseau hydrographique est produit par `geographic`, exposé par
  `DomainGeographicContext`, consommé par `zone_meshing`.
- `Domain` ne porte pas la logique de maillage ; il reste le support
  métier des paramètres (`FieldParam`).
- Les deux chemins (lire un maillage existant, générer un maillage
  conforme) convergent sur `GmshPlanarMesh2D` plus un sidecar de
  métadonnées.
- Les triangles sont la cible de la première itération ; la recombination
  quadrilatérale viendra ensuite si besoin.
