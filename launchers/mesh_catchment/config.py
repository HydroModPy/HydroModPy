"""Pydantic schemas for launcher-level catchment meshing sections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from hydromodpy.data_managers.variables.geology.config import GeologyConfigSchema
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingSettingsSchema,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.domain import (
    ZoneMeshingDomainBBoxSchema,
    ZoneMeshingDomainGeographicBoxBufferSchema,
    ZoneMeshingDomainGeographicWatershedBoxSchema,
    ZoneMeshingDomainGeographicWatershedSchema,
    ZoneMeshingDomainPolygonSchema,
    ZoneMeshingDomainVectorSchema,
)


ZoneMeshingDomainSchema = (
    ZoneMeshingDomainBBoxSchema
    | ZoneMeshingDomainPolygonSchema
    | ZoneMeshingDomainVectorSchema
    | ZoneMeshingDomainGeographicBoxBufferSchema
    | ZoneMeshingDomainGeographicWatershedSchema
    | ZoneMeshingDomainGeographicWatershedBoxSchema
)


class MeshCatchmentRiversConfigSchema(BaseModel):
    """River-trace inputs consumed by the conformal mesher."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        default="domain_geographic",
        description=(
            "Origin of the river constraints used to force mesh edges along the river network. "
            "Use 'domain_geographic' for the in-memory river trace produced by geographic preprocessing, "
            "or 'file' to reload a vector river dataset from disk."
        ),
    )
    path: str | None = Field(
        default=None,
        description=(
            "Vector file path used only when source='file'. "
            "The path may be absolute or relative to the TOML location and should point to a line dataset "
            "describing the river centerlines to honor during meshing."
        ),
    )
    clip_to_domain: bool = Field(
        default=True,
        description=(
            "If true, clip the river trace to the effective meshing support before sending it to Gmsh. "
            "Keep this enabled in most workflows to avoid constraining the mesh with segments that lie outside "
            "the chosen domain or scope."
        ),
    )
    min_segment_length: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Minimum retained river segment length, in projected metres after reprojection. "
            "Use this to discard tiny residual segments created by clipping or noisy hydrography "
            "that would only add mesh complexity without hydraulic meaning."
        ),
    )
    snap_tolerance: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Reserved snapping tolerance, in projected metres, for future cleanup of nearly coincident river vertices. "
            "The current workflow stores the value in the config contract but does not yet apply an additional snapping pass."
        ),
    )

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: object) -> str:
        token = str(value).strip().lower()
        if token not in {"domain_geographic", "file"}:
            raise ValueError("rivers.source must be 'domain_geographic' or 'file'.")
        return token

    @field_validator("path")
    @classmethod
    def _validate_optional_path(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("rivers.path cannot be empty when provided.")
        return text

    @model_validator(mode="after")
    def _validate_file_mode(self) -> "MeshCatchmentRiversConfigSchema":
        if self.source == "file" and self.path is None:
            raise ValueError("rivers.path is required when rivers.source='file'.")
        return self


class MeshCatchmentConfigSchema(BaseModel):
    """Top-level launcher contract for one mono-catchment meshing run."""

    model_config = ConfigDict(extra="forbid")

    constraints_mode: str = Field(
        ...,
        description=(
            "Meshing compliance target. "
            "'geology_only' conforms the mesh to geology interfaces only, "
            "'rivers_only' conforms the mesh to river traces only, and "
            "'geology_rivers' enforces both sets of constraints in one mesh."
        ),
    )
    output_mesh: str | None = Field(
        default=None,
        description=(
            "Optional `.msh` output path for the generated planar mesh. "
            "When omitted, the launcher writes the mesh to `results_stable/mesh/gmsh/mesh_catchment.msh` "
            "inside the active catchment workspace."
        ),
    )
    output_summary_json: str | None = Field(
        default=None,
        description=(
            "Optional JSON sidecar path for QA metrics, cleaned-input diagnostics, "
            "and summary metadata describing the generated mesh. "
            "When omitted, the launcher writes it next to the default mesh output."
        ),
    )
    output_figure: str | None = Field(
        default=None,
        description=(
            "Optional overview figure path. "
            "Use it when you want a quick visual QA artifact showing the support domain, "
            "geology zones, river constraints, and final mesh footprint."
        ),
    )
    show_plot: bool = Field(
        default=False,
        description=(
            "If true, open the generated overview figure interactively at the end of the run. "
            "Keep it false for batch or headless execution."
        ),
    )
    rivers: MeshCatchmentRiversConfigSchema = Field(
        default_factory=MeshCatchmentRiversConfigSchema,
        description=(
            "River-constraint section used when constraints_mode includes rivers. "
            "The default behavior is to reuse the in-memory river trace already built by the geographic pipeline."
        ),
    )
    geology: GeologyConfigSchema | None = Field(
        default=None,
        description=(
            "Optional geology support used when constraints_mode includes geology. "
            "This section defines which polygon source represents lithological zones and how those polygons "
            "should be interpreted before conformal meshing."
        ),
    )
    domain: ZoneMeshingDomainSchema = Field(
        default_factory=ZoneMeshingDomainGeographicBoxBufferSchema,
        description=(
            "Effective support domain to mesh. "
            "The default `geographic_box_buffer` mode reuses the catchment bounding box plus geographic buffer "
            "prepared during delineation, which is usually the right support for mono-catchment meshing."
        ),
    )
    interface_scope: ZoneMeshingDomainSchema | None = Field(
        default=None,
        description=(
            "Optional sub-domain where geology and river interfaces are actually materialized. "
            "Use it to keep the support domain large enough for context while constraining interfaces "
            "only on a stricter inner area."
        ),
    )
    refinement_scope: ZoneMeshingDomainSchema | None = Field(
        default=None,
        description=(
            "Optional sub-domain where interface refinement is allowed to act. "
            "This scope is always clipped to the effective interface_scope and is useful when you want interfaces "
            "on a broad support but fine cells only near the core catchment."
        ),
    )
    zone_meshing: ZoneMeshingSettingsSchema = Field(
        default_factory=ZoneMeshingSettingsSchema,
        description=(
            "Low-level Gmsh sizing and cleanup parameters controlling cell size, simplification, "
            "and interface refinement. Defaults are valid, but project examples typically override them "
            "to target a desired number of cells."
        ),
    )

    @field_validator("constraints_mode")
    @classmethod
    def _validate_constraints_mode(cls, value: object) -> str:
        token = str(value).strip().lower()
        if token not in {"geology_only", "rivers_only", "geology_rivers"}:
            raise ValueError(
                "constraints_mode must be one of: geology_only, rivers_only, geology_rivers."
            )
        return token

    @field_validator("output_mesh", "output_summary_json", "output_figure")
    @classmethod
    def _validate_optional_output_path(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("output paths cannot be empty when provided.")
        return text

    @model_validator(mode="after")
    def _validate_required_subsections(self) -> "MeshCatchmentConfigSchema":
        if self.constraints_mode in {"geology_only", "geology_rivers"} and self.geology is None:
            raise ValueError(
                "geology section is required when constraints_mode includes geology."
            )
        return self


class MeshCatchmentBatchOutputsSchema(BaseModel):
    """Output filename patterns for batch meshing."""

    model_config = ConfigDict(extra="forbid")

    mesh_filename: str | None = Field(
        default=None,
        description=(
            "Relative filename pattern for each generated mesh, resolved inside the outlet-specific mesh output folder. "
            "Use tokens like {outlet_id} and {catch_name}."
        ),
    )
    summary_filename: str | None = Field(
        default=None,
        description=(
            "Relative filename pattern for each JSON mesh summary written in batch mode."
        ),
    )
    figure_filename: str | None = Field(
        default=None,
        description=(
            "Relative filename pattern for each overview figure written in batch mode."
        ),
    )
    manifest_csv: str | None = Field(
        default=None,
        description=(
            "Manifest CSV path summarizing the status of all outlet runs. "
            "Relative paths are resolved from the base catchment project root."
        ),
    )

    @field_validator("mesh_filename", "summary_filename", "figure_filename", "manifest_csv")
    @classmethod
    def _validate_optional_pattern(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("batch output patterns cannot be empty when provided.")
        return text


class MeshCatchmentBatchSectionSchema(BaseModel):
    """Optional batch loop over several outlet coordinates."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "Enable batch mode. When false or omitted, the launcher runs one mono-catchment workflow only."
        ),
    )
    outlets_table_path: str | None = Field(
        default=None,
        description=(
            "CSV or vector table listing outlet points to process in batch mode."
        ),
    )
    outlet_id_column: str = Field(
        default="outlet_id",
        description="Column storing the outlet identifier in the batch table.",
    )
    x_column: str = Field(
        default="x_outlet_m",
        description="Column storing the outlet X coordinate in the batch table.",
    )
    y_column: str = Field(
        default="y_outlet_m",
        description="Column storing the outlet Y coordinate in the batch table.",
    )
    selection_mode: str = Field(
        default="all",
        description=(
            "Batch selection strategy. Use 'all' to process every outlet in the table, or 'selected' "
            "to restrict the batch to the outlet ids listed in selected_outlet_ids."
        ),
    )
    selected_outlet_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit subset of outlet ids to mesh when selection_mode='selected'."
        ),
    )
    catch_name_pattern: str = Field(
        default="{catch_name}_outlet_{outlet_id}",
        description=(
            "Pattern used to derive the child catchment workspace name for each outlet. "
            "It must contain the {outlet_id} token."
        ),
    )
    continue_on_error: bool = Field(
        default=False,
        description=(
            "If true, keep processing later outlets after one batch item fails."
        ),
    )
    outputs: MeshCatchmentBatchOutputsSchema = Field(
        default_factory=MeshCatchmentBatchOutputsSchema,
        description=(
            "Optional batch-specific filename patterns. Use them whenever the main [mesh_catchment] section contains fixed output paths, "
            "so each outlet writes distinct artifacts."
        ),
    )

    @field_validator("outlets_table_path", "outlet_id_column", "x_column", "y_column", "catch_name_pattern")
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("batch text fields cannot be empty when provided.")
        return text

    @field_validator("selection_mode")
    @classmethod
    def _validate_selection_mode(cls, value: object) -> str:
        token = str(value).strip().lower()
        if token not in {"all", "selected"}:
            raise ValueError("selection_mode must be 'all' or 'selected'.")
        return token

    @field_validator("selected_outlet_ids", mode="before")
    @classmethod
    def _normalize_selected_outlet_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)) or not isinstance(value, list):
            raise ValueError("selected_outlet_ids must be a list when provided.")
        return [str(item).strip() for item in value if str(item).strip() != ""]

    @model_validator(mode="after")
    def _validate_enabled_contract(self) -> "MeshCatchmentBatchSectionSchema":
        if not self.enabled:
            return self
        if self.outlets_table_path is None:
            raise ValueError("outlets_table_path is required when batch mode is enabled.")
        if self.selection_mode == "selected" and not self.selected_outlet_ids:
            raise ValueError(
                "selection_mode='selected' requires at least one selected_outlet_ids value."
            )
        if "{outlet_id}" not in self.catch_name_pattern:
            raise ValueError("catch_name_pattern must contain '{outlet_id}'.")
        return self


def validate_mesh_catchment_config_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one `[mesh_catchment]` section and return normalized data."""
    if not isinstance(config_data, Mapping):
        raise ValueError("mesh_catchment configuration must be a mapping.")
    try:
        parsed = MeshCatchmentConfigSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python")


def validate_mesh_catchment_batch_config_data(
    config_data: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one optional `[mesh_catchment_batch]` section."""
    if not isinstance(config_data, Mapping):
        raise ValueError("mesh_catchment_batch configuration must be a mapping.")
    try:
        parsed = MeshCatchmentBatchSectionSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python")


__all__ = [
    "MeshCatchmentBatchOutputsSchema",
    "MeshCatchmentBatchSectionSchema",
    "MeshCatchmentConfigSchema",
    "MeshCatchmentRiversConfigSchema",
    "validate_mesh_catchment_batch_config_data",
    "validate_mesh_catchment_config_data",
]
