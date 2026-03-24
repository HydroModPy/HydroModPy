# Zone Meshing

Ce dossier contient le coeur du maillage conforme 2D sur lequel s'appuient les
workflows `gmsh_grid` et, indirectement, `mesh_catchment`.

Le but du code est le suivant :

- recevoir une zonation polygonale et un domaine de travail ;
- produire une partition plane propre, sans recouvrements residuels ;
- injecter des contraintes lineaires eventuelles comme les rivieres ;
- construire un champ de tailles de maille ;
- appeler Gmsh et exporter un maillage plan exploitable par HydroModPy.

Le dossier est volontairement separe par responsabilites :

- `config.py` : validation des parametres
- `domain.py` : chargement du domaine effectif
- `_geometry_cleaning.py` : nettoyage et partitionnement geometrique
- `_refinement_grid.py` : index spatial local pour le raffinement
- `_refinement_policy.py` : politique locale de budget de raffinement
- `_gmsh_driver.py` : appels directs a l'API Python de Gmsh
- `conformal.py` : orchestration globale

## Entrees / Sorties

### Entrees du coeur de maillage

Les deux entrees publiques principales sont :

- `generate_zone_conformal_mesh_from_dataframe(...)`
- `generate_zone_conformal_mesh_from_geology_config(...)`

La premiere attend une zonation deja chargee en memoire.
La seconde charge la geologie depuis un fichier avant d'appeler la premiere.

### Sortie principale

La sortie publique est `ZoneConformalMeshResult`, qui contient :

- `mesh`
  maillage plan runtime `GmshPlanarMesh2D`
- `partition`
  partition plane nettoyee, avant/avec split des contraintes lineaires
- `output_path`
  chemin du `.msh` ecrit sur disque
- `physical_groups`
  groupes physiques Gmsh exportes
- `summary`
  resume stable pour QA, reporting et debugging

### Sorties sur disque

Le coeur `zone_meshing` ecrit au minimum :

- un fichier `.msh`

Le cas de reference et le launcher `mesh_catchment` ajoutent ensuite :

- un resume JSON
- une ou plusieurs figures
- eventuellement un bundle d'echange

## Comment L'Utiliser De L'Exterieur

### 1. Cas le plus simple : a partir d'un GeoDataFrame

```python
from pathlib import Path

import geopandas as gpd

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing import (
    generate_zone_conformal_mesh_from_dataframe,
)

gdf = gpd.read_file("zones.geojson")

result = generate_zone_conformal_mesh_from_dataframe(
    gdf,
    output_path=Path("outputs/zone_mesh.msh"),
    zone_key_column="zone_key",
    global_size=300.0,
    refine_interfaces=True,
    interface_size=120.0,
    interface_distance=450.0,
)

print(result.mesh.n_cells)
print(result.summary["interface_group_count"])
```

### 2. A partir d'une config geologie

```python
from pathlib import Path

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing import (
    generate_zone_conformal_mesh_from_geology_config,
)

result = generate_zone_conformal_mesh_from_geology_config(
    {
        "source": {
            "path": "examples/data/geology/GEO1M.shp",
            "kind": "vector",
            "code_field": "CODE_LEG",
        }
    },
    output_path=Path("outputs/geology_mesh.msh"),
    global_size=500.0,
)
```

### 3. Via le workflow pedagogique de cas de reference

Utiliser :

- `run_reference_2d_zone_conformal_case_from_toml(...)`

Ce runner ajoute :

- resolution de config TOML
- preparation du cas
- sorties PNG / JSON
- reporting plus explicite

### 4. Via le launcher `mesh_catchment`

Le launcher est le point d'entree quand le maillage est produit dans un
workflow complet de bassin versant :

- identification / contexte geographique
- trace hydrographique
- geologie
- maillage
- bundle d'echange

Dans ce cas, `zone_meshing` est le moteur de maillage, pas l'API utilisateur
finale.

## API Publique

### `parse_zone_meshing_settings(config_data)`

Role :
- valider les reglages de maillage

Entree :
- mapping Python ou section TOML deja lue

Sortie :
- `ZoneMeshingSettings`

### `parse_zone_meshing_domain_config(config_data)`

Role :
- valider la definition du domaine effectif

Sortie :
- `ZoneMeshingDomainConfig`

### `load_zone_meshing_domain_payload(...)`

