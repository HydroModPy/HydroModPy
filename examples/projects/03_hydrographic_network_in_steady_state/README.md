# 03 - Hydrographic network in steady state

Bassin du Canut (Bretagne, EPSG:2154) extrait du MNT régional 75 m par
accrochage d'exutoire. Écoulement souterrain **stationnaire** dans un
aquifère de 50 m découpé en **cinq couches**, résolu avec **MODFLOW 6**.

Trois réseaux sont mis côte à côte :

- le réseau **observé**, BD Topage (`reference`) ;
- le réseau **délimité depuis le MNT** par accumulation de flux (`generated`) ;
- le réseau **actif simulé**, les mailles que la nappe alimente
  (`simulated_active`).

C'est le cas « comment le réseau pérenne émerge de la nappe » : en faisant
varier K, le réseau actif passe de tout le bassin à quelques mailles de fond
de vallée.

## Lancer

```bash
# le run de référence et sa galerie de figures
hmp run examples/projects/03_hydrographic_network_in_steady_state/project.toml

# le balayage en K, le cœur de l'exemple, via l'API Python
python examples/projects/03_hydrographic_network_in_steady_state/run_manual.py

# régénérer la galerie d'un run sans le rejouer
hmp viz gallery examples/projects/03_hydrographic_network_in_steady_state/project.toml
```

Durée : environ 25 s pour le run de référence (bassin ~9300 mailles, 5 couches),
environ 70 s pour les 10 runs du balayage.

## Données

Toutes partagées sous `examples/data/`, résolues par nom de fichier :

| Source | Famille | Rôle |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | MNT régional 75 m (couvre le Canut) |
| `geology/GEO1M.shp` (`CODE_LEG`) | geology | carte géologique BRGM 1/1 000 000, contexte |
| BD Topage, provider `bdtopage` | hydrography | réseau observé, rôle `reference` |
| recharge synthétique | recharge | climatologie mensuelle, moyenne 1.17 mm/j |

La géologie est déclarée dans `[domain] zone_ids` pour être cartographiée,
mais aucun paramètre n'est zoné dessus : K reste homogène, ce qui est la
condition du balayage.

L'ancien script chargeait aussi les stations hydrométriques et les stations
ONDE en décor de carte. Elles ne sont pas reprises ici : le tree partagé n'a
pas de chronique dans le bassin du Canut, donc `[data.hydrometry]` et
`[data.intermittency]` se chargeraient sans rien produire. Les exemples 04 et
05 sont ceux qui montrent l'inventaire de stations.

## Figures de la galerie

| Figure | Ce qu'elle montre |
|---|---|
| `watershed_id_card` | carte d'identité du bassin |
| `mesh_map` | grille du solveur colorée par la topographie |
| `piezometric_map` | altitude de la nappe |
| `watertable_depth_map` | profondeur de nappe |
| `seepage_map` | zones de suintement |
| `hydrographic_network_reference` | réseau observé BD Topage |
| `hydrographic_network_generated` | réseau délimité depuis le MNT |
| `hydrographic_network_comparison` | observé contre délimité, avec les métriques |
| `simulated_active_network` | mailles drainantes actives |
| `simulated_active_network_reference_overlay` | réseau actif simulé sur le réseau observé |
| `accumulation_map` | flux de drainage accumulé |
| `cross_section` | coupe topographie / nappe / 5 couches |
| `water_budget` | bilan par composante |

## Le balayage en K

`run_manual.py` fait varier K sur cinq décades, de 1e-8 à 1e-3 m/s en dix
valeurs log-espacées, une simulation par valeur. La densité de drainage
active, part des mailles du bassin dont le flux de drain routé est positif,
s'effondre quand K augmente : un aquifère plus transmissif abaisse la nappe,
donc moins de mailles alimentent un drain.

| K (m/s) | densité de drainage (%) | suintement (%) | débit de base (m3/s) |
|---|---|---|---|
| 1.0e-08 | 100 | 100 | 0.337 |
| 4.6e-07 | 95.3 | 93.3 | 0.337 |
| 1.7e-06 | 57.9 | 49.5 | 0.343 |
| 6.0e-06 | 16.1 | 14.3 | 0.344 |
| 2.2e-05 | 5.3 | 4.8 | 0.314 |
| 1.0e-03 | 0.2 | 0.2 | 0.000 |

La colonne débit de base n'est pas tracée, elle n'est que dans le CSV : tant
que la nappe affleure il est imposé par la recharge, au delà de 1e-5 m/s
l'aquifère évacue le flux en souterrain et il chute avec le réseau.

Le script écrit trois figures propres à l'exemple sous
`share/hydraulic_conductivity_sweep/`, plus le tableau ci-dessus en CSV :

| Figure | Ce qu'elle montre |
|---|---|
| `sweep_active_network.png` | une carte par K, réseau observé par dessus |
| `sweep_water_table.png` | une nappe par K sur une même coupe ouest-est |
| `sweep_drainage_density.png` | densité de drainage et suintement contre K |

Il sert aussi de point d'entrée à l'API Python : ouvrir un projet, lancer
plusieurs simulations avec un override de paramètre, relire un champ, une
vue dérivée et un bilan, et rendre une figure du registre. Tout y passe par
les commandes publiques, sans chemin construit à la main.

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
genmtd_lay = "constant"
nlay = 5
```
