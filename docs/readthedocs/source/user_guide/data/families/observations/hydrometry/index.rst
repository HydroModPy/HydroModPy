Hydrometry
==========

``hydrometry`` loads discharge stations and streamflow chronicles. The family
is used for basin screening, outlet-response checks, calibration objectives,
and post-simulation hydrograph comparison.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - Local station and discharge files are authoritative.
     - :doc:`custom`
   * - ``hubeau``
     - Hub'Eau hydrometry should discover or download public discharge data.
     - :doc:`hubeau`

Minimal example
---------------

.. code-block:: toml

   [data.hydrometry]
   date_start = "2000-01-01"
   date_end = "2020-12-31"

   [[data.hydrometry.sources]]
   source = "hubeau"
   product = "QmnJ"
   extent = "watershed"

Visual check
------------

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_timeseries_discharge.png
   :alt: Nancon discharge time series
   :width: 100%

   The discharge chronicle should show station identity, date coverage, gaps,
   and magnitude before it is used for calibration or comparison.

.. figure:: /_static/user_guide/data/observations_local_timeseries_examples.png
   :alt: Local hydrometry chronicle alongside other observation families
   :width: 100%

   The first panel is a local hydrometry chronicle. It illustrates the
   minimum custom-source check: the station has a readable period, magnitude,
   and event structure before it becomes a calibration or comparison target.

Downstream uses
---------------

- observed hydrographs;
- calibration objectives;
- discharge comparison metrics;
- active-network interpretation when combined with hydrography.

.. toctree::
   :maxdepth: 1

   custom
   hubeau
