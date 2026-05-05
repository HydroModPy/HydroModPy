ETP Source: sim2
================

Use ``source = "sim2"`` to retrieve SIM2 potential evapotranspiration fields.

.. code-block:: toml

   [[data.etp.sources]]
   source = "sim2"
   extent = "watershed"

Use the climatic summary for pre-solver checks, then inspect water-budget terms
after ETP has been activated in the flow configuration.
