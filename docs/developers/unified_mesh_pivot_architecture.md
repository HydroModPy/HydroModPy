# Maillages dans HydroModPy — Guide développeur

## 1. Vue d'ensemble

HydroModPy manipule plusieurs types de maillages 2D et 3D pour discrétiser
des paramètres hydrogéologiques (conductivité, emmagasinement, recharge, etc.)
et les transmettre aux solveurs (MODFLOW NWT, MODFLOW 6).

Ce document couvre :

- La **hiérarchie de classes** de maillage (`BaseFieldMesh` et ses sous-classes)
- Le **format pivot** `HydroMesh` qui unifie tous les types
- Comment **poser des variables** sur un maillage (`FieldParam`, `FieldSpatial`)
- L'**extrusion 3D** et les profils verticaux
- Le **plotting unifié**, l'**I/O disque** (VTU), les **adaptateurs FloPy**
- Le **pipeline forcing** (recharge, variables climatiques)
- Les **limitations actuelles** et le périmètre du pivot

---

## 2. Types de maillages

### 2.1 Hiérarchie de classes

```
BaseFieldMesh (ABC)                      # hydromodpy/field/core/field_mesh.py
├── StructuredFieldMesh                  # hydromodpy/field/meshes/structured_field_mesh.py
│     _kind = "structured"               # Quadrilatères sur grille régulière
├── TriangularStructuredFieldMesh        # hydromodpy/field/meshes/triangular_field_mesh.py
│     _kind = "triangular_structured"    # Triangles sur grille régulière
├── TriangularUnstructuredFieldMesh      # hydromodpy/field/meshes/triangular_field_mesh.py
│     _kind = "triangular_unstructured"  # Triangles Delaunay aléatoires
├── GeologyStructuredMesh                # hydromodpy/data_managers/geology/geology_mesh.py
│     _kind = "structured_rect"          # Quadrilatères en coordonnées réelles
└── GmshPlanarMesh2D                     # hydromodpy/solver/utils/mesh/gmsh_grid/gmsh_planar_mesh.py
      _kind = "gmsh_2d"                  # Triangles ou quads depuis fichier .msh

ExtrudedPrismMesh3D                      # hydromodpy/solver/utils/mesh/gmsh_grid/extruded_prism_mesh.py
      # Prismes 3D par extrusion verticale d'un GmshPlanarMesh2D
```

### 2.2 Contrat commun (`BaseFieldMesh`)

Toutes les sous-classes implémentent :

| Propriété / Méthode | Description |
|---------------------|-------------|
| `x_plot`, `y_plot` | Coordonnées des nœuds (1D ou 2D arrays) |
| `shape` | Forme du tableau de nœuds `(ny, nx)` ou `(n_nodes,)` |
| `n_nodes` | Nombre total de nœuds |
| `n_cells` | Nombre total de cellules |
| `cells` | Tuple de `MeshCell` (géométrie explicite par cellule) |
| `iter_cells()` | Générateur de `MeshCell` |
| `cell_centroids()` | Coordonnées des centres de cellules |
| `to_cell_values(values)` | Normalise un tableau brut en 1 valeur / cellule |
| `plot_cell_values(ax, values, ...)` | Visualisation matplotlib |
| `to_hydro_mesh()` | Conversion vers le format pivot `HydroMesh` |
| `attach_cell_values(values, label)` | Retourne un `MeshWithValues` |

### 2.3 `MeshCell` — une cellule individuelle

```python
@dataclass(frozen=True)
class MeshCell:
    index: int                        # Indice global dans le maillage
    kind: str                         # "triangle", "quadrilateral"
    node_indices: tuple[int, ...]     # Indices des nœuds
    vertices: np.ndarray              # Coordonnées (n_nodes_per_cell, 2)
    centroid: tuple[float, float]     # Centre de la cellule
```

### 2.4 `MeshWithValues` — maillage + données

```python
@dataclass(frozen=True)
class MeshWithValues:
    mesh: BaseFieldMesh
    cell_values: np.ndarray    # 1 valeur par cellule
    label: str | None = None
```

