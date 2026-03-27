# Note d'integration du maillage Gmsh

Statut : note de travail vivante.

Une partie importante des propositions historiques ci-dessous est maintenant
implantee dans le depot. Cette note reste utile comme trace de conception,
mais elle ne doit plus etre lue comme une description exacte, ligne a ligne,
de l'arborescence courante.

## Objectif

Introduire un backend de maillage planaire base sur Gmsh qui puisse etre
utilise a cote du workflow cartesien actuel pour :

- la preparation
- les figures
- le post-traitement hors solveur

La premiere cible n'est **pas** l'integration solveur. Le workflow solveur
structure doit rester inchange dans la premiere iteration.

## Pourquoi cette note existe

Le depot contient deja :

- un workflow de grille structuree oriente solveur dans
  `hydromodpy/solver/utils/mesh/cartesian_grid/`
- un contrat de maillage planaire generique dans
  `hydromodpy/field/core/field_mesh.py`
- une logique de discretisation champ/support qui depend du maillage dans
  `hydromodpy/domain/spatial_support.py`

Le travail autour de Gmsh doit reutiliser ce contrat de maillage generique
existant plutot que de creer une troisieme abstraction parallele.

## Etat actuel du code

### Mise a jour de statut

Au moment de cette mise a jour, les briques suivantes existent deja dans le
code :

- un maillage planaire Gmsh 2D concret avec pont vers `HydroMesh`
- une extrusion prismatique 3D reutilisable hors solveur
- une discretisation `Field` / `FieldParam` sur ces maillages 2D et 3D
- un workflow de maillage conforme aux zones geologiques et aux rivieres
- un launcher `mesh-catchment` mono-catchment et batch
- un export de bundle externe pour reutilisation hors HydroModPy
- des cas de reference et des tests de non-regression 2D et 3D

En revanche, deux limites structurantes restent ouvertes :

- le couplage solveur non structure n'est toujours pas la cible de cette note
- la geometrie verticale reste basee sur des interfaces `z` globales, sans
  `top` / `bottom` variables cellule par cellule ni pinchout

Convention pratique a garder :

- les fichiers sous `cases/*/outputs/` ne doivent rester versionnes que s'ils
  jouent le role d'actifs de reference pour les cas ou les tests
- les dossiers `scratch_tests/` et autres sorties de runtime locale ne doivent
  pas etre suivis dans Git

### Le chemin solveur structure est volontairement specifique

`hydromodpy/solver/utils/mesh/cartesian_grid/` est aujourd'hui lie au chemin
solveur structure :

- `sgrid_config.py` ne valide que `sgrid_type = "structured"`
- `sgrid_generation.py` construit un `flopy.discretization.StructuredGrid`
- `sgrid_fieldparam_discretization.py` suppose une sortie structuree
  `(nlay, nrow, ncol)`
- `solver/modflow_nwt/modflow/property_mapping.py` consomme ce chemin structure

Cela fait de `cartesian_grid` un mauvais emplacement pour une interface commune
hors solveur.

### Un contrat de maillage generique existe deja

`hydromodpy/field/core/field_mesh.py` fournit deja les pieces principales
necessaires a une API commune hors solveur :

- `MeshCell`
- `MeshWithValues`
- `BaseFieldMesh`
- `FieldMesh`

Les methodes importantes pour l'interchangeabilite sont deja definies :

- `iter_cells()`
- `cell_centroids()`
- `to_cell_values()`
- `plot_cell_values()`
- `attach_cell_values()`

Pour l'usage actuel vis-a-vis de `Field` et `FieldParam`, ce contrat est deja
presque au bon niveau : il represente un **support geometrique planaire par
cellule**, et non un objet solveur complet.

### La discretisation des supports gere deja triangles et quadrilateres

`hydromodpy/domain/spatial_support.py` echantillonne deja :

- des cellules quadrilateres
- des cellules triangulaires

C'est important, car cela veut dire qu'une premiere implementation Gmsh peut se
brancher directement sur :

1. `support_field.on_mesh(mesh)`
2. `FieldParam.to_mesh_field(...)`

tant que le maillage expose des cellules `triangle` ou `quadrilateral` via
`BaseFieldMesh`.

### Relation entre `BaseFieldMesh` et `StructuredGrid`

Le point important est de ne pas confondre deux niveaux d'objet :

- `BaseFieldMesh` : contrat geometrique minimal consomme par `Field`,
  `GeologyField`, `FieldParam` et, plus tard, par une partie du postprocessing
  hors solveur
- `StructuredGrid` : objet solveur riche, specifique a FloPy/MODFLOW, qui porte
  beaucoup plus d'information que ce dont `Field` et `FieldParam` ont besoin

Aujourd'hui, le lien entre les deux est un **adaptateur** :

- `hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_mesh_adapter.py`

Cet adaptateur convertit un `StructuredGrid` en une vue 2D compatible
`BaseFieldMesh`, uniquement pour la projection planaire des supports.

Autrement dit :

- `Field` et `FieldParam` ne devraient pas connaitre `StructuredGrid`
- le solveur peut, lui, continuer a manipuler directement un objet plus riche
- l'adaptation `StructuredGrid -> BaseFieldMesh` est une operation normale et
  souhaitable

## Contrat minimal reellement consomme aujourd'hui

Pour l'usage actuel, le contrat effectivement consomme par `Field`,
`GeologyField` et `FieldParam` est tres petit.

### Cote `Field` / `GeologyField.on_mesh(mesh)`

La projection d'un support spatial sur un maillage consomme essentiellement :

- `mesh.cells`
- `mesh.n_cells`
- `mesh.to_cell_values(...)`

et, a travers chaque cellule :

- `cell.index`
- `cell.kind`
- `cell.vertices`
- `cell.centroid`

En pratique, c'est un contrat de **cellules geometriques 2D explicites**.

### Cote `FieldParam.to_mesh_field(...)`

Le mapping des valeurs sur le maillage consomme essentiellement :

- `mesh.n_cells`
- `mesh.to_cell_values(...)`
- `mesh.attach_cell_values(...)`

`FieldParam` ne depend pas de `StructuredGrid`, ni de notions solveur comme :

- `nlay`
- `top`
- `botm`
- `delr` / `delc`
- les conventions d'indexation MODFLOW

## Conclusion sur la suffisance du contrat

Pour l'objectif vise, ma lecture est la suivante :

- **oui**, `BaseFieldMesh` est globalement suffisant comme contrat commun pour
  `Field` et `FieldParam`
- **oui**, c'est bien ce contrat-la qui devrait etre la seule interface de
  maillage visible depuis `Field` / `FieldParam`
- **oui**, le solveur peut tres bien continuer a acceder a davantage
  d'information via `StructuredGrid`, sans que ce soit un probleme

Le point cle est donc moins "faut-il remplacer `StructuredGrid` ?" que
"faut-il bien separer le contrat geometrique commun du contrat solveur ?".

Pour moi, la reponse est oui.

## Separation stricte des responsabilites

Le plan d'implementation doit rester lisible sur ce point :

- le maillage porte la geometrie, la topologie, la lecture et l'ecriture
- `Field` porte le support spatial et sa projection sur un maillage
- `FieldParam` porte le mapping des valeurs et la logique verticale eventuelle

Autrement dit :

- le maillage **ne doit pas** connaitre la geologie ou la logique de
  `FieldParam`
- `Field` **ne doit pas** connaitre les details internes de Gmsh
- `FieldParam` **ne doit pas** connaitre les details internes de Gmsh

### Responsabilites de la couche maillage

La couche maillage peut connaitre :

- les noeuds
- les cellules
- la connectivite
- les centres
- les bornes
- les formats d'echange (`.msh`, `.vtu`, ...)
- l'extrusion 3D

Mais elle ne doit pas connaitre :

- les zones geologiques
- les fractions de support
- les lois de variation de `FieldParam`

### Responsabilites de `Field`

`Field` doit uniquement :

- prendre un objet conforme a `BaseFieldMesh`
- echantillonner le support spatial sur ce maillage
- retourner un objet de discretisation intermediaire

`Field` ne doit pas dependre :

- du format `.msh`
- de `meshio`
- d'une connectivite Gmsh specifique
- d'une implementation de maillage particuliere

### Responsabilites de `FieldParam`

`FieldParam` doit uniquement :

- consommer un maillage 2D via `BaseFieldMesh`
- ou consommer la discretisation issue de `Field.on_mesh(mesh)`
- produire une valeur par cellule
- gerer, si besoin, une dependance en profondeur

`FieldParam` ne doit pas faire :

- de lecture de maillage
- d'ecriture de maillage
- de manipulation directe de connectivite Gmsh
- de logique d'extrusion geometrique

### Ou passent les details Gmsh

Les details Gmsh doivent rester confines a :

- `gmsh_reader.py`
- `gmsh_planar_mesh.py`
- `gmsh_from_config.py`
- `extruded_prism_mesh.py`

Ce sont ces couches qui savent :

- lire un `.msh`
- convertir ce contenu en cellules
- ecrire un maillage
- construire l'extrusion prismatique 3D

Le reste du code ne doit voir que :

- `BaseFieldMesh` pour le planaire 2D
- une structure de resultat 3D deja preparee pour l'extrusion

## Faut-il etendre `BaseFieldMesh` ?

### Reponse courte

Pas de maniere urgente pour le couplage `Field` / `FieldParam`.