Role :
- charger la geometrie effective du domaine

Sortie :
- `ZoneMeshingDomainPayload`

### `build_zone_conformal_partition_from_dataframe(...)`

Role :
- nettoyer les polygones
- resoudre les recouvrements
- polygoniser la partition finale

Sortie :
- `ZoneConformalPartition`

### `generate_zone_conformal_mesh_from_dataframe(...)`

Role :
- point d'entree principal du maillage conforme

Sortie :
- `ZoneConformalMeshResult`

### `generate_zone_conformal_mesh_from_geology_config(...)`

Role :
- charger la geologie puis lancer le maillage conforme

Sortie :
- `ZoneConformalMeshResult`

## Parametres Publics

La reference pratique la plus importante est celle de
`generate_zone_conformal_mesh_from_dataframe(...)`.

### Parametres obligatoires

| Parametre | Type | Role |
| --- | --- | --- |
| `gdf` | `GeoDataFrame` | Zonation polygonale source |
| `output_path` | `str | Path` | Chemin du mesh `.msh` a ecrire |

### Parametres de zonation

| Parametre | Valeur typique | Role | Bonne pratique |
| --- | --- | --- | --- |
| `zone_key_column` | `"zone_key"` | colonne identifiant la zone | utiliser une cle stable, normalisee et non vide |
| `priority_column` | `None` | priorite si zones qui se recouvrent | n'utiliser que si le recouvrement source est attendu et assume |

### Parametres de domaine

| Parametre | Valeur typique | Role | Bonne pratique |
| --- | --- | --- | --- |
| `domain_geometry` | `None` ou polygon | domaine effectif a mailler | laisser `None` si le domaine doit etre l'union des zones nettoyees |

### Parametres de taille de maille

| Parametre | Valeur typique | Role | Bonne pratique |
| --- | --- | --- | --- |
| `global_size` | `100` a `1000` m | taille de fond | commencer simple avec une valeur grossiere |
| `min_size` | `None` ou `0.3 * global_size` | borne basse | fixer si le raffinement cree des mailles trop petites |
| `max_size` | `None` ou `1.5 * global_size` | borne haute | fixer si le domaine devient trop grossier loin des interfaces |

### Parametres de nettoyage geometrique

| Parametre | Valeur typique | Role | Bonne pratique |
| --- | --- | --- | --- |
| `simplify_tolerance` | `0` a `0.2 * global_size` | simplification geometrique | partir de `0`; augmenter seulement si les contours sont tres bruités |
| `heal_tolerance` | `0` a `0.1 * global_size` | recollement / correction de petits ecarts | rester petit; trop grand peut modifier la topologie |
| `min_polygon_area` | `0` a `global_size^2 / 10` | suppression de micro-polygones | utile sur sources tres fragmentees |

### Parametres de raffinement d'interface

| Parametre | Valeur typique | Role | Bonne pratique |
| --- | --- | --- | --- |
| `refine_interfaces` | `True` / `False` | active le champ de raffinement | tester d'abord sans raffinement pour valider la geometrie |
| `interface_size` | `0.3` a `0.6 * global_size` | taille cible pres des interfaces | doit rester `<= global_size` |
| `interface_distance` | `1` a `3 * global_size` | distance de retour au fond | commencer court puis etendre si besoin |
| `interface_sampling` | `32` a `128` | echantillonnage Gmsh du champ | augmenter si les courbes sont longues et detaillees |

### Parametres d'algorithme Gmsh

| Parametre | Valeur typique | Role | Bonne pratique |
| --- | --- | --- | --- |
| `algorithm` | `"delaunay"` | algorithme 2D Gmsh | garder `delaunay` comme base; `frontal` est utile en repli sur certains cas difficiles |

### Parametres de contraintes lineaires

| Parametre | Type | Role | Bonne pratique |
| --- | --- | --- | --- |
| `linear_constraints` | sequence de `ZoneLinearConstraint` | contraintes explicites | nommer clairement chaque contrainte et eviter les segments quasi degeneres |
| `river_trace` | objet avec `.lines` | raccourci pour injecter les rivieres | preferer `linear_constraints` si plusieurs familles lineaires doivent coexister |

### Parametres de raffinement local avance

