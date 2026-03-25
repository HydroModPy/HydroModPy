# HydroMesh

Ce dossier porte le **pivot de maillage unifie** d'HydroModPy.

L'idee est simple :

- tous les producteurs de maillage convertissent vers `HydroMesh` ;
- tous les consommateurs de maillage lisent `HydroMesh` ;
- on evite ainsi les couplages directs entre formats techniques
  (`meshio`, `flopy`, `GmshPlanarMesh2D`, maillages du module `field`, etc.).

Le package `hydromodpy.spatial.mesh` ne construit pas les maillages lui-meme. Il
definit :

- le **contrat de donnees** commun (`HydroMesh`, `CellBlock`, `CellType`) ;
- les **adapters** vers et depuis les representations externes ;
- les **sorties I/O** de base (`VTU`) ;
- le **plotting unifie** pour les valeurs par cellule.

## Quand Utiliser `HydroMesh`

`HydroMesh` est le bon objet quand on veut :

- passer un maillage d'un sous-systeme a un autre ;
- serialiser un maillage sans perdre la topologie ;
- tracer rapidement des valeurs cellule par cellule ;
- construire une passerelle entre une representation specialisee et une API
  plus generique ;
- disposer d'un resume compact du maillage pour du diagnostic ou du debug.

## Structure Du Package

- [hydro_mesh.py](./hydro_mesh.py)
  Contrat principal : `HydroMesh` et `CellBlock`.
- [cell_types.py](./cell_types.py)
  Enumeration canonique des types de cellules.
- [plotting.py](./plotting.py)
  Affichage Matplotlib unifie pour maillages 2D.
- [adapters](./adapters)
  Conversions vers / depuis `meshio`, `flopy`, `field`, `gmsh`.
- [io/vtu_io.py](./io/vtu_io.py)
  Lecture / ecriture VTU.
- [UML.md](./UML.md)
  Diagrammes UML textuels.

## Entrees / Sorties

### Entree centrale

L'entree centrale du package est la creation d'un `HydroMesh` :

```python
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

mesh = HydroMesh(
    vertices=points_xy,
    cell_blocks=(
        CellBlock(CellType.TRIANGLE, connectivity),
    ),
)
```

### Sortie centrale

La sortie centrale du package est aussi un `HydroMesh`. Les adapters et la
lecture VTU retournent tous ce meme objet.

### Convention de donnees

`HydroMesh` contient :

- `vertices`
  coordonnees des noeuds, shape `(n_nodes, 2)` ou `(n_nodes, 3)` ;
- `cell_blocks`
  un ou plusieurs blocs homogenes de connectivite ;
- `cell_data`
  donnees par cellule, shape aplatie `(n_cells,)` ;
- `point_data`
  donnees par point, shape aplatie `(n_nodes,)` ;
- `structured_shape`
  hint optionnel pour les grilles structurees.

## Comment L'Utiliser De L'Exterieur

### 1. Construire un maillage depuis du code Python

```python
import numpy as np

from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

vertices = np.array(
    [
        [0.0, 0.0],
        [1.0, 0.0],
        [0.5, 1.0],
        [1.5, 1.0],
    ]
)
connectivity = np.array(
    [
        [0, 1, 2],
        [1, 3, 2],
    ],
    dtype=int,
)

mesh = HydroMesh(
    vertices=vertices,
    cell_blocks=(CellBlock(CellType.TRIANGLE, connectivity),),
)
```

### 2. Ajouter des champs cellule / noeud

```python
mesh = mesh.with_cell_data(conductivity=np.array([1.0e-5, 5.0e-6]))
mesh = mesh.with_point_data(elevation=np.array([10.0, 10.2, 11.1, 10.8]))
```

### 3. Convertir depuis une representation existante

#### Depuis `meshio`

```python
from hydromodpy.spatial.mesh.adapters import from_meshio

hydro_mesh = from_meshio(meshio_mesh)
```

