# 01 - Simplified example presented in the paper

Bassin du Canut (Bretagne, EPSG:2154) extrait du MNT régional 75 m par
accrochage d'exutoire. Écoulement souterrain **stationnaire**, cinq couches
qui s'épaississent avec la profondeur, conductivité hydraulique et
emmagasinement **décroissant exponentiellement avec la profondeur**, résolu
avec **MODFLOW 6**, suivi d'un suivi de particules.

C'est le fil conducteur du papier : délimitation, aquifère stratifié avec
profil de profondeur, et trajectoires de temps de résidence.

## Lancer

```bash
hmp run examples/projects/01_simplified_example_presented_in_the_paper/project.toml

# temps de résidence depuis les trajectoires, via l'API Python
python examples/projects/01_simplified_example_presented_in_the_paper/run_manual.py

hmp viz gallery examples/projects/01_simplified_example_presented_in_the_paper/project.toml
```

Durée : environ 4 s (bassin ~9300 mailles, 5 couches, 300 particules).

## Données

| Fichier | Famille | Rôle |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | MNT régional 75 m (couvre le Canut) |
| recharge synthétique | recharge | recharge moyenne stationnaire, 0.96 mm/j (350 mm/an) |

## Profil de profondeur

La conductivité de surface (2e-5 m/s) décroît en `exp(-profondeur / 20 m)` :
environ la moitié à 14 m, un plancher à 1e-3 de la valeur de surface. C'est
la signature d'un aquifère de socle fracturé (zone altérée conductrice en
surface, socle sain imperméable en profondeur). Exprimé par
`[flow.param.K.field_vertical_profile]` mode `exponential`.

## Figures

| Figure | Ce qu'elle montre |
|---|---|
| `watershed_id_card` | carte d'identité du bassin |
| `mesh_map` | grille du solveur colorée par la topographie |
| `piezometric_map` | altitude de la nappe |
| `watertable_depth_map` | profondeur de nappe + suintement |
| `seepage_map` | zones de suintement |
| `particle_tracks` | trajectoires colorées par temps de transit |
| `cross_section` | coupe topographie / nappe / 5 couches épaississantes |
| `simulated_active_network` | mailles drainantes actives |
| `water_budget` | bilan par composante |

## Suivi de particules : forward

MODFLOW 6 PRT ne suit les particules que vers l'aval : elles sont relâchées
sur le domaine et se terminent là où la nappe affleure, ce qui donne les
temps de résidence recharge -> suintement. Le script legacy faisait du
backward depuis les zones de suintement ; voir l'exemple 00 pour la bascule
vers NWT + MODPATH si le backward est nécessaire.

`run_manual.py` lit les trajectoires et résume la distribution des temps de
résidence (médiane ~1 an, p90 ~7 ans sur ce jeu de paramètres).

## Non porté depuis le script legacy

La visualisation 3D interactive et la coupe cliquable du script d'origine
sont par nature interactives ; elles ne font pas partie des figures
statiques du registre. La signature de débit observée (Q/A interannuel) et
les cartes de géologie relèvent du workflow `overview` (voir les exemples
04 et 05 de données).
