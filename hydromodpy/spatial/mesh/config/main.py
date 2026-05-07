"""Top-level mono-catchment launcher contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr, StripLower
from hydromodpy.spatial.mesh.config.hydraulic import (
    MeshCatchmentHydraulicPropertiesConfig,
)
from hydromodpy.spatial.mesh.config.rivers import MeshCatchmentRiversConfig
from hydromodpy.spatial.mesh.config.watershed import MeshCatchmentWatershedBoundaryConfig
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingSettings,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.domain import (
    ZoneMeshingDomain as ZoneMeshingDomainSchema,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.domain import (
    ZoneMeshingDomainGeographicBoxBuffer,
)
from hydromodpy.spatial.protocols import get_geology_data_source


class MeshCatchmentConfig(HydroModelBase):
    """Top-level launcher contract for one mono-catchment meshing run."""

    constraints_mode: Annotated[
        Literal["geology_only", "rivers_only", "geology_rivers"],
        StripLower,
        Profile.USER,
    ] = Field(
        "geology_rivers",
        description=(
            "Meshing compliance target. "
            "'geology_only' conforms the mesh to geology interfaces only, "
            "'rivers_only' conforms the mesh to river traces only, and "
            "'geology_rivers' enforces both sets of constraints in one mesh."
        ),
    )
    output_mesh: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional `.msh` output path for the generated planar mesh. "
            "When omitted, the launcher writes the mesh to `results_stable/mesh/mesh_catchment.msh` "
            "inside the active catchment workspace in standard layout, or directly to "
            "`workspace.project_root/mesh_catchment.msh` when `output_layout='flat'` is used."
        ),
    )
    output_summary_json: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional JSON sidecar path for QA metrics, cleaned-input diagnostics, "
            "and summary metadata describing the generated mesh. "
            "When omitted, the launcher writes it next to the default mesh output."
        ),
    )
    output_figure: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional overview figure path. "
            "Use it when you want a quick visual QA artifact showing the support domain, "
            "geology zones, river constraints, and final mesh footprint."
        ),
    )
    output_figure_regional: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional regional overview figure path. "
            "When omitted but output_figure is set, the launcher writes a second figure next to the main one "
            "with suffix `_regional` to show where the catchment sits on the full DEM."
        ),
    )
    figures_enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "If true, generate the overview figure artifacts when figure output paths are configured. "
            "Set it to false to skip figure creation entirely, even in batch mode where default filename patterns are present."
        ),
    )
    export_exchange_bundle: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "If true, export the solver-exchange mesh bundle next to the generated mesh. "
            "Set it to false for profiling or mesh-only runs that do not need bundle metadata. "
            "Downstream solvers that require runtime mesh support may fail without this bundle."
        ),
    )
    figure_dpi: Annotated[int, Profile.USER] = Field(
        default=300,
        gt=0,
        description=(
            "Pixel density used when rendering the main mesh overview figure. "
            "Increase it when you need to inspect mesh edges and constraints more closely in the saved PNG."
        ),
    )
    figure_regional_dpi: Annotated[int, Profile.USER] = Field(
        default=220,
        gt=0,
        description=(
            "Pixel density used when rendering the regional overview figure. "
            "Keep it lower than figure_dpi when you want detailed local mesh inspection without making the regional PNG too heavy."
        ),
    )
    output_layout: Annotated[Literal["standard", "flat"], StripLower, Profile.USER] = Field(
        default="standard",
        description=(
            "Dedicated-launcher output layout. "
            "Use 'standard' to keep final mesh artifacts under `results_stable/mesh/`, "
            "or 'flat' to write final mesh artifacts directly under `workspace.project_root` "
            "while keeping intermediate runtime folders out of that final directory."
        ),
    )
    show_plot: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "If true, open the generated overview figure interactively at the end of the run. "
            "Keep it false for batch or headless execution."
        ),
    )
    geographic_outputs_mode: Annotated[Literal["keep", "cleanup"], StripLower, Profile.DEV] = Field(
        default="keep",
        description=(
            "Control what happens to intermediate geographic preprocessing artifacts after the mesh run. "
            "Use 'keep' to preserve the canonical `results_stable/geographic` and `results_stable/demcorrecflow` "
            "folders, or 'cleanup' to delete them at the end of the dedicated mesh launcher once the mesh outputs "
            "and exchange bundle have been written."
        ),
    )
    rivers: Annotated[MeshCatchmentRiversConfig, Profile.USER] = Field(
        default_factory=MeshCatchmentRiversConfig,
        description=(
            "River-constraint section used when constraints_mode includes rivers. "
            "The default behavior is to reuse the in-memory river trace already built by the geographic pipeline."
        ),
    )
    geology: Annotated[dict[str, Any] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional geology support used when constraints_mode includes geology. "
            "This section defines which polygon source represents lithological zones and how those polygons "
            "should be interpreted before conformal meshing. "
            "Validated through the geology data-source Protocol; stored as a normalized mapping."
        ),
    )
    watershed_boundary: Annotated[MeshCatchmentWatershedBoundaryConfig, Profile.USER] = Field(
        default_factory=MeshCatchmentWatershedBoundaryConfig,
        description=(
            "Optional watershed-boundary mesh constraint. "
            "Enable it to force a conformal mesh line along the catchment boundary while keeping the geology zonation "
            "represented on the whole support domain."
        ),
    )
    hydraulic_properties: Annotated[MeshCatchmentHydraulicPropertiesConfig | None, Profile.USER] = (
        Field(
            default=None,
            description=(
                "Optional hydraulic-property tables keyed by geology zones. "
                "The launcher projects geology on the mesh and exports per-cell conductivity/storage values "
                "as weighted averages of geology fractions."
            ),
        )
    )
    domain: Annotated[ZoneMeshingDomainSchema, Profile.USER] = Field(
        default_factory=ZoneMeshingDomainGeographicBoxBuffer,
        description=(
            "Effective support domain to mesh. "
            "The default `geographic_box_buffer` mode reuses the catchment bounding box plus geographic buffer "
            "prepared during delineation, which is usually the right support for mono-catchment meshing."
        ),
    )
    zone_meshing: Annotated[ZoneMeshingSettings, Profile.DEV] = Field(
        default_factory=ZoneMeshingSettings,
        description=(
            "Low-level Gmsh sizing and cleanup parameters controlling cell size, simplification, "
            "and interface refinement. Defaults are valid, but project examples typically override them "
            "to target a desired number of cells."
        ),
    )

    @field_validator("geology", mode="before")
    @classmethod
    def _validate_geology_block(cls, value: object) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError("geology section must be a mapping.")
        return get_geology_data_source().validate_config(dict(value))

    @model_validator(mode="after")
    def _validate_required_subsections(self) -> MeshCatchmentConfig:
        if self.constraints_mode in {"geology_only", "geology_rivers"} and self.geology is None:
            raise ValueError("geology section is required when constraints_mode includes geology.")
        if (
            self.geology is None
            and self.watershed_boundary.geology_conformity.mode != "full_domain"
        ):
            raise ValueError("watershed_boundary.geology_conformity requires the geology section.")
        if self.hydraulic_properties is not None and self.geology is None:
            raise ValueError(
                "hydraulic_properties requires the geology section because exported properties are keyed by geology zones."
            )
        return self


def parse_mesh_catchment_config_data(
    config_data: Mapping[str, Any],
) -> MeshCatchmentConfig:
    """Validate one `[mesh_catchment]` section and return the typed model."""
    if not isinstance(config_data, Mapping):
        raise ValueError("mesh_catchment configuration must be a mapping.")
    for removed_key in ("interface_scope", "refinement_scope"):
        if removed_key in config_data:
            raise ValueError(
                f"[mesh_catchment.{removed_key}] is no longer supported. "
                "Keep one single support domain and constrain the mesh with geology and/or rivers only."
            )
    raw_constraints_mode = config_data.get("constraints_mode")
    if raw_constraints_mode is None or str(raw_constraints_mode).strip() == "":
        raise ValueError("constraints_mode is required.")
    try:
        return MeshCatchmentConfig.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


__all__ = [
    "MeshCatchmentConfig",
    "ZoneMeshingDomainSchema",
    "parse_mesh_catchment_config_data",
]
