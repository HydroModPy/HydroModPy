Calibration Architecture
========================

.. raw:: html

   <p class="lead">
   Software architecture of the calibration stack in
   ``hydromodpy.calibration``: the code-oriented architecture map plus
   the full operational guide for adding methods, observables, and
   objectives.
   </p>

For the user-facing hub, see :doc:`../../user_guide/workflows/calibration`.
For the scientific side (inverse problem, methods), see
:doc:`../../theory/calibration/index`.

Pages
-----

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Code-oriented architecture
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: calibration-architecture
      :link-type: doc

      Package map, recommended reading path, and every UML diagram
      (config, runtime, execution flows, case structure) in one
      place.

   .. grid-item-card:: Operational calibration guide
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: calibration-guide
      :link-type: doc

      TOML sections, optimizer catalogue, storage rules, common
      pitfalls, and the Python API for custom observables and
      objectives.

.. toctree::
   :hidden:
   :maxdepth: 1

   calibration-architecture
   calibration-guide