C'est le type de retour de `FieldParam.to_mesh_field()` — le résultat de la
discrétisation d'un paramètre sur un maillage.

---

## 3. Créer un maillage

### 3.1 Grille structurée (carré unitaire)

```python
from hydromodpy.field.cases.square.field_mesh_square import FieldMeshSquare

# Grille quadrilatérale 20×20 = 400 cellules
mesh = FieldMeshSquare.from_unit_square(
    target_n_cells=400,
    mesh_kind="structured",    # "structured" | "triangular_structured" | "triangular_unstructured"
    seed=42,
)
# mesh.kind == "structured"
# mesh.n_cells == 400
# mesh.shape == (21, 21)  # nœuds
```

### 3.2 Grille triangulaire structurée

```python
mesh = FieldMeshSquare.from_unit_square(
    target_n_cells=400,
    mesh_kind="triangular_structured",
)
# mesh.kind == "triangular_structured"
# mesh.n_cells == 800  # ~2× plus de cellules (chaque quad → 2 triangles)
```

### 3.3 Grille triangulaire non-structurée (Delaunay)

```python
mesh = FieldMeshSquare.from_unit_square(
    target_n_cells=400,
    mesh_kind="triangular_unstructured",
    seed=42,  # reproductibilité des points aléatoires
)
```

### 3.4 Maillage Gmsh depuis fichier `.msh`

```python
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D

planar = GmshPlanarMesh2D.from_file("domain.msh")
# planar.points_xy → ndarray (n_nodes, 2)
# planar.connectivity → ndarray (n_cells, 3)  ou (n_cells, 4)
# planar.cell_type → "triangle" ou "quadrilateral"
```

### 3.5 Maillage géologique en coordonnées réelles

```python
from hydromodpy.data_managers.geology.geology_mesh import GeologyStructuredMesh

mesh = GeologyStructuredMesh.from_bounds(
    [xmin, ymin, xmax, ymax],
    target_n_cells=400,
)
# mesh.kind == "structured_rect"
```

### 3.6 Maillage 3D extrudé (prismes)

```python
from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh import ExtrudedPrismMesh3D

mesh_3d = ExtrudedPrismMesh3D.from_planar_mesh(
    planar,
    z_interfaces=[0.0, -5.0, -15.0, -50.0],  # 3 couches
)
# mesh_3d.n_layers == 3
# mesh_3d.n_prisms == n_cells_2d × n_layers
# mesh_3d.cell_type_3d → "triangular_prism" ou "quadrilateral_prism"
```

Alternative avec épaisseurs :

```python
mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
    planar,
    top_z=100.0,
    layer_thicknesses=[5.0, 10.0, 35.0],
)
```

### 3.7 Depuis la configuration TOML

```python
mesh = FieldMeshSquare.from_toml("config.toml", section="mesh")
```

Avec un TOML contenant :

```toml
[mesh]
target_n_cells = 400
mesh_kind = "structured"
seed = 42
```

---

## 4. Poser des variables sur un maillage

Le pipeline de discrétisation utilise trois objets :

| Objet | Rôle |
|-------|------|
| `Field` (ou `FieldSpatial`) | Géométrie spatiale : définit les zones (ex : granite / micaschistes) |
| `FieldParam` | Valeur du paramètre : scalaire ou par zone, avec unité et profil vertical |
| `BaseFieldMesh` | Support géométrique : les cellules sur lesquelles discrétiser |

### 4.1 Cas homogène (valeur unique)

```python
from hydromodpy.field.core.field_param import FieldParam

K = FieldParam(
    identifier="K",
    kind="homogeneous",
    unit="m/s",
    value=1e-4,
)

# Discrétiser sur un maillage :
result = K.to_mesh_field(mesh=mesh)
# result.cell_values → ndarray, toutes les cellules = 1e-4
# result.mesh == mesh
```

### 4.2 Cas hétérogène (plusieurs zones)

Trois étapes :

