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

- ``launchers/mesh_catchment/batch.py``:
  batch loop, child-workspace derivation, and manifest updates.
- ``launchers/mesh_catchment/runtime.py``:
  reused mono-run entry point.
- ``launchers/mesh_catchment/reporting`` or batch-side output helpers:
  persisted progress and summary artifacts.

Recommended reading path
------------------------

1. ``launchers/mesh_catchment/batch.py``
2. ``launchers/mesh_catchment/runtime.py``
3. the batch reporting/output helpers referenced by ``batch.py``

Diagram source
--------------

.. uml:: ../launchers/diagrams/mesh_catchment_batch_activity.wsd

.. literalinclude:: ../launchers/diagrams/mesh_catchment_batch_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - mesh-catchment batch activity

Notes
-----

- The batch loop reuses the same mono-catchment callback as the dedicated
  launcher. There is no separate batch-only meshing engine.
- The manifest CSV is rewritten after each outlet so progress remains visible
  even when the batch stops early.
- A summary that returns without a written mesh file is treated as a failure.

Related diagrams
----------------

- :doc:`mesh-catchment-package-component-diagram`
- :doc:`mesh-catchment-output-layout-activity-diagram`
