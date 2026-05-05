Forcing Families
================

Forcing families load gridded or point variables over a project period. Some
variables are direct solver inputs, such as ``recharge`` and ``etp``. Others
are hydrological or meteorological drivers that support preprocessing,
diagnostics, or future process chains.

Supported families
------------------

.. list-table::
   :header-rows: 1
   :widths: 22 26 52

   * - Family
     - Accepted sources
     - Main role
   * - ``recharge``
     - ``custom``, ``sim2``, ``synthetic``
     - Diffuse recharge forcing or controlled recharge tests.
   * - ``precipitation``
     - ``custom``, ``sim2``
     - Rain/snow/total precipitation context or preprocessing input.
   * - ``etp``
     - ``custom``, ``sim2``
     - Potential evapotranspiration forcing.
   * - ``temperature``
     - ``custom``, ``sim2``
     - Air-temperature forcing and climate context.
   * - ``wind``
     - ``custom``, ``sim2``
     - Wind forcing and climate context.
   * - ``humidity``
     - ``custom``, ``sim2``
     - Relative-humidity forcing and climate context.
   * - ``radiation``
     - ``custom``, ``sim2``
     - Atmospheric or visible radiation forcing.
   * - ``soil_moisture``
     - ``custom``, ``sim2``
     - Soil-moisture fields or time series.
   * - ``runoff``
     - ``custom``, ``sim2``
     - Surface-runoff forcing or hydrological diagnostic.

Common checks
-------------

- period coverage must match the intended simulation, overview, or
  preprocessing window;
- units must be explicit for custom files;
- gridded data must align with the requested ``extent`` and project CRS;
- aggregation to solver stress periods should be checked when the variable is
  consumed by a solver.

What to show first
------------------

For forcing data, a complete solver run is not the first diagnostic. Start with
coverage, units, and aggregate behavior. Then add solver response figures only
when the page explains how the forcing reaches a package such as recharge or
evapotranspiration.

Visual reference
----------------

.. figure:: /_static/user_guide/data/forcing_local_recharge_runoff_example.png
   :alt: Local custom recharge and runoff source series
   :width: 100%

   The local custom forcing run shows the pre-solver contract: period coverage,
   magnitude, and cumulative behaviour are visible before recharge or runoff is
   interpreted as a model flux.

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 local gridded forcing example
   :width: 100%

   The SIM2 local NetCDF figure adds the gridded part of the contract: spatial
   support and monthly climate summaries should be inspected before any solver
   package consumes the forcing.

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_climatic_summary.png
   :alt: Nancon climatic forcing summary
   :width: 100%

   The climatic summary is the compact pre-solver check for SIM2-style forcing:
   it shows period coverage and aggregate behavior before any solver package
   consumes the values.

Solver response check
---------------------

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_water_budget.png
   :alt: Nancon water budget after transient forcing
   :width: 100%

   A water budget is post-solver evidence. It should be read after the forcing
   has already passed source, period, unit, and aggregation checks.

.. toctree::
   :maxdepth: 3

   recharge/index
   precipitation/index
   etp/index
   temperature/index
   wind/index
   humidity/index
   radiation/index
   soil-moisture/index
   runoff/index
