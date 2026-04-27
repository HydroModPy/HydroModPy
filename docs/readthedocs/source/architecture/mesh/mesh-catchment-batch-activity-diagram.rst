Mesh Catchment Batch Activity
=============================

Scope
-----

This diagram documents the control-flow of the dedicated
``[mesh_catchment_batch]`` loop.

It focuses on:

- pre-loop validation of outputs and raster coverage,
- derivation of child workspaces and child outlet coordinates,
- incremental manifest updates,
- the ``continue_on_error`` branch that decides whether the loop stops or
  keeps running.

Code map
--------

- ``hydromodpy/spatial/mesh/batch.py``:
  batch loop, child-workspace derivation, and manifest updates.
- ``hydromodpy/spatial/mesh/runtime.py``:
  reused mono-run entry point.
- ``hydromodpy/spatial/mesh/batch_io.py`` and
  ``hydromodpy/spatial/mesh/batch_reporting.py``:
  persisted progress and summary artifacts.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/mesh/batch.py``
2. ``hydromodpy/spatial/mesh/runtime.py``
3. ``hydromodpy/spatial/mesh/batch_io.py`` and ``batch_reporting.py``

Diagram source
--------------

.. uml:: diagrams/mesh_catchment_batch_activity.wsd

.. literalinclude:: diagrams/mesh_catchment_batch_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - mesh-catchment batch activity

Notes
-----

- The batch loop reuses the same mono-catchment callback as the public
  runtime entry point. There is no separate batch-only meshing engine.
- The manifest CSV is rewritten after each outlet so progress remains visible
  even when the batch stops early.
- A summary that returns without a written mesh file is treated as a failure.

Related diagrams
----------------

- :doc:`mesh-catchment-package-component-diagram`
- :doc:`mesh-catchment-output-layout-activity-diagram`
