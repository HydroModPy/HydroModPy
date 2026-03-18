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

## Confiance et securite

Le point a comprendre avant diffusion externe est le suivant :

- `distribution/mesh` execute bien le fichier `reader.py` present dans le
  bundle ;
- ce fichier est du code Python, pas un format de donnees passif.

Consequence pratique :

- il faut distribuer seulement des bundles de confiance ;
- le destinataire doit considerer `reader.py` comme du code executable ;
- si le contexte est sensible, il faut preferer une distribution interne, ou
  a minima accompagner le bundle d'un hash ou d'un canal de validation.

## Arborescence du sous-outil

- [models.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/models.py)
  Definit les dataclasses, protocoles et constantes partages.
- [config.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/config.py)
  Lit et valide le TOML.
- [toml_schema.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/toml_schema.py)
  Porte le schema Pydantic du TOML et les descriptions courtes des parametres.
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

## Archive recommandee

Pour une diffusion propre, le plus simple est de preparer une archive avec une
arborescence explicite, par exemple :

```text
mesh_distribution_package/
  hydromodpy_annex/
    distribution/
      mesh/
        README.md
        environment.yml
        run_visualization.py
        config.py
        bundle_loading.py
        models.py
        summary.py
        visualization.py
        workflow.py
        examples/
          config_example.toml
  sample_bundle/
    mesh_2d.msh
    nodes.csv
    cells.csv
    edges.csv
    cell_geology_fractions.csv
    metadata.json
    mesh_summary.json
    reader.py
  config_distribution.toml
```

Fichier `config_distribution.toml` conseille :

```toml
[mesh_distribution]
bundle_dir = "sample_bundle"
figure_output_path = "outputs/apercu_maillage.png"
summary_output_path = "outputs/resume_apercu_maillage.json"
show_window = false

[mesh_distribution.plot]
color_field = "geology_key"
color_map = "tab20"
show_topography_panel = true
```

Contenu recommande de l'archive :

- le dossier `hydromodpy_annex/distribution/mesh` ;
- un ou plusieurs bundles a partager ;
- un TOML deja renseigne pour le ou les bundles fournis ;
- eventuellement un court `README_distribution.md` specifique au cas livre.

Contenu a ne pas inclure dans l'archive :

- l'ensemble du depot HydroModPy si seul le viewer est necessaire ;
- des dossiers `outputs/` deja generes, sauf si vous voulez aussi livrer les
  figures comme reference ;
- des dossiers temporaires, caches Python ou artefacts de test ;
- des bundles non verifies ou obsoletes qui risqueraient de creer de la
  confusion.

Convention pratique recommandee :

- un bundle par dossier ;
- un TOML par bundle si les reglages de rendu changent ;
- un nom d'archive qui porte a la fois le nom du bassin et une date ou version,
  par exemple `mesh_nancon_bundle_2026-03-18.zip`.

## Structure detaillee du bundle

Le bundle exporte par HydroModPy est un dossier autonome, en general nomme
`<nom_du_maillage>_bundle`, place a cote du fichier `.msh`.

Exemple d'arborescence :

```text
mesh_catchment_outlet_5_bundle/
  mesh_2d.msh
  nodes.csv
  cells.csv
  edges.csv
  cell_geology_fractions.csv
  metadata.json
  mesh_summary.json
  reader.py
  README.md
```

Conventions generales :

- tous les index de noeuds, cellules et aretes sont en base 0 ;
- les coordonnees sont exprimees dans le SCR indique dans `metadata.json` ;
- une cellule vide dans un CSV signifie "valeur non disponible" ;
- `mesh_summary.json` est optionnel ;
- `reader.py` est le lecteur de reference du bundle distribue.

### `mesh_2d.msh`

Ce fichier contient le maillage 2D Gmsh original.

Il porte :

- la geometrie nodale du maillage ;
- la connectivite des elements ;
- les groupes physiques Gmsh eventuellement presents.

Il ne porte pas directement les champs tabulaires pedagogiques utilises par
`distribution/mesh`. Ceux-ci sont dans les CSV.

### `nodes.csv`

Ce fichier contient un enregistrement par noeud.

