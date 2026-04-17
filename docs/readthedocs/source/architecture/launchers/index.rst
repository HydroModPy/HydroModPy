Launchers Architecture
======================

This section documents the application-level orchestration layer implemented
in the top-level ``launchers`` package.

It now focuses on:

- the simulation-plan launcher family,
- the dedicated model-calibration launcher family,
- the high-level bootstrap and handoff logic around ``process_simulation``.

Mesh-generation pages that were previously grouped here now live under
:doc:`../mesh/index`, so that all catchment-meshing views stay together in one
place.

.. toctree::
   :maxdepth: 2

   model-calibration-launcher-architecture
   launcher-simulation-sequence-diagram
   launcher-simulation-activity-diagram
