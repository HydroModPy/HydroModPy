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

from __future__ import annotations

from hydromodpy.core.site.config import SITE_NAME_PATTERN, SITE_URI_PATTERN, SiteConfig
from hydromodpy.core.site.fingerprint import site_fingerprint
from hydromodpy.core.site.gauge import GaugeConflictError, resolve_gauge
from hydromodpy.core.site.row import SITE_ROW_COLUMNS, SiteRow

__all__ = [
    "SITE_NAME_PATTERN",
    "SITE_ROW_COLUMNS",
    "SITE_URI_PATTERN",
    "GaugeConflictError",
    "SiteConfig",
    "SiteRow",
    "resolve_gauge",
    "site_fingerprint",
]
