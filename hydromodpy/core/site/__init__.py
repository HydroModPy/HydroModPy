"""The site: one catchment, declared once and recognized everywhere.

A site is what a run is about: a name, a label, the gauge that scores it, an
optional URI that survives two workspaces, and an outlet or a polygon. The
``[site]`` section of a project (:class:`SiteConfig`) declares it; a row of
``data/sites/catalog.csv`` (:class:`SiteRow`) stores it for the workspace.
:func:`site_fingerprint` recognizes a site from its declaration, never from a
DEM, and :func:`resolve_gauge` makes ``[site] gauge`` the single source of the
station every other key falls back to.

This package lives in ``core`` because the config layer, the result formats and
the data layer all read it, and none of them may import another for it.
"""
