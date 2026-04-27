Architecture Overview
=====================

This section groups architecture notes that cut across several HydroModPy
packages. Use it when the question is not "how does one package work?" but
rather "where does one responsibility live?" or "which layer should I change?".

The pages below focus on the recurring maintenance boundaries:

- the split between reusable scientific benchmarks and pytest entrypoints,
- the compatibility layers that keep legacy or simplified imports alive
  while internals are reorganized,
- the root data-manager orchestration layer that decides what is loaded,
  from where, and under which external constraints,
- the dual DuckDB layout that holds the input cache and the simulation
  catalog,
- the code-reading map that points developers to the right package
  README or runtime entry point before diving into implementation
  details.

They are deliberately complementary to the package-level sections in
:doc:`../index`.

.. toctree::
   :maxdepth: 2

   code-reading-guide
   tests-and-validation
   compatibility-facades
   data-managers-and-external-dependencies
   two-databases
