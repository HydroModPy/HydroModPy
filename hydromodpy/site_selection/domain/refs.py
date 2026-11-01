"""Stable evidence-reference helpers for site selection."""

from __future__ import annotations


def observation_evidence_ref(
    *,
    site_id: str,
    observation_type: str,
    feature_id: str | None,
) -> str | None:
    """Return a stable reference for an observation feature."""

    if not feature_id:
        return None
    return ":".join(
        [
            _clean_part(observation_type),
            _clean_part(site_id),
            _clean_part(feature_id),
        ]
    )


def influence_evidence_ref(
    *,
    site_id: str,
    influence_type: str,
    feature_id: str | None = None,
    feature_index: int | None = None,
) -> str:
    """Return a stable reference for one influence feature."""

    identifier = feature_id if feature_id else str(feature_index or "unknown")
    return ":".join(
        [
            "influence",
            _clean_part(site_id),
            _clean_part(influence_type),
            _clean_part(identifier),
        ]
    )


def geology_evidence_ref(
    *,
    site_id: str,
    source_layer: str | None,
    geology_class: str | None,
) -> str | None:
    """Return a stable reference for one geology class in one catchment."""

    if not source_layer or not geology_class:
        return None
    return ":".join(
        [
            "geology",
            _clean_part(site_id),
            _clean_part(source_layer),
            _clean_part(geology_class),
        ]
    )


def _clean_part(value: object) -> str:
    text = str(value).strip()
    return text.replace(":", "_") if text else "unknown"


__all__ = [
    "geology_evidence_ref",
    "influence_evidence_ref",
    "observation_evidence_ref",
]
