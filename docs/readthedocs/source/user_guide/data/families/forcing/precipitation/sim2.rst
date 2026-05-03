Precipitation Source: sim2
==========================

Use ``source = "sim2"`` to retrieve SIM2 precipitation fields.

.. code-block:: toml

   [[data.precipitation.sources]]
   source = "sim2"
   components = ["liquid", "solid", "total"]
   extent = "watershed"

Inspect the climatic summary to verify that the requested period and selected
components are available.
