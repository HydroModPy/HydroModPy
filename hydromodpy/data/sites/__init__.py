"""Sites of a workspace: the catalog ``data/sites/catalog.csv``, its importers, the gauge.

- ``catalog``: read and write the catalog in ``SiteRow`` rows, the nearest site,
  the name and distance checks of ``hmp site add`` and ``import``.
- ``importers``: a site table, a vector layer, Hub'Eau stations or a
  site-selection manifest to rows.
- ``gauge``: ``[site] gauge`` as the station of the series sources, and the
  gauge a run records.
"""
