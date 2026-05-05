Recharge Source: custom
=======================

Use ``source = "custom"`` when a local recharge raster, NetCDF file, or time
series is the reference input.

Minimal example
---------------

.. code-block:: toml

   [[data.recharge.sources]]
   source = "custom"
   path = "data/recharge/recharge_daily.nc"
   source_unit = "mm/day"
   extent = "watershed"

Operational checks
------------------

- Set ``source_unit`` when file metadata are missing or ambiguous.
- Check the date dimension against ``date_start`` and ``date_end``.
- Confirm whether the values represent recharge only or already include runoff
  partitioning.
- Inspect solver aggregation when the recharge is used in a transient model.
