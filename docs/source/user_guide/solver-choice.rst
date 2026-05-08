Solver Choice
=============

.. note::

   Use this page when the question is:
   "Which backend should I pick for this case, and which numerical option
   matters before I trust the result?"

HydroModPy currently exposes three flow solvers. They are not interchangeable:
each one constrains the mesh family, the available packages, and the
calibration budget. The summary table below is the fastest way to scope a
backend choice; the deeper trade-offs (XT3D, DISV, transport coupling, PETSc
backend) live in the linked theory pages.

Pick a flow solver
------------------

.. list-table::
   :header-rows: 1
   :widths: 18 22 22 38

   * - Solver
     - Best fit
     - Mesh support
     - Notes
   * - ``modflownwt``
     - Legacy MODFLOW-family flow
     - Structured ``sgrid`` only
     - Continuity with historical studies; gateway to the ``MODPATH`` and
       ``MT3DMS`` ecosystem.
   * - ``modflow6``
     - Modern MODFLOW-family flow
     - Structured ``sgrid`` and runtime DISV-style irregular meshes
     - Preferred when irregular meshes, modern package semantics, or
       MODFLOW 6 GWT transport coupling matter.
   * - ``boussinesq``
     - In-house shallow-groundwater flow
     - Triangular runtime meshes from the Gmsh pipeline
     - Useful for solver-to-solver comparisons and explicit Boussinesq
       formulations; still under active validation.

Decision matrix
---------------

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Question
     - Best entry point
   * - What can each solver family represent?
     - :doc:`../theory/solvers/solver-capability-matrix`
   * - How do MODFLOW 6 and MODFLOW-NWT differ scientifically?
     - :doc:`../theory/solvers/modflow6-vs-modflownwt-scientific-comparison`
   * - Why is XT3D important on irregular meshes?
     - :doc:`../theory/solvers/xt3d-on-irregular-disv-meshes`
   * - Where are the analytical and semi-analytical validation cases?
     - :doc:`../capability_gallery/validation`
   * - Where are stable solver-to-solver comparison cases?
     - :doc:`../capability_gallery/simulation_comparison`
   * - Where is the solver package architecture documented?
     - :doc:`../architecture/solver/index`

Minimal selection snippet
-------------------------

The active backend is declared in ``[solver]``. Backend-specific options live
under ``[modflow6]`` or ``[modflownwt]``. Process binding remains in
``[[simulation.process]]``.

.. code-block:: toml

   [solver]
   solver_engine = "modflow6"

   [modflow6.runtime]
   xt3d = true

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

Read more
---------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Theory
      :link: ../theory/solvers/index
      :link-type: doc

      Solver families, governing equations, package semantics, and
      cross-cutting numerical notes.

   .. grid-item-card:: Validation
      :link: ../capability_gallery/validation
      :link-type: doc

      Analytical and semi-analytical comparisons rendered as reproducible
      teaching figures.

   .. grid-item-card:: Comparison
      :link: comparison
      :link-type: doc

      Shared-case studies that quantify solver, mesh, or option
      differences.

   .. grid-item-card:: Architecture
      :link: ../architecture/solver/index
      :link-type: doc

      Package boundaries, adapter contracts, and runtime handoff.

See also
--------

- :doc:`solver-process-map` for the process-first map of flow,
  transport, postprocess, and display solver families.
- :doc:`mesh` for discretization-level diagnostics.
- :doc:`../api/index` for the solver-facing API reference.
