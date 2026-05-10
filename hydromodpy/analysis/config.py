"""Analysis hub aggregating capability-gallery and comparison sub-configs.

Single TOML entry point ``[analysis]`` for every post-simulation analysis
sub-section. Replaces the disjoint root-level entries previously exposed
under root-level analysis sections.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import ConfigDict, Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

if TYPE_CHECKING:
    from hydromodpy.analysis.capability_gallery import CapabilityGalleryConfig
    from hydromodpy.analysis.comparison.config import ComparisonSection


class AnalysisConfig(HydroModelBase):
    """Hub aggregating every post-simulation analysis sub-section.

    Each field is optional: ``[analysis.capability_gallery]`` selects figures
    for the versionable gallery, and ``[analysis.comparison]`` drives the
    comparison launcher.
    """

    model_config = ConfigDict(extra="forbid")

    capability_gallery: Annotated[CapabilityGalleryConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional publication block copying selected run figures into a "
            "versionable capability-gallery source folder, loaded from "
            "[analysis.capability_gallery]."
        ),
    )
    comparison: Annotated[ComparisonSection | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional simulation-comparison block loaded from [analysis.comparison]. "
            "Parsed standalone via ComparisonConfig under the section name [comparison]."
        ),
    )


__all__ = ["AnalysisConfig"]
