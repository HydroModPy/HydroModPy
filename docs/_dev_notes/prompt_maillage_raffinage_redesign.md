# Prompt — Refonte de la logique de raffinage du maillage (HydroModPy)

## Mission

Repenser et réimplémenter la **logique de raffinage automatique** du maillage catchment
MODFLOW 6 de HydroModPy pour qu'elle raffine **ce qui compte physiquement** (rives de lac,
cours d'eau, zone du voile/barrage = exutoire) au lieu de ce qu'elle raffine aujourd'hui
(tout l'intérieur du lac + toute la ligne de partage des eaux du bassin). Ajouter un
mécanisme de **zones d'intérêt fournies par l'utilisateur** (couches de polygones et/ou
points). Garder l'orthogonalité Voronoi (XT3D-free). Livrer testé, avec un rendu Chèze
avant/après pour prouver l'amélioration.

Tu es un agent de code autonome. Le dépôt est à
`/home/bb/Documents/01_Git_Repository/03-HydroModPy-lakeres`. Active l'env d'abord :
`mamba activate hmp_refact`. Pour lancer HydroModPy sur ce dépôt (le `hmp` installé pointe
sur un AUTRE checkout) : `PYTHONPATH=$REPO python -m hydromodpy <verbe> ...`.

---

## Contexte technique (à connaître avant de toucher au code)

HydroModPy construit une grille DISV MODFLOW 6 en **deux étages** joints par un seam :

1. **Triangulation conforme GMSH** (`hydromodpy/spatial/mesh/gmsh_grid/zone_meshing/`) :
   les polygones géologie deviennent une partition OCC, les lignes rivière/lac/barrage sont
   embarquées comme **arêtes** de contrainte, et l'adaptativité vient de **champs de taille
   GMSH** (distance→`Threshold` autour des courbes + champs régionaux "inside/outside" pour
   les zones), tous combinés par un `Min` (`_gmsh_fields.py:40`).
2. **Dual Voronoi/PEBI** au seam `_build_extruded_solver_mesh_from_runtime_planar`
   (`hydromodpy/solver/modflow_grid/discretization_spatial.py:150-161`) : quand
   `grid_dual == "voronoi"` (défaut), les **sommets** de la triangulation deviennent les
   générateurs Voronoi, et **le générateur = le centre de cellule DISV** (`voronoi.py:150`).
   C'est ce qui rend la grille exactement K-orthogonale (TPFA sans XT3D).

**INVARIANT À NE JAMAIS CASSER** : générateur = centre de cellule. Toute cette tâche ne touche
QUE *quelles géométries alimentent les champs de taille GMSH* (donc où les sommets sont denses).
Le dual (`voronoi.py:81-151`) et le seam ne changent pas.

Le raffinage n'améliore PAS la conformité aux features (le Voronoi met la feature au centre des
cellules, pas sur une arête — c'est un autre chantier, "seeds en paires miroir", hors scope ici).
Ici on corrige seulement **où** et **quoi** on raffine, pas la conformité arête.

---

## Le problème (ce que reproche l'utilisateur)

> "L'automatisation du raffinage est très mauvaise, il ne raffine pas ce qu'il faut. Il faut
> raffiner l'exutoire du lac mais il raffine toute une ligne que je ne comprends même pas
> pourquoi. Je ne comprends pas la logique de raffinage en dehors de celle des cours d'eau."

Idéal exprimé par l'utilisateur :
- les **bordures (rives) du lac** raffinées,
- le **BV pour les cours d'eau** (réseau hydro) raffiné,
- **toute la zone HFB** (voile sous barrage) raffinée, ce qui **raffine l'exutoire du lac par
  la même occasion** (le voile est au barrage = à l'exutoire),
- et éventuellement un mécanisme où **l'utilisateur fournit des zones d'intérêt** (couche(s) de
  polygones et/ou des points x,y) pour dire où raffiner.

---

## Ce que le raffinage fait AUJOURD'HUI (6 sources, avec ancres code)

1. **Réseau de cours d'eau** — famille `river`/interface, champs distance autour des lignes de
   rivière. `apply_family_refinement_fields` (`gmsh_grid/zone_meshing/_gmsh_fields.py:104`).
   *(Celle que l'utilisateur comprend et veut garder.)*
2. **Footprint du lac** — `lake::footprint` : raffine **tout l'intérieur** du polygone lac à
   `cell_size`. `lake_refinement.py:85-95`, `region_geometry = lake_polygon` (le polygone plein).
   → Gaspillage : c'est la **rive** (marnage, empreinte LAK) qui a besoin de finesse, pas
   l'intérieur.
3. **Disque au barrage** — `lake::dam_outlet` : disque de rayon `dam_buffer` autour de `dam_xy`,
   à `dam_cell_size`. `lake_refinement.py:96-109`.
4. **Structures hydrauliques** — `feature::<label>` : voile, seuil lac-lac, déversoirs, entrées
   SFR→lac, bufferisés en corridors. `lake_refinement.py:110-130`. Assemblées par
   `_hydraulic_feature_geometries` (`hydromodpy/workflow/steps/mesh.py:113`).
5. **Frontière du BV** — famille `watershed_boundary`, **activée par défaut**
   (`gmsh_grid/zone_meshing/config.py:153` : `{"enabled": True, "priority": 100}`, champ défini
   `config.py:81`). Raffine **toute la ligne de partage des eaux** (contour fermé de dizaines de
   km). Raison : mettre la frontière de routage DRN sur des arêtes de cellules. **C'est la "ligne
   mystère" que l'utilisateur ne comprend pas** : un long ruban fin sans intérêt pour la physique
   lac/barrage.
6. **Interfaces géologie** — famille `geology_interface` (si géologie présente).

Point de câblage central : `hydromodpy/workflow/steps/mesh.py:163-179` lit
`mesh_catchment.lake_refinement` et appelle `build_lake_refinement_size_fields(lake_polygon=...,
dam_xy=..., cfg=..., global_size=..., feature_geometries=_hydraulic_feature_geometries(...))`
(`hydromodpy/spatial/mesh/lake_refinement.py:57`).

Config Chèze concernée (variantes du projet exemple) :
`examples/projects/19_cheze_reservoir/project_preretenue_5m.toml`, sections `[mesh_catchment]`,
`[mesh_catchment.lake_refinement]` (cell_size, buffer, dam_cell_size, dam_buffer),
`[mesh_catchment.watershed_boundary]` (enabled=true), et
`[mesh_catchment.zone_meshing.refinement_policy.families.watershed_boundary]`.

---

## Le modèle cible (l'idée)

Le raffinage = **union de sources claires**, chacune = (géométrie, taille cible, distance de
fondu). Concrètement :

| Source | Géométrie à alimenter | Remplace / change |
|---|---|---|
| **Rive du lac** | `lake_polygon.boundary` bufferisé en bande (PAS le polygone plein) | remplace `lake::footprint` intérieur |
| **Cours d'eau** | réseau SFR/rivière (inchangé) | garder |
| **Zone HFB / voile** | tracé du voile bufferisé en **zone** (buffer élargi, pas corridor étroit) | absorbe `lake::dam_outlet` (redondant : le voile est à l'exutoire) |
| **Zones d'intérêt utilisateur** *(NOUVEAU)* | couche(s) gpkg/shp de polygones (= zones) et/ou points (= corridors), chacune avec une taille cible | nouvelle sous-config |
| **Frontière BV** | — | **désactiver par défaut** (opt-in explicite si on veut la frontière DRN nette) |

La rive du lac + la zone HFB (qui couvre l'exutoire) + les cours d'eau = exactement l'idéal
décrit. La frontière BV off supprime la ligne mystère.

---

## Pourquoi c'est faisable (la machinerie existe déjà)

`ZoneRegionalSizeField` (`hydromodpy/spatial/mesh/gmsh_grid/zone_meshing/contracts.py`, construit
dans `lake_refinement.py:87`) prend **n'importe quelle géométrie** + `inside_size` / `outside_size`
/ `transition_distance`, et bufferise déjà points/lignes en corridors (`lake_refinement.py:114-119`).
Donc :
- Rive du lac : passer `lake_polygon.boundary.buffer(bande)` au lieu du polygone plein → trivial.
- Zone HFB : élargir le buffer du `feature::voile` → trivial.
- Zones utilisateur : nouvelle sous-config + loader gpkg (réutiliser la machinerie InputFile du
  projet) + une famille/champ régional par zone → petit.
- Frontière BV off : `gmsh_grid/zone_meshing/config.py:153` `enabled: False`.

---

## Travail demandé (dans cet ordre)

1. **Rive du lac au lieu du footprint.** Dans `LakeRefinementConfig`
   (`hydromodpy/spatial/mesh/lake_refinement.py:29`) et `build_lake_refinement_size_fields`,
   raffiner une **bande de rive** (`lake_polygon.boundary` bufferisée) au lieu du polygone plein.
   Garder une option (`refine_interior: bool = False` ou `interior_size`) pour raffiner aussi un
   peu l'intérieur si demandé (utile marnage/bathymétrie) — voir décisions.
2. **Zone HFB élargie** couvrant l'exutoire ; supprimer/rendre optionnel le disque
   `lake::dam_outlet` redondant.
3. **Frontière BV off par défaut** (`config.py:153`). Documenter que c'est un opt-in DRN-routing.
4. **Zones d'intérêt utilisateur** : nouvelle sous-config, p.ex.
   ```toml
   [[mesh_catchment.refinement_zone]]
   path = "zone_captage.gpkg"   # polygones (zones) ou points (corridors)
   cell_size = 40.0
   buffer = 120.0
   ```
   Loader (gpkg/shp, reprojeté au CRS projet), chaque feature → un `ZoneRegionalSizeField`.
   Placer la config sur `MeshCatchmentConfig` (`hydromodpy/spatial/mesh/config/main.py:31`),
   câbler dans `workflow/steps/mesh.py`.
5. **Tests unitaires** : la bande de rive raffine bien la rive et pas l'intérieur ; une zone
   utilisateur produit un champ ; la frontière BV n'est plus active par défaut.
6. **Rendu Chèze avant/après** : lancer
   `PYTHONPATH=$REPO python -m hydromodpy run examples/projects/19_cheze_reservoir/project_preretenue_5m.toml --no-display --force --until BuildMeshStep`,
   puis générer/mettre à jour une figure du maillage (zoom réservoir + barrage) montrant que la
   rive et la zone HFB/exutoire sont raffinées et que la ligne BV a disparu. Un script de
   comparaison de maillage existe déjà dans le scratchpad de session (`compare_meshes.py`, lit le
   `.disv.grb`) — s'en inspirer.

---

## Décisions à trancher (poser la question ou choisir un défaut raisonnable)

- **Rive seule vs rive + intérieur léger.** Défaut recommandé : bande de rive fine + intérieur
  laissé au `global_size` ; option `interior_size` pour ceux qui veulent aussi l'intérieur (lacs
  à marnage/bathymétrie). L'utilisateur a explicitement demandé ce choix.
- **Largeur de la bande de rive** : proportionnelle à `cell_size` (p.ex. `buffer` existant) ou un
  nouveau `shoreline_band`.
- **Zones utilisateur** : points → corridor (buffer) ; polygones → zone telle quelle. Confirmer.

---

## Contraintes (RESPECTER ABSOLUMENT)

- **Architecture en couches stricte** (voir `CLAUDE.md` + `tests/unit/architecture/layer_matrix.yaml`).
  `spatial/mesh` reste dans sa couche ; pas de nouvel import circulaire ; le seam
  `discretization_spatial.py` et le dual `voronoi.py` ne changent pas.
- **Invariant orthogonalité** : générateur = centre de cellule. On ne touche qu'aux champs de
  taille (densité des sommets), jamais au calcul du dual.
- **Pydantic v2**, tout `BaseModel` a `model_config = ConfigDict(extra="forbid")`. Types hints
  partout. Docstrings courtes en anglais. Pas de commentaires superflus.
- **Pas de code legacy / pas d'alias / pas de shim de compat.** Un symbole = un nom canonique.
- `ruff check --fix .` puis `ruff format .` avant tout commit. Obligatoire.
- **NE PAS toucher `examples/projects/` SAUF les variantes `project_preretenue_5m*.toml` du projet
  Chèze** (créées pour ce travail). `hydromodpy_annex/` et `_archive/` interdits.
- **Réponses à l'utilisateur en français** (termes techniques anglais OK), pas d'em-dashes, pas de
  filler IA.
- **Jamais de branche, jamais de commit/push sauf demande explicite.** Rester sur la branche
  active `dev-lakeres_refact`.
- **Pas de Streamlit nulle part** (préférence forte de l'utilisateur, tout Streamlit a été retiré).

---

## Vérification finale

- `ruff check` + `ruff format` clean.
- `pytest tests/unit/spatial/ -k "mesh or refinement or lake"` vert.
- Test architecture `tests/unit/architecture/test_layer_matrix.py` vert.
- Rendu Chèze : la rive du lac + la zone HFB/exutoire sont nettement raffinées, la ligne de
  partage des eaux n'est plus un ruban fin, l'intérieur du lac est grossier (sauf option).
- Le run `--until BuildMeshStep` termine sans erreur ; idéalement un run
  `--until RunSolverStep` converge (Normal termination) — noter si le solve reste instable
  (problème séparé de projection d'altitude, hors scope de cette tâche).

## Références de session (contexte plus large)

- `docs/_dev_notes/plan_maillage_altitude_2026-07-09.md` — plan étagé complet (maillage +
  projection d'altitude + délinéation), bake-off Voronoi/triangle, verdict mf6Voronoi.
- Le raffinage-conformité (seeds en paires miroir, méthode B1) et la projection d'altitude
  (échantillonnage zonal, structure-carve du barrage) sont des chantiers SÉPARÉS, hors scope de
  ce prompt qui se limite à *quoi/où raffiner*.
