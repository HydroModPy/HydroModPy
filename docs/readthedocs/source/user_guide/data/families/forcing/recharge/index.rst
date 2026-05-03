Recharge
========

``recharge`` loads or generates diffuse recharge forcing. It can be consumed
directly by MODFLOW-style flow processes, inspected in hydrological summaries,
or used in controlled analytical and synthetic cases.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - Local recharge files are authoritative.
     - :doc:`custom`
   * - ``sim2``
     - SIM2 gridded recharge should be retrieved over the project period.
     - :doc:`sim2`
   * - ``synthetic``
     - A deterministic recharge sequence is needed for tests or examples.
     - :doc:`synthetic`

Minimal example
---------------

.. code-block:: toml

   [data.recharge]
   date_start = "2000-01-01"
   date_end = "2002-12-31"

   [[data.recharge.sources]]
   source = "sim2"
   extent = "watershed"

Visual check
------------

Use the climatic summary for source-period checks and the water budget for
post-solver confirmation that recharge was consumed as intended.

.. toctree::
   :maxdepth: 1

   custom
   sim2
   synthetic
