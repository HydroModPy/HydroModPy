Intermittency
=============

``intermittency`` loads flow-state observations such as ONDE-style dry or
flowing states. It is useful for diagnosing active network behavior and for
qualitative comparison with simulated drainage activation.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - Local flow-state observations are authoritative.
     - :doc:`custom`
   * - ``hubeau``
     - Hub'Eau/ONDE-style public intermittency observations should be retrieved.
     - :doc:`hubeau`

Minimal example
---------------

.. code-block:: toml

   [data.intermittency]
   date_start = "2010-01-01"
   date_end = "2020-12-31"

   [[data.intermittency.sources]]
   source = "hubeau"
   extent = "watershed"

Visual check
------------

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_timeseries_intermittency.png
   :alt: Nancon intermittency time series
   :width: 100%

   Intermittency is a state observation. The figure should make the state
   coding, dates, and stations readable before it is compared with a simulated
   active network.

Downstream uses
---------------

- active-network interpretation;
- qualitative validation of drainage/seepage behavior;
- seasonal low-flow diagnostics.

.. toctree::
   :maxdepth: 1

   custom
   hubeau