| Parametre | Type | Role | Bonne pratique |
| --- | --- | --- | --- |
| `refinement_policy` | `ZoneMeshingRefinementPolicy` | filtre local des familles de raffinement | utile surtout sur grands bassins mixtes geologie + rivieres |
| `refinement_scope_geometry` | geometrie ou `None` | limite spatiale du raffinement | garder le raffinement concentre la ou l'information est importante |
| `regional_size_fields` | sequence de `ZoneRegionalSizeField` | champs de taille regionaux | utiliser pour imposer des mailles plus grosses ou plus fines par sous-zone |

### Parametre de nommage

| Parametre | Valeur typique | Role | Bonne pratique |
| --- | --- | --- | --- |
| `model_name` | `"zone_conformal_mesh"` | nom du modele Gmsh | utile surtout pour le debug et les traces |

## Parametres de `ZoneLinearConstraint`

| Champ | Role | Bonne pratique |
| --- | --- | --- |
| `name` | nom stable de la contrainte | utiliser un prefixe semantique comme `river::trace` |
| `kind` | type logique | ex. `river_trace`, `watershed_boundary` |
| `lines` | segments Shapely | fournir des lignes valides, non vides |
| `participates_in_refinement` | participe ou non au champ | laisser `False` pour les contraintes geometriques que l'on ne veut pas sur-raffiner |

## Parametres de `ZoneRegionalSizeField`

| Champ | Role | Bonne pratique |
| --- | --- | --- |
| `name` | identifiant stable | unique par champ |
| `region_geometry` | zone d'effet | la clipper logiquement au domaine cible |
| `inside_size` | taille cible dans la region | la garder compatible avec `min_size` |
| `outside_size` | taille hors region | utile pour faire varier la resolution de fond |
| `transition_distance` | transition douce | mettre `0` si la rupture nette est acceptable |
| `grid_resolution` | resolution de rasterisation du champ | la choisir plus fine que la taille de maille cible |

## Parametres de politique locale de raffinement

Les familles actuelles sont :

- `river`
- `geology_interface`
- `watershed_boundary`

Parametres principaux :

| Parametre | Role | Bonne pratique |
| --- | --- | --- |
| `enabled` | active la politique | inutile sur petits cas simples |
| `mode` | strategie locale | `grid_local_budget` est le plus robuste sur grands bassins |
| `hotspot.radius` | voisinage d'analyse | le lier a `interface_distance` |
| `hotspot.max_curve_count` | budget de densite locale | abaisser si le reseau devient trop dense |
| `hotspot.min_gap` | ecart minimal inter-familles | utile pour signaler les quasi-superpositions |
| `grid.cell_size` | pas du quadrillage | typiquement proche de `interface_distance / 2` |
| `grid.neighborhood_rings` | taille du voisinage | `1` est une bonne base |
| `grid.enable_exact_gap_check` | active les distances Shapely fines | a eviter sur les plus gros cas si le temps devient prohibitif |

## Bonnes Pratiques

- Commencer par un cas sans raffinement d'interface pour valider la geometrie.
- Introduire ensuite `refine_interfaces=True` avec `interface_size` moderement plus petit que `global_size`.
- Garder `heal_tolerance` bien plus petit que les tailles de maille cibles.
- Ne pas utiliser `simplify_tolerance` tant qu'un vrai bruit geometrique n'est pas observe.
- Sur grands bassins avec geologie + rivieres, preferer `grid_local_budget`.
- Utiliser des noms de contraintes stables et semantiques.
- Lire `result.summary` avant de regarder seulement le `.msh` : c'est souvent le moyen le plus rapide de comprendre pourquoi un cas est difficile.

## UML

Les diagrammes UML proposes pour documenter cette partie sont dans
[UML.md](./UML.md).

Je recommande de maintenir au minimum :

- un diagramme de composants
- un diagramme de classes des contrats publics
- un diagramme de sequence du workflow principal
- un diagramme d'activite du pipeline de maillage

## Pistes De Refactor Plus Profondes

Sans changer les fonctionnalites, les simplifications suivantes restent
pertinentes :

- sortir de `conformal.py` la construction du resume final ;
- isoler completement la logique de groupes physiques dans un module dedie ;
- separer davantage la politique de raffinement en trois blocs :
  candidats, detection, resolution ;
- introduire un petit contexte interne de build pour limiter les gros paquets
  de dictionnaires transitoires ;
- rendre encore plus explicite la difference entre :
  contraintes geometriques,
  champs de raffinement,
  champs de taille regionaux.
