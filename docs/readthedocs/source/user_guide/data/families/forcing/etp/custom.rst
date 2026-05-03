ETP Source: custom
==================

Use ``source = "custom"`` for local potential evapotranspiration forcing.

.. code-block:: toml

   [[data.etp.sources]]
   source = "custom"
   path = "data/etp/etp_daily.nc"
   source_unit = "mm/day"

Check units, period coverage, non-negative values, and stress-period
aggregation before interpreting a solver response.
