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
