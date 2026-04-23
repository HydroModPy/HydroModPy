Mesh Catchment Output Layout
============================

Scope
-----

This diagram documents how the dedicated mesh workflow resolves final
artifacts and cleanup behavior.

It focuses on:

- the ``standard`` versus ``flat`` output layout split,
- optional figure generation,
- exchange-bundle export,
- cleanup of intermediate geographic artifacts,
- extra naming and manifest rules when batch mode is active.

Code map
--------

- ``launchers/mesh_catchment/runtime_single_run.py``:
  resolution of final artifacts for one mono-run execution.
- batch-side helpers under ``launchers/mesh_catchment/batch.py``:
  outlet-specific naming and manifest rules.
- ``hydromodpy/spatial/mesh/gmsh_grid`` exporters:
  mesh, figure, sidecar, and exchange-bundle persistence.

Recommended reading path
------------------------

1. ``launchers/mesh_catchment/runtime_single_run.py``
2. ``launchers/mesh_catchment/batch.py`` when batch naming matters
3. the exporter helpers under ``hydromodpy/spatial/mesh/gmsh_grid/``

Diagram source
--------------

.. uml:: ../launchers/diagrams/mesh_catchment_output_layout_activity.wsd

.. literalinclude:: ../launchers/diagrams/mesh_catchment_output_layout_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - mesh-catchment output layout activity

Notes
-----

- ``flat`` layout is a dedicated-launcher convenience. It writes the final mesh
  artifacts directly under ``workspace.project_root`` while the intermediate
  runtime workspace lives elsewhere and can be deleted afterwards.
- ``process_simulation`` keeps the standard workspace structure because the
  simulation workflow still needs its runtime folders.
- Batch mode adds per-outlet filename patterns and one manifest CSV, but it
  still reuses the same mono-catchment output-resolution rules.

Related diagrams
----------------

- :doc:`mesh-catchment-batch-activity-diagram`
- :doc:`mesh-catchment-in-process-simulation-activity-diagram`
