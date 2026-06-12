"""Pydantic configuration models for ``[simulation.results]``."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.config_kit.profile import Profile


class DerivedConfig(HydroModelBase):
    """Toggle flags for derived variable computation."""

    watertable_elevation: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Compute water-table elevation from uppermost saturated layer.",
    )
    watertable_depth: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Compute water-table depth (surface minus water-table elevation).",
    )
    seepage_areas: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Identify seepage areas where water table >= surface elevation.",
    )
    groundwater_flux: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Magnitude of inter-cell flow (right/front/lower face). Volumetric.",
    )
    release_flux: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Positive total groundwater release flux from drains and surface excess.",
    )
    accumulation_flux: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Drain flux routed on the drainage network.",
    )
    release_accumulation_flux: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Release flux routed on surface drainage paths.",
    )
    outflow_drain: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Positive per-cell drain outflow summed over layers.",
    )
    concentration_seepage: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Concentration at seepage cells only. Requires transport.",
    )
    mass_seepage: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Mass flux at seepage cells. Requires transport + budget.",
    )
    mass_accumulated: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Cumulative mass_seepage over time.",
    )


class BudgetConfig(HydroModelBase):
    """Budget extraction configuration."""

    spatial_fields: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Extract per-cell budget fields (DRN, RCH, etc.) into Zarr.",
    )


class ResultsConfig(HydroModelBase):
    """Configuration for ``[simulation.results]``.

    Controls whether simulation outputs are stored in the Catalog and
    which derived variables are computed. Automated export formats live in the
    top-level ``[export]`` section (:class:`ExportConfig`), not here.
    """

    persistence: Annotated[PersistenceConfig, Profile.USER] = Field(
        default_factory=PersistenceConfig,
        description=(
            "Simulation-run persistence switch passed to the result catalog "
            "(DuckDB rows, Zarr fields, Parquet tables, lockfile)."
        ),
    )
    keep_solver_files: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Keep raw solver output files (.hds, .cbc, .lst) after ingestion.",
    )
    solver_scratch: Annotated[str, Profile.DEV] = Field(
        default=".solver_scratch",
        description=(
            "Directory for temporary solver files, relative to the project. "
            "Use an absolute path (e.g. /scratch/$USER/hmp) for HPC."
        ),
    )
    derived: Annotated[DerivedConfig, Profile.USER] = Field(
        default_factory=DerivedConfig,
        description="Derived variable computation toggles.",
    )
    budget: Annotated[BudgetConfig, Profile.DEV] = Field(
        default_factory=BudgetConfig,
        description="Budget extraction configuration.",
    )


__all__ = [
    "BudgetConfig",
    "DerivedConfig",
    "ResultsConfig",
]
