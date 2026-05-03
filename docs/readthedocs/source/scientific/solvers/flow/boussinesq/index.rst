Boussinesq Internals
====================

This section structures the in-house ``flow/boussinesq`` documentation inside
the ``flow`` process.

The useful reading hierarchy is:

1. **equation and unknowns**: what physical balance is solved and which
   quantities are reconstructed from hydraulic head;
2. **Boussinesq method**: how the finite-volume triangular-mesh method turns
   the equation into steady or transient residuals;
3. **surface interaction**: how near-surface interception, drainage, and
   saturation excess are represented;
4. **solver engines**: which nonlinear runtime can solve which method;
5. **possibility map**: which combination is relevant for validation,
   comparison, larger meshes, or PETSc-only experiments.

Current Boussinesq Flow Route
-----------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Axis
     - Current choices
     - Meaning
   * - Process/solver pair
     - ``flow/boussinesq``
     - HydroModPy-native shallow-groundwater flow backend.
   * - Spatial support
     - Cell-centered finite volumes on triangular runtime meshes.
     - The solver owns a compact triangular mesh view derived from catchment
       mesh bundles.
   * - Time regime
     - Steady balance or transient backward Euler.
     - The same spatial operators are used in both regimes; transient runs add
       the storage term.
   * - Surface closure
     - ``regularized_partition`` or ``complementarity``.
     - The first is the cross-platform baseline; the second is the PETSc mixed
       saturation-excess route.
   * - Runtime engine
     - ``local``, ``scipy``, ``scipy_sparse``, ``petsc``.
     - Execution choice, not a different hydrological process.

.. toctree::
   :maxdepth: 2

   equation-and-unknowns
   boussinesq-method
   surface-interaction
   solver-engines
   possibility-map

Reference Notes
---------------

The detailed mathematical note remains available at
:doc:`../../boussinesq-mathematical-notes`. The pages in this section are a
more navigable entry point into the same material.

Related Pages
-------------

- :doc:`../boussinesq-family`
- :doc:`../shared-flow-numerics`
- :doc:`../../solver-capability-matrix`
- :doc:`../../../../architecture/solver/flow/boussinesq-family`
