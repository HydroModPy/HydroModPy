Boussinesq Solver Engines
=========================

This page distinguishes the physical method from the execution engine.

The user-facing runtime backend names are:

.. code-block:: text

   local
   scipy
   scipy_sparse
   petsc

They are not separate hydrological models. They are numerical engines used to
solve one resolved Boussinesq method.

Engine Matrix
-------------

.. list-table::
   :header-rows: 1
   :widths: 18 26 26 30

   * - Runtime backend
     - Linear layout
     - Supported method
     - Best use
   * - ``local``
     - Dense
     - ``head_only_regularized_partition``
     - Small validation meshes and transparent debugging.
   * - ``scipy``
     - Dense
     - ``head_only_regularized_partition``
     - Dense SciPy reference route around the same residual.
   * - ``scipy_sparse``
     - Sparse
     - ``head_only_regularized_partition``
     - Cross-platform reference for larger triangular meshes.
   * - ``petsc``
     - Sparse
     - ``head_only_regularized_partition`` or ``mixed_complementarity``
     - Linux/PETSc route for sparse SNES solves, surface complementarity and
       lower-obstacle drying tests.

Surface Model Resolution
------------------------

The process-to-runtime selection resolves two axes:

.. code-block:: text

   runtime_backend + surface_interaction_model -> method + engine

The surface-interaction token can be:

.. code-block:: text

   auto
   regularized_partition
   complementarity

With ``auto``:

- ``petsc`` resolves to ``complementarity``;
- non-PETSc backends resolve to ``regularized_partition``.

If ``complementarity`` is requested with a non-PETSc runtime, the code rejects
the combination because that method is currently implemented only for
``runtime_backend = "petsc"``.

Minimal Configuration Shape
---------------------------

The exact surrounding TOML depends on the workflow, but the relevant flow
choice is conceptually:

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["boussinesq"]

   [flow]
   flow_regime = "transient"
   runtime_backend = "scipy_sparse"
   surface_interaction_model = "regularized_partition"

For a PETSc complementarity experiment:

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["boussinesq"]

   [flow]
   flow_regime = "transient"
   runtime_backend = "petsc"
   surface_interaction_model = "complementarity"

Interpretation Rule
-------------------

When comparing outputs, record both axes:

- the method: formulation, surface closure, space scheme, and time scheme;
- the engine: nonlinear solver, matrix layout, Jacobian strategy, and linear
  solver.

Two runs can share the same method but differ by engine. Two PETSc runs can
share the same engine name but differ by method if their surface closure is
different.

Related Pages
-------------

- :doc:`boussinesq-method`
- :doc:`surface-interaction`
- :doc:`lower-obstacle-drying`
- :doc:`possibility-map`