Colonnes :

- `node_id` : identifiant du noeud ;
- `x` : coordonnee X ;
- `y` : coordonnee Y ;
- `z_top` : altitude topographique au noeud, si disponible.

Usage principal :

- reconstruction simple des positions des noeuds ;
- rendu topographique par interpolation ou coloration nodale.

### `cells.csv`

Ce fichier contient un enregistrement par cellule du maillage.

Colonnes de structure :

- `cell_id` : identifiant de cellule ;
- `geom_type` : type geometrique, par exemple `triangle` ;
- `n0`, `n1`, `n2`, `n3` : indices des noeuds de la cellule ;
- `centroid_x` : abscisse du centroide ;
- `centroid_y` : ordonnee du centroide ;
- `area_m2` : surface de la cellule en metres carres.

Colonnes topographiques :

- `z_top_centroid` : altitude topographique au centroide ;
- `z_top_mean` : altitude topographique moyenne sur les noeuds de la cellule.

Colonnes geologiques :

- `geology_code` : code geologique dominant de la cellule ;
- `geology_key` : cle geologique dominante normalisee.

Colonnes hydrauliques optionnelles :

- `hydraulic_conductivity_m_s` : conductivite hydraulique exportee en `m/s` ;
- `storage_coefficient` : coefficient d'emmagasinement exporte sans unite.

Important :

- `geology_code` et `geology_key` correspondent a l'unite dominante ;
- si une cellule recoupe plusieurs unites geologiques, le detail complet est
  donne dans `cell_geology_fractions.csv` ;
- les champs hydrauliques sont calcules a partir de ces fractions geologiques
  quand une table de correspondance a ete fournie au moment de l'export.

### `edges.csv`

Ce fichier contient un enregistrement par arete unique du maillage.

Colonnes :

- `edge_id` : identifiant de l'arete ;
- `node_a` : premier noeud ;
- `node_b` : second noeud ;
- `cell_a` : premiere cellule adjacente ;
- `cell_b` : seconde cellule adjacente, vide pour une arete de bord ;
- `length_m` : longueur de l'arete ;
- `edge_kind` : type d'arete ;
- `is_river` : indicateur booleen pour les aretes reconnues comme rivieres ;
- `geology_a_key` : unite geologique du cote `cell_a` ;
- `geology_b_key` : unite geologique du cote `cell_b`.

Valeurs usuelles de `edge_kind` :

- `boundary` : arete de bord externe ;
- `internal` : arete interne standard ;
- `geology_interface` : arete entre deux unites geologiques distinctes.

### `cell_geology_fractions.csv`

Ce fichier contient la decomposition geologique de chaque cellule.

Colonnes :

- `cell_id` : identifiant de cellule ;
- `geology_key` : cle geologique ;
- `fraction` : fraction surfacique de cette unite dans la cellule.

Ce fichier est essentiel quand on veut :

- reconstituer des maillages heterogenes plus finement que par la seule unite dominante ;
- verifier le melange geologique local ;
- comprendre comment une propriete hydraulique par maille a ete calculee.

### `metadata.json`

Ce fichier documente le contrat global du bundle.

Champs racine typiques :

- `bundle_schema_version` : version du schema du bundle ;
- `mesh_kind` : type logique du maillage ;
- `cell_type` : type d'element dominant ;
- `indexing` : convention d'indexation, actuellement `zero_based` ;
- `crs` : systeme de coordonnees ;
- `n_nodes` : nombre de noeuds ;
- `n_cells` : nombre de cellules ;
- `constraints_mode` : mode de conformite du maillage ;
- `topography` : description des champs topographiques exportes ;
- `geology` : description de la geologie exportee ;
- `hydraulic_properties` : description des proprietes hydrauliques exportees ;
- `files` : noms attendus des fichiers du bundle ;
- `source_mesh_path` : chemin du maillage source au moment de l'export.

Sous-structure `topography` :

- `node_field` : nom du champ nodal topographique ;
- `cell_fields` : liste des champs topographiques par cellule ;
- `source_path` : chemin du raster topographique source.

Sous-structure `geology` :

