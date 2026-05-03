Process Architecture
====================

This section documents the process runtime layer implemented in
``hydromodpy.physics``.

For solver-side meshing and structured-grid documentation, see
:doc:`../mesh/index`.

Use it when you want:

- the package map behind ``Flow`` / ``Transport`` / forcing builders,
- the split between generic contracts and process-specific business objects,
- the runtime handoff from process objects to solver adapters.
- the way process types generalize into the process/solver registry documented
  under :doc:`../solver/process-solver-registry`.

.. toctree::
   :maxdepth: 2

   process-package-map
   process-runtime-class-diagram
   process-config-class-diagram
   process-runtime-to-solver-sequence-diagram
   process-spatial-lifecycle-state-machine
   process-layer-separation-component-diagram
   process-extension-activity-diagram
