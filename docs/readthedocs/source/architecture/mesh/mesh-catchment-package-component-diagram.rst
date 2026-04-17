Mesh Catchment Package Components
=================================

Scope
-----

This diagram documents the internal package layout of the dedicated
``mesh_catchment`` workflow.

It focuses on:

- public launcher entry points,
- separation between the public runtime facade and the concrete mono-run path,
- batch-specific IO and reporting helpers,
- versioned scenarios and operational tools that live next to the runtime code.

Code map
--------

- ``launchers/mesh_catchment/runtime.py``:
  public runtime facade.
- ``launchers/mesh_catchment/runtime_single_run.py``:
  concrete mono-run execution path.
- ``launchers/mesh_catchment/batch.py``:
  batch orchestration and manifest handling.
- ``launchers/mesh_catchment/scenarios`` and ``tools``:
  versioned operational assets next to the runtime core.

Recommended reading path
------------------------

1. ``launchers/mesh_catchment/runtime.py``
2. ``launchers/mesh_catchment/runtime_single_run.py``
3. ``launchers/mesh_catchment/batch.py``
4. one scenario or tool file only if the question is operational rather than
   architectural

Diagram source
--------------

.. uml:: ../launchers/diagrams/mesh_catchment_package_components.wsd

.. literalinclude:: ../launchers/diagrams/mesh_catchment_package_components.wsd
   :language: text
   :caption: PlantUML (.wsd) source - mesh-catchment package components

Notes
-----

- ``runtime.py`` is intentionally thin. It validates the public launcher
  payloads and delegates the concrete mono-run path to
  ``runtime_single_run.py``.
- ``batch.py`` does not implement a second meshing engine. It derives one
  outlet-specific child runtime, then reuses the same mono-catchment callback.
- ``scenarios/`` and ``tools/`` are part of the package discoverability story,
  but they are versioned operational assets rather than the runtime core.
- For launcher-level simulation orchestration around those mesh artifacts, see
  :doc:`../launchers/launcher-simulation-sequence-diagram`.

Related diagrams
----------------

- :doc:`mesh-catchment-batch-activity-diagram`
- :doc:`catchment-conformal-meshing-diagrams`
