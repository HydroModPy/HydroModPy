"""A ``[site]`` of one project resolved against the site catalog of the workspace.

A project that models one catchment names it in ``[site]``. When the
workspace keeps a site catalog (``data/sites/catalog.csv``), the name is
looked up there: a known name whose outlet lies farther than ``near_site_m``
from the declared one is refused, since two projects would then call two
catchments by one name. An unknown name near a declared site is returned
with ``known_name=False``, so the caller can say under which name the
catalog knows it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.site import SiteRow
from hydromodpy.core.workspace.workspace_toml import NEAR_SITE_M_DEFAULT
from hydromodpy.core.workspace.workspace_toml import near_site_m as workspace_near_site_m


class SiteMismatchError(ConfigError):
    """The site named by the project is another catchment in the catalog."""


@dataclass(frozen=True, slots=True)
class SiteMatch:
    """The catalog row a project's site resolved to, and how far its outlet is."""

    row: SiteRow
    distance_m: float | None
    known_name: bool
    """Whether the row was found by name (True) or by outlet distance (False)."""


def match_site(
    name: str,
    outlet: tuple[float, float] | None,
    crs: str | None,
    rows: Sequence[SiteRow],
    *,
    near_site_m: float = NEAR_SITE_M_DEFAULT,
) -> SiteMatch | None:
    """Resolve a site against catalog rows.

    A row of the same name is the match; its outlet farther than
    *near_site_m* from *outlet* raises :class:`SiteMismatchError`. Without a
    row of that name, the nearest row within *near_site_m* is returned with
    ``known_name=False``; none gives ``None``.
    """
    from hydromodpy.data.sites.catalog import nearest_site

    by_name = next((row for row in rows if row.site == name), None)
    if by_name is not None:
        distance = None
        if outlet is not None:
            found = nearest_site([by_name], x=outlet[0], y=outlet[1], crs=crs)
            distance = found[1] if found is not None else None
        if distance is not None and distance > near_site_m:
            raise SiteMismatchError(
                f"[site] name = {name!r} is declared in the site catalog with an outlet "
                f"{distance:.0f} m away (near_site_m = {near_site_m:g} m): another "
                "catchment, or a moved outlet. Name this site otherwise, or fix the catalog."
            )
        return SiteMatch(row=by_name, distance_m=distance, known_name=True)
    if outlet is None:
        return None
    found = nearest_site(rows, x=outlet[0], y=outlet[1], crs=crs)
    if found is None or found[1] > near_site_m:
        return None
    return SiteMatch(row=found[0], distance_m=found[1], known_name=False)


def resolve_single_site(
    config: Any, workspace_root: str | Path, *, near_site_m: float | None = None
) -> SiteMatch | None:
    """Resolve ``[site]`` of a loaded configuration against the workspace catalog.

    Returns ``None`` without a ``[site]`` or without a catalog. Raises
    :class:`SiteMismatchError` when the catalog knows the name under another
    outlet. *near_site_m* unset is ``[sites] near_site_m`` of the workspace.
    """
    site = getattr(config, "site", None)
    if site is None:
        return None
    from hydromodpy.data.sites.catalog import catalog_path, read_catalog

    root = Path(workspace_root)
    if not catalog_path(root).is_file():
        return None
    geographic = getattr(config, "geographic", None)
    x = getattr(geographic, "x_outlet", None)
    y = getattr(geographic, "y_outlet", None)
    outlet = (float(x), float(y)) if x is not None and y is not None else None
    crs = getattr(geographic, "crs_project", None)
    distance = workspace_near_site_m(root) if near_site_m is None else near_site_m
    return match_site(site.name, outlet, crs, read_catalog(root), near_site_m=distance)


__all__ = ["SiteMatch", "SiteMismatchError", "match_site", "resolve_single_site"]
