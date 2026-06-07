Radiation
=========

``radiation`` loads atmospheric and visible radiation components.

Accepted sources
----------------

- ``custom``
- ``sim2``

.. code-block:: toml

   [[data.radiation.sources]]
   source = "sim2"
   components = ["atmospheric", "visible"]
   extent = "watershed"

Checks
------

- ``components`` accepts ``atmospheric`` and ``visible``.
- Confirm units and period coverage before using radiation in preprocessing.

Radiation Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local radiation fields or station series.

.. code-block:: toml

   [[data.radiation.sources]]
   source = "custom"
   path = "data/radiation/radiation.nc"
   components = ["atmospheric"]

Check component names, units, date coverage, and spatial support.


Radiation Source: sim2
^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 radiation fields.

.. code-block:: toml

   [[data.radiation.sources]]
   source = "sim2"
   components = ["atmospheric", "visible"]
   extent = "watershed"

Use the climatic summary as the first visible check.
