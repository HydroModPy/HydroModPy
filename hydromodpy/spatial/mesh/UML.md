# UML

Ce fichier propose quelques diagrammes UML simples pour documenter le package
`hydromodpy.spatial.mesh`.

Les diagrammes sont fournis en `plantuml` pour rester :

- textuels ;
- faciles a versionner ;
- faciles a mettre a jour pendant les refactors.

## 1. Diagramme De Composants

```plantuml
@startuml
package "hydromodpy.spatial.mesh" {
  [cell_types.py] as CellTypes
  [hydro_mesh.py] as HydroMesh
  [plotting.py] as Plotting
  package adapters {
    [meshio_adapter.py] as MeshioAdapter
    [flopy_adapter.py] as FlopyAdapter
    [field_mesh_adapter.py] as FieldAdapter
  }
  package io {
    [vtu_io.py] as VTUIO
  }
}

CellTypes --> HydroMesh : validates cell types
HydroMesh --> Plotting : rendered by
HydroMesh --> MeshioAdapter : converted to/from
HydroMesh --> FlopyAdapter : converted to/from
HydroMesh --> FieldAdapter : converted to/from
MeshioAdapter --> VTUIO : used by
@enduml
```

## 2. Diagramme De Classes

```plantuml
@startuml
enum CellType {
  TRIANGLE
  QUADRILATERAL
  WEDGE
  HEXAHEDRON
}

class CellBlock {
  +cell_type : CellType
  +connectivity : ndarray
  +n_cells : int
}

class HydroMesh {
  +vertices : ndarray
  +cell_blocks : tuple[CellBlock, ...]
  +cell_data : dict[str, ndarray]
  +point_data : dict[str, ndarray]
  +structured_shape : tuple[int, ...]?
  +ndim : int
  +n_nodes : int
  +n_cells : int
  +is_structured : bool
  +bounds()
  +with_cell_data(...)
  +with_point_data(...)
  +as_summary()
}

CellBlock --> CellType
HydroMesh "1" o-- "*" CellBlock
@enduml
```

## 3. Diagramme De Sequence

Exemple d'usage externe typique :

```plantuml
@startuml
actor User
participant "from_gmsh_planar(...)" as Adapter
participant "HydroMesh" as Mesh
participant "plot_cell_values(...)" as Plotting
participant "write_vtu(...)" as VTU

User -> Adapter : planar_mesh
Adapter --> User : HydroMesh
User -> Mesh : with_cell_data(...)
Mesh --> User : HydroMesh enriched
User -> Plotting : mesh + values
Plotting --> User : matplotlib mappable
User -> VTU : path + mesh
VTU --> User : written file
@enduml
```

## 4. Diagramme D'Activite

```plantuml
@startuml
start
:Receive vertices and connectivity;
:Validate cell types and connectivity shape;
:Build HydroMesh;
if (Need conversion?) then (yes)
  :Use appropriate adapter;
endif
if (Need plotting?) then (yes)
  :Dispatch to structured / triangle / polygon renderer;
endif
if (Need disk export?) then (yes)
  :Convert to meshio;
  :Write VTU;
endif
stop
@enduml
```

## Diagrammes Les Plus Utiles A Maintenir

Je recommande de maintenir en priorite :

- le diagramme de composants, pour expliquer la separation pivot /
  adapters / io / plotting ;
- le diagramme de classes, pour documenter `HydroMesh` comme contrat de
  donnees ;
- le diagramme de sequence, pour montrer comment le package est utilise de
  l'exterieur.
