# 05 - Piezometry in a coastal aquifer

Bande côtière de Gouville (Normandie, EPSG:2154). Le domaine est un polygone
(`model_area`) sur un MNT côtier 25 m. Écoulement souterrain **stationnaire**
résolu avec **MODFLOW 6**, avec une **frontière marine** : toute maille dont
la surface est sous le niveau marin moyen est maintenue à ce niveau (charge
imposée). La nappe descend donc de la butte de recharge intérieure vers le
rivage.

## Lancer

```bash
hmp run examples/projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/project.toml

# gradient côtier de la nappe, via l'API Python
python examples/projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/run_manual.py

hmp viz gallery examples/projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/project.toml
```

Durée : environ 1 s (bande côtière ~5200 mailles à 25 m).

## Données

| Fichier | Famille | Rôle |
|---|---|---|
| `dem/DEM_gouville_25m.tif` | dem | MNT côtier 25 m (NGF ; la mer est sous 0 m) |
| `watershed_polygon/gouville_model_area.shp` | polygone | emprise du modèle côtier |
| recharge synthétique | recharge | recharge moyenne stationnaire, 1.0 mm/j |

## La frontière marine

La BC `ocean` applique une charge constante au niveau marin (`value = "0 m"`
NGF) sur toutes les mailles dont le MNT est sous ce seuil. Aucun trait de
côte n'est requis : le MNT côtier suffit, la mer est identifiée par
l'altitude. Le résultat (voir `piezometric_map`) est la forme côtière
classique de la nappe : 0 m au rivage, remontant vers l'intérieur (~16 m ici).

## Figures

| Figure | Ce qu'elle montre |
|---|---|
| `mesh_map` | grille du solveur |
| `piezometric_map` | altitude de la nappe (0 au rivage, remontant à l'intérieur) |
| `watertable_depth_map` | profondeur de nappe + suintement |
| `seepage_map` | zones de suintement (dont la frange littorale) |
| `cross_section` | coupe ouest-est de la mer vers l'aquifère |
| `water_budget` | bilan par composante (recharge vs mer + drainage) |

## Non porté depuis le script legacy

Le cas legacy avait plusieurs raffinements que ce portage laisse de côté
pour un premier cas côtier propre, et qui sont la dette naturelle :

- **Conductivité hétérogène par zones** (`param_zones.shp`) : ici K est
  homogène. La v1 gère l'hétérogène par support spatial + table de valeurs,
  mais le câblage zones-shapefile -> champ K reste à faire proprement.
- **Comparaison à la piézométrie observée** : le cas d'origine calait sur
  des piézomètres. Les données et les figures sim/obs existent (voir la
  famille `piezometry` et `piezo_timeseries_sim_obs`), mais le calage côtier
  n'est pas monté ici.
- **Dynamique de marée** : la BC marine est fixée au niveau moyen (0 m). Une
  série temporelle de marée (`[flow.bc.dirichlet.ocean.forcing]`) et un run
  transitoire donneraient la respiration tidale de la nappe.
- **MNT 5 m** : le portage utilise le 25 m ; le 5 m affine le littoral.
