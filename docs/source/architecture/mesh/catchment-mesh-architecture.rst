Catchment-Mesh Architecture
===========================

This page documents the dedicated catchment-mesh workflow built around
``hydromodpy.spatial.mesh``: package layout, runtime entry points,
batch loop, simulation embedding, output layout, and the conformal
Gmsh meshing core.

Code map
--------

- ``hydromodpy/spatial/mesh/runtime.py``: public mono-catchment entry
  point. Called by ``Project.build_mesh()``.
- ``hydromodpy/spatial/mesh/hydro_mesh.py``: concrete ``HydroMesh``
  runtime object behind the public facade.
- ``hydromodpy/spatial/mesh/batch.py``: batch orchestration and
  manifest handling.
- ``hydromodpy/spatial/mesh/batch_io.py`` and ``batch_reporting.py``:
  IO and reporting helpers used by ``batch.py``.
- ``hydromodpy/spatial/mesh/config.py``: Pydantic configuration
  schema (``[mesh_catchment]`` block).
- ``hydromodpy/spatial/mesh/gmsh_grid/zone_meshing/``: conformal
  meshing core and export helpers.
- ``hydromodpy/spatial/geographic`` and related domain helpers:
  geographic context preparation before meshing.

Recommended reading path:

1. ``hydromodpy/spatial/mesh/runtime.py``
2. ``hydromodpy/spatial/mesh/hydro_mesh.py``
3. ``hydromodpy/spatial/mesh/gmsh_grid/runtime_support.py``
4. ``hydromodpy/spatial/mesh/gmsh_grid/zone_meshing/conformal.py``
5. ``hydromodpy/spatial/mesh/batch.py`` and ``config.py``

Package components
------------------

The internal package layout: public runtime entry points, the runtime
facade and the concrete mono-run execution path, batch-specific IO
and reporting helpers, and the configuration objects describing a
meshing case.

.. uml:: diagrams/mesh_catchment_package_components.wsd

Notes:

- ``runtime.py`` is intentionally thin. It validates the public
  payload and delegates concrete execution to ``hydro_mesh.py``.
- ``batch.py`` does not implement a second meshing engine. It derives
  one outlet-specific child runtime, then reuses the same
  mono-catchment callback.

Conformal meshing pipeline
--------------------------

The chain that turns one domain plus optional geology zones and river
constraints into one planar mesh, one QA sidecar, one optional
figure, and one optional exchange bundle.

The chosen UML set is intentionally narrow: an activity diagram for
the branching driven by ``constraints_mode`` and constraint
availability, a sequence diagram for the runtime handoff between
public mesh facade, shared runtime helpers, geographic context,
conformal case, and exports, and a component diagram for the stable
boundaries between orchestration, domain preparation, constraint
sources, meshing core, and exporters.

Activity:

.. uml:: diagrams/catchment_conformal_meshing_activity.wsd

Sequence (mesh facade to Gmsh):

.. uml:: diagrams/catchment_conformal_meshing_sequence.wsd

Components:

.. uml:: diagrams/catchment_conformal_meshing_components.wsd

Notes:

- ``mesh_catchment_batch`` is intentionally not modeled as a separate
  meshing engine.
- The diagrams stop at the planar catchment mesh plus exchange
  bundle. 3D extrusion and field-parameter discretization are
  documented in :doc:`structured-grid-architecture` and
  :doc:`../mesh_pivot`.

Batch loop
----------

The ``[mesh_catchment_batch]`` loop: pre-loop validation of outputs
and raster coverage, derivation of child workspaces and outlet
coordinates, incremental manifest updates, and the
``continue_on_error`` branch that decides whether the loop stops or
keeps running.

.. uml:: diagrams/mesh_catchment_batch_activity.wsd

Notes:

- The batch loop reuses the same mono-catchment callback as the
  public runtime entry point.
- The manifest CSV is rewritten after each outlet so progress remains
  visible even when the batch stops early.
- A summary that returns without a written mesh file is treated as a
  failure.

In-process simulation embedding
-------------------------------

How the simulation pipeline accepts, rejects, or reuses runtime
meshes: the mutual exclusion between ``[mesh_catchment]`` and
``[mesh_input]``, the early rejection of ``[mesh_catchment_batch]``
inside the simulation workflow, the solver-compatibility guard that
rejects runtime Gmsh meshes with ``modflownwt``, and the handoff of
loaded or generated mesh artifacts into the ``Project`` runtime
state before solver execution.

.. uml:: diagrams/mesh_catchment_in_process_simulation_activity.wsd

Notes:

- The simulation workflow can embed one mono-catchment mesh phase or
  reuse one precomputed mesh, but not both in the same run.
- Runtime Gmsh meshes are currently intended for ``boussinesq`` and
  ``modflow6``. ``modflownwt`` stays on the structured ``sgrid``
  path.

Output layout
-------------

How the dedicated mesh workflow resolves final artifacts and cleanup
behavior: the ``standard`` versus ``flat`` output layout split,
optional figure generation, exchange-bundle export, cleanup of
intermediate geographic artifacts, and extra naming and manifest
rules in batch mode.

.. uml:: diagrams/mesh_catchment_output_layout_activity.wsd

Notes:

- ``flat`` layout is a convenience for the dedicated mesh workflow.
  It writes the final mesh artifacts directly under
  ``workspace.project_root`` while the intermediate runtime workspace
  lives elsewhere and can be deleted afterwards.
- The full simulation workflow keeps the standard workspace structure
  because it still needs its runtime folders.
- Batch mode adds per-outlet filename patterns and one manifest CSV,
  but it still reuses the same mono-catchment output-resolution
  rules.

See also
--------

- :doc:`structured-grid-architecture` for the SGrid path and the
  bridge to ``Field`` / ``FieldParam``.
- :doc:`../mesh_pivot` for the cross-mesh pivot format.
- :doc:`../gmsh_meshing` for the conformal Gmsh pipeline.
- :doc:`../simulation/simulation-orchestration-class-diagram` for
  the simulation-side consumer.
