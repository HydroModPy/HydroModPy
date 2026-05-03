Runoff
======

``runoff`` loads surface-runoff forcing or hydrological diagnostics. It should
not be confused with groundwater discharge or drainage-package fluxes.

Accepted sources
----------------

- :doc:`custom`
- :doc:`sim2`

.. code-block:: toml

   [[data.runoff.sources]]
   source = "sim2"
   extent = "watershed"

Check period coverage, units, and semantic meaning before comparing runoff
with simulated groundwater discharge.

.. toctree::
   :maxdepth: 1

   custom
   sim2
