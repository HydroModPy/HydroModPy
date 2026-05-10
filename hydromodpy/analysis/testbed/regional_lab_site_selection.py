"""Regional-lab site selection helpers."""

from __future__ import annotations

from collections.abc import Sequence

from hydromodpy.analysis.testbed.regional_lab_config import RegionalLabSelectionConfig
from hydromodpy.analysis.testbed.regional_lab_types import RegionalLabSiteRecord


def matches_text_filter(value: str | None, allowed: tuple[str, ...]) -> bool:
    """Return whether one optional text value matches one allowed-text filter."""
    if not allowed:
        return True
    normalized_value = "" if value is None else value.lower()
    return normalized_value in {item.lower() for item in allowed}


def site_matches_selection(
    site: RegionalLabSiteRecord,
    *,
    selection: RegionalLabSelectionConfig,
) -> bool:
    """Return whether one regional-lab site matches selection filters."""
    if not selection.include_disabled and not site.enabled:
        return False
    if selection.site_ids and site.site_id.lower() not in {
        item.lower() for item in selection.site_ids
    }:
        return False
    if not matches_text_filter(site.cluster_id, selection.cluster_ids):
        return False
    if not matches_text_filter(site.region_id, selection.regions):
        return False
    if not matches_text_filter(site.cluster_family, selection.families):
        return False
    if not matches_text_filter(site.cluster_scale, selection.scales):
        return False
    if not matches_text_filter(site.site_status, selection.statuses):
        return False
    if not matches_text_filter(site.maturity, selection.maturity_levels):
        return False
    if selection.tags:
        site_tags = {item.lower() for item in site.tags}
        required_tags = {item.lower() for item in selection.tags}
        if not required_tags.issubset(site_tags):
            return False
    return True


def filter_sites(
    sites: Sequence[RegionalLabSiteRecord],
    *,
    selection: RegionalLabSelectionConfig,
) -> list[RegionalLabSiteRecord]:
    """Filter and stably sort regional-lab site records."""
    selected = [site for site in sites if site_matches_selection(site, selection=selection)]
    selected.sort(
        key=lambda site: (
            "" if site.region_id is None else site.region_id.lower(),
            "" if site.cluster_id is None else site.cluster_id.lower(),
            site.site_id.lower(),
        )
    )
    if selection.limit is not None:
        return selected[: int(selection.limit)]
    return selected


__all__ = [
    "filter_sites",
    "matches_text_filter",
    "site_matches_selection",
]