#### Depuis `flopy.StructuredGrid`

```python
from hydromodpy.spatial.mesh.adapters import from_flopy_structured

hydro_mesh = from_flopy_structured(sgrid)
```

#### Depuis un maillage `field` / `gmsh`

```python
from hydromodpy.spatial.mesh.adapters import from_field_mesh, from_gmsh_planar

hydro_mesh = from_field_mesh(field_mesh)
hydro_mesh = from_gmsh_planar(planar_mesh)
```

### 4. Exporter / reimporter un maillage

```python
from hydromodpy.spatial.mesh.io.vtu_io import read_vtu, write_vtu

write_vtu("mesh.vtu", hydro_mesh)
reloaded = read_vtu("mesh.vtu")
```

### 5. Tracer une grandeur par cellule

```python
import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.spatial.mesh.plotting import plot_cell_values

fig, ax = plt.subplots()
mappable = plot_cell_values(
    ax,
    hydro_mesh,
    np.array([1.0, 2.0]),
    cmap="viridis",
    show_mesh=True,
)
fig.colorbar(mappable, ax=ax)
```

## API Publique

### `CellType`

Enumeration des geometries supportees :

- `TRIANGLE`
- `QUADRILATERAL`
- `WEDGE`
- `HEXAHEDRON`

Elle sert a :

- valider la largeur des connectivites ;
- harmoniser les noms avec `meshio` ;
- distinguer les maillages 2D et 3D.

### `CellBlock`

Un bloc homogene de cellules d'un meme type.

Entree :

- `cell_type`
- `connectivity`

Sortie :

- un objet valide, immuable, avec `n_cells`

### `HydroMesh`

Conteneur principal.

Methodes utiles :

- `bounds()`
- `with_cell_data(...)`
- `with_point_data(...)`
- `as_summary()`

Proprietes utiles :

- `ndim`
- `n_nodes`
- `n_cells`
- `is_structured`
- `cell_types`
- `single_cell_type`
- `flat_connectivity`

## Liste Des Parametres

### Parametres de `CellBlock`

| Parametre | Type | Role | Valeur / bonne pratique |
| --- | --- | --- | --- |
| `cell_type` | `CellType | str` | type geometrique du bloc | preferer `CellType.*`; les alias texte sont acceptes pour les adapters |
| `connectivity` | `ndarray[int]` | indices de noeuds par cellule | shape `(n_cells, nodes_per_cell)` strictement compatible avec `cell_type` |

### Parametres de `HydroMesh`

| Parametre | Type | Role | Valeur / bonne pratique |
| --- | --- | --- | --- |
| `vertices` | `ndarray[float]` | coordonnees des noeuds | shape `(n_nodes, 2)` pour 2D, `(n_nodes, 3)` pour 3D |
| `cell_blocks` | `tuple[CellBlock, ...]` | blocs de connectivite | au moins un bloc ; plusieurs blocs seulement si la mixite est vraiment voulue |
| `cell_data` | `dict[str, ndarray]` | champs par cellule | chaque tableau doit avoir `n_cells` valeurs |
| `point_data` | `dict[str, ndarray]` | champs par point | chaque tableau doit avoir `n_nodes` valeurs |
| `structured_shape` | `tuple[int, ...] | None` | hint de grille structuree | `None` pour unstructured ; `(nrow, ncol)` ou `(nlay, nrow, ncol)` sinon |

### Parametres de `plot_cell_values(...)`

| Parametre | Type | Role | Valeur / bonne pratique |
| --- | --- | --- | --- |
| `ax` | `matplotlib.axes.Axes` | support de trace | fourni par l'appelant |
| `hydro_mesh` | `HydroMesh` | maillage a afficher | 2D uniquement |
| `values` | `array-like` | une valeur par cellule | taille exacte `n_cells` |
| `cmap` | `str` | palette Matplotlib | `viridis` par defaut ; garder une palette perceptuelle |
| `show_mesh` | `bool` | affiche les aretes | utile pour QA, a couper pour les cartes finales |
| `vmin`, `vmax` | `float | None` | bornes de couleur | fixer pour comparer plusieurs figures |

