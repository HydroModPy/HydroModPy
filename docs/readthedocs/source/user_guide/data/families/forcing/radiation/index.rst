Radiation
=========

``radiation`` loads atmospheric and visible radiation components.

Accepted sources
----------------

- :doc:`custom`
- :doc:`sim2`

.. code-block:: toml

   [[data.radiation.sources]]
   source = "sim2"
   components = ["atmospheric", "visible"]
   extent = "watershed"

Checks
------

- ``components`` accepts ``atmospheric`` and ``visible``.
- Confirm units and period coverage before using radiation in preprocessing.

.. toctree::
   :maxdepth: 1

   custom
   sim2