Le contrat actuel couvre deja l'essentiel du besoin :

- enumeration explicite des cellules
- geometrie des cellules
- normalisation d'une valeur par cellule
- attachement de valeurs au maillage
- trace de valeurs par cellule

Il faut toutefois noter que le contrat actuel melange legerement deux niveaux :

- un noyau geometrique reellement necessaire a `Field` / `FieldParam`
- quelques facilites de visualisation ou de manipulation

Ce melange n'est pas bloquant a court terme. Il devient seulement un sujet si
l'on souhaite, plus tard, separer tres strictement :

- le contrat geometrique minimal
- les services de visualisation/postprocessing

### Pourquoi on pourrait vouloir les separer plus tard

Il y a plusieurs raisons possibles, mais aucune n'impose ce refactoring
maintenant.

Les raisons defensibles seraient par exemple :

- vouloir distribuer un package de maillage tres leger a un collegue, avec
  lecture/ecriture et geometrie seulement
- eviter qu'un contrat de maillage impose des choix de rendu ou des
  dependances de visualisation
- permettre plusieurs couches de rendu au-dessus du meme maillage :
  Matplotlib, export VTK, export GeoJSON, postprocessing 3D, etc.
- garder une frontiere tres nette entre :
  - "ce qu'est le maillage"
  - "ce qu'on sait faire avec lui"

Autrement dit, la separation devient utile si l'on veut faire du maillage un
objet plus autonome, plus distribuable et moins couple aux usages actuels de
figure.

### Faut-il le faire maintenant ?

Ma recommandation est : **non, pas maintenant**.

Pour l'etat actuel du projet, le contrat `BaseFieldMesh` reste suffisamment
petit et suffisamment lisible. Le fait qu'il porte aussi `plot_cell_values()`
ne me semble pas assez couteux pour justifier un refactoring de structure
immediat.

Le bon compromis me semble etre :

- garder `BaseFieldMesh` tel quel pour la premiere iteration Gmsh
- ne pas ouvrir tout de suite un chantier de separation "mesh pur" /
  "visualisation"
- en revanche, ecrire le nouveau code de facon a ce que la logique de plotting
  reste deja le plus localisee possible dans des modules dedies

Autrement dit :

- **decision court terme** : ne pas separer maintenant
- **discipline d'implementation** : ne pas melanger inutilement la lecture,
  l'ecriture, la geometrie et les figures dans les memes modules

### Signe qui dirait qu'il faut le faire plus tard

Je commencerais a envisager la separation seulement si l'un de ces besoins
apparait clairement :

- un collegue doit utiliser les classes de maillage sans embarquer la couche de
  rendu du projet
- plusieurs backends de visualisation deviennent importants
- le 3D extrude impose une API de rendu tres differente du 2D
- le contrat `BaseFieldMesh` commence a grossir avec des methodes qui ne sont
  plus geometriques

En resume :

- on le ferait pour clarifier encore plus le perimetre du maillage
- mais on n'en a pas besoin tout de suite
- il vaut mieux garder ce refactoring comme option de deuxieme temps

### Ce qu'il ne faut pas remonter dans le contrat commun

Je ne recommanderais pas d'ajouter dans `BaseFieldMesh` des concepts propres au
solveur, par exemple :

- la discretisation verticale
- les surfaces `top` / `botm`
- les conventions `nlay, nrow, ncol`
- les proprietes numeriques specifiees pour MODFLOW
- des hypotheses structurees obligatoires

Ces informations appartiennent au contrat solveur, pas au contrat de maillage
commun utilise par `Field` et `FieldParam`.

### Extensions eventuelles mais optionnelles

Si l'on veut rendre le contrat plus confortable plus tard, les extensions les
plus defensibles seraient plutot des metadonnees ou aides generiques, par
exemple :

- `bounds` ou une methode equivalente pour recuperer l'emprise XY
- `crs` comme metadonnee facultative
- un indicateur du type de maillage (`structured`, `triangle`,
  `quadrilateral`, `extruded_prism`)
- une convention plus explicite pour l'ordre des valeurs cellule

Mais ces extensions ne me semblent pas necessaires pour la premiere decision
d'architecture.

## Position proposee pour la suite

Je proposerais de formaliser la lecture suivante :

1. `BaseFieldMesh` est le contrat commun **hors solveur** pour `Field`,
   `FieldParam` et les futurs usages de postprocessing planaire.
2. `StructuredGrid` reste un objet **solveur** plus riche, libre d'exposer plus
   d'information.
3. Le passage de l'un a l'autre se fait par adaptateur, et non par extension du
   contrat `Field`.
4. Si de nouveaux besoins apparaissent en postprocessing, on evaluera s'ils
   relevent :
   - du contrat commun `BaseFieldMesh`
   - ou d'un contrat supplementaire distinct

### Les maillages concrets existants ne sont pas tous reutilisables au meme niveau

Deux implementations existantes sont pertinentes :

- `hydromodpy/field/cases/square/field_mesh_square.py`
- `hydromodpy/field/geology/geology_mesh.py`

`field_mesh_square.py` est utile comme reference pour les maillages
triangulaires, mais reste oriente demonstration.

`geology_mesh.py` constitue une meilleure base pour de vraies coordonnees
cartesiennes.

### Point important sur `StructuredFieldMesh`

`StructuredFieldMesh` n'est pas seulement un objet d'exemple.
Dans l'etat actuel du code, il est deja sur un chemin de production :

