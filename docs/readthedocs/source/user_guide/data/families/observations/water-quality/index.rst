Water Quality
=============

``water_quality`` loads chemistry observations for river or piezometer sites.
It documents additional observational context and can support transport or
diagnostic workflows when the selected parameters are meaningful for the study.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - Local chemistry records are authoritative.
     - :doc:`custom`
   * - ``hubeau``
     - Hub'Eau chemistry observations should be retrieved.
     - :doc:`hubeau`

Minimal example
---------------

.. code-block:: toml

   [data.water_quality]
   date_start = "2010-01-01"
   date_end = "2020-12-31"

   [[data.water_quality.sources]]
   source = "hubeau"
   site_type = "river"
   parameters = ["NO3"]
   extent = "watershed"

Visual check
------------

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_timeseries_water_quality.png
   :alt: Nancon water-quality time series
   :width: 100%

   Chemistry records should expose parameter identity, unit, station, and date
   coverage before being used in a workflow.

Downstream uses
---------------

- observation context in basin reports;
- transport or concentration workflows when relevant;
- data availability screening.

.. toctree::
   :maxdepth: 1

   custom
   hubeau