```python
# 1) Définir la géométrie spatiale (zones)
from hydromodpy.field.cases.square.field_spatial_square import FieldSquare

field = FieldSquare(
    line="diag_main",           # diag_main | diag_anti | axis_vertical | axis_horizontal
    zone1_side="positive",
    identifier="geology_field",
    zone1_name="granite",
    zone2_name="micaschists",
)

# 2) Projeter les zones sur le maillage
#    → calcule la fraction de chaque zone dans chaque cellule
field_discretization = field.on_mesh(mesh, cell_samples_per_axis=10)
# field_discretization.weighted_components() → (zone_keys, fractions_by_zone)

# 3) Discrétiser le paramètre avec la répartition des zones
K = FieldParam(
    identifier="K",
    kind="heterogeneous",
    unit="m/s",
    values_by_key={"granite": 1e-4, "micaschists": 1e-6},
    field_spatial_id="geology_field",
)

result = K.to_mesh_field(field_discretization)
# result.cell_values → moyenne pondérée par zone dans chaque cellule
# Cellule 100% granite → 1e-4
# Cellule 60% granite / 40% micaschistes → 0.6 × 1e-4 + 0.4 × 1e-6
```

### 4.3 Profil vertical (variation avec la profondeur)

Le `FieldParam` peut porter un profil vertical multiplicatif :

```python
K = FieldParam(
    identifier="K",
    kind="homogeneous",
    unit="m/s",
    value=1e-4,
    vertical_profile={
        "mode": "exponential",     # "none" | "exponential" | "tabulated"
        "decay_length": 30.0,      # K(z) = K_ref × exp(-z/30)
        "min_factor": 0.01,        # plancher à 1% de K_ref
    },
)

# Facteur à 10 m de profondeur :
factor = K.vertical_factor(depth=10.0)  # ≈ 0.716

# Facteur à 100 m :
factor = K.vertical_factor(depth=100.0)  # ≈ 0.036
```

Mode tabulé :

```python
vertical_profile={
    "mode": "tabulated",
    "depths": [0.0, 10.0, 50.0, 100.0],
    "factors": [1.0, 0.8, 0.3, 0.05],
}
```

### 4.4 Discrétisation 3D sur grille structurée (SGrid)

Pour le pipeline MODFLOW (grille flopy `StructuredGrid`) :

```python
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_fieldparam_discretization import (
    discretize_fieldparam_on_sgrid,
)

result = discretize_fieldparam_on_sgrid(
    support_field=field,     # Field (zones spatiales), ou None si homogène
    field_param=K,           # FieldParam
    sgrid=model.modelgrid,   # flopy StructuredGrid (nrow, ncol, nlay)
)
# result.values_3d → (nlay, nrow, ncol)  — valeur par cellule avec profil vertical
# result.values_2d → (nrow, ncol)        — valeur de référence en surface
```

### 4.5 Discrétisation 3D sur maillage extrudé (Gmsh)

Pour les maillages non-structurés :

```python
from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_fieldparam_discretization import (
    discretize_fieldparam_on_extruded_mesh,
)

result = discretize_fieldparam_on_extruded_mesh(
    support_field=field,
    field_param=K,
    mesh_3d=mesh_3d,           # ExtrudedPrismMesh3D
)
# result.values_3d → (n_layers, n_cells_2d)
# result.prism_center_depths → (n_layers, n_cells_2d)
```

### 4.6 Unités

Les valeurs sont **toujours stockées en SI** dans `FieldParam`. La conversion
depuis l'unité d'entrée est automatique à la construction :

| Paramètre | Unités acceptées | Stockage interne |
|-----------|-----------------|-----------------|
| K (conductivité) | m/s, m/day, cm/s, cm/day, m/min, cm/min | m/s |
| Sy (porosité efficace) | - (sans dimension) | - |
| Ss (emmagasinement spécifique) | m⁻¹, cm⁻¹ | m⁻¹ |

---

## 5. Format pivot `HydroMesh`

### 5.1 Principe

`HydroMesh` est un **conteneur de données immuable** qui représente n'importe
quel maillage 2D ou 3D de façon uniforme :

