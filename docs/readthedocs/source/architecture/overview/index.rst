Architecture Overview
=====================

This section groups architecture notes that cut across several HydroModPy
packages. Use it when the question is not "how does one package work?" but
rather "where does one responsibility live?" or "which layer should I change?".

The pages below focus on the recurring maintenance boundaries:

- the quality ladder from local unit checks to scientific benchmark
  validation, with the routine commands used to run each level,
- the split between reusable scientific benchmarks and pytest entrypoints,
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

   test-families-and-quality-roles
   mental-model-and-design-choices
   testbed-workflow-architecture
   hydrographic-network-uml-diagrams
   hydrographic-network-simulated-active-inventory
   code-reading-guide
   tests-and-validation
   data-managers-and-external-dependencies
   two-databases
