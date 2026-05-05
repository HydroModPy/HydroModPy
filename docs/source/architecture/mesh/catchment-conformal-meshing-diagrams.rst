Catchment Conformal Meshing Diagrams
====================================

Scope
-----

These diagrams document the 2D catchment meshing workflow built around:

- ``hydromodpy.spatial.mesh``,
- ``hydromodpy.spatial.mesh.runtime``,
- ``build_domain_geographic_context(...)``,
- ``run_reference_2d_zone_conformal_case_from_toml(...)``,
- the Gmsh zone-conformal meshing core.

They focus on the chain that turns one domain plus optional geology zones and
river constraints into one planar mesh, one QA sidecar, one optional figure,
and one optional exchange bundle.

Code map
--------

- ``hydromodpy/spatial/mesh/runtime.py``:
  public mono-catchment entry point.
- ``hydromodpy/spatial/mesh/hydro_mesh.py``:
  concrete runtime object behind the public facade.
- ``hydromodpy/spatial/geographic`` and related domain helpers:
  geographic context preparation before meshing.
- ``hydromodpy/spatial/mesh/gmsh_grid/zone_meshing/``:
  conformal meshing core and export helpers.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/mesh/runtime.py``
2. ``hydromodpy/spatial/mesh/hydro_mesh.py``
3. ``hydromodpy/spatial/mesh/gmsh_grid/runtime_support.py``
4. ``hydromodpy/spatial/mesh/gmsh_grid/zone_meshing/conformal.py``
5. the surrounding files under ``zone_meshing/`` when a lower-level
   geometry question appears

Recommended UML Views
---------------------

The chosen UML set is intentionally narrow:

- Activity diagram: best to explain the branching logic driven by
  ``constraints_mode`` and by the availability of geology and river
  constraints.
- Sequence diagram: best to explain the concrete runtime handoff
  between the public mesh facade, shared runtime helpers, geographic
  context building, the conformal case, and exports.
- Component diagram: best to document the stable architectural boundaries
  between orchestration, domain/context preparation, constraint sources,
  meshing core, and output exporters.

Use-case and state-machine diagrams are less useful here: the workflow is a
developer-facing data pipeline with short-lived execution, not a long-lived
stateful object model.

Conformal Meshing Activity
--------------------------

.. uml:: diagrams/catchment_conformal_meshing_activity.wsd

.. literalinclude:: diagrams/catchment_conformal_meshing_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - catchment conformal meshing activity

Mesh Facade To Gmsh Sequence
----------------------------

.. uml:: diagrams/catchment_conformal_meshing_sequence.wsd

.. literalinclude:: diagrams/catchment_conformal_meshing_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - catchment conformal meshing sequence

Conformal Meshing Components
----------------------------

.. uml:: diagrams/catchment_conformal_meshing_components.wsd

.. literalinclude:: diagrams/catchment_conformal_meshing_components.wsd
   :language: text
   :caption: PlantUML (.wsd) source - catchment conformal meshing component diagram

Notes
-----

- ``mesh_catchment_batch`` is intentionally not modeled as a separate meshing
  engine. It loops over outlet-specific configs and reuses the same mono-
  catchment runtime.
- These diagrams stop at the planar catchment mesh plus exchange bundle. 3D
  extrusion and field-parameter discretization remain documented separately in
  the other mesh architecture pages.

Related diagrams
----------------

- :doc:`mesh-catchment-package-component-diagram`
- :doc:`mesh-catchment-in-process-simulation-activity-diagram`
- :doc:`sgrid-fieldparam-discretization-diagrams`
