Boussinesq Method
=================

This page describes the method layer between the equation and the nonlinear
solver engine.

In the code, this layer is explicit: ``formulations/`` defines algebraic
unknowns and surface closures, ``discretization/`` defines space/time schemes,
and ``methods/`` combines them into named method families.

Spatial Method
--------------

The current space scheme is:

.. code-block:: text

   finite-volume triangular cell-centered method

The solver works on a compact triangular mesh view. Internal edge fluxes use:

- owner cell pairs;
- edge length;
- centroid-to-centroid distance;
- harmonic conductivity;
- averaged saturated thickness.

The method is conservative on internal edges: the flux leaving one cell enters
the neighboring cell with the opposite sign.

Time Methods
------------

Two regimes are documented and implemented:

.. list-table::
   :header-rows: 1
   :widths: 26 32 42

   * - Regime
     - Scheme
     - Interpretation
   * - Steady
     - ``steady_balance``
     - Solve one nonlinear balance with no storage term.
   * - Transient
     - ``backward_euler``
     - Fully implicit time stepping with storage evaluated between accepted
       snapshots.

Current Method Families
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 32 28 40

   * - Method id
     - Unknown layout
     - Surface closure
   * - ``head_only_regularized_partition``
     - ``head_only``
     - ``regularized_partition``
   * - ``mixed_complementarity``
     - ``head_plus_qex_qdry``
     - ``complementarity``

The method id is the physically meaningful combination. A runtime backend such
as ``scipy_sparse`` or ``petsc`` only says how that method is solved.

Head-Only Regularized Partition
-------------------------------

This is the historical comparison baseline. The unknown vector only contains
hydraulic head. Surface excess is reconstructed from the head and the lateral
balance through a smooth regularized partition law.

Use it when:

- the run must stay cross-platform;
- the goal is comparison with existing validation cases;
- the mesh is small enough for dense engines or large enough for
  ``scipy_sparse``;
- a smooth head-only residual is preferred over an explicit complementarity
  constraint.

Mixed Complementarity
---------------------

This method adds two cellwise algebraic unknowns:

.. math::

   q_i^{ex}

for saturation excess at the surface, and:

.. math::

   q_i^{dry}

for the lower drying obstacle. The PETSc runtime solves head, surface excess
and dry deficit together as a double-obstacle complementarity problem.

Use it when:

- PETSc is available;
- the question is specifically about on/off surface-threshold behavior;
- dry-down and repeated activation/deactivation of the surface threshold are
  important diagnostics.
- lower-obstacle drying must be enforced explicitly.

Related Pages
-------------

- :doc:`equation-and-unknowns`
- :doc:`surface-interaction`
- :doc:`lower-obstacle-drying`
- :doc:`solver-engines`
