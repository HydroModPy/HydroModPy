"""Reusable catchment report presets."""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.display.catchment_report.artifacts import (
    DEFAULT_ARTIFACT_SPECS,
    ReportArtifactSpec,
)
from hydromodpy.display.catchment_report.block_specs import (
    GENERIC_BLOCK_SPECS,
    ReportBlockSpec,
)


@dataclass(frozen=True)
class CatchmentReportPreset:
    name: str
    artifact_specs: tuple[ReportArtifactSpec, ...]
    block_specs: tuple[ReportBlockSpec, ...]
    description: str = ""


GENERIC_REPORT_PRESET = CatchmentReportPreset(
    name="generic_catchment_report",
    artifact_specs=DEFAULT_ARTIFACT_SPECS,
    block_specs=GENERIC_BLOCK_SPECS,
    description="Generic catchment report preset using local artifacts only.",
)

PRESETS_BY_NAME = {
    GENERIC_REPORT_PRESET.name: GENERIC_REPORT_PRESET,
    "generic": GENERIC_REPORT_PRESET,
}


def preset_from_name(name: str) -> CatchmentReportPreset:
    try:
        return PRESETS_BY_NAME[name]
    except KeyError as exc:
        choices = ", ".join(sorted(PRESETS_BY_NAME))
        raise ValueError(f"Unknown catchment report preset {name!r}. Choices: {choices}.") from exc


__all__ = [
    "CatchmentReportPreset",
    "GENERIC_REPORT_PRESET",
    "PRESETS_BY_NAME",
    "preset_from_name",
]
