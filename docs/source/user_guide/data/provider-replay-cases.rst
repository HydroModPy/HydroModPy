Provider Replay Cases
=====================

Provider-specific documentation should be reproducible. The figures on this
page are built from committed provider artifacts in ``examples/data`` rather
than from live API calls. That makes the examples stable enough for Read the
Docs while still showing the real payload shapes used by SHOM, Hub'Eau, SIM2,
and hydrography providers.

Policy
------

.. figure:: /_static/user_guide/data/provider_gallery_policy_ladder.png
   :alt: Provider gallery policy from replay to refresh, cache, lock, and compare
   :width: 100%

   The default documentation path is replay first. Live downloads should be
   intentional refresh runs, followed by cache persistence, lockfile recording,
   and a visible provider-specific comparison.

Hub'Eau Replay
--------------

.. figure:: /_static/user_guide/data/hubeau_provider_replay_examples.png
   :alt: Hub'Eau provider replay across observation families
   :width: 100%

   Hub'Eau is not one visual contract. Hydrometry, piezometry, water quality,
   and ONDE-style intermittency all use station metadata plus chronicles, but
   their units, quality flags, and downstream meanings differ. The replay
   figure keeps those families visible on one page without calling the API.

SHOM Replay
-----------

.. figure:: /_static/user_guide/data/shom_provider_replay_example.png
   :alt: SHOM provider replay for one coastal sea-level station
   :width: 100%

   The SHOM replay shows both station selection and the sea-level chronicle.
   The custom mirror is useful for testing the loader and for documenting the
   boundary-stage contract without depending on a live coastal-data request.

Hydrography Replay
------------------

.. figure:: /_static/user_guide/data/hydrography_provider_replay_examples.png
   :alt: Hydrography provider replay for custom, BD Topage, OSM, and EU-Hydro data
   :width: 100%

   The committed replay now covers the local/custom regional network and a
   small Couesnon bbox for BD Topage, OSM, and EU-Hydro. The three public
   provider files are stored as GPKG artifacts in ``examples/data/hydrography``.

.. figure:: /_static/user_guide/data/hydrography_provider_couesnon_comparison.png
   :alt: Couesnon hydrography comparison between BD Topage, OSM, and EU-Hydro
   :width: 100%

   The comparison clips all three provider payloads to the same bbox before
   plotting density. This makes the provider choice visible: OSM is denser in
   small tributaries, EU-Hydro is coarser, and BD Topage sits between them for
   this local case.

The provider refresh script is intentionally separate from the replay-only
figure renderer:

.. code-block:: powershell

   python docs/source/user_guide/data/refresh_hydrography_provider_replays.py --case couesnon --providers bdtopage osm euhydro

SIM2 Replay
-----------

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 gridded forcing replay
   :width: 100%

   SIM2 replay needs both a map and a temporal aggregate: the gridded support
   confirms spatial coverage, while monthly summaries make the selected period
   auditable.

Next Provider Cases
-------------------

The remaining provider-specific gallery work should be done in this order:

- Repeat the hydrography comparison on a second basin where OSM completeness
  is less favorable, so the documentation does not imply that one density
  result generalizes everywhere.
- Add a larger EU-Hydro basin where the continental product is used at its
  intended scale rather than only as a contrast on a small bbox.
- A coastal SHOM basin where the stage chronicle is connected to an actual
  coastal boundary condition rather than only a data replay.
- A Hub'Eau refresh case that displays downloaded station discovery next to a
  frozen replay from the cache and lockfile.
