# Distribution pedagogique des maillages

Ce sous-repertoire contient une brique autonome pour relire un bundle de
maillage HydroModPy et produire des sorties simples a partager.

Le mot important ici est `autonome` :

- on ne recalcule pas le maillage ;
- on ne depend pas du package `hydromodpy` complet pour la relecture ;
- on utilise le `reader.py` distribue dans chaque bundle comme lecteur local.

L'objectif pratique est de pouvoir envoyer :

- un dossier de donnees de maillage ;
- un petit bloc de code de lecture/visualisation ;
- un fichier TOML clair ;

et de permettre a un tiers de recharger le maillage, comprendre sa structure
et produire une figure sans connaitre le reste du depot.

## Idee generale

Le workflow est volontairement lineaire :

1. lire un fichier TOML ;
2. localiser le dossier bundle ;
3. charger dynamiquement le fichier `reader.py` contenu dans ce bundle ;
4. reconstruire en memoire une structure de maillage ;
5. produire une figure pedagogique ;
6. ecrire un resume JSON compact.

Cette organisation separe nettement :

- la lecture des donnees ;
- la fabrication des figures ;
- l'orchestration de bout en bout.

## Pourquoi utiliser `reader.py` du bundle

Le choix le plus important de cette brique est celui-ci :

- `distribution/mesh` ne va pas importer directement le lecteur interne
  HydroModPy ;
- il charge le `reader.py` present dans le bundle a distribuer.

Ce choix apporte plusieurs avantages :

- le lecteur voyage avec les donnees ;
- un bundle reste lisible meme hors depot HydroModPy ;
- l'environnement d'installation devient tres leger ;
- on fige explicitement le contrat de lecture associe a chaque export.

Autrement dit, ce code de distribution depend d'abord du bundle lui-meme,
pas de l'arborescence complete du projet source.

## Arborescence du sous-outil

- [models.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/models.py)
  Definit les dataclasses, protocoles et constantes partages.
- [config.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/config.py)
  Lit et valide le TOML.
- [bundle_loading.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/bundle_loading.py)
  Charge `reader.py` du bundle et reconstruit l'objet de travail.
- [summary.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/summary.py)
  Construit le resume JSON compact.
- [visualization.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/visualization.py)
  Construit les objets matplotlib et assemble la figure finale.
- [workflow.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/workflow.py)
  Orchestre l'execution complete.
- [run_visualization.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/run_visualization.py)
  Fournit le point d'entree en ligne de commande.
- [examples/config_example.toml](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/examples/config_example.toml)
  Exemple de configuration a adapter a un bundle reel.
- [environment.yml](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/environment.yml)
  Environnement conda minimal pour cette brique.

## Ce qu'il faut distribuer

Pour relire un maillage avec cette brique, il faut au minimum :

1. le dossier `hydromodpy_annex/distribution/mesh`
2. le dossier bundle du maillage

Le bundle doit contenir typiquement :

- `mesh_2d.msh`
- `nodes.csv`
- `cells.csv`
- `edges.csv`
- `cell_geology_fractions.csv`
- `metadata.json`
- `mesh_summary.json`
- `reader.py`

Le fichier `reader.py` est obligatoire dans cette logique de distribution,
car c'est lui qui sait reconstruire en memoire les classes Python du bundle.

## Que contient l'objet relu en memoire

Le point d'entree principal cote lecture est
[load_visualization_data](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/bundle_loading.py).

Cette fonction retourne un objet
[MeshVisualizationData](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/models.py)
qui regroupe :

- `config` : les parametres du TOML, deja valides ;
- `mesh` : l'objet bundle reconstruit par `reader.py`.

Le code de visualisation n'impose pas une classe HydroModPy concrete. Il attend
simplement un objet compatible avec l'interface documentee dans `models.py`
via les protocoles :

- `MeshBundleLike`
- `MeshNodeLike`
- `MeshCellLike`
- `MeshEdgeLike`
- `GeologyFractionLike`

Cela rend la brique plus robuste pour un usage de distribution.

## Sorties produites

Selon la configuration, le module peut produire :

- une figure PNG avec un ou deux panneaux ;
- un resume JSON compact et lisible ;
- une fenetre matplotlib interactive si l'option est activee.

Par defaut, la figure contient :

- a gauche : une vue structurelle du maillage ;
- a droite : une vue topographique type MNT.

Le panneau topographique utilise d'abord les altitudes nodales `z_top`.
Si ces altitudes ne sont pas disponibles de maniere exploitable sur les noeuds,
le code se replie automatiquement sur un rendu par cellule avec
`z_top_mean` ou `z_top_centroid`.

## Installation

Depuis la racine du depot :

```bash
conda env create -f hydromodpy_annex/distribution/mesh/environment.yml
conda activate hydromodpy-distribution-mesh
```

L'environnement est volontairement minimal. Il couvre seulement ce qui est
necessaire pour :

- executer Python ;
- lire le TOML avec la bibliotheque standard ;
- construire les figures matplotlib.

## Lancement

Commande standard :

```bash
python hydromodpy_annex/distribution/mesh/run_visualization.py --config hydromodpy_annex/distribution/mesh/examples/config_example.toml
```

La commande :

1. charge le TOML ;
2. recharge le bundle cible ;
3. ecrit la figure si `figure_output_path` est renseigne ;
4. ecrit le resume JSON si `summary_output_path` est renseigne ;
5. affiche le resume sur la sortie standard.

## Structure du TOML

Exemple minimal :

```toml
[mesh_distribution]
bundle_dir = "C:/results/HydromodPy/mesh_catchment_bretagne_outlet_34/results_stable/mesh/gmsh/mesh_catchment_outlet_34_bundle"
figure_output_path = "outputs/apercu_maillage.png"
summary_output_path = "outputs/resume_apercu_maillage.json"
show_window = false

[mesh_distribution.plot]
color_field = "geology_key"
color_map = "tab20"
figure_size = [16.0, 8.0]
dpi = 170
show_topography_panel = true
topography_field = "z_top_mean"
topography_cmap = "terrain"
show_mesh_edges = true
show_boundaries = true
show_geology_interfaces = true
show_river_edges = true
annotate_cell_ids = false
```

Les fichiers TOML doivent utiliser uniquement les noms anglais du contrat
courant.

## Champs disponibles

Pour `color_field` :

- `geology_key`
- `geology_code`
- `area_m2`
- `z_top_mean`
- `z_top_centroid`

Pour `topography_field` :

- `z_top_mean`
- `z_top_centroid`

## Resume JSON produit

Le resume ecrit par l'outil utilise des cles en anglais, par exemple :

- `node_count`
- `cell_count`
- `edge_count`
- `geology_available`
- `topography_render_mode`

L'objectif est d'avoir une API de distribution coherente avec des identifiants
de code eux aussi en anglais.

## Limites actuelles et evolution souhaitable

### Contour du bassin versant

Oui, il est pertinent d'ajouter le contour du bassin versant sur les deux
panneaux. En revanche, cette information n'est pas encore fournie par les
donnees exportees utilisees ici.

La strategie propre serait la suivante :

1. faire exporter le contour amont, par exemple en `contour_bassin.geojson`
2. enregistrer ce fichier, ou sa reference, dans le bundle
3. le charger dans `bundle_loading.py`
4. le superposer dans `visualization.py`

La modification locale est donc simple, mais elle depend d'abord d'une
evolution du code qui produit les donnees du bundle.
