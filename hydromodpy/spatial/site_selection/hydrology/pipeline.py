"""Catchment-delineation phase for site-selection builds."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hydromodpy.spatial.site_selection.candidates.outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.hydrology.delineation import (
    AreaReader,
    DelineatedCatchment,
    DelineationBuilder,
    try_delineate_candidate_outlet,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts


def delineate_site_selection_candidates(
    candidates: Iterable[CandidateOutlet],
    *,
    flow_products: SiteSelectionFlowProducts,
    output_root: str | Path,
    snap_dist_m: int,
    crs_project: str | None,
    backend: object | None = None,
    delineation_builder: DelineationBuilder | None = None,
    area_reader: AreaReader | None = None,
    reference_network: object | None = None,
    reference_network_source: str = "",
    reference_network_snap_tolerance_m: float | None = None,
) -> list[DelineatedCatchment]:
    """Delineate all candidate outlets with the same DEM products and settings."""

    builder_kwargs = {}
    if delineation_builder is not None:
        builder_kwargs["builder"] = delineation_builder

    return [
        try_delineate_candidate_outlet(
            outlet=candidate,
            flow_products=flow_products,
            output_root=output_root,
            snap_dist_m=snap_dist_m,
            crs_project=crs_project or candidate.crs,
            site_id=candidate.candidate_id,
            backend=backend,
            area_reader=area_reader,
            reference_network=reference_network,
            reference_network_source=reference_network_source,
            reference_network_snap_tolerance_m=reference_network_snap_tolerance_m,
            **builder_kwargs,
        )
        for candidate in candidates
    ]


__all__ = ["delineate_site_selection_candidates"]
