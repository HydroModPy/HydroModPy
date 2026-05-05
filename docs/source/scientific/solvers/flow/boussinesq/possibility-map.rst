Boussinesq Possibility Map
==========================

This page makes the current possibilities explicit.

It is intentionally a map, not a promise that every combination is equally
mature. Use the capability gallery and validation pages before treating a
combination as production-ready.

Main Possibilities
------------------

.. list-table::
   :header-rows: 1
   :widths: 26 30 22 22

   * - Goal
     - Recommended combination
     - Surface closure
     - Runtime
   * - Small analytical validation
     - Head-only finite-volume Boussinesq.
     - ``regularized_partition``
     - ``local`` or ``scipy``
   * - Larger cross-platform triangular mesh
     - Head-only sparse Boussinesq.
     - ``regularized_partition``
     - ``scipy_sparse``
   * - PETSc sparse baseline
     - Head-only PETSc partition route.
     - ``regularized_partition``
     - ``petsc``
   * - Surface-threshold activation study
     - Mixed head-plus-saturation-excess-plus-dry-deficit route.
     - ``complementarity``
     - ``petsc``
   * - Drying and rewetting study
     - PETSc mixed double-obstacle route.
     - ``complementarity``
     - ``petsc``
   * - MODFLOW/Boussinesq simulation comparison
     - Start from shared geometry and forcing, then document closure and mesh
       differences explicitly.
     - Depends on comparison question.
     - Usually ``scipy_sparse`` or ``petsc``.

Possibility Axes
----------------

The Boussinesq route should be described along these axes:

.. list-table::
   :header-rows: 1
   :widths: 24 36 40

   * - Axis
     - Values
     - Why it matters
   * - Flow regime
     - ``steady`` or ``transient``.
     - Adds or removes storage and time-step history.
   * - Mesh
     - Triangular runtime mesh.
     - Controls internal-edge fluxes and cellwise top/bottom support.
   * - Hydraulic properties
     - Scalar or mapped ``K`` and storage values.
     - Changes transmissivity and transient response.
   * - Surface closure
     - ``regularized_partition`` or ``complementarity``.
     - Changes how surface interception, saturation excess and lower-obstacle
       drying are represented.
   * - Runtime engine
     - ``local``, ``scipy``, ``scipy_sparse``, ``petsc``.
     - Changes nonlinear solve strategy and scalability.

What To Report In A Comparison
------------------------------

Always report:

- mesh source and resolution;
- top and bottom surfaces;
- hydraulic conductivity and storage mapping;
- recharge and well forcing;
- boundary supports;
- flow regime and time stepping;
- surface-interaction closure;
- runtime backend.

Without these fields, it is too easy to attribute differences to
``boussinesq`` as a solver name when the actual difference comes from the
surface closure, mesh, property transfer, or runtime-specific convergence
path.

Related Pages
-------------

- :doc:`equation-and-unknowns`
- :doc:`boussinesq-method`
- :doc:`surface-interaction`
- :doc:`lower-obstacle-drying`
- :doc:`solver-engines`
- :doc:`../../solver-capability-matrix`
