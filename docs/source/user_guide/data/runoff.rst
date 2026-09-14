Runoff
======

``runoff`` loads surface-runoff forcing or hydrological diagnostics. It should
not be confused with groundwater discharge or drainage-package fluxes. Field
definitions, types, and defaults live in the generated reference at
:doc:`/user_guide/config_reference/data`; this page only names them and shows
how to use them.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - A local station chronicle (directory of location and CSV files) or a
       single gridded NetCDF/GeoTIFF file is authoritative.
     - ``custom``
   * - ``sim2``
     - SIM2 ``RUNC_Q`` runoff should be retrieved over the project period and
       extent.
     - ``sim2``

Minimal example
---------------

.. code-block:: toml

   [data.runoff]
   date_start = "2000-01-01"
   date_end = "2002-12-31"

   [[data.runoff.sources]]
   source = "sim2"
   extent = "watershed"

``date_start`` and ``date_end`` are defined at
:ref:`date_start <data-runoff-date-start>` and
:ref:`date_end <data-runoff-date-end>`.
:ref:`source <data-runoff-sources-source>` selects the provider, and
:ref:`extent <data-runoff-sources-extent>` picks the bounding box. Check period
coverage, units, and semantic meaning before comparing runoff with simulated
groundwater discharge.

Loaded shape
------------

``RunoffManager`` (``hydromodpy.data.variables.runoff.manager``, in the
:mod:`hydromodpy.data` layer) normalizes every source to the internal unit
``mm/day``. What it returns depends on
:ref:`path <data-runoff-sources-path>`: a directory of a location file plus
chronicle CSVs yields one point time series per station, while a single
``.nc`` or ``.tif`` file, or the ``sim2`` source, yields a gridded field.

Runoff does not enter the ``Flow`` process as a groundwater forcing the way
recharge does. It stays a loaded, station- or grid-based quantity that
calibration and comparison logic can later add to the simulated
groundwater-release signal, to check against total observed streamflow at
outlet scale. The full semantic split is documented in
:doc:`/theory/hydrology/recharge-and-surface-exchange-semantics`.

Visual check
------------

.. figure:: /_static/user_guide/data/forcing_local_recharge_runoff_example.png
   :alt: Local custom runoff and recharge source series
   :width: 100%

   Runoff should be read as a forcing or diagnostic source, not as simulated
   groundwater discharge. The paired custom figure makes that distinction
   visible by keeping the source chronicle separate from any solver response.

Downstream uses
---------------

- calibration and comparison logic, which may add runoff to the simulated
  groundwater-release signal before comparing against observed streamflow
  (:doc:`/theory/hydrology/recharge-and-surface-exchange-semantics`);
- water-balance and forcing checks alongside :doc:`recharge` and
  :doc:`precipitation`, which share the same station and gridded conventions;
- diagnostic figures produced from local or SIM2 sources, as listed in
  :doc:`runs-and-figures`.

Runoff Source: custom
^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local runoff fields or time series. ``path`` can
point to a directory of station files or to a single gridded file, as defined
at :ref:`path <data-runoff-sources-path>`.

.. code-block:: toml

   [[data.runoff.sources]]
   source = "custom"
   path = "data/runoff/runoff.nc"
   source_unit = "mm/day"

Set :ref:`source_unit <data-runoff-sources-source-unit>` when file metadata
are missing or ambiguous, and check the semantic meaning of the runoff
product before using it in water balance reasoning.

Runoff Source: sim2
^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 runoff fields.

.. code-block:: toml

   [[data.runoff.sources]]
   source = "sim2"
   extent = "watershed"

The overview climatic summary panel plots precipitation and ETP only, so it
does not show runoff. Use the source chronicle under `Visual check`_ for
period and magnitude checks, and keep runoff distinct from modeled drainage or
groundwater discharge.