```python
from hydromodpy.mesh import HydroMesh, CellBlock, CellType

mesh = HydroMesh(
    vertices=points_xy,                              # ndarray (n_nodes, 2|3)
    cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),  # connectivité
    cell_data={"K": conductivity_array},              # scalaires par cellule
    point_data={},                                    # scalaires par nœud
    structured_shape=(nrow, ncol),                    # hint optionnel
)
```

### 5.2 Pourquoi un format pivot ?

Avant `HydroMesh`, chaque type de maillage avait son propre modèle de données
et ses propres routines de plotting. Écrire du code générique (ex : un
post-traitement qui marche sur structuré ET non-structuré) était impossible
sans coupler au type concret.

`HydroMesh` résout cela :

```
StructuredFieldMesh ─┐
TriangularFieldMesh ─┤                  ┌── plot_cell_values()
GmshPlanarMesh2D ────┼── .to_hydro_mesh() ──┼── write_vtu() / read_vtu()
ExtrudedPrismMesh3D ─┤                  ├── to_flopy_disv_args()
FloPy StructuredGrid ┘                  └── to_meshio()
```

### 5.3 Types de cellules (`CellType`)

```
TRIANGLE        3 nœuds   2D   aliases: "tri", "triangle", "triangles"
QUADRILATERAL   4 nœuds   2D   aliases: "quad", "quads", "quadrilateral"
WEDGE           6 nœuds   3D   aliases: "wedge", "triangular_prism"
HEXAHEDRON      8 nœuds   3D   aliases: "hex", "hexahedron", "quadrilateral_prism"
```

Propriétés utiles :

```python
CellType.TRIANGLE.nodes_per_cell  # 3
CellType.TRIANGLE.dimension       # 2
CellType.TRIANGLE.meshio_name     # "triangle"
CellType.from_string("tri")       # CellType.TRIANGLE
```

### 5.4 Propriétés de `HydroMesh`

| Propriété | Type | Description |
|-----------|------|-------------|
| `ndim` | int | 2 ou 3 (dimension spatiale) |
| `n_nodes` | int | Nombre de sommets |
| `n_cells` | int | Nombre total de cellules |
| `is_structured` | bool | `True` si `structured_shape` est défini |
| `cell_types` | tuple[CellType] | Types de cellules par bloc |
| `single_cell_type` | CellType | Type unique (lève si mélange) |
| `flat_connectivity` | ndarray | Connectivité concaténée de tous les blocs |
| `bounds()` | tuple | `(xmin, ymin, [zmin,] xmax, ymax, [zmax])` |

### 5.5 Immuabilité

`HydroMesh` est une `frozen dataclass`. Pour ajouter des données :

```python
# Ajouter des données par cellule :
mesh2 = mesh.with_cell_data(K=conductivity, Sy=porosity)

# Ajouter des données par nœud :
mesh2 = mesh.with_point_data(head=head_values)
```

Ces méthodes retournent une **nouvelle instance** sans modifier l'originale.

### 5.6 Conversions

Toutes les classes de maillage exposent `.to_hydro_mesh()` :

```python
# Depuis n'importe quel BaseFieldMesh :
hm = structured_mesh.to_hydro_mesh()
hm = triangular_mesh.to_hydro_mesh()

# Depuis GmshPlanarMesh2D (override optimisé) :
hm = planar.to_hydro_mesh()

# Depuis ExtrudedPrismMesh3D :
hm = mesh_3d.to_hydro_mesh()
# → préserve cell_data["layer_index"] et cell_data["source_cell_index"]

# Depuis flopy StructuredGrid :
from hydromodpy.mesh.adapters import from_flopy_structured
hm = from_flopy_structured(model.modelgrid)

# Retour vers GmshPlanarMesh2D :
planar_bis = GmshPlanarMesh2D.from_hydro_mesh(hm)
```

### 5.7 Le hint `structured_shape`

Quand un maillage provient d'une grille régulière, `structured_shape` conserve
`(nrow, ncol)`. Cela permet au plotting d'utiliser `pcolormesh` (plus rapide
que `PolyCollection`) et aux exports d'utiliser le format DIS au lieu de DISV.

