"""Reusable catchment report presets."""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.display.catchment_report.artifacts import (
    DEFAULT_ARTIFACT_SPECS,
    NANCON_ARTIFACT_SPECS,
    ReportArtifactSpec,
)
from hydromodpy.display.catchment_report.block_specs import (
    GENERIC_BLOCK_SPECS,
    NANCON_BLOCK_SPECS,
    ReportBlockSpec,
)


@dataclass(frozen=True)
class CatchmentReportPreset:
    name: str
    artifact_specs: tuple[ReportArtifactSpec, ...]
    block_specs: tuple[ReportBlockSpec, ...]
    allow_gallery_fallbacks: bool = True
    description: str = ""


NANCON_REPORT_PRESET = CatchmentReportPreset(
    name="nancon_reference",
    artifact_specs=NANCON_ARTIFACT_SPECS,
    block_specs=NANCON_BLOCK_SPECS,
    allow_gallery_fallbacks=True,
    description="Reference report preset used to preserve the validated Nancon HTML.",
)

GENERIC_REPORT_PRESET = CatchmentReportPreset(
    name="generic_catchment_report",
    artifact_specs=DEFAULT_ARTIFACT_SPECS,
    block_specs=GENERIC_BLOCK_SPECS,
    allow_gallery_fallbacks=False,
    description="Generic catchment report preset using local artifacts only.",
)


__all__ = [
    "CatchmentReportPreset",
    "GENERIC_REPORT_PRESET",
    "NANCON_REPORT_PRESET",
]
