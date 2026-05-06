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
     - ``custom``
   * - ``hubeau``
     - Hub'Eau chemistry observations should be retrieved.
     - ``hubeau``

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

.. figure:: /_static/user_guide/data/observations_local_timeseries_examples.png
   :alt: Local water-quality chronicle alongside other observation families
   :width: 100%

   The lower panel is a local chemistry chronicle. This kind of figure should
   name the parameter and make the concentration scale visible before the
   record is reused in transport or diagnostic workflows.

Downstream uses
---------------

- observation context in basin reports;
- transport or concentration workflows when relevant;
- data availability screening.

Water Quality Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` when local chemistry station and chronicle files
should be authoritative.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.water_quality.sources]]
   source = "custom"
   path = "data/water_quality"
   site_type = "river"
   col_id = "station"
   col_datetime = "date"
   col_value = "value"
   source_unit = "mg/L"

Operational checks
""""""""""""""""""

- Keep parameter names and units explicit.
- Distinguish river and piezometer sites with ``site_type``.
- Inspect records for censoring, gaps, and inconsistent units before reuse.


Water Quality Source: hubeau
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "hubeau"`` to retrieve public chemistry observations.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.water_quality.sources]]
   source = "hubeau"
   site_type = "river"
   parameters = ["NO3"]
   extent = "watershed"
   require_observations = true

Operational checks
""""""""""""""""""

- ``site_type`` selects river or piezometer observations.
- ``parameters`` should be narrow enough to keep the downloaded chronology
  interpretable.
- Always inspect units and station metadata before comparing values across
  providers or sites.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/hubeau_provider_replay_examples.png
   :alt: Hub'Eau water-quality replay with station inventory and chronicle coverage
   :width: 100%

   The water-quality part of the Hub'Eau replay is intentionally plotted with
   the other observation families: chemistry shares the station/time-series
   contract, but parameter identity and units decide whether the values are
   usable.
