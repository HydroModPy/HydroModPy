Wind
====

``wind`` loads wind forcing and climate context.

Accepted sources
----------------

- :doc:`custom`
- :doc:`sim2`

.. code-block:: toml

   [[data.wind.sources]]
   source = "sim2"
   extent = "watershed"

Check unit convention, period coverage, and whether the variable is being used
only for reporting or for a preprocessing chain.

.. toctree::
   :maxdepth: 1

   custom
   sim2
