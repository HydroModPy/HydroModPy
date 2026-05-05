Mesh Catchment Package Components
=================================

Scope
-----

This diagram documents the internal package layout of the
``hydromodpy.spatial.mesh`` package, which owns the catchment-mesh
generation workflow.

It focuses on:

- public runtime entry points used by ``Project.build_mesh()``,
- the runtime facade and the concrete mono-run execution path,
- batch-specific IO and reporting helpers,
- the configuration objects that describe a meshing case.

Code map
--------

- ``hydromodpy/spatial/mesh/runtime.py``:
  public runtime facade. Called by ``Project.build_mesh()``.
- ``hydromodpy/spatial/mesh/hydro_mesh.py``:
  concrete ``HydroMesh`` runtime object.
- ``hydromodpy/spatial/mesh/batch.py``:
  batch orchestration and manifest handling.
- ``hydromodpy/spatial/mesh/batch_io.py`` and
  ``hydromodpy/spatial/mesh/batch_reporting.py``:
  IO and reporting helpers used by ``batch.py``.
- ``hydromodpy/spatial/mesh/config.py``:
  Pydantic configuration schema (``[mesh_catchment]`` block).

Recommended reading path
------------------------

1. ``hydromodpy/spatial/mesh/runtime.py``
2. ``hydromodpy/spatial/mesh/hydro_mesh.py``
3. ``hydromodpy/spatial/mesh/batch.py``
4. ``hydromodpy/spatial/mesh/config.py``

Diagram source
--------------

.. uml:: diagrams/mesh_catchment_package_components.wsd

.. literalinclude:: diagrams/mesh_catchment_package_components.wsd
   :language: text
   :caption: PlantUML (.wsd) source - mesh-catchment package components

Notes
-----

- ``runtime.py`` is intentionally thin. It validates the public payload
  and delegates the concrete execution path to ``hydro_mesh.py``.
- ``batch.py`` does not implement a second meshing engine. It derives
  one outlet-specific child runtime, then reuses the same
  mono-catchment callback.
- For higher-level simulation orchestration around mesh artifacts,
  see :doc:`../simulation/simulation-orchestration-class-diagram`.

Related diagrams
----------------

- :doc:`mesh-catchment-batch-activity-diagram`
- :doc:`catchment-conformal-meshing-diagrams`
