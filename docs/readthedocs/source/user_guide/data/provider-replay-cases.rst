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
   :alt: Hydrography provider replay for custom and BD Topage data
   :width: 100%

   The current committed replay covers local/custom hydrography and BD Topage
   samples. OSM and EU-Hydro are deliberately marked as a remaining gallery gap
   until a small bbox can be fetched, cached, locked, and published as a stable
   replay artifact.

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

- OSM versus BD Topage on one small bbox, with network density and geometry
  differences made explicit.
- EU-Hydro on the same bbox or a larger basin where a continental product is
  meaningful.
- A coastal SHOM basin where the stage chronicle is connected to an actual
  coastal boundary condition rather than only a data replay.
- A Hub'Eau refresh case that displays downloaded station discovery next to a
  frozen replay from the cache and lockfile.
