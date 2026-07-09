"""Pydantic configuration for optional report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

ReportProfileName = Literal["catchment_gauged", "generic_simulation", "site_selection"]


class HtmlReportConfig(HydroModelBase):
    """Intent for optional HTML report artifacts."""

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Prepare artifacts required by the selected HTML report profile. "
            "When omitted, build_at_end=true also enables artifact preparation."
        ),
    )
    build_at_end: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Request end-of-run report handling. This implies enabled=true; "
            "workflow-specific builders can use it to write the final HTML."
        ),
    )
    profile: Annotated[ReportProfileName, Profile.USER] = Field(
        default="catchment_gauged",
        description="Report profile declaring the required and optional artifacts.",
    )
    config_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional workflow-specific report TOML. For profile='catchment_gauged', "
            "this points to the catchment report layout/config used after the "
            "simulation has produced its artifacts."
        ),
    )
    strict: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Fail report postflight when required artifacts are missing. Defaults "
            "to false so ordinary runs can produce partial reports."
        ),
    )

    @model_validator(mode="after")
    def _build_at_end_enables_report(self) -> HtmlReportConfig:
        if self.build_at_end and not self.enabled:
            object.__setattr__(self, "enabled", True)
        return self


class ReportConfig(HydroModelBase):
    """Top-level [report] TOML section."""

    html: Annotated[HtmlReportConfig, Profile.USER] = Field(
        default_factory=HtmlReportConfig,
        description="Optional HTML report intent and artifact contract.",
    )


__all__ = [
    "HtmlReportConfig",
    "ReportConfig",
    "ReportProfileName",
]
