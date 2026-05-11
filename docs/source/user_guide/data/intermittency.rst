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
     - ``custom``
   * - ``hubeau``
     - Hub'Eau/ONDE-style public intermittency observations should be retrieved.
     - ``hubeau``

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

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_timeseries_intermittency.png
   :alt: Nancon intermittency time series
   :width: 100%

   Intermittency is a state observation. The figure should make the state
   coding, dates, and stations readable before it is compared with a simulated
   active network.

Local deterministic run
-----------------------

The repository also includes a local intermittency-only case under
``hydromodpy/data/variables/intermittency/cases``. It is useful for explaining
the custom file convention without relying on an online Hub'Eau request.

.. figure:: /_static/user_guide/data/intermittency_local_state_example.png
   :alt: Local custom intermittency state timeline and state-count histogram
   :width: 100%

   The timeline checks whether station identifiers, dates, and categorical
   state codes were loaded as intended. The histogram makes the balance between
   dry, transitional, and flowing states visible before the data are compared
   with a simulated active network.

Downstream uses
---------------

- active-network interpretation;
- qualitative validation of drainage/seepage behavior;
- seasonal low-flow diagnostics.

Intermittency Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` when local flow-state observations should be
ingested from project files.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.intermittency.sources]]
   source = "custom"
   path = "data/intermittency"
   col_id = "station"
   col_datetime = "date"
   col_value = "state"

Operational checks
""""""""""""""""""

- Document the state coding used in the local file.
- Confirm that station coordinates are available or discoverable.
- Do not compare state observations to simulated fluxes until the thresholding
  rule has been stated explicitly.


Intermittency Source: hubeau
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "hubeau"`` to retrieve public flow-state observations.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.intermittency.sources]]
   source = "hubeau"
   extent = "watershed"
   code_departement = ["35", "53"]

Operational checks
""""""""""""""""""

- Department filters can keep discovery predictable.
- Check observation dates against the simulation or comparison window.
- The data are categorical observations, not discharge values.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/hubeau_provider_replay_examples.png
   :alt: Hub'Eau intermittency replay with station inventory and categorical states
   :width: 100%

   The intermittency part of the Hub'Eau replay shows categorical state values,
   not a continuous hydrological flux. That distinction should be visible
   before ONDE-style data are compared with a simulated active network.
