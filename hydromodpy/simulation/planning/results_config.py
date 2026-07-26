"""Pydantic configuration models for ``[simulation.results]``."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.config_kit.profile import Profile


class DerivedConfig(HydroModelBase):
    """Toggle flags for derived variable computation.

    There is no ``groundwater_flux`` flag: no backend stores the intercell
    face flows it would need. MODFLOW 6 filters FLOW-JA-FACE out of the
    per-cell budget (it is an antisymmetric vector record, not a scalar
    stress term), Boussinesq has no face record at all, and the derivation
    could only ever fail after the solve. The flag was removed with its
    computation rather than kept as a run-killing option.
    """

    watertable_elevation: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Persist water-table elevation (uppermost saturated layer) as a Zarr field. "
            "Off by default: figures recompute it on the fly from the stored head."
        ),
    )
    watertable_depth: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Persist water-table depth (surface minus water-table elevation) as a Zarr "
            "field. Off by default: recomputed on the fly from head at render time."
        ),
    )
    seepage_areas: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Persist the seepage mask (water table >= surface elevation) as a Zarr field. "
            "Off by default: recomputed on the fly from head at render time."
        ),
    )
    release_flux: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Positive total groundwater release flux from drains and surface excess.",
    )
    accumulation_flux: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Drain flux routed on the drainage network.",
    )
    release_accumulation_flux: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Release flux routed on surface drainage paths.",
    )
    outflow_drain: Annotated[bool, Profile.DEV] = Field(
        default=False,
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

    spatial_fields: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Persist per-cell budget fields (DRN, RCH, etc.) into Zarr. Off by default: "
            "the lumped per-component budget still lands in the budgets table, and the "
            "catchment scalars (discharge, well pumping) are derived from it. Turn it on "
            "to map or export a per-cell flux, at the cost of the heaviest arrays a run "
            "can hold."
        ),
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
            "(DuckDB rows, Zarr fields, Parquet tables)."
        ),
    )
    keep_solver_files: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Keep raw solver output files (.hds, .cbc, .lst) after ingestion.",
    )
    derived: Annotated[DerivedConfig, Profile.USER] = Field(
        default_factory=DerivedConfig,
        description="Derived variable computation toggles.",
    )
    budget: Annotated[BudgetConfig, Profile.USER] = Field(
        default_factory=BudgetConfig,
        description="Budget extraction configuration.",
    )


__all__ = [
    "BudgetConfig",
    "DerivedConfig",
    "ResultsConfig",
]
