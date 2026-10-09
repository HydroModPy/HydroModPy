Calibration architecture
========================

.. rst-class:: lead

Software architecture of the calibration stack in
``hydromodpy.calibration``: the code-oriented architecture map plus
the full operational guide for adding methods, observables, and
objectives.

For the scientific side (inverse problem, methods), see
:doc:`/theory/index`.

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

   .. grid-item-card:: How the calibration engine runs
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: calibration-guide
      :link-type: doc

      How a calibration file becomes trials: the steps a trial replays,
      what is stored, the cache, and what a search reports about itself.

.. toctree::
   :hidden:
   :maxdepth: 1

   calibration-architecture
   calibration-guide