```python
hm = structured_mesh.to_hydro_mesh()
hm.is_structured          # True
hm.structured_shape       # (20, 20)
```

---

## 6. Plotting unifié

### 6.1 Fonction unique

```python
from hydromodpy.mesh.plotting import plot_cell_values

fig, ax = plt.subplots()
mappable = plot_cell_values(ax, hydro_mesh, values, cmap="coolwarm")
fig.colorbar(mappable)
```

### 6.2 Dispatch automatique

La fonction détecte la stratégie de rendu à partir de la topologie :

| Condition | Stratégie | Performance |
|-----------|-----------|-------------|
| `is_structured` + QUADRILATERAL | `pcolormesh` | Très rapide |
| TRIANGLE | `tripcolor` | Rapide |
| Tout autre (QUAD non-structuré, mixte) | `PolyCollection` | Plus lent |

### 6.3 Depuis les classes existantes

Les méthodes `plot_cell_values()` des classes existantes **délèguent** toutes
au plotter unifié en interne :

```python
# Ces 3 appels font la même chose en interne :
structured_mesh.plot_cell_values(ax, values)
structured_mesh.to_hydro_mesh()  # → puis plot_cell_values(ax, hm, values)

# L'interface publique ne change pas — le code appelant n'a rien à modifier.
```

Classes concernées :
- `StructuredFieldMesh.plot_cell_values()`
- `TriangularStructuredFieldMesh.plot_cell_values()`
- `TriangularUnstructuredFieldMesh.plot_cell_values()`
- `GmshPlanarMesh2D.plot_cell_values()`
- `GeologyStructuredMesh.plot_cell_values()`
- `extruded_mesh_visualization.plot_planar_cell_values()`

---

## 7. I/O disque

### 7.1 Format VTU (recommandé)

VTU (VTK Unstructured Grid XML) est le format de sérialisation recommandé :

```python
from hydromodpy.mesh.io import write_vtu, read_vtu

# Écriture :
write_vtu("output.vtu", hydro_mesh)

# Lecture :
mesh = read_vtu("output.vtu")
```

Avantages du VTU :
- Auto-descriptif (sommets, connectivité, types de cellules, données)
- Supporté par ParaView, PyVista, meshio, QGIS
- Agnostique 2D/3D et structuré/non-structuré
- Round-trip garanti avec `HydroMesh`

Dépendance : `meshio` (optionnel, importé à la demande).

### 7.2 Format Gmsh (`.msh`)

Pour les maillages Gmsh :

```python
# Lecture :
planar = GmshPlanarMesh2D.from_file("domain.msh")

# Écriture :
planar.to_file("output.msh")
```

### 7.3 API publique d'échange (exchange_api)

L'API publique dans `hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api` :

```python
from hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api import (
    load_planar_as_hydro_mesh,     # .msh → HydroMesh 2D
    load_extruded_as_hydro_mesh,   # .vtu → HydroMesh 3D
    save_hydro_mesh_vtu,           # HydroMesh → .vtu
    load_hydro_mesh_vtu,           # .vtu → HydroMesh
)
```

### 7.4 Conversion meshio round-trip

```python
from hydromodpy.mesh.adapters import from_meshio, to_meshio

# HydroMesh → meshio.Mesh :
meshio_mesh = to_meshio(hydro_mesh)

# meshio.Mesh → HydroMesh :
hydro_mesh = from_meshio(meshio_mesh)
```

---

## 8. Adaptateurs FloPy

### 8.1 Import depuis flopy (DIS → HydroMesh)

```python
from hydromodpy.mesh.adapters import from_flopy_structured

sgrid = model.modelgrid  # flopy StructuredGrid
hm = from_flopy_structured(sgrid)
# hm.is_structured == True
# hm.structured_shape == (nrow, ncol)
# hm.single_cell_type == CellType.QUADRILATERAL
```

### 8.2 Export vers MODFLOW 6 DISV

```python
from hydromodpy.mesh.adapters import to_flopy_disv_args

disv_kwargs = to_flopy_disv_args(
    hydro_mesh,
    top=100.0,
    botm=botm_array,   # (nlay, ncpl)
)
# disv_kwargs = {nvert, vertices, ncpl, cell2d, top, botm}

flopy.mf6.ModflowGwfdisv(gwf, **disv_kwargs)
```

