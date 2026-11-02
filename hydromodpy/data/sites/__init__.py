"""Sites of a workspace: the catalog ``data/sites/catalog.csv``, its importers, the gauge.

- ``catalog``: read and write the catalog in ``SiteRow`` rows, the nearest site,
  the name and distance checks of ``hmp site add`` and ``import``.
- ``importers``: a site table, a vector layer, or Hub'Eau stations
  to rows.
- ``outlet_snap``: move an outlet onto the nearest line of a river network.
- ``gauge``: ``[site] gauge`` as the station of the series sources, and the
  gauge a run records.
"""
