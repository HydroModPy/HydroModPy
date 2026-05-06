ETP
===

``etp`` loads potential evapotranspiration. It can be passed to solver
evapotranspiration packages when the flow process activates ETP forcing.

Accepted sources
----------------

- ``custom``
- ``sim2``

Minimal example
---------------

.. code-block:: toml

   [[data.etp.sources]]
   source = "sim2"
   extent = "watershed"

Checks
------

- ETP should be non-negative before solver assembly.
- Check time aggregation when ETP is applied to stress periods.

ETP Source: custom
^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local potential evapotranspiration forcing.

.. code-block:: toml

   [[data.etp.sources]]
   source = "custom"
   path = "data/etp/etp_daily.nc"
   source_unit = "mm/day"

Check units, period coverage, non-negative values, and stress-period
aggregation before interpreting a solver response.


ETP Source: sim2
^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 potential evapotranspiration fields.

.. code-block:: toml

   [[data.etp.sources]]
   source = "sim2"
   extent = "watershed"

Use the climatic summary for pre-solver checks, then inspect water-budget terms
after ETP has been activated in the flow configuration.
