Figure Catalog
==============

Figures live in ``hydromodpy.display`` and consume the persisted
:class:`hydromodpy.results.run.Run` interface. They are solver-agnostic: the
same figure name can render MODFLOW-NWT, MODFLOW 6, or Boussinesq outputs when
the required result fields exist.

Basic usage
-----------

.. code-block:: python

   from hydromodpy.display import get, list_figures

   list_figures()
   get("piezometric_map").plot(run, save_path="head.png")

From the CLI:

.. code-block:: bash

   hmp display <sim_id>
   hmp run project.toml --no-display

Registered figure names
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 28 28 44

   * - Family
     - Figure names
     - Expected result families
   * - Watershed and network
     - ``watershed_id_card``, ``hydrographic_network_reference``,
       ``hydrographic_network_generated``,
       ``hydrographic_network_comparison``,
       ``hydrographic_network_reference_missing_only``,
       ``hydrographic_network_generated_extra_only``,
       ``simulated_active_network``,
       ``simulated_active_network_reference_overlay``
     - Geographic support, observed hydrography, simulated seepage or active
       stream-network fields.
   * - Flow maps and sections
     - ``piezometric_map``, ``recharge_map``, ``seepage_map``,
       ``difference_map``, ``side_by_side``, ``cross_section``
     - Mesh or raster support plus persisted scalar fields.
   * - Time-series diagnostics
     - ``hydrograph``, ``duration_curve``, ``seasonal_boxplot``,
       ``recession``, ``ensemble_band``
     - Observed and simulated time-series records.
   * - Budgets and balances
     - ``water_budget``
     - Persisted budget or mass-balance tables.
   * - Calibration
     - ``calibration_convergence``, ``calibration_landscape``,
       ``calibration_objective_surface``, ``calibration_pairplot``,
       ``calibration_posterior``, ``calibration_trace``
     - Calibration session, objective values, candidate parameters, and
       posterior samples when available.
   * - Transport and particles
     - ``concentration_map``, ``particle_tracks``
     - Persisted concentration fields or pathline outputs.
   * - Hydrochemistry
     - ``piper_diagram``, ``schoeller_diagram``, ``stiff_diagram``
     - Water-quality point samples and chemistry tables.

Choosing figures in TOML
------------------------

Simulation configurations can request report figures through the display
section. Exact options depend on the current configuration schema:

.. code-block:: toml

   [display]
   figures = ["piezometric_map", "water_budget", "simulated_active_network"]

Use ``hmp display <sim_id>`` to rerender figures after a run, and use
``--no-display`` during ``hmp run`` when the workflow should persist results
without rendering report figures.

Compatibility rule
------------------

Figure names are stable entry points, but every figure still depends on data
being present in the run store. If a figure cannot render, inspect the run first
with:

.. code-block:: bash

   hmp inspect <sim_id>
   hmp show <sim_id>

For low-level display objects, see :doc:`../api/index`.
