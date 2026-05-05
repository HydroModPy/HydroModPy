Piezometry
==========

``piezometry`` loads groundwater-level observation wells and chronicles. It is
used to inspect aquifer state information, calibrate heads or depths, and
compare simulated groundwater levels against observed records.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - Local piezometer records are authoritative.
     - :doc:`custom`
   * - ``hubeau``
     - Hub'Eau piezometry should discover or download public observations.
     - :doc:`hubeau`

Minimal example
---------------

.. code-block:: toml

   [data.piezometry]
   date_start = "2000-01-01"
   date_end = "2020-12-31"

   [[data.piezometry.sources]]
   source = "hubeau"
   product = "level"
   extent = "watershed"

Visual check
------------

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_timeseries_piezometry.png
   :alt: Nancon piezometry time series
   :width: 100%

   Piezometry records should be checked for product meaning, date coverage,
   gaps, and vertical reference before they are compared to simulated heads.

.. figure:: /_static/user_guide/data/observations_local_timeseries_examples.png
   :alt: Local piezometry chronicle alongside other observation families
   :width: 100%

   The middle panel is a local piezometry chronicle. It keeps the groundwater
   level semantics separate from discharge and chemistry even though the file
   convention is similar.

Downstream uses
---------------

- head or depth calibration targets;
- groundwater-state validation;
- basin screening before solver setup;
- comparison reports.

.. toctree::
   :maxdepth: 1

   custom
   hubeau
