"""Analysis hub aggregating batch, capability-gallery, and comparison sub-configs.

Single TOML entry point ``[analysis]`` for every post-simulation analysis
sub-section. Replaces the disjoint root-level entries previously exposed
under ``[batch]`` and ``[capability_gallery]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

if TYPE_CHECKING:
    from hydromodpy.analysis.batch.config import RegionalLabConfig
    from hydromodpy.analysis.capability_gallery import CapabilityGalleryConfig
    from hydromodpy.analysis.comparison.experiment_config import ComparisonSection


class AnalysisConfig(HydroModelBase):
    """Hub aggregating every post-simulation analysis sub-section.

    Each field is optional: enabling ``[analysis.batch]`` triggers the
    regional-lab launcher, ``[analysis.capability_gallery]`` selects
    figures for the versionable gallery, and ``[analysis.comparison]``
    drives the comparison launcher.
    """

    batch: Annotated[RegionalLabConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional regional-lab batch settings loaded from "
            "[analysis.batch]. Parsed standalone via "
            "RegionalLabLauncher under the section name [regional_lab]."
        ),
    )
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
            "Parsed standalone via SimulationComparisonConfig under the section name [comparison]."
        ),
    )


__all__ = ["AnalysisConfig"]
