Runoff
======

``runoff`` loads surface-runoff forcing or hydrological diagnostics. It should
not be confused with groundwater discharge or drainage-package fluxes.

Accepted sources
----------------

- ``custom``
- ``sim2``

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

Runoff Source: custom
^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local runoff fields or time series.

.. code-block:: toml

   [[data.runoff.sources]]
   source = "custom"
   path = "data/runoff/runoff.nc"
   source_unit = "mm/day"

Check the semantic meaning of the runoff product before using it in water
balance reasoning.


Runoff Source: sim2
^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 runoff fields.

.. code-block:: toml

   [[data.runoff.sources]]
   source = "sim2"
   extent = "watershed"

Use the climatic summary for data checks and keep runoff distinct from modeled
drainage or groundwater discharge.
