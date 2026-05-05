Runoff Source: custom
=====================

Use ``source = "custom"`` for local runoff fields or time series.

.. code-block:: toml

   [[data.runoff.sources]]
   source = "custom"
   path = "data/runoff/runoff.nc"
   source_unit = "mm/day"

Check the semantic meaning of the runoff product before using it in water
balance reasoning.