---

## 9. Pipeline forcing (recharge et variables climatiques)

### 9.1 Contexte

Les variables climatiques (recharge, précipitations, ETP, etc.) transitent
par le système `LoadResult` → `ForcingBridge` → `Flow`.

### 9.2 Chaîne de traitement

```
DataManager.load()
       │
       ▼
   LoadResult          # points: list[PointRecord], fields: list[FieldRecord]
       │
       ▼
resolve_forcing()      # → ResolvedForcing (homogène ou hétérogène)
       │
       ▼
apply_recharge_load_result_to_flow()   # → FlowRechargeConfig → Flow
       │
       ▼
SolverAdapter          # FlowModflowInputs → MODFLOW packages
```

### 9.3 Modes spatiaux

| Mode | Description | Pipeline |
|------|-------------|----------|
| Homogène | Valeur unique par pas de temps | `series: pd.Series` (m/s) |
| Hétérogène | Valeur par cellule par pas de temps | `LoadResult.fields` → interpolation sur grille |

### 9.4 Limitation actuelle

**Le pipeline forcing est actuellement câblé sur les grilles structurées.**
La discrétisation hétérogène utilise `sgrid.nrow` / `sgrid.ncol` pour
construire les tableaux 2D. Le support des maillages non-structurés (DISV)
nécessiterait d'adapter la discrétisation spatiale des `FieldRecord` sur
les cellules d'un `HydroMesh` au lieu d'une grille `(nrow, ncol)`.

---

## 10. Architecture du module `hydromodpy/mesh/`

```
hydromodpy/mesh/
├── __init__.py              # Exports : CellType, CellBlock, HydroMesh
├── cell_types.py            # Enum CellType + aliases + propriétés
├── hydro_mesh.py            # CellBlock + HydroMesh (frozen dataclasses)
├── plotting.py              # plot_cell_values() — dispatch unifié
├── adapters/
│   ├── __init__.py          # Re-exports de tous les adaptateurs
│   ├── meshio_adapter.py    # from_meshio() / to_meshio()
│   ├── field_mesh_adapter.py   # from_field_mesh() / from_gmsh_planar() / from_extruded_prism()
│   └── flopy_adapter.py     # from_flopy_structured() / to_flopy_disv_args()
└── io/
    └── vtu_io.py            # write_vtu() / read_vtu()
```

### 10.1 Dépendances

Le cœur (`cell_types.py`, `hydro_mesh.py`) ne dépend que de **numpy**.

| Module | Dépendances supplémentaires |
|--------|---------------------------|
| `plotting.py` | matplotlib |
| `meshio_adapter.py` | meshio (optionnel) |
| `vtu_io.py` | meshio (optionnel) |
| `flopy_adapter.py` | flopy (import lazy de `sgrid_mesh_adapter`) |
| `field_mesh_adapter.py` | Aucune (duck-typing sur `BaseFieldMesh`) |

---

## 11. Flux de données complet

```
                    ┌──────────────────────────────────────┐
                    │         Configuration TOML            │
                    │  [field] [mesh] [field_param]         │
                    └──────┬───────────┬───────────────────┘
                           │           │
                           ▼           ▼
                    FieldSquare    FieldParam
                    (géométrie)    (K=1e-4 m/s, zones, profil vertical)
                           │           │
                           ▼           │
                    field.on_mesh()    │
                           │           │
                           ▼           ▼
                    FieldDiscretization    ←── field_param.to_mesh_field()
                    (zone_keys, fractions)           │
                                                     ▼
                                              MeshWithValues
                                              (mesh + cell_values)
                                                     │
                    ┌────────────────────────────────┼───────────────────┐
                    │                                │                   │
                    ▼                                ▼                   ▼
        discretize_fieldparam       discretize_fieldparam    .to_hydro_mesh()
          _on_sgrid()                _on_extruded_mesh()            │
                    │                                │              ▼
                    ▼                                ▼         HydroMesh
        values_3d (nlay,nrow,ncol)   values_3d (nlay,n2d)         │
                    │                                │       ┌────┼────┐
                    ▼                                ▼       │    │    │
             MODFLOW NWT/6                    export VTU   plot  VTU  DISV
```

