# 02 - Basic features and overview of possibilities

Petit bassin conceptuel de démonstration, délimité depuis son exutoire sur
un MNT de teaching, résolu en **régime stationnaire** avec **MODFLOW 6**.
C'est le cas « toute la chaîne sur un domaine jouet », entièrement
hors-ligne, qui exerce l'ensemble des figures standard.

## Lancer

```bash
hmp run examples/projects/02_basic_features_and_overview_of_possibilities/project.toml

# run + inspection + figures, via l'API Python
python examples/projects/02_basic_features_and_overview_of_possibilities/run_manual.py

hmp viz gallery examples/projects/02_basic_features_and_overview_of_possibilities/project.toml
```

Durée : moins de 1 s (bassin conceptuel ~60 mailles).

## Données

| Fichier | Famille | Rôle |
|---|---|---|
| `dem/conceptual_dem.tif` | dem | MNT conceptuel 75 m (topographie de teaching) |
| recharge synthétique | recharge | recharge moyenne stationnaire, 1.5 mm/j |

## Les cas de recharge

Pour explorer les scénarios sec / normal / humide, changer la valeur
`values` de `[[data.recharge.sources]]` dans `project.toml` et relancer :
une recharge plus forte remonte la nappe, donc plus de mailles affleurent en
suintement.

## Figures

| Figure | Ce qu'elle montre |
|---|---|
| `mesh_map` | grille du solveur |
| `recharge_map` | recharge par maille |
| `piezometric_map` | altitude de la nappe |
| `watertable_depth_map` | profondeur de nappe + suintement |
| `seepage_map` | zones de suintement |
| `cross_section` | coupe topographie / nappe / base d'aquifère |
| `water_budget` | bilan par composante (recharge = drainage en stationnaire) |

## Modes de définition du domaine

Le script legacy montrait quatre façons de définir un bassin. Elles existent
toutes en v1, via `[geographic.catchment].catch_def` :

| Mode | `catch_def` | Exemple |
|---|---|---|
| depuis un exutoire | `from_outlet_coord` | ici, 00, 01, 03, 04 |
| depuis un polygone | `from_polyg_shp` | - |
| grille XYZ texte | `txt` | - |
| domaine analytique | `source_mode = "synthetic"` | 00_getting_started |

## Dette technique

- Le mode `catch_def = "dem"` (le MNT EST le domaine, sans délimitation) ne
  masque pas le nodata du raster : les cellules nodata entrent dans le
  domaine actif et ruinent les figures. On délimite donc depuis l'exutoire,
  qui masque proprement. Un masquage nodata en mode `dem` serait le correctif.
- Un balayage de scénarios dans un même process Python bute sur la connexion
  DuckDB (`hmp.run` rouvre le catalogue à chaque appel). Le pattern propre
  multi-run est `hmp.Project` + `project.simulate(...)` (voir l'exemple 03),
  qui ne surcharge que les paramètres flow ; varier la recharge se fait donc
  en éditant le TOML.
