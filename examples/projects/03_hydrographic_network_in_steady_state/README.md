# 03 - Hydrographic network in steady state

Bassin du Canut (Bretagne, EPSG:2154) extrait du MNT régional 75 m par
accrochage d'exutoire. Écoulement souterrain **stationnaire**, aquifère à
cinq couches, résolu avec **MODFLOW 6**. Le réseau hydrographique est
délimité depuis le MNT et le **réseau actif simulé** (mailles où la nappe
alimente un drain) est rendu par-dessus.

C'est le cas « comment le réseau pérenne émerge de la nappe » : en faisant
varier K on voit le réseau actif grandir ou se réduire.

## Lancer

```bash
hmp run examples/projects/03_hydrographic_network_in_steady_state/project.toml

# balayage en K (le cœur de l'exemple), via l'API Python
python examples/projects/03_hydrographic_network_in_steady_state/run_manual.py

hmp viz gallery examples/projects/03_hydrographic_network_in_steady_state/project.toml
```

Durée : environ 2 s pour un run (bassin ~9300 mailles, 5 couches).

## Données

Toutes partagées sous `examples/data/`, résolues par nom de fichier :

| Fichier | Famille | Rôle |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | MNT régional 75 m (couvre le Canut) |
| recharge synthétique | recharge | recharge moyenne stationnaire, 1.2 mm/j |

Le réseau est **délimité depuis le MNT** (`geographic.river_network`),
sans donnée externe. La référence BD Topage du Canut n'est pas dans le tree
partagé, donc les figures de comparaison à une référence ne sont pas
activées ici (le réseau généré et le réseau actif simulé le sont).

## Figures

| Figure | Ce qu'elle montre |
|---|---|
| `watershed_id_card` | carte d'identité du bassin |
| `mesh_map` | grille du solveur colorée par la topographie |
| `piezometric_map` | altitude de la nappe |
| `watertable_depth_map` | profondeur de nappe + suintement |
| `seepage_map` | zones de suintement |
| `hydrographic_network_generated` | réseau délimité depuis le MNT |
| `simulated_active_network` | mailles drainantes actives (le réseau pérenne simulé) |
| `cross_section` | coupe topographie / nappe / 5 couches |
| `water_budget` | bilan par composante |

## Le balayage en K

`run_manual.py` fait varier K de 1e-7 à 1e-4 m/s. Le nombre de mailles
drainantes actives chute quand K augmente (un aquifère plus transmissif
abaisse la nappe, donc moins de mailles alimentent un drain) :

| K (m/s) | mailles actives |
|---|---|
| 1e-7 | ~9300 |
| 1e-6 | ~7700 |
| 1e-5 | ~990 |
| 1e-4 | ~170 |

Chaque K est une simulation distincte obtenue par un seul override de
paramètre (`project.simulate(name=..., K=k)`) ; aucune figure n'est codée
dans le `.py`, ce sont les figures nommées du registre via `hmp.figure`.

## Basculer vers MODFLOW-NWT

Remplacer le solveur et le préfixe de section :

```toml
[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]

[modflownwt.sgrid.planar]
mode = "keep_native"

[modflownwt.sgrid.vertical]
nlay = 5
```