---

## 12. Méthodes ajoutées aux classes existantes

| Classe | Méthode | Notes |
|--------|---------|-------|
| `BaseFieldMesh` | `to_hydro_mesh()` | Hérité par toutes les sous-classes |
| `GmshPlanarMesh2D` | `to_hydro_mesh()` | Override optimisé (accès direct aux arrays) |
| `GmshPlanarMesh2D` | `from_hydro_mesh(hm)` | Classmethod, reconstruit depuis HydroMesh 2D |
| `ExtrudedPrismMesh3D` | `to_hydro_mesh()` | Préserve `layer_index` et `source_cell_index` |

---

## 13. Relation avec les classes existantes

Les classes existantes (`GmshPlanarMesh2D`, `StructuredFieldMesh`, etc.)
**restent en place**. `HydroMesh` ne les remplace pas — il sert de format
d'échange entre elles.

Chaque classe conserve sa logique métier (génération, validation,
association avec `FieldParam`) et peut produire ou consommer un `HydroMesh`
via `.to_hydro_mesh()`.

À terme, les nouveaux modules devraient préférer `HydroMesh` comme type
d'entrée/sortie plutôt que de dépendre directement d'une implémentation
concrète.

---

## 14. Limitations actuelles et périmètre

| Fonctionnalité | Structuré (DIS) | Non-structuré (DISV) |
|---------------|-----------------|---------------------|
| FieldParam → discrétisation 2D | Oui | Oui |
| FieldParam → discrétisation 3D | Oui (`sgrid`) | Oui (`extruded_mesh`) |
| Plotting unifié | Oui | Oui |
| I/O VTU | Oui | Oui |
| MODFLOW NWT solver | Oui (DIS) | Non (DIS uniquement) |
| MODFLOW 6 solver | Oui (DIS) | Non (DISV pas câblé) |
| Pipeline recharge/forcing | Oui | Non (hardcodé `nrow×ncol`) |
| Export DISV vers flopy | Disponible (`to_flopy_disv_args`) | Non câblé au solver |

**En résumé :** le pivot `HydroMesh` unifie le plotting, l'I/O et les
conversions entre types de maillages. La discrétisation des paramètres
(`FieldParam`) fonctionne sur tous les types. Mais le pipeline
solver (MODFLOW NWT / MF6) et le pipeline forcing restent structurés
uniquement. L'adaptateur `to_flopy_disv_args()` existe pour DISV mais
n'est pas encore branché dans le runner de simulation.

---

## 15. Choix de conception

### 15.1 Pourquoi pas xugrid / UGRID NetCDF ?

- **xugrid** est excellent pour le 2D + pseudo-3D layered (UGRID2D), mais ne
  supporte pas le fully 3D unstructured.
- Pour le stockage de résultats temporels (time series par cellule), UGRID
  NetCDF reste pertinent via xugrid comme format de *sortie*.
- Mais comme format *pivot interne*, vertices + connectivity est plus simple,
  plus général, et sans dépendance lourde.

### 15.2 Pourquoi pas meshio directement ?

meshio est une dépendance optionnelle (I/O), pas un type pivot :
- `meshio.Mesh` n'est pas frozen/immutable
- Il supporte ~30 types de cellules dont la plupart ne nous concernent pas
- Le mapping `cell_data` est en listes de listes (par block), pas en arrays plats

`HydroMesh` est un sous-ensemble strict et normalisé du modèle meshio,
avec des conversions round-trip garanties par les adaptateurs.

### 15.3 Pourquoi frozen dataclass ?

L'immuabilité garantit qu'un `HydroMesh` ne peut pas être modifié après
construction. Cela simplifie le raisonnement sur le flux de données et
évite les bugs liés à des mutations accidentelles. Les méthodes
`with_cell_data()` / `with_point_data()` retournent des copies.