### Parametres des adapters publics

#### `from_meshio(mesh)`

| Parametre | Role | Bonne pratique |
| --- | --- | --- |
| `mesh` | objet `meshio.Mesh` | garder uniquement des types de cellules supportes |

#### `to_meshio(hydro_mesh)`

| Parametre | Role | Bonne pratique |
| --- | --- | --- |
| `hydro_mesh` | maillage pivot a exporter | preferer une geometrie 2D/3D propre ; les points 2D seront completes en `z=0` |

#### `from_flopy_structured(sgrid)`

| Parametre | Role | Bonne pratique |
| --- | --- | --- |
| `sgrid` | grille `flopy` structuree | s'appuyer sur `xvertices` / `yvertices` quand disponibles |

#### `to_flopy_disv_args(hydro_mesh, top, botm)`

| Parametre | Role | Bonne pratique |
| --- | --- | --- |
| `hydro_mesh` | maillage 2D a projeter en DISV | utiliser un maillage plan, pas 3D |
| `top` | top global ou par cellule | scalaire ou tableau coherent avec `ncpl` |
| `botm` | bottoms par couche | shape `(nlay, ncpl)` |

### Parametres I/O

#### `write_vtu(path, hydro_mesh)`

| Parametre | Role | Bonne pratique |
| --- | --- | --- |
| `path` | chemin de sortie | utiliser `.vtu` explicitement |
| `hydro_mesh` | maillage a ecrire | verifier `cell_data` / `point_data` avant ecriture |

#### `read_vtu(path)`

| Parametre | Role | Bonne pratique |
| --- | --- | --- |
| `path` | chemin d'entree | verifier que le fichier provient d'un flux compatible `meshio` |

## Bonnes Pratiques

- Preferer `HydroMesh` comme pivot d'echange entre modules, pas comme moteur
  de calcul.
- Garder des noms de champs explicites dans `cell_data` et `point_data`
  (`conductivity`, `layer_index`, `elevation`, etc.).
- Eviter les maillages mixtes sauf si un consumer sait vraiment les lire.
- Conserver `structured_shape` quand le maillage est structure : cela ouvre des
  adapters plus efficaces.
- Utiliser `as_summary()` pour le debug et les resumes JSON legers.
- Pour les comparaisons visuelles, fixer `vmin`/`vmax` et laisser
  `show_mesh=False` si le maillage devient dense.
- Passer par les adapters publics au lieu de reconstruire manuellement les
  connectivites dans plusieurs sous-modules.

## Diagrammes UML Recommandes

Les diagrammes UML sont dans [UML.md](./UML.md).

Je recommande de maintenir au minimum :

- un diagramme de composants du package `mesh` ;
- un diagramme de classes autour de `CellType`, `CellBlock`, `HydroMesh` ;
- un diagramme de sequence d'un flux d'usage externe ;
- un diagramme d'activite pour `plot_cell_values(...)`.

## Refactors Plus Profonds Sans Changer Les Fonctionnalites

Les simplifications suivantes me paraissent pertinentes :

- separer encore plus clairement le **pivot** (`HydroMesh`) des **conversions**
  (`adapters`) et des **affichages** (`plotting`) ;
- introduire un petit protocole `MeshLike -> HydroMesh` commun pour eviter les
  heuristiques `hasattr(...)` dans certains adapters ;
- normaliser les noms de champs standard (`layer_index`, `source_cell_index`,
  `elevation`) dans une petite reference partagee ;
- ajouter un validateur optionnel plus riche pour verifier :
  orientation, degenerescence, types de cellule mixtes, champs manquants ;
- documenter plus explicitement les contrats de compatibilite entre
  `HydroMesh` et `gmsh_grid`, `field`, `flopy`, `meshio`.
