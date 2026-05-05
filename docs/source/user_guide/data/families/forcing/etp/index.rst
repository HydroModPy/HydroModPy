ETP
===

``etp`` loads potential evapotranspiration. It can be passed to solver
evapotranspiration packages when the flow process activates ETP forcing.

Accepted sources
----------------

- :doc:`custom`
- :doc:`sim2`

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

.. toctree::
   :maxdepth: 1

   custom
   sim2
