Mesh Catchment Output Layout
============================

Scope
-----

This diagram documents how the mesh-catchment runner resolves final artifacts
and cleanup behavior. In the user guide, mesh studies are routed through the
testbed workflow; this architecture page describes the lower-level runner that
the testbed delegates to.

It focuses on:

- the ``standard`` versus ``flat`` output layout split,
- optional figure generation,
- exchange-bundle export,
- cleanup of intermediate geographic artifacts,
- extra naming and manifest rules when batch mode is active.

Code map
--------

- ``hydromodpy/spatial/mesh/runtime.py``:
  resolution of final artifacts for one mono-run execution.
- ``hydromodpy/spatial/mesh/batch.py``:
  outlet-specific naming and manifest rules.
- ``hydromodpy/spatial/mesh/gmsh_grid`` exporters:
  mesh, figure, sidecar, and exchange-bundle persistence.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/mesh/runtime.py``
2. ``hydromodpy/spatial/mesh/batch.py`` when batch naming matters
3. the exporter helpers under ``hydromodpy/spatial/mesh/gmsh_grid/``

Diagram source
--------------

.. uml:: diagrams/mesh_catchment_output_layout_activity.wsd

.. literalinclude:: diagrams/mesh_catchment_output_layout_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - mesh-catchment output layout activity

Notes
-----

- ``flat`` layout is a convenience for mesh-catchment runner executions. It
  writes the final mesh artifacts directly under
  ``workspace.project_root`` while the intermediate runtime workspace
  lives elsewhere and can be deleted afterwards.
- The full simulation workflow keeps the standard workspace structure
  because it still needs its runtime folders.
- Batch mode adds per-outlet filename patterns and one manifest CSV,
  but it still reuses the same mono-catchment output-resolution rules.

Related diagrams
----------------

- :doc:`mesh-catchment-batch-activity-diagram`
- :doc:`mesh-catchment-in-process-simulation-activity-diagram`
