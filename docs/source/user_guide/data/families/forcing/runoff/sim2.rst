Runoff Source: sim2
===================

Use ``source = "sim2"`` to retrieve SIM2 runoff fields.

.. code-block:: toml

   [[data.runoff.sources]]
   source = "sim2"
   extent = "watershed"

Use the climatic summary for data checks and keep runoff distinct from modeled
drainage or groundwater discharge.