- il est re-exporte publiquement depuis [field/__init__.py](c:/codes/HydroModPy-GH/hydromodpy/field/__init__.py#L16)
- il est re-exporte depuis [field/cases/__init__.py](c:/codes/HydroModPy-GH/hydromodpy/field/cases/__init__.py#L6)
- il est utilise par l'adaptateur solveur->field dans [sgrid_mesh_adapter.py](c:/codes/HydroModPy-GH/hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_mesh_adapter.py#L18)
- il est tape dans la discretisation centrale de `FieldParam` sur SGrid dans [sgrid_fieldparam_discretization.py](c:/codes/HydroModPy-GH/hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_fieldparam_discretization.py#L21)

Donc oui : son emplacement actuel dans `field/cases/square/` est trop profond
et trompeur.

Il y a meme un indice concret que cet emplacement est devenu inadapté :
le plotting de [field_mesh_square.py](c:/codes/HydroModPy-GH/hydromodpy/field/cases/square/field_mesh_square.py#L165)
et [field_mesh_square.py](c:/codes/HydroModPy-GH/hydromodpy/field/cases/square/field_mesh_square.py#L248)
force encore `xlim/ylim = [0, 1]`, ce qui correspond bien a un cas carre unite,
pas a une implementation generale de maillage structure.

### Emplacement plus logique a court terme

Le deplacement le plus pragmatique me semble etre :

```text
hydromodpy/field/
  core/
    field_mesh.py              # contrats abstraits
  meshes/
    __init__.py
    structured_field_mesh.py   # StructuredFieldMesh
    triangular_field_mesh.py   # TriangularStructuredFieldMesh, ...
```

Cette option a plusieurs avantages :

- `field/core/` reste reserve aux contrats abstraits
- `field/meshes/` devient l'emplacement des implementations concretes generiques
- `field/cases/` redevient vraiment reserve aux cas de demonstration ou de
  reference
- le backend solveur cartesien peut importer un maillage concret sans dependre
  d'un dossier `cases`

### Emplacement cible a moyen terme

Si l'on pousse le nettoyage plus loin, la vraie cible conceptuelle reste un
package neutre :

```text
hydromodpy/mesh/
  core.py
  structured_2d.py
  triangular_2d.py
  gmsh_planar_2d.py
  extruded_prism_3d.py
```

Mais je ne ferais pas ce grand deplacement tout de suite si l'on veut avancer
sur Gmsh sans ouvrir un refactoring trop large.

### Strategie de migration recommandee

Je recommanderais une migration en deux temps :

1. deplacer `StructuredFieldMesh` et les variantes triangulaires vers
   `hydromodpy/field/meshes/`
2. garder temporairement des re-exports compatibilite depuis
   `hydromodpy/field/cases/square/__init__.py` et `hydromodpy/field/__init__.py`

Cela permet :

- de nettoyer l'architecture
- de limiter le risque de casse immediate
- d'eviter une migration big bang

### Plan de migration concret, fichier par fichier

Je recommanderais le plan de migration suivant.

#### 1. Creer un package `hydromodpy/field/meshes/`

Nouveaux fichiers :

```text
hydromodpy/field/meshes/
  __init__.py
  structured_field_mesh.py
  triangular_field_mesh.py
```

Contenu cible :

- `structured_field_mesh.py`
  - `StructuredFieldMesh`
- `triangular_field_mesh.py`
  - `_TriangularBaseFieldMesh`
  - `TriangularStructuredFieldMesh`
  - `TriangularUnstructuredFieldMesh`

Objectif :

- sortir les implementations generiques concretes de `field/cases/square/`
- garder `field/core/` reserve aux abstractions

#### 2. Reduire `field_mesh_square.py` a son vrai role de cas / factory

Fichier concerne :

- [field_mesh_square.py](c:/codes/HydroModPy-GH/hydromodpy/field/cases/square/field_mesh_square.py)

Role cible apres migration :

- garder les helpers de generation du carre unite
- garder `FieldMeshSquare`
- importer les classes concretes depuis `hydromodpy.field.meshes`
- ne plus definir lui-meme `StructuredFieldMesh` ni les classes triangulaires

Autrement dit, ce fichier doit devenir un module de cas et de generation
specifique au carre unite, pas le lieu canonique des classes generiques.

#### 3. Basculer les imports du coeur du code

Fichiers a modifier en priorite :

- [sgrid_mesh_adapter.py](c:/codes/HydroModPy-GH/hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_mesh_adapter.py)
- [sgrid_fieldparam_discretization.py](c:/codes/HydroModPy-GH/hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_fieldparam_discretization.py)
- [field/__init__.py](c:/codes/HydroModPy-GH/hydromodpy/field/__init__.py)
- [field/cases/__init__.py](c:/codes/HydroModPy-GH/hydromodpy/field/cases/__init__.py)
- [field/cases/square/__init__.py](c:/codes/HydroModPy-GH/hydromodpy/field/cases/square/__init__.py)

Changement cible :

```python
from hydromodpy.field.meshes import StructuredFieldMesh
```

ou :

```python
from hydromodpy.field.meshes import (
    StructuredFieldMesh,
    TriangularStructuredFieldMesh,
    TriangularUnstructuredFieldMesh,
)
```

et non plus :

```python
from hydromodpy.field.cases.square.field_mesh_square import StructuredFieldMesh
```

#### 4. Mettre en place une compatibilite transitoire

Pendant une phase intermediaire, je recommanderais de garder des re-exports
compatibilite :

- `hydromodpy/field/__init__.py`
- `hydromodpy/field/cases/__init__.py`
- `hydromodpy/field/cases/square/__init__.py`

Eventuellement, on peut aussi garder une compatibilite dans
`field_mesh_square.py`, par exemple en reimportant les classes depuis
`hydromodpy.field.meshes`.

L'idee est la suivante :

- les nouveaux imports du coeur pointent vers `field.meshes`
- les anciens imports externes continuent de fonctionner pendant un temps

#### 5. Corriger les hypotheses "carre unite" dans les classes generiques

Le point a traiter en meme temps que le deplacement est le suivant :

- les methodes `plot_cell_values(...)` des classes issues de
  `field_mesh_square.py` ne doivent plus forcer `xlim/ylim = [0, 1]`

Une fois deplacees dans `field/meshes/`, ces classes doivent devenir
geometriquement generiques :

- utiliser les coordonnees du maillage
- ne plus supposer un domaine unite

Le code de demonstration carre unite peut garder, lui, des conventions
d'affichage specifiques dans les runners ou les cas.

#### 6. Ajuster les exports publics

Fichiers a harmoniser :

- [field/__init__.py](c:/codes/HydroModPy-GH/hydromodpy/field/__init__.py)
- [field/core/__init__.py](c:/codes/HydroModPy-GH/hydromodpy/field/core/__init__.py)
- nouveau `hydromodpy/field/meshes/__init__.py`

Je recommanderais la regle suivante :

- `field.core` exporte les abstractions uniquement
- `field.meshes` exporte les implementations concretes generiques
- `field` peut re-exporter les deux pour le confort utilisateur

Cela donne une structure beaucoup plus lisible :

- abstrait dans `core`
- concret generique dans `meshes`
- cas de demonstration dans `cases`

#### 7. Ajouter des tests de non-regression de migration

Tests a ajouter ou adapter :

- verifier que `build_field_mesh_from_sgrid(...)` retourne toujours un maillage
  fonctionnel
- verifier que `support_field.on_mesh(mesh)` continue a fonctionner
- verifier que `FieldParam.to_mesh_field(...)` ne change pas de comportement
- verifier que les anciens imports publics critiques continuent a fonctionner
  pendant la phase transitoire

#### 8. Eventuelle phase 2

Une fois la migration stabilisee, on pourra decider :

- soit de laisser `field.meshes` comme emplacement durable
- soit de pousser ensuite vers `hydromodpy/mesh/`

Je ne ferais pas cette phase 2 tout de suite. Le bon premier nettoyage est
deja de sortir `StructuredFieldMesh` du dossier `cases`.

## Recommandation d'architecture

### Recommandation court terme

Ajouter un nouveau package frere :

```text
hydromodpy/solver/utils/mesh/
  cartesian_grid/
  gmsh_grid/
    __init__.py
    gmsh_config.py
    gmsh_reader.py
    gmsh_planar_mesh.py
    extruded_prism_mesh.py
    extruded_fieldparam_discretization.py
    gmsh_from_config.py
    gmsh_plotting.py
    gmsh_case_runner.py
    cases/
      __init__.py
      reference_2d_geology_base/
        README.md
        run_case_gmsh.py
        case_config_gmsh.toml
        data/
          mesh/
            reference_triangles.msh
            reference_quads.msh
        outputs/
          exported_meshes/
      comparison_cartesian_vs_gmsh_2d/
        README.md
        run_compare.py
        case_config_cartesian.toml
        case_config_gmsh.toml
        outputs/
          exported_meshes/
      synthetic_2d/
        README.md
        run_case.py
        case_config.toml
        data/
          mesh/
            synthetic_triangles.msh
        outputs/
          exported_meshes/
```

et conserver l'interface commune au-dessus du contrat existant `BaseFieldMesh`.

Cela apporte :

- une symetrie avec l'organisation actuelle du depot
- un risque d'implementation faible
- aucune perturbation du chemin solveur structure
- un support explicite pour un cas visuel de reference, un cas de comparaison
  et un cas synthetique leger pour tests rapides

### Classe de maillage explicite et distribuable

Le point que tu ajoutes est important : le maillage ne doit pas etre seulement
un objet intermediaire de calcul. Il doit exister sous la forme d'une classe
concrete, clairement identifiable, que l'on puisse :

- lire
- ecrire
- distribuer avec des exemples
- reutiliser hors du reste du solveur

La bonne lecture est donc :

- `BaseFieldMesh` reste le **contrat abstrait 2D** consomme par `Field` et
  `FieldParam`
- mais le backend Gmsh doit fournir une **classe concrete 2D en propre**
- et, en plus, une **classe concrete 3D d'extrusion** reliee a cette classe 2D

Je proposerais explicitement :

- `GmshPlanarMesh2D(BaseFieldMesh)` dans `gmsh_planar_mesh.py`
- `ExtrudedPrismMesh3D` dans `extruded_prism_mesh.py`

Le point important est que ces deux classes soient visibles tout de suite dans
des fichiers tres explicites, et non diluees dans des helpers ou dans la seule
config.

### API minimale attendue pour un collegue

Si un collegue n'a besoin que du maillage, de sa lecture et de quelques
fonctions essentielles, l'API publique minimale devrait etre simple.

Pour `GmshPlanarMesh2D` :

- `from_file(path)`
- `to_file(path)`
- `n_nodes`
- `n_cells`
- `cells`
- `points_xy`
- `cell_centroids()`
- `bounds`
- `as_dict()`

Pour `ExtrudedPrismMesh3D` :

- `from_planar_mesh(...)`
- `from_file(path)`
- `to_file(path)`
- `n_nodes`
- `n_cells_2d`
- `n_cells_3d`
- `n_layers`
- `points_xyz`
- `prisms`
- `prism_centroids()`
- `top`
- `botm`
- `layer_center_depths`
- `as_dict()`

Cette API doit rester lisible et peu dependante du reste du package.

### Lecture / ecriture du maillage

Pour la diffusion des exemples, je recommanderais deux niveaux :

1. un format d'echange standard
2. une API Python stable au-dessus

Le format d'echange standard peut etre :

- `.msh` pour le 2D
- `.vtu` ou `.msh` pour le 3D prismatique

via `meshio`.

L'API Python stable doit etre portee par les classes elles-memes :

- `GmshPlanarMesh2D.from_file(...)`
- `GmshPlanarMesh2D.to_file(...)`
- `ExtrudedPrismMesh3D.from_file(...)`
- `ExtrudedPrismMesh3D.to_file(...)`

Le lecteur bas niveau `gmsh_reader.py` peut rester une brique interne, mais il
ne devrait pas etre l'interface principale exposee a l'utilisateur.

Il serait utile d'ajouter des exemples tres courts du type :

- `read_planar_mesh.py`
- `write_planar_mesh.py`
- `extrude_planar_mesh.py`
- `read_prism_mesh.py`

de facon a fournir tout de suite au collegue un point d'entree autonome.

### Recommandation moyen terme

Une fois les deux backends en place et l'API stabilisee, extraire le code
commun de maillage dans un package neutre du type :

```text
hydromodpy/mesh/
  core.py
  structured.py
  triangular.py
  gmsh.py
  factory.py
```

A ce stade :

- `cartesian_grid/` reste specifique au solveur
- `gmsh_grid/` peut rester une couche de compatibilite ou etre reduit
- tous les workflows hors solveur consomment un package de maillage neutre

## Cas de reference souhaite

Le dossier `cases/` doit jouer trois roles en meme temps :

1. servir de cas visuel de controle pendant le developpement
2. fournir un actif de reference stable pour les tests
3. donner un exemple minimal de workflow complet pour les futurs utilisateurs

Le point important est le suivant :

- le **cas principal** doit etre un cas geologique reemployant la base de
  `run_demo_2d`
- le **cas secondaire** doit comparer explicitement maillage cartesien et
  maillage Gmsh sur le meme support
- le **cas synthetique** reste utile, mais comme cas leger et isole, pas comme
  reference principale

## Cas principal : `reference_2d_geology_base`

### Reponse a la question sur la base geologique de `run_demo_2d`

Oui, il est possible et meme souhaitable de prendre comme base du cas test la
geologie reduite utilisee par `run_demo_2d`.

Cette base est aujourd'hui beaucoup plus adaptee qu'un gros jeu de donnees
France complet, car elle conserve un vrai contenu geologique tout en restant
legere.

Les actifs deja disponibles sont :

- `data/Brittany_small_test_example/geology/GEO1M_brittany.shp`
- `data/Brittany_small_test_example/geology/geology_K_dummy_demo.csv`
- `hydromodpy/solver/utils/mesh/cartesian_grid/examples/discretization/demo_top_bretagne_10km.tif`

### Pourquoi ce choix est bon

Ce choix permet de figer un cas ou :

- le support geologique est realiste
- le mapping du parametre est deja present
- le domaine est deja connu dans le depot
- la logique de verification de `run_demo_2d` est directement reutilisable

En pratique, cela permet de ne changer qu'une seule chose entre deux workflows :

- le backend de maillage

alors que :

- le support geologique
- le champ de parametre
- la logique de visualisation
- le type de controle visuel

restent autant que possible identiques.

### Objectif exact du cas principal

Le cas `reference_2d_geology_base` doit permettre de verifier visuellement et
numeriquement :

- que le maillage Gmsh est lu correctement
- que son contour couvre bien le meme domaine utile que le cas cartesien
- que la projection du support geologique sur le maillage est coherente
- que la projection du `FieldParam` sur le maillage est coherente
- que les figures restent lisibles pour un controle manuel

Autrement dit, ce cas doit etre tres proche de `run_demo_2d` dans son
intention :

1. support geologique brut
2. discretisation du support sur le maillage
3. valeurs finales du parametre sur le maillage

### Ce que l'on doit reutiliser de `run_demo_2d`

Le cas principal doit reprendre :

- la meme base geologique reduite Bretagne
- le meme CSV de valeurs geologiques factices pour `K`
- la meme logique de preparation du support
- la meme structure de figure en trois panneaux

Il n'est pas obligatoire de reprendre a l'identique :

- la discretisation cartesienne
- la forme des cellules
- les details solveur de `StructuredGrid`

Le but n'est pas de refaire `run_demo_2d` a l'identique, mais de produire son
equivalent conceptuel pour un backend Gmsh.

### Heterogeneite attendue dans ce cas principal

Le point clef n'est pas d'inventer une heterogeneite artificielle de plus,
mais de reutiliser l'heterogeneite deja presente dans le support geologique
Bretagne.

Ce cas est interessant parce qu'il contient naturellement :

- plusieurs unites geologiques
- des interfaces non alignees sur le maillage
- des zones larges et des zones plus fines
- des cellules qui seront pleinement dans une unite
- des cellules mixtes a cheval sur plusieurs unites

Cela montre deja, de maniere beaucoup plus convaincante qu'un cas minimal :

- que le maillage est correctement positionne
- que la projection surfacique est correcte
- que le mapping `FieldParam` suit bien la discretisation de la geologie

### Figure cible pour le cas principal

Le cas principal doit produire une figure analogue a `run_demo_2d` :

1. panneau gauche : support geologique brut + contour du maillage Gmsh
2. panneau centre : geologie discretisee sur le maillage Gmsh
3. panneau droit : valeurs finales du `FieldParam` sur le maillage Gmsh

Le point important est que cette figure permette de controler visuellement :

- la couverture spatiale du maillage
- la coherence des interfaces geologiques
- la presence de cellules mixtes
- la coherence des valeurs finales

### Ce que doit produire le runner du cas principal

Le runner `reference_2d_geology_base/run_case_gmsh.py` devrait produire au
minimum :

- une figure PNG de controle visuel
- un resume JSON compact
- un export du maillage 2D relu-able
- un export du maillage 3D extrude relu-able
- eventuellement un tableau des valeurs cellule

Le resume JSON devrait contenir :

- nombre de noeuds
- nombre de cellules
- types de cellules
- bornes XY
- statistiques globales des valeurs finales
- quelques signatures simples de projection

### Remarque sur le maillage du cas principal

Pour ce cas, il est raisonnable de commencer avec :

- une variante triangle
- une variante quadrilatere

sur le meme domaine geologique de Bretagne, de facon a separer proprement les
questions :

- lecture du maillage
- discretisation du support
- rendu visuel

## Cas secondaire : `comparison_cartesian_vs_gmsh_2d`

### Pourquoi un second cas est utile

Oui, une deuxieme version de comparaison des deux maillages est tres utile.

Elle ne remplace pas le cas principal. Elle le complete.

Le cas principal repond a la question :

- "est-ce que le backend Gmsh fonctionne bien sur le cas geologique de
  reference ?"

Le cas de comparaison repond a la question :

- "a support et parametrage quasi identiques, est-ce que les workflows
  cartesien et Gmsh donnent des resultats visuellement et numeriquement
  coherents ?"

### Principe du cas de comparaison

Le cas `comparison_cartesian_vs_gmsh_2d` doit repartir de la meme base
geologique que `run_demo_2d`, puis construire :

- un maillage cartesien de reference
- un maillage Gmsh sur la meme emprise

et produire des sorties comparables.

L'idee est de garder constants :

- le shapefile geologique
- le CSV de valeurs
- le raster de reference
- le domaine
- les conventions de figure

et de faire varier uniquement :

- le type de maillage

### Finalite de ce cas de comparaison

Ce cas doit servir surtout a :

- la comparaison visuelle
- le diagnostic de regression
- la discussion scientifique ou technique sur les effets du maillage

Ce n'est pas necessairement le meilleur cas pour un test unitaire rapide, mais
c'est un cas tres utile pour le developpement et la validation.

### Sorties attendues pour le cas de comparaison

Le cas de comparaison peut produire :

- une figure cartesien
- une figure Gmsh
- une figure comparee cote a cote
- un JSON de comparaison

Le JSON de comparaison peut inclure :

- stats globales de chaque maillage
- ecarts de moyenne et de quantiles
- eventuellement une comparaison spatialement agregee

Il ne faut pas viser une egalite cellule a cellule entre les deux maillages.
Le bon niveau de comparaison est plutot :

- coherence spatiale
- memes structures heterogenes globales
- signatures statistiques compatibles

## Cas de postprocessing : `comparison_cartesian_vs_gmsh_3d`

Une variante 3D legere est utile une fois les deux workflows 3D disponibles :

- le workflow cartesien structure existant
- le workflow Gmsh extrude deja discretise en 3D

Ce cas doit rester dans une couche de **cas / postprocessing**.
Il ne doit pas pousser de logique de comparaison dans :

- `Field`
- `FieldParam`
- `BaseFieldMesh`
- les objets coeur du maillage 3D

Le bon niveau de comparaison pour ce cas 3D n'est toujours **pas**
l'egalite cellule a cellule.

Le niveau cible est plutot :

- comparaison des shapes de grilles / maillages 3D
- comparaison de l'emprise spatiale XY
- comparaison des stats globales
- comparaison des stats par couche
- comparaison de signatures numeriques compactes
- comparaison de quelques profils verticaux sur des positions XY partagees

Les sorties attendues sont alors :

- un JSON de comparaison 3D
- des figures par couche
- une figure de profils verticaux compares
- une figure synthetique de comparaison

La regle importante est la suivante :

- le runner 3D compare des **coupes et agregats**
- il ne construit pas de carte de difference cellule a cellule entre
  cartesian et Gmsh
- il reutilise les structures de valeurs 3D deja disponibles de chaque cote
  pour faire seulement du QA visuel et numerique

Cette limite de comparaison doit rester explicite dans la doc et dans les
sorties JSON, afin d'eviter de surinterpreter les ecarts lies a des maillages
de nature differente.

## Visualisation 3D legere

La premiere V1 ne doit pas introduire de rendu 3D interactif.

La bonne cible est une couche de visualisation simple, reutilisable, fondee
sur des coupes 2D :

- cartes par couche
- profils verticaux sur quelques cellules 2D sources
- figures compactes de QA

Cette couche doit etre factorisee dans un module dedie, par exemple :

- `extruded_mesh_visualization.py`

Elle doit consommer :

- `ExtrudedPrismMeshWithValues`

et fournir des helpers du type :

- `build_layer_maps_figure(...)`
- `build_vertical_profiles_figure(...)`
- `build_visualization_summary(...)`

L'objectif est double :

- eviter que la logique de trace reste enfouie dans les runners de cas
- donner une base simple pour le postprocessing manuel hors solveur

## Cas secondaire leger : `synthetic_2d`

### Role du cas synthetique

Le cas synthetique reste tres utile, mais il ne doit plus etre presente comme
le cas principal.

Son role est different :

- isoler un probleme de geometrie
- fournir un test leger et deterministe
- permettre un debuggage rapide sans dependre de la geologie Bretagne

### Heterogeneite recommandee pour le cas synthetique

Le cas `synthetic_2d` peut utiliser un support spatial de type
"geology-like" entierement analytique, avec priorite de recouvrement explicite.

Je recommanderais :

1. une zone de fond
2. une bande oblique
3. une lentille circulaire ou elliptique

Exemple :

- domaine : `[0, 1] x [0, 1]`
- `background` : zone par defaut
- `band` : `abs(y - (0.20 + 0.60 * x)) <= 0.08`
- `lens` : `(x - 0.72)^2 + (y - 0.35)^2 <= 0.12^2`
- priorite : `lens > band > background`

Valeurs conseillees :

- `background = 1.0`
- `band = 5.0`
- `lens = 12.0`

Cette heterogeneite est suffisante pour montrer :

- des cellules pleines
- des cellules mixtes
- des interfaces obliques
- une petite structure locale

### Pourquoi garder ce cas synthetique

Il reste utile pour :

- des tests unitaires tres rapides
- des tests sans dependance GIS supplementaire
- l'isolation des bugs de lecture ou de projection

Il faut simplement le positionner correctement :

- **cas leger de debug et de test**
- pas **cas principal de reference fonctionnelle**

## Contrat propose pour le premier perimetre

La premiere iteration Gmsh devrait supporter :

- des maillages plans 2D
- des triangles lineaires
- des quadrilateres lineaires
- une extrusion 3D simple de ce maillage 2D
- des cellules prismatiques lineaires pour le 3D extrude

La premiere iteration devrait exclure explicitement :

- l'integration directe a un solveur MODFLOW non structure
- le support Gmsh 3D general non derive du 2D
- les elements finis d'ordre eleve
- les polygones arbitraires au-dela triangle/quadrilatere en 2D
- les polyedres arbitraires au-dela prisme lineaire en 3D

La bonne limite fonctionnelle est donc :

- **oui** au 2D planaire hors solveur
- **oui** au 3D derive par extrusion verticale du 2D
- **non** a un vrai backend 3D non structure complet des la premiere iteration

Cela garde l'implementation alignee avec la logique actuelle de discretisation :

- projection du support sur un maillage 2D
- evaluation des proprietes sur des profondeurs ou couches
- construction finale d'un resultat 3D par extrusion

## Comportement cible du backend

Le workflow hors solveur vise doit etre le meme pour les maillages cartesiens
et Gmsh :

1. Charger un maillage depuis une config ou un fichier.
2. Projeter un support spatial sur ce maillage avec `support_field.on_mesh(mesh)`.
3. Construire un champ de parametre avec `FieldParam.to_mesh_field(...)`.
4. Tracer ou exporter une valeur scalaire par cellule via l'objet maillage.

Autrement dit, le code appelant ne devrait dependre que de `BaseFieldMesh`, et
non du type de backend.

Le solveur, lui, peut continuer a dependre d'un objet plus riche si c'est
necessaire. Il n'y a pas de contradiction a cela.

Pour le 3D extrude, le workflow cible doit etre explicite :

1. Charger ou construire `GmshPlanarMesh2D`.
2. Projeter le support spatial sur ce maillage 2D.
3. Construire les valeurs 2D de reference avec `FieldParam.to_mesh_field(...)`.
4. Extruder le maillage 2D en `ExtrudedPrismMesh3D`.
5. Evaluer les valeurs aux profondeurs ou centres de couches du maillage 3D.
6. Produire un resultat 3D prismatique.

Le point important est que, comme pour `cartesian_grid`, le support spatial
reste d'abord traite sur le maillage planaire 2D, puis la variation verticale
est construite ensuite.

### Frontiere effective de `BaseFieldMesh`

La frontiere a garder en tete est la suivante :

- pour le 2D, tout doit bien se passer via `BaseFieldMesh`
- pour le 3D extrude, `BaseFieldMesh` reste la porte d'entree pour la
  projection du support, puis un orchestrateur d'extrusion prend le relais

Autrement dit :

- `Field.on_mesh(...)` ne recoit qu'un maillage 2D conforme a `BaseFieldMesh`
- `FieldParam.to_mesh_field(...)` travaille d'abord sur cette base 2D
- l'objet 3D et la construction couche par couche restent dans la couche
  `extruded_fieldparam_discretization.py`

Cela signifie que, dans ce plan :

- **oui**, `Field` et `FieldParam` restent decouples des details Gmsh
- **oui**, l'interface commune reste `BaseFieldMesh` pour tout ce qui concerne
  la projection spatiale
- **oui**, les details Gmsh n'apparaissent que dans la couche maillage et dans
  la couche d'extrusion
- **non**, il ne faut pas faire entrer la connectivite prismatique 3D dans
  `Field` ou `FieldParam`

## Schema d'implementation detaille

Ce qui suit est la proposition de schema d'implementation cible pour une
premiere iteration suffisamment propre.

### 1. Couche lecture de maillage

Fichier :

- `gmsh_reader.py`

Responsabilites :

- lire un fichier `.msh`
- extraire les noeuds XY
- extraire les connectivites d'elements 2D
- filtrer les types supportes
- eventuellement filtrer un groupe physique
- retourner un payload brut simple, independant de `Field`

Payload recommande :

```text
GmshMeshData
  points_xy: np.ndarray
  cells: list[GmshCellBlock]
  cell_tags: ...
  physical_names: ...
  source_path: Path
```

Invariants :

- les points sont en XY seulement
- chaque bloc d'elements a un type explicite
- aucun traitement solveur n'apparait ici

### 2. Couche maillage 2D compatible `Field`

Fichier :

- `gmsh_planar_mesh.py`

Responsabilites :

- transformer `GmshMeshData` en `BaseFieldMesh`
- exposer une liste stable de `MeshCell`
- fournir `to_cell_values(...)`
- fournir `plot_cell_values(...)`
- fournir une API publique simple de lecture/ecriture

Classe cible :

```text
GmshPlanarMesh2D(BaseFieldMesh)
```

Invariants recommandes :

- `mesh.kind == "gmsh_2d"`
- `cell.kind in {"triangle", "quadrilateral"}`
- ordre stable des cellules
- `cell.index` dense en `0..n_cells-1`
- `to_cell_values(values)` renvoie un vecteur 1D `(n_cells,)`

Important :

Pour ce backend, la representation naturelle des valeurs cellule est un vecteur
1D. Il ne faut pas forcer artificiellement une representation 2D structuree.

API publique minimale recommandee :

- `GmshPlanarMesh2D.from_file(path)`
- `GmshPlanarMesh2D.to_file(path)`
- `GmshPlanarMesh2D.from_meshio(mesh)`
- `GmshPlanarMesh2D.to_meshio()`

En plus de ces methodes de classe, une V1 exploitable peut exposer des helpers
de plus haut niveau via un module dedie, par exemple :

- `exchange_api.py`
- `load_planar_mesh(path)`
- `save_planar_mesh(mesh, path)`

### 2.bis Couche maillage 3D d'extrusion

Fichier :

- `extruded_prism_mesh.py`

Responsabilites :

- construire un maillage 3D a partir d'un maillage 2D
- stocker explicitement les noeuds 3D et la connectivite prismatique
- exposer les centres et profondeurs de couches
- fournir une API publique simple de lecture/ecriture

Classe cible :

```text
ExtrudedPrismMesh3D
```

Invariants recommandes :

- le maillage 3D garde un lien explicite vers son maillage 2D d'origine
- chaque cellule 2D donne naissance a un prisme par couche
- `n_cells_3d = n_layers * n_cells_2d`
- les centres de prismes et profondeurs de couches sont accessibles simplement

API publique minimale recommandee :

- `ExtrudedPrismMesh3D.from_planar_mesh(...)`
- `ExtrudedPrismMesh3D.from_file(path)`
- `ExtrudedPrismMesh3D.to_file(path)`
- `ExtrudedPrismMesh3D.to_meshio()`

Pour l'usage "collegue externe", il est utile de completer cette API par :

- `load_extruded_mesh(path)`
- `save_extruded_mesh(mesh, path)`
- `load_extruded_mesh_values(path)`
- `save_extruded_mesh_values(mesh_with_values, path)`
- `save_extruded_values_npy(mesh_with_values, path)`
- `save_extruded_values_summary(mesh_with_values, path)`

Un petit exemple de lecture seule doit accompagner cette API, par exemple :

- `examples/read_only_example.py`

Remarque importante :

`ExtrudedPrismMesh3D` n'a pas besoin d'etre un `BaseFieldMesh` dans la premiere
iteration. Le contrat `BaseFieldMesh` reste le contrat planaire 2D utilise par
`Field` et `FieldParam` pour la projection du support.

### 3. Couche config / factory

Fichiers :

- `gmsh_config.py`
- `gmsh_from_config.py`

Responsabilites :

- valider la config Gmsh
- resoudre les chemins relatifs
- charger le maillage
- retourner un `GmshPlanarMesh2D`
- construire, si demande, une extrusion `ExtrudedPrismMesh3D`

Exemple de contrat :

```toml
[mesh]
backend = "gmsh"

[mesh.gmsh]
path = "data/mesh/reference_triangles.msh"
physical_name = "domain"

[mesh.extrusion]
enabled = true
nlay = 5
mode = "constant_thickness"
total_thickness = 200.0
```

Extension recommandee pour l'extrusion :

```toml
[mesh.extrusion]
enabled = true
mode = "layers"
nlay = 5
top_source = "constant"
top_value = 0.0
botm_source = "constant_thickness"
total_thickness = 200.0
```

### 4. Couche plotting

Fichier :

- `gmsh_plotting.py`

Responsabilites :

- centraliser les figures de controle visuel
- eviter de disperser la logique Matplotlib dans plusieurs scripts

Fonctions recommandees :

- `plot_mesh_geometry(...)`
- `plot_reference_geology_case(...)`
- `plot_cartesian_vs_gmsh_comparison(...)`
- `plot_synthetic_reference_case(...)`

### 5. Couche runner de cas

Fichier :

- `gmsh_case_runner.py`

Responsabilites :

- charger une config de cas
- construire le maillage
- construire le support spatial
- construire le `FieldParam`
- produire les valeurs sur le maillage
- sauver un resume JSON et les figures

Le runner doit etre assez generique pour etre reutilise :

- par `cases/reference_2d_geology_base/run_case_gmsh.py`
- par `cases/comparison_cartesian_vs_gmsh_2d/run_compare.py`
- par `cases/synthetic_2d/run_case.py`
- par les tests unitaires

Dans la variante 3D extrudee, le runner doit aussi pouvoir :

- construire `ExtrudedPrismMesh3D` a partir du 2D
- calculer les profondeurs de centres de prismes
- produire une sortie 3D par couche ou par prisme

### 5.bis Discretisation `FieldParam` sur maillage extrude

Fichier :

- `extruded_fieldparam_discretization.py`

Responsabilites :

- reprendre la logique de `sgrid_fieldparam_discretization.py`
- discretiser d'abord le support sur `GmshPlanarMesh2D`
- evaluer ensuite `FieldParam` sur les profondeurs du maillage 3D extrude
- retourner a la fois la vue 2D de reference et le resultat 3D

Classe ou resultat cible :

```text
ExtrudedFieldParamDiscretizationResult
  planar_mesh_values
  values_2d
  values_3d
  mesh_2d
  mesh_3d
  field_discretization
  prism_center_depths
```

Fonction cible :

```text
discretize_fieldparam_on_extruded_mesh(
    support_field,
    field_param,
    mesh_3d,
    ...
)
```

Principe de calcul recommande :

1. projeter `support_field` sur `mesh_2d` avec `on_mesh(...)`
2. calculer les valeurs 2D de reference avec `FieldParam.to_mesh_field(...)`
3. construire les profondeurs des centres de prismes
4. reevaluer `FieldParam.to_mesh_field(..., depth=...)` pour chaque couche
5. stocker le resultat dans une structure 3D `(nlay, n_cells_2d)` ou equivalent

Le point clef est de rester aligne avec la logique du backend cartesien :

- le support est discretise en 2D
- la variation verticale est ajoutee ensuite
- le 3D est un resultat d'extrusion, pas un support geologique 3D direct

Pour le cas de reference 3D, il est acceptable qu'un runner applique un
override local de `vertical_profile` au `FieldParam` lu depuis le cas 2D, tant
que :

- l'objet `FieldParam` lui-meme n'est pas modifie dans son API
- l'override reste local au runner de cas
- la logique de discretisation 3D reste entierement dans la couche
  d'orchestration

### 5.ter Dossier `cases/reference_3d_fieldparam`

Structure recommandee :

```text
hydromodpy/solver/utils/mesh/gmsh_grid/cases/reference_3d_fieldparam/
  README.md
  run_case_3d_fieldparam.py
  case_config_3d_fieldparam.toml
  outputs/
```

Ce cas doit reutiliser :

- le cas 2D geologique de reference pour la geologie et le `FieldParam`
- le cas 3D purement maillage pour l'extrusion prismatique

Il peut en plus definir un override local de profil vertical pour rendre la
signature 3D plus informative.

### 5.quater Postprocessing / export 3D

Fichier :

- `extruded_mesh_values.py`

Responsabilites :

- associer un `ExtrudedPrismMesh3D` et des valeurs 3D indexees par
  `(layer, source_cell_2d)`
- fournir des helpers minimaux de postprocessing hors solveur
- exporter le maillage 3D et ses valeurs dans un format de travail externe

Structure cible :

```text
ExtrudedPrismMeshWithValues
  mesh
  values_3d
  prism_center_depths
  label
  metadata
```

Helpers cibles :

- extraction d'une couche 2D comme vue planaire
- extraction d'un profil vertical pour une cellule 2D source
- stats globales
- stats par couche
- signature compacte pour les tests et le debug

La couche de visualisation legere doit rester separee de cette couche de
stockage. Une implementation cible peut vivre dans :

- `extruded_mesh_visualization.py`

avec des responsabilites limitees a :

- construire des figures par couche
- construire des profils verticaux
- produire un petit resume JSON des coupes affichees
- reutiliser `ExtrudedPrismMeshWithValues` sans y melanger la logique de trace

Export cible :

- `.vtu` avec une valeur par prisme dans `cell_data`
- `.npy` pour un dump simple des valeurs 3D
- `.json` compact pour les signatures

Runner de reference recommande :

- `cases/reference_3d_fieldparam/run_postprocess_3d.py`
- `cases/reference_3d_fieldparam/run_visualize_3d.py`

Ce runner doit reutiliser :

- le cas `reference_3d_fieldparam` pour la discretisation
- la nouvelle structure `ExtrudedPrismMeshWithValues` pour l'export et les
  aides de postprocessing
- la couche `extruded_mesh_visualization.py` pour les figures

Si `meshio` n'est pas disponible, l'export `.vtu` peut etre saute proprement,
mais la couche de postprocessing doit rester testable via `.npy` et `.json`.

### 5.quinquies Visualisation 3D interactive locale

Fichier :

- `interactive_3d_viewer.py`

Responsabilites :

- convertir un `ExtrudedPrismMesh3D` ou un `ExtrudedPrismMeshWithValues` vers
  une structure PyVista
- fournir un petit viewer local pour inspection interactive du maillage 3D
- exposer quelques operations de base utiles pour le controle visuel :
  coupe plane, seuil, selection d'une couche, exageration verticale

Contraintes :

- cette couche reste strictement optionnelle
- elle ne doit pas etre requise pour la lecture, l'ecriture, la
  discretisation, ou le postprocessing non interactif
- elle ne doit pas introduire de dependance de `Field` ou `FieldParam` vers
  PyVista

API publique recommandee :

- `build_pyvista_grid(mesh_3d)`
- `build_pyvista_grid_with_values(mesh_with_values, ...)`
- `show_interactive_mesh_3d(mesh_3d, ...)`
- `show_interactive_values_3d(mesh_with_values, ...)`
- `add_layer_slice(...)`
- `add_threshold(...)`
- `add_clip_plane(...)`
- `add_vertical_exaggeration(...)`

Metadonnees a conserver dans la structure PyVista :

- `layer_index`
- `source_cell_index`
- `prism_center_depth`
- la ou les valeurs de `FieldParam`

Runner de reference recommande :

- `cases/reference_3d_fieldparam/run_interactive_viewer.py`
- `cases/reference_3d_fieldparam/case_interactive_viewer.toml`

Dependance recommandee :

- dependance optionnelle `viewer3d = ["pyvista"]`

Le viewer doit etre testable sans ouverture de fenetre, avec `off_screen=True`,
et les tests doivent etre sautes proprement si `pyvista` n'est pas installe.

### 6. Dossier `cases/reference_2d_geology_base`

Structure recommandee :

```text
hydromodpy/solver/utils/mesh/gmsh_grid/cases/reference_2d_geology_base/
  README.md
  run_case_gmsh.py
  case_config_gmsh.toml
  data/
    mesh/
      reference_triangles.msh
      reference_quads.msh
  outputs/
    exported_meshes/
```

Le contenu de `case_config_gmsh.toml` devrait definir :

- quel `.msh` charger
- quel support geologique charger
- quel `FieldParam` utiliser
- ou ecrire les sorties

Il devrait surtout pointer explicitement vers les actifs existants :

- `data/Brittany_small_test_example/geology/GEO1M_brittany.shp`
- `data/Brittany_small_test_example/geology/geology_K_dummy_demo.csv`
- `hydromodpy/solver/utils/mesh/cartesian_grid/examples/discretization/demo_top_bretagne_10km.tif`

### 7. Dossier `cases/comparison_cartesian_vs_gmsh_2d`

Structure recommandee :

```text
hydromodpy/solver/utils/mesh/gmsh_grid/cases/comparison_cartesian_vs_gmsh_2d/
  README.md
  run_compare.py
  case_config_cartesian.toml
  case_config_gmsh.toml
  outputs/
    exported_meshes/
```

Ce dossier doit permettre de lancer un workflow de comparaison sur le meme
support geologique, avec deux backends de maillage.

Le script `run_compare.py` peut :

- lancer le workflow cartesien existant ou un wrapper leger
- lancer le workflow Gmsh
- sauver les figures
- sauver un resume de comparaison

### 8. Dossier `cases/synthetic_2d`

Structure recommandee :

```text
hydromodpy/solver/utils/mesh/gmsh_grid/cases/synthetic_2d/
  README.md
  run_case.py
  case_config.toml
  data/
    mesh/
      synthetic_triangles.msh
  outputs/
    exported_meshes/
```

Ce dossier reste un support de debug et de test leger.

### 9. Choix du support spatial

Le choix du support doit maintenant etre explicite selon le type de cas :

- `reference_2d_geology_base` : geologie Bretagne de `run_demo_2d`
- `comparison_cartesian_vs_gmsh_2d` : meme geologie Bretagne, deux backends
- `synthetic_2d` : support analytique fond + bande + lentille

Ce point est important, car il evite une ambiguite de conception :

- la reference fonctionnelle principale est geologique
- la reference technique legere est synthetique

### 10. Figure de controle proposee

Pour `reference_2d_geology_base`, la figure de controle doit etre :

1. support geologique brut + contour du maillage
2. geologie discretisee sur le maillage
3. valeurs finales `FieldParam` par cellule

Pour `comparison_cartesian_vs_gmsh_2d`, la figure peut etre :

1. cartesien discretise
2. Gmsh discretise
3. comparaison des valeurs finales

Pour `synthetic_2d`, la figure peut rester plus simple.

### 11. Strategie de tests unitaires

Je recommanderais d'organiser les tests comme suit :

```text
tests/unit/solver/utils/mesh/gmsh_grid/
  test_gmsh_reader.py
  test_gmsh_planar_mesh.py
  test_extruded_prism_mesh.py
  test_extruded_fieldparam_discretization.py
  test_gmsh_reference_geology_case.py
  test_gmsh_synthetic_case.py
  golden/
    gmsh_reference_geology_signatures.json
    gmsh_synthetic_signatures.json
```

Repartition :

- `test_gmsh_reader.py` : tests de lecture / ecriture bruts via `meshio`
- `test_gmsh_planar_mesh.py` : tests du contrat `BaseFieldMesh`,
  principalement en memoire
- `test_extruded_prism_mesh.py` : tests du maillage 3D extrude
- `test_extruded_fieldparam_discretization.py` : tests de la discretisation 3D
- `test_gmsh_reference_geology_case.py` : test de bout en bout sur le cas
  Bretagne
- `test_gmsh_synthetic_case.py` : test rapide sur le cas analytique

### 12. Ce que doit verifier `test_gmsh_reference_geology_case.py`

Le test de cas geologique devrait verifier au minimum :

- nombre de noeuds
- nombre de cellules
- types de cellules
- shape et stats des valeurs finales
- presence de cellules mixtes dans la projection
- quelques valeurs de cellules de controle
- une signature JSON compacte

Le point important est de verifier qu'il existe bien :

- des cellules homogenes
- des cellules mixtes

de sorte que le test prouve reellement que la projection geologique n'est pas
trivialement alignee sur le maillage.

### 13. Ce que doit verifier `test_gmsh_synthetic_case.py`

Le test synthetique doit rester leger et tres robuste.

Il peut verifier :

- le nombre de cellules
- les types de cellules
- la presence d'interfaces obliques
- quelques signatures de valeurs finales

### 13.bis Ce que doivent verifier les tests 3D d'extrusion

Les tests 3D devraient verifier au minimum :

- la construction correcte des noeuds 3D
- la connectivite prismatique
- la coherence `n_cells_3d = n_layers * n_cells_2d`
- la coherence des centres de prismes
- la coherence des profondeurs de centres de couches
- la stabilite de l'ecriture / relecture du maillage 3D
- la coherence d'une extrusion de `FieldParam` sur plusieurs couches

### 14. Reutilisation exacte entre cas et tests

Le niveau de reutilisation vise devrait etre :

- meme `.msh`
- meme config de cas
- meme runner
- sorties dirigees vers un dossier temporaire dans les tests

Cela donne un chemin tres lisible :

```text
cas interactif manuel
  -> run_case_gmsh.py ou run_compare.py
test unitaire
  -> gmsh_case_runner.py avec la meme config de reference
```

## Arborescence cible recommandee

Version detaillee :

```text
hydromodpy/solver/utils/mesh/gmsh_grid/
  __init__.py
  gmsh_config.py
  gmsh_reader.py
  gmsh_planar_mesh.py
  extruded_prism_mesh.py
  extruded_fieldparam_discretization.py
  gmsh_from_config.py
  gmsh_plotting.py
  gmsh_case_runner.py
  cases/
    __init__.py
    reference_2d_geology_base/
      README.md
      run_case_gmsh.py
      case_config_gmsh.toml
      data/
        mesh/
          reference_triangles.msh
          reference_quads.msh
      outputs/
        exported_meshes/
    comparison_cartesian_vs_gmsh_2d/
      README.md
      run_compare.py
      case_config_cartesian.toml
      case_config_gmsh.toml
      outputs/
        exported_meshes/
    synthetic_2d/
      README.md
      run_case.py
      case_config.toml
      data/
        mesh/
          synthetic_triangles.msh
      outputs/
        exported_meshes/

tests/unit/solver/utils/mesh/gmsh_grid/
  test_gmsh_reader.py
  test_gmsh_planar_mesh.py
  test_extruded_prism_mesh.py
  test_extruded_fieldparam_discretization.py
  test_gmsh_reference_geology_case.py
  test_gmsh_synthetic_case.py
  golden/
    gmsh_reference_geology_signatures.json
    gmsh_synthetic_signatures.json
```

## Esquisse de configuration

La configuration du maillage hors solveur devrait etre independante de la
configuration `sgrid` du solveur.

Une direction possible serait :

```toml
[mesh]
backend = "cartesian"

[mesh.cartesian]
xmin = 0.0
ymin = 0.0
xmax = 1000.0
ymax = 800.0
nx = 40
ny = 32
```

ou :

```toml
[mesh]
backend = "gmsh"

[mesh.gmsh]
path = "data/mesh/domain.msh"
cell_type = "triangle"
physical_name = "domain"
```

Un chargeur generique pourrait alors dispatcher :

- `backend = "cartesian"` -> constructeur de maillage cartesien
- `backend = "gmsh"` -> lecteur de maillage Gmsh

Pour le cas geologique de reference, la config devrait aussi reprendre la
structure logique de `run_demo_2d` :

```toml
[case]
output_figure = "outputs/reference_geology_gmsh.png"
output_summary_json = "outputs/reference_geology_gmsh_summary.json"

[case.geology]
id = "field_geology"
cell_samples_per_axis = 8

[case.geology.source]
path = "../../../../../../../data/Brittany_small_test_example/geology/GEO1M_brittany.shp"
kind = "vector"
code_field = "CODE_LEG"
reference_raster_path = "../../../../cartesian_grid/examples/discretization/demo_top_bretagne_10km.tif"

[case.field_param.field]
id = "K"
kind = "heterogeneous"

[case.field_param.field_heterogeneous]
values_source = "csv"
values_csv_file = "../../../../../../../data/Brittany_small_test_example/geology/geology_K_dummy_demo.csv"
csv_key_column = "zone_key"
csv_value_column = "K_value"
field_spatial_id = "field_geology"

[mesh]
backend = "gmsh"

[mesh.gmsh]
path = "data/mesh/reference_triangles.msh"
physical_name = "domain"
```

## Choix du lecteur / ecrivain

Pour la premiere implementation, lire et ecrire les fichiers de maillage via
`meshio` est preferable a l'utilisation directe de l'API Python `gmsh`, car le
besoin immediat est :

- de consommer des maillages existants
- d'exporter des maillages 2D et 3D pour diffusion
- de garder une interface simple de lecture / ecriture

Implication :

- `meshio` devient la dependance explicite de lecture / ecriture du backend
  Gmsh 2D
- un fallback de lecture `.msh` ASCII simple peut etre tolere pour les actifs
  de reference et les tests locaux, mais il ne remplace pas `meshio` comme
  interface principale
- les tests du contrat geometrique 2D peuvent rester majoritairement en
  memoire, sans dependre de `meshio`
- les tests de roundtrip fichier via `from_file(...)` / `to_file(...)` peuvent
  etre gardes separement et actives seulement si `meshio` est disponible

L'API Python directe de `gmsh` pourra etre introduite plus tard si la
generation de maillages dans le depot devient une exigence.

## Ou doivent vivre les fichiers de maillage

Le code du backend appartient a l'arborescence du package, mais les fichiers
`.msh` eux-memes devraient vivre avec les cas qui les utilisent.

Dans le cas present, je recommanderais :

- `reference_2d_geology_base/data/mesh/` pour les maillages du cas geologique
- `synthetic_2d/data/mesh/` pour les maillages du cas synthetique
- `cases/*/outputs/exported_meshes/` pour les maillages ecrits par les classes
  2D et 3D lors des exemples

Ce choix est justifie ici, car ces petits maillages jouent un role de support
de developpement et de test.

## Plan de tests pour la premiere iteration

Zone de tests unitaires suggeree :

```text
tests/unit/solver/utils/mesh/gmsh_grid/
```

Premiers tests suggeres :

- le lecteur charge un `.msh` compose uniquement de triangles
- le lecteur charge un `.msh` compose uniquement de quadrilateres
- le maillage 2D expose une geometrie `MeshCell` valide
- le maillage 2D se reecrit et se relit sans perte structurelle majeure
- l'extrusion 3D construit bien des prismes coherents
- le maillage 3D se reecrit et se relit sans perte structurelle majeure
- `to_cell_values()` valide correctement la taille et la forme
- `plot_cell_values()` fonctionne sur un maillage simple
- `support_field.on_mesh(mesh)` fonctionne sur le backend Gmsh
- le cas geologique Bretagne produit une signature stable
- le cas synthetique produit une signature stable

## Point de vigilance de conception

Ne pas construire le backend Gmsh de production directement sur
`field/cases/square/field_mesh_square.py`.

Ce module reste utile comme reference pour :

- la gestion de connectivite triangulaire
- la construction des `MeshCell`
- `plot_cell_values()` sur des maillages triangulaires

Mais le backend de production ne doit pas heriter des hypotheses du cas carre.

## Chemin d'implementation immediat

Ordre recommande :

1. Implementer `gmsh_reader.py` avec `meshio`.
2. Implementer `GmshPlanarMesh2D(BaseFieldMesh)` dans `gmsh_planar_mesh.py`.
3. Ajouter `from_file(...)` / `to_file(...)` sur la classe 2D.
4. Implementer `ExtrudedPrismMesh3D` dans `extruded_prism_mesh.py`.
5. Ajouter `from_planar_mesh(...)`, `from_file(...)` et `to_file(...)` sur la classe 3D.
6. Implementer `gmsh_config.py` et `gmsh_from_config.py`.
7. Implementer `extruded_fieldparam_discretization.py`.
8. Ajouter `gmsh_plotting.py` pour les figures de controle.
9. Ajouter `gmsh_case_runner.py`.
10. Ajouter `cases/reference_2d_geology_base/` avec :
   - un ou deux petits `.msh`
   - un `case_config_gmsh.toml`
   - un `run_case_gmsh.py`
   - le branchement sur la geologie Bretagne existante
11. Ajouter `cases/comparison_cartesian_vs_gmsh_2d/`.
12. Ajouter `cases/synthetic_2d/` pour le debug et les tests rapides.
13. Prouver la compatibilite avec `support_field.on_mesh(mesh)` en 2D puis en extrusion 3D.
14. Ajouter les tests unitaires en reutilisant les actifs des cas.
15. Ajouter un golden numerique compact si l'on veut une non-regression stable.

## Decisions tranchees et clarifications

### 1. Abstraction de maillage partagee

Decision recommandee pour l'iteration 1 :

- garder l'abstraction partagee la ou elle est aujourd'hui, dans
  `hydromodpy/field/core/`
- ne pas deplacer tout de suite vers `hydromodpy/mesh/`

Conseil :

Le deplacement vers un package neutre `hydromodpy/mesh/` est une bonne cible
conceptuelle a moyen terme, mais il ouvrirait trop de front de refactoring
maintenant :

- imports
- exports publics
- migration de `StructuredFieldMesh`
- Gmsh 2D
- extrusion 3D

Le meilleur compromis est donc :

- iteration 1 : garder `BaseFieldMesh` dans `field/core`
- iteration 2 eventuelle : reevaluer un package `hydromodpy/mesh/` quand le
  backend Gmsh et la migration de `StructuredFieldMesh` seront stabilises

### 2. Maillages mixtes triangle + quadrilatere

Decision :

- **non** aux maillages mixtes dans la premiere implementation
- un maillage est soit triangulaire, soit quadrangulaire

Implication :

- validation plus simple
- lecture plus simple
- plotting plus simple
- tests plus simples

### 3. Filtrage par groupes physiques

Clarification :

Dans Gmsh, un **groupe physique** sert a nommer ou etiqueter une partie du
maillage ou de la geometrie, par exemple :

- le domaine utile
- une frontiere
- une sous-zone

Le filtrage par groupes physiques veut donc dire :

- charger seulement les cellules associees a un groupe donne
- ou distinguer plusieurs sous-ensembles dans un meme fichier `.msh`

Decision pour la premiere iteration :

- pas necessaire comme prerequis absolu
- utile seulement si un meme fichier `.msh` contient plusieurs zones ou bords
  et que l'on veut en selectionner un sous-ensemble

Recommendation :

- le garder comme option de conception
- ne pas le rendre obligatoire pour debuter

### 4. Point d'entree commun cartesien / Gmsh

Clarification :

Un meme point d'entree veut dire que le code appelant pourrait charger un
maillage via une interface commune du type :

```toml
[mesh]
backend = "cartesian"
```

ou :

```toml
[mesh]
backend = "gmsh"
```

avec le meme orchestrateur au-dessus.

Avantages :

- scripts de cas plus homogènes
- comparaison cartesian / Gmsh plus simple
- tests plus simples
- moins de branchements ad hoc dans les runners

Decision recommandee :

- **ne pas** refactoriser tout de suite le cartesien pour cela
- mais garder cette cible en tete pour les cas de comparaison et les runners

Autrement dit :

- avantage reel, surtout pour la comparaison et les workflows hors solveur
- mais pas un prerequis de la premiere iteration

### 5. Contrat commun

Decision :

- garder le contrat strictement minimal

Implication :

- ne pas enrichir `BaseFieldMesh` au-dela de ce qui est reellement utile a
  `Field` et `FieldParam`
- si des metadonnees comme le type de maillage sont ajoutees plus tard, elles
  doivent rester facultatives

### 6. Export de maillage

Clarification :

Un "chemin d'export de maillage" veut dire autre chose que le simple trace
Matplotlib.

Cela veut dire :

- ecrire le maillage dans un format d'echange
- ou le convertir dans une structure reexploitable par d'autres outils

Exemples :

- `vtk` / `vtu` : visualisation 3D, ParaView, postprocessing
- `geojson` : echange SIG 2D
- `geopandas` : conversion vers un `GeoDataFrame` pour traitements Python

Decision pour l'iteration 1 :

- **oui** a un vrai export de maillage
- mais de maniere limitee et pragmatique

Perimetre recommande :

- `.msh` pour le 2D
- `.vtu` et/ou `.msh` pour le 3D prismatique
- pas de chemin `geopandas` obligatoire des la premiere iteration

### 7. Variantes geologiques

Decision :

- deux variantes des le depart, selectionnables par parametres
- une variante triangles
- une variante quadrilateres

### 8. Comparaison cartesian / Gmsh

Decision :

- oui a une comparaison visuelle explicite entre les deux maillages
- c'est meme un objectif important du dossier `comparison_cartesian_vs_gmsh_2d`

### 9. Formats d'echange

Decision :

- garder les deux formats d'echange
- `.msh`
- `.vtu`

### 10. Stockage du 3D

Decision :

- stocker le maillage 3D par prismes avec connectivite explicite

Implication :

- le 3D n'est pas seulement un tableau de valeurs
- le maillage 3D devient un vrai objet geometrico-topologique relisible

Precision d'implementation pour la premiere iteration :

- l'extrusion 3D repose sur une serie globale d'interfaces `z` partagee par
  toutes les colonnes du maillage 2D
- il n'y a pas encore, a ce stade, de `top` / `bottom` variables cellule par
  cellule ni de pinchout
- cette simplification est volontaire pour figer d'abord proprement l'objet
  maillage 3D et ses formats d'echange

## Etat du maillage contraint par les limites de zones

Ce point n'est plus une simple piste de conception : il existe maintenant dans
le depot via le workflow de maillage conforme aux zones et aux rivieres.

Le backend actuel sait deja :

- fournir au mailleur une decomposition en zones 2D
- demander au maillage de suivre explicitement les limites de ces zones
- creer des groupes physiques de surface et de courbe
- embarquer des contraintes de trace de riviere dans le meme contrat
- produire des sorties QA stables pour les cas de reference

Principe :

- fournir au mailleur une decomposition en zones 2D
- demander au maillage de suivre explicitement les limites de ces zones

Interet :

- diminuer le nombre de cellules mixtes
- aligner le maillage sur les interfaces geologiques ou de support
- rendre la projection de `Field` puis de `FieldParam` plus propre

Contraintes et impacts qui restent vrais :

- il faut disposer d'une geometrie de zones propre et topologiquement
  consistente
- la preparation geometrique devient plus complexe
- le nombre de cellules peut augmenter fortement si les interfaces sont tres
  decoupees
- cette extension est beaucoup plus naturelle avec des triangles qu'avec des
  quadrilateres purs

Ce qui reste ouvert apres cette implementation :

- durcir encore les tests E2E du launcher autour de ces cas
- maintenir la documentation synchronisee avec l'etat reel du code
- nettoyer les artefacts de runtime qui ne sont pas des actifs de reference
- decider si la suite vise un simple export externe ou un vrai couplage solveur
- si besoin, etendre ensuite la geometrie verticale a des surfaces variables par
  cellule

## Conclusion proposee pour l'iteration 1

Pour l'iteration 1, la direction la plus pragmatique est :

- conserver le code solveur structure inchange
- ajouter `hydromodpy/solver/utils/mesh/gmsh_grid/`
- reutiliser `BaseFieldMesh` comme interface commune hors solveur
- ne pas faire remonter les concepts solveur dans le contrat `BaseFieldMesh`
- ajouter une classe 2D concrete, identifiable et distribuable
- ajouter une classe 3D d'extrusion prismatique derivee du 2D
- supporter des maillages Gmsh 2D triangle/quadrilatere et leur extrusion 3D
- prendre comme cas principal la base geologique reduite de `run_demo_2d`
- ajouter un cas explicite de comparaison cartesien vs Gmsh
- garder un cas synthetique secondaire pour les tests rapides et le debug
- reprendre la logique visuelle de `run_demo_2d` pour la figure de controle
- aligner la discretisation 3D sur la logique de `cartesian_grid` :
  discretisation 2D du support puis extrusion verticale des proprietes
- s'appuyer sur le maillage contraint par limites de zones comme brique deja
  disponible du backend actuel
- repousser le couplage solveur non structure a une note de conception ulterieure
