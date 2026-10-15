"""The ``[sites]`` section: one project, N catchments, M recipes.

``models`` holds the section as the TOML declares it, validated when the file
is read and without touching the disk. Expanding sites x recipes into cases
(reading the site table, rendering ``bind``, the precedence of a case) builds
on these models in the same package.
"""

from __future__ import annotations

from hydromodpy.config.sites.models import (
    RECIPE_NAME_PATTERN,
    RecipeDecl,
    RecipeSpec,
    SitesConfig,
    SitesExportRequest,
    SitesRunConfig,
    SitesSummaryConfig,
)

__all__ = [
    "RECIPE_NAME_PATTERN",
    "RecipeDecl",
    "RecipeSpec",
    "SitesConfig",
    "SitesExportRequest",
    "SitesRunConfig",
    "SitesSummaryConfig",
]
