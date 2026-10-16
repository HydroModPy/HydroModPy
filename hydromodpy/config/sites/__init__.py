"""The ``[sites]`` section: one project, N catchments, M recipes.

``models`` holds the section as the TOML declares it, validated when the file
is read and without touching the disk; this package re-exports it, since the
root configuration imports it. The rest is imported by module, because it
imports the root configuration back:

- ``expansion``: :func:`~hydromodpy.config.sites.expansion.expand_plan`, sites
  x recipes resolved into cases, the precedence of a case, the site scoped
  keys, the origin of every error;
- ``plan``: :func:`~hydromodpy.config.sites.plan.write_plan_draft`, the plan
  written once under ``plan/<hash>/``;
- ``budget``: what a plan costs, the lines of ``--dry-run``, the ceilings;
- ``check``: :func:`~hydromodpy.config.sites.check.check_project`, the one
  check behind ``hmp config check``;
- ``single_site``: a ``[site]`` resolved against the site catalog of the
  workspace.
"""

from __future__ import annotations

from hydromodpy.config.sites.models import (
    PARALLEL_CEILING,
    RECIPE_NAME_PATTERN,
    RecipeDecl,
    RecipeSpec,
    SitesConfig,
    SitesExportRequest,
    SitesRunConfig,
    SitesSummaryConfig,
)

__all__ = [
    "PARALLEL_CEILING",
    "RECIPE_NAME_PATTERN",
    "RecipeDecl",
    "RecipeSpec",
    "SitesConfig",
    "SitesExportRequest",
    "SitesRunConfig",
    "SitesSummaryConfig",
]
