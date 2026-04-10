Mesh Catchment Package Components
=================================

Scope
-----

This diagram documents the internal package layout of the dedicated
``mesh_catchment`` launcher family.

It focuses on:

- public launcher entry points,
- separation between the public runtime facade and the concrete mono-run path,
- batch-specific IO and reporting helpers,
- versioned scenarios and operational tools that live next to the code.

Diagram source
--------------

.. uml:: diagrams/mesh_catchment_package_components.wsd

.. literalinclude:: diagrams/mesh_catchment_package_components.wsd
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
