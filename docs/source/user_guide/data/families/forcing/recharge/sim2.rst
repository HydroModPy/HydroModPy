Recharge Source: sim2
=====================

Use ``source = "sim2"`` when SIM2 recharge should be retrieved for the project
support and period.

Minimal example
---------------

.. code-block:: toml

   [[data.recharge.sources]]
   source = "sim2"
   extent = "watershed"

Operational checks
------------------

- The configured period should match the intended hydrological or simulation
  window.
- Cache metadata should be preserved when runs must be reproducible.
- Inspect forcing summaries before looking at model response.

Provider replay
---------------

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 replay with recharge grid and climate cycle
   :width: 100%

   The recharge replay shows both the gridded support and the selected period.
   This is the provider-level check to perform before values are aggregated
   into solver stress periods.
