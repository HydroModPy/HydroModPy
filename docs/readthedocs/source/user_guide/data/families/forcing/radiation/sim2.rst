Radiation Source: sim2
======================

Use ``source = "sim2"`` to retrieve SIM2 radiation fields.

.. code-block:: toml

   [[data.radiation.sources]]
   source = "sim2"
   components = ["atmospheric", "visible"]
   extent = "watershed"

Use the climatic summary as the first visible check.