- `available` : geologie exportee ou non ;
- `field_id` : identifiant logique du champ geologique ;
- `source_kind` : nature de la source geologique ;
- `cell_samples_per_axis` : densite d'echantillonnage utilisee ;
- `zone_keys` : liste des cles geologiques presentes.

Sous-structure `hydraulic_properties` :

- `available` : proprietes hydrauliques exportees ou non ;
- `averaging` : mode d'agregation, actuellement par fractions geologiques ;
- `cell_fields` : champs hydrauliques disponibles dans `cells.csv` ;
- `conductivity` : source et couverture de `hydraulic_conductivity_m_s` ;
- `storage_coefficient` : source et couverture de `storage_coefficient`.

Cette partie est la reference a lire en premier pour savoir si un bundle
contient effectivement de la geologie, de la topographie ou des proprietes
hydrauliques.

### `mesh_summary.json`

Ce fichier est une copie du resume de generation du maillage, quand il existe.

Il n'est pas indispensable a la lecture du bundle, mais il est utile pour :

- relire les metriques QA du maillage ;
- retrouver le mode de generation ;
- tracer l'origine exacte du bundle.

Le code de `distribution/mesh` peut le charger pour enrichir le resume final,
mais il doit rester possible de travailler sans lui.

### `reader.py`

Ce fichier est le lecteur autonome distribue avec le bundle.

Il definit en general :

- les dataclasses `CatchmentMeshBundleNode`, `CatchmentMeshBundleCell`,
  `CatchmentMeshBundleEdge` et `CatchmentMeshBundleGeologyFraction` ;
- la fonction `load_catchment_mesh_bundle(...)`.

`distribution/mesh` charge dynamiquement ce fichier au lieu d'importer le
lecteur interne HydroModPy. Cela permet de figer la compatibilite de lecture
au niveau du bundle lui-meme.

### `README.md`

Ce fichier peut etre genere dans le bundle pour rappeler :

- la liste des fichiers ;
- les conventions d'indexation ;
- la presence ou non de geologie et de proprietes hydrauliques.

Il joue surtout un role de documentation rapide cote donnees distribuees.

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

Depuis le dossier distribue contenant ce sous-outil :

```bash
cd hydromodpy_annex/distribution/mesh
conda env create -f environment.yml
conda activate hydromodpy-distribution-mesh
```

L'environnement est volontairement minimal. Il couvre seulement ce qui est
necessaire pour :

- executer Python ;
- lire le TOML avec la bibliotheque standard ;
- valider le TOML via le schema Pydantic ;
- construire les figures matplotlib.

Si vous travaillez encore depuis le depot HydroModPy, la commande equivalente
depuis la racine reste valide :

```bash
conda env create -f hydromodpy_annex/distribution/mesh/environment.yml
conda activate hydromodpy-distribution-mesh
```

## Lancement

Commande standard depuis le dossier distribue :

```bash
cd hydromodpy_annex/distribution/mesh
python run_visualization.py --config examples/config_example.toml
```

Commande equivalente depuis la racine du depot :

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
bundle_dir = "../sample_bundle"
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

Les commentaires fournis dans les TOML d'exemple sont alignes sur les
descriptions du schema Pydantic defini dans
[toml_schema.py](/c:/codes/HydroModPy-GH/hydromodpy_annex/distribution/mesh/toml_schema.py).

## Champs disponibles

Pour `color_field` :

- `geology_key`
- `geology_code`
- `area_m2`
- `z_top_mean`
- `z_top_centroid`
- `hydraulic_conductivity_m_s`
- `storage_coefficient`

Note :

- certains bundles plus anciens ne portent pas encore les champs hydrauliques ;
- dans ce cas, le viewer affiche un fond neutre au lieu de planter ;
- le resume JSON signale alors une couverture hydraulique nulle.

Pour `topography_field` :

- `z_top_mean`
- `z_top_centroid`

## Resume JSON produit

Le resume ecrit par l'outil utilise des cles en anglais, par exemple :

- `node_count`
- `cell_count`
- `edge_count`
- `geology_available`
- `hydraulic_properties_available`
- `hydraulic_conductivity_cell_count`
- `storage_coefficient_cell_count`
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
