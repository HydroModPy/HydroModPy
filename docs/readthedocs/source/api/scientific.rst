Scientific API
==============

Use this layer when you work directly with scientific components instead of the
high-level ``Project`` interface. These pages expose the public technical
surface for preprocessing, data, solvers, calibration, and analysis.

Reference Groups
----------------

.. grid:: 1 1 2 3
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-geographic
      :link-type: doc

      **Geographic preprocessing**
      ^^^
      Catchment delineation, DEM products, geographic runtime context, and
      river network configuration.

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-data
      :link-type: doc

      **Data managers**
      ^^^
      Data plans, data manager configuration, provider source blocks, and
      variable configuration objects.

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-modeling
      :link-type: doc

      **Numerical engines**
      ^^^
      Solver-facing classes for MODFLOW-NWT, MODPATH, transport helpers, and
      other numerical surfaces.

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-analysis-calibration
      :link-type: doc

      **Analysis and calibration**
      ^^^
      Calibration contracts, objectives, optimizers, reports, comparison, and
      batch analysis entry points.

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-pyhelp
      :link-type: doc

      **HELP coupling**
      ^^^
      HELP land-surface coupling utilities and conversion helpers used by
      HydroModPy workflows.

Use Boundary
------------

The scientific API is not a shortcut around validation. Build objects through
documented config models when possible. Direct internal imports are for
developer work and belong in :doc:`developer`.

.. toctree::
   :hidden:
   :maxdepth: 2

   hydromodpy-geographic
   hydromodpy-data
   hydromodpy-modeling
   hydromodpy-analysis-calibration
   hydromodpy-pyhelp
