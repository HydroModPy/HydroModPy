# UML

Ce fichier propose des diagrammes UML simples pour documenter le coeur
`zone_meshing`.

Les diagrammes sont ecrits en `plantuml` pour rester textuels, versionnables et
faciles a faire evoluer.

## 1. Diagramme De Composants

Ce diagramme montre la separation des responsabilites.

```plantuml
@startuml
package "zone_meshing" {
  [config.py] as Config
  [domain.py] as Domain
  [conformal.py] as Conformal
  [_geometry_cleaning.py] as Cleaning
  [_refinement_grid.py] as Grid
  [_refinement_policy.py] as Policy
  [_gmsh_driver.py] as GmshDriver
}

Config --> Conformal : validated settings
Domain --> Conformal : domain payload
Cleaning --> Conformal : cleaned geometry,\npartition helpers
Grid --> Policy : local indexing
Policy --> Conformal : active refinement curves
GmshDriver --> Conformal : OCC + Gmsh API
@enduml
```

## 2. Diagramme De Classes

Ce diagramme cible les contrats publics manipules le plus souvent.

```plantuml
@startuml
class ZoneMeshingSettings
class ZoneMeshingDomainConfig
class ZoneMeshingDomainPayload
class ZoneLinearConstraint
class ZoneRegionalSizeField
class ZonePartitionFace
class ZoneConformalPartition
class ZoneConformalPhysicalGroup
class ZoneConformalMeshResult

ZoneConformalPartition "1" o-- "*" ZonePartitionFace
ZoneConformalMeshResult "1" o-- "1" ZoneConformalPartition
ZoneConformalMeshResult "1" o-- "*" ZoneConformalPhysicalGroup

ZoneMeshingDomainConfig --> ZoneMeshingDomainPayload : load
ZoneMeshingSettings --> ZoneConformalMeshResult : drives generation
ZoneLinearConstraint --> ZoneConformalMeshResult : embedded as curves
ZoneRegionalSizeField --> ZoneConformalMeshResult : optional size field
@enduml
```

## 3. Diagramme De Sequence

Ce diagramme montre le workflow principal quand on part d'un `GeoDataFrame`.

```plantuml
@startuml
actor User
participant "generate_zone_conformal_mesh_from_dataframe" as Entry
participant "_geometry_cleaning" as Cleaning
participant "_refinement_policy" as Policy
participant "_gmsh_driver" as Gmsh

User -> Entry : gdf + parameters
Entry -> Cleaning : build_zone_conformal_partition_from_dataframe(...)
Cleaning --> Entry : ZoneConformalPartition
Entry -> Entry : normalize constraints\nand regional fields
Entry -> Gmsh : create OCC points/lines/surfaces
Entry -> Policy : build_refinement_candidates(...)
Policy --> Entry : active refinement curves
Entry -> Gmsh : apply mesh fields
Entry -> Gmsh : mesh.generate(2)
Entry -> Gmsh : write + capture runtime mesh
Entry --> User : ZoneConformalMeshResult
@enduml
```

## 4. Diagramme D'Activite

Ce diagramme montre les grandes etapes du pipeline.

```plantuml
@startuml
start
:Validate settings;
:Clean input polygons;
:Build conformal partition;
:Normalize linear constraints;
:Split partition with constraints;
:Create OCC entities;
:Create physical groups;
if (refine_interfaces?) then (yes)
  :Build refinement candidates;
  if (refinement policy enabled?) then (yes)
    :Filter active refinement curves;
  endif
  :Create interface size fields;
endif
if (regional size fields?) then (yes)
  :Create regional size fields;
endif
:Generate 2D mesh with Gmsh;
:Write .msh and build runtime mesh;
:Assemble summary;
stop
@enduml
```

## Diagrammes UML Recommandes A Maintenir

Je recommande de maintenir en priorite :

- le diagramme de composants, pour expliquer l'architecture du package ;
- le diagramme de classes, pour documenter les contrats publics ;
- le diagramme de sequence, pour expliquer comment utiliser le code depuis
  l'exterieur ;
- le diagramme d'activite, pour garder une vue simple du pipeline.

Sur des evolutions plus profondes, un cinquieme diagramme utile serait un
diagramme de sequence dedie au workflow `mesh_catchment -> case planning ->
zone_meshing`.
