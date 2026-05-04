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

Visual check
------------

.. figure:: /_static/user_guide/data/forcing_local_recharge_runoff_example.png
   :alt: Local custom runoff and recharge source series
   :width: 100%

   Runoff should be read as a forcing or diagnostic source, not as simulated
   groundwater discharge. The paired custom figure makes that distinction
   visible by keeping the source chronicle separate from any solver response.

.. toctree::
   :maxdepth: 1

   custom
   sim2
