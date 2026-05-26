"""Adapters from current evidence objects to normalized evidence records."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from hydromodpy.spatial.site_selection.context_evidence import GeologyEvidence
from hydromodpy.spatial.site_selection.decisions.models import EvidenceRecord
from hydromodpy.spatial.site_selection.evidence_refs import (
    geology_evidence_ref,
    influence_evidence_ref,
    observation_evidence_ref,
)
from hydromodpy.spatial.site_selection.influence import InfluenceEvidence
from hydromodpy.spatial.site_selection.types import ObservationEvidence


def evidence_records_from_site_selection_evidence(
    *,
    run_id: str,
    observation_evidence: Iterable[ObservationEvidence] = (),
    influence_evidence: Iterable[InfluenceEvidence] = (),
    geology_evidence: Iterable[GeologyEvidence] = (),
) -> list[EvidenceRecord]:
    """Convert current specialized evidence objects into normalized records."""

    records = [
        *evidence_records_from_observation_evidence(
            observation_evidence,
            run_id=run_id,
        ),
        *evidence_records_from_influence_evidence(
            influence_evidence,
            run_id=run_id,
        ),
        *evidence_records_from_geology_evidence(
            geology_evidence,
            run_id=run_id,
        ),
    ]
    return sorted(
        records,
        key=lambda record: (
            record.catchment_id,
            record.criterion_family,
            record.criterion_id,
            record.evidence_ref,
        ),
    )


def evidence_records_from_observation_evidence(
    evidence: Iterable[ObservationEvidence],
    *,
    run_id: str,
) -> list[EvidenceRecord]:
    """Convert observation evidence into normalized evidence records."""

    records: list[EvidenceRecord] = []
    for item in evidence:
        evidence_ref = observation_evidence_ref(
            site_id=item.site_id,
            observation_type=item.observation_type,
            feature_id=item.feature_id,
        )
        if evidence_ref is None:
            continue
        record = item.to_record()
        provider_location = dict((item.evidence_json or {}).get("provider_location") or {})
        records.append(
            EvidenceRecord(
                run_id=run_id,
                evidence_ref=evidence_ref,
                catchment_id=item.site_id,
                criterion_family="observations",
                criterion_id=item.observation_type,
                source_name=item.source_dataset,
                feature_id=item.feature_id,
                feature_label=item.feature_label,
                geometry=_point_geometry(provider_location),
                properties={
                    **record,
                    "provider_location_crs": provider_location.get("crs"),
                },
            )
        )
    return records


def evidence_records_from_influence_evidence(
    evidence: Iterable[InfluenceEvidence],
    *,
    run_id: str,
) -> list[EvidenceRecord]:
    """Convert influence evidence into normalized evidence records."""

    records: list[EvidenceRecord] = []
    for item in evidence:
        evidence_ref = influence_evidence_ref(
            site_id=item.site_id,
            influence_type=item.influence_type,
            feature_id=item.feature_id,
            feature_index=item.feature_index,
        )
        records.append(
            EvidenceRecord(
                run_id=run_id,
                evidence_ref=evidence_ref,
                catchment_id=item.site_id,
                criterion_family="anthropic_influence",
                criterion_id="influence",
                source_name=item.source_layer,
                feature_id=item.feature_id,
                feature_label=item.feature_label,
                geometry=item.geometry,
                properties={
                    **item.to_record(),
                    "evidence_ref": evidence_ref,
                },
            )
        )
    return records


def evidence_records_from_geology_evidence(
    evidence: Iterable[GeologyEvidence],
    *,
    run_id: str,
) -> list[EvidenceRecord]:
    """Convert geology evidence into normalized evidence records."""

    records: list[EvidenceRecord] = []
    for item in evidence:
        evidence_ref = geology_evidence_ref(
            site_id=item.site_id,
            source_layer=item.source_layer,
            geology_class=item.geology_class,
        )
        if evidence_ref is None:
            continue
        records.append(
            EvidenceRecord(
                run_id=run_id,
                evidence_ref=evidence_ref,
                catchment_id=item.site_id,
                criterion_family="geology",
                criterion_id="geology",
                source_name=item.source_layer,
                feature_id=";".join(item.feature_ids) or item.geology_class,
                feature_label=item.geology_class,
                geometry=item.geometry,
                properties={
                    **item.to_record(),
                    "evidence_ref": evidence_ref,
                },
            )
        )
    return records


def _point_geometry(provider_location: dict[str, Any]) -> dict[str, Any] | None:
    x = provider_location.get("x")
    y = provider_location.get("y")
    if x is None or y is None:
        return None
    try:
        return {"type": "Point", "coordinates": [float(x), float(y)]}
    except (TypeError, ValueError):
        return None


__all__ = [
    "evidence_records_from_geology_evidence",
    "evidence_records_from_influence_evidence",
    "evidence_records_from_observation_evidence",
    "evidence_records_from_site_selection_evidence",
]
