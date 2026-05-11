Calibration
===========

.. raw:: html

   <p class="lead">
   Scientific side of the HydroModPy calibration stack. Complements the
   architecture pages by answering what is solved, how objectives are
   built, and how each implemented method behaves numerically.
   </p>

The scope here is the calibration code in ``hydromodpy.calibration``,
exposed through ``hmp run <calibration.toml>``.

Topic pages
-----------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Inverse-problem formulation
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: inverse-problem-formulation
      :link-type: doc

      What inverse problem HydroModPy solves: parameter
      identifiability, objective construction, prior assumptions,
      and the difference between a best-fit point and a posterior
      distribution.

   .. grid-item-card:: Calibration methods
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: calibration-methods
      :link-type: doc

      What each built-in optimizer or sampler actually does:
      ``grid``, ``optuna`` (TPE, CMA-ES), ``scipy_de``,
      ``scipy_nelder_mead``, and the distribution-valued methods.

See also
--------

- :doc:`/user_guide/workflows/calibration` for the operational
  walkthrough and the "Pick a method" decision table.
- :doc:`/architecture/calibration/index` for the package layout and
  runtime classes behind the engine.
- :doc:`/capability_gallery/calibration` for stable benchmark pages
  with posteriors and objective landscapes.

.. toctree::
   :hidden:
   :maxdepth: 1

   inverse-problem-formulation
   calibration-methods
