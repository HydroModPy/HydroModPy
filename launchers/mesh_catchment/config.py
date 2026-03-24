"""Schema contract for the dedicated mesh-catchment launcher.

This module sits one layer above the generic HydroModPy runtime schemas. It
defines the launcher-only sections that control how a delineated catchment is
meshed, how optional batch loops are configured, and how launcher-level output
paths are resolved.

The underlying meshing, geology, and geographic models live elsewhere in the
codebase; this file assembles those pieces into one user-facing TOML contract.
"""

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


# ---------------------------------------------------------------------------
# River constraints
# ---------------------------------------------------------------------------

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
            "Reserved snapping tolerance, in projected metres, for possible future cleanup of nearly coincident "
            "river vertices. The current workflow stores the value in the launcher contract but does not apply an "
            "additional snapping pass."
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


class MeshCatchmentWatershedBoundarySmoothingConfigSchema(BaseModel):
    """Optional smoothing controls for the watershed-boundary constraint."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "If true, apply the smoothing controls below before converting the watershed boundary into one linear constraint."
        ),
    )
    distance: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional regularization tolerance, in projected metres, used to simplify the watershed boundary "
            "at roughly the target internal mesh scale before it is injected as a linear mesh constraint. "
            "When omitted, the mesher reuses zone_meshing.global_size."
        ),
    )
    river_buffer_distance: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional protective buffer around river traces, in projected metres, merged into the boundary-support "
            "polygon before smoothing so the final watershed boundary stays slightly outside river corridors near the basin edge."
        ),
    )
    outer_bias_distance: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional outward bias, in projected metres, applied after smoothing so the final watershed boundary "
            "remains slightly englobing instead of cutting back toward the raw catchment contour."
        ),
    )


class MeshCatchmentWatershedOutsideCoarseningConfigSchema(BaseModel):
    """Optional coarse-background size controls outside the watershed."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "If true, add one regional mesh-size field that keeps the current background size inside the watershed "
            "and coarsens the mesh outside it."
        ),
    )
    size_factor: float = Field(
        default=2.0,
        ge=1.0,
        description=(
            "Multiplicative factor applied to zone_meshing.global_size outside the watershed. "
            "Use 2.0 for an outside background roughly twice as coarse as the internal baseline."
        ),
    )
    transition_distance: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional transition width, in projected metres, used to ramp from the internal background size "
            "to the coarser outside size away from the watershed boundary."
        ),
    )
    grid_resolution: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "Optional structured-grid resolution, in projected metres, used to discretize the outside coarsening field. "
            "When omitted, the mesher reuses zone_meshing.global_size."
        ),
    )


class MeshCatchmentWatershedGeologyConformityConfigSchema(BaseModel):
    """Optional control of where geology remains conformal around the watershed."""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(
        default="full_domain",
        description=(
            "Control where geology remains conformal. "
            "Use 'full_domain' to keep the current behavior, or 'buffered_watershed_envelope' "
            "to keep geology conformal only inside one buffered envelope around the regularized watershed."
        ),
    )
    buffer_distance: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional outward buffer, in projected metres, added around the regularized watershed before clipping "
            "the geology-conformal region. When omitted in buffered_watershed_envelope mode, the mesher reuses zone_meshing.global_size."
        ),
    )

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, value: object) -> str:
        token = str(value).strip().lower()
        if token not in {"full_domain", "buffered_watershed_envelope"}:
            raise ValueError(
                "geology_conformity.mode must be 'full_domain' or 'buffered_watershed_envelope'."
            )
        return token


class MeshCatchmentWatershedBoundaryConfigSchema(BaseModel):
    """Optional watershed-boundary mesh constraint."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "If true, inject the watershed boundary as one dedicated linear constraint in addition to geology "
            "and/or river constraints."
        ),
    )
    boundary_refinement_distance: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional influence distance, in projected metres, used for the watershed-boundary refinement family. "
            "When omitted, the mesher derives one conservative distance from the boundary extent."
        ),
    )
    smoothing: MeshCatchmentWatershedBoundarySmoothingConfigSchema = Field(
        default_factory=MeshCatchmentWatershedBoundarySmoothingConfigSchema,
        description=(
            "Optional regularization controls applied before the watershed boundary is converted to a linear constraint."
        ),
    )
    outside_coarsening: MeshCatchmentWatershedOutsideCoarseningConfigSchema = Field(
        default_factory=MeshCatchmentWatershedOutsideCoarseningConfigSchema,
        description=(
            "Optional coarse-background size field applied outside the regularized watershed while keeping the geology partition unchanged."
        ),
    )
    geology_conformity: MeshCatchmentWatershedGeologyConformityConfigSchema = Field(
        default_factory=MeshCatchmentWatershedGeologyConformityConfigSchema,
        description=(
            "Optional control of where geology remains conformal relative to the watershed. "
            "Keep the default full_domain mode to preserve the current behavior."
        ),
    )


_SUPPORTED_HYDRAULIC_VALUE_SOURCES = {"inline", "csv"}


def _validate_hydraulic_scalar(
    value: object,
    *,
    label: str,
) -> float | str | None:
    """Normalize one hydraulic-property scalar coming from TOML or CSV."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{label} must be numeric or a non-empty string.")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        raise ValueError(f"{label} cannot be empty when provided.")
    return text


class MeshCatchmentHydraulicPropertyMappingSchema(BaseModel):
    """Zone-key to property mapping contract used by bundle export."""

    model_config = ConfigDict(extra="forbid")

    values_source: str = Field(
        default="inline",
        description=(
            "Source of the geology-key to property mapping. "
            "Use 'inline' for TOML dictionaries or 'csv' for an external table."
        ),
    )
    values: dict[str, object] | None = Field(
        default=None,
        description=(
            "Inline mapping from geology zone key to property value. "
            "Keys must match the normalized `zone_key` values exported by the geology loader."
        ),
    )
    values_csv_file: str | None = Field(
        default=None,
        description=(
            "CSV file used when values_source='csv'. "
            "Relative paths are resolved from the launcher TOML directory."
        ),
    )
    csv_key_column: str = Field(
        default="zone_key",
        description="CSV column containing geology zone keys.",
    )
    csv_value_column: str = Field(
        default="value",
        description="CSV column containing numeric property values.",
    )
    default_value: object | None = Field(
        default=None,
        description=(
            "Fallback value applied when one geology zone has no explicit mapping. "
            "Leave empty to keep exported cell values undefined for unmapped zones."
        ),
    )

    @field_validator("values_source")
    @classmethod
    def _validate_values_source(cls, value: object) -> str:
        token = str(value).strip().lower()
        if token not in _SUPPORTED_HYDRAULIC_VALUE_SOURCES:
            allowed = ", ".join(sorted(_SUPPORTED_HYDRAULIC_VALUE_SOURCES))
            raise ValueError(f"values_source must be one of: {allowed}.")
        return token

    @field_validator("values")
    @classmethod
    def _validate_values(cls, value: object) -> dict[str, float | str] | None:
        if value is None:
            return None
        mapping = dict(value)
        if len(mapping) == 0:
            raise ValueError("values cannot be empty when provided.")
        out: dict[str, float | str] = {}
        for raw_key, raw_value in mapping.items():
            key = str(raw_key).strip()
            if key == "":
                raise ValueError("values cannot contain empty geology keys.")
            normalized = _validate_hydraulic_scalar(
                raw_value,
                label=f"values[{key!r}]",
            )
            if normalized is None:
                raise ValueError(f"values[{key!r}] cannot be null.")
            out[key] = normalized
        return out

    @field_validator("values_csv_file")
    @classmethod
    def _validate_values_csv_file(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("values_csv_file cannot be empty when provided.")
        return text

    @field_validator("csv_key_column", "csv_value_column")
    @classmethod
    def _validate_csv_column(cls, value: object) -> str:
        text = str(value).strip()
        if text == "":
            raise ValueError("CSV column names cannot be empty.")
        return text

    @field_validator("default_value")
    @classmethod
    def _validate_default_value(cls, value: object) -> float | str | None:
        return _validate_hydraulic_scalar(value, label="default_value")

    @model_validator(mode="after")
    def _validate_mapping_payload(self) -> "MeshCatchmentHydraulicPropertyMappingSchema":
        if self.values_source == "inline":
            if self.values is None and self.default_value is None:
                raise ValueError(
                    "values or default_value is required when values_source='inline'."
                )
            return self
        if self.values_csv_file is None:
            raise ValueError("values_csv_file is required when values_source='csv'.")
        return self


# ---------------------------------------------------------------------------
# Hydraulic property export contract
# ---------------------------------------------------------------------------

class MeshCatchmentHydraulicConductivitySchema(
    MeshCatchmentHydraulicPropertyMappingSchema
):
    """Conductivity mapping exported on mesh cells."""

    unit: str = Field(
        default="m/s",
        description=(
            "Input unit used by conductivity values. "
            "Exported bundle values are always converted to `m/s`."
        ),
    )

    @field_validator("unit")
    @classmethod
    def _validate_unit(cls, value: object) -> str:
        text = str(value).strip()
        if text == "":
            raise ValueError("conductivity.unit cannot be empty.")
        return text


class MeshCatchmentStorageCoefficientSchema(
    MeshCatchmentHydraulicPropertyMappingSchema
):
    """Storage-coefficient mapping exported on mesh cells."""


class MeshCatchmentHydraulicPropertiesConfigSchema(BaseModel):
    """Optional hydraulic properties derived from the geology zonation."""

    model_config = ConfigDict(extra="forbid")

    conductivity: MeshCatchmentHydraulicConductivitySchema | None = Field(
        default=None,
        description=(
            "Optional hydraulic-conductivity mapping by geology key. "
            "When provided, the bundle exports one `hydraulic_conductivity_m_s` value per cell."
        ),
    )
    storage_coefficient: MeshCatchmentStorageCoefficientSchema | None = Field(
        default=None,
        description=(
            "Optional storage-coefficient mapping by geology key. "
            "When provided, the bundle exports one `storage_coefficient` value per cell."
        ),
    )

    @model_validator(mode="after")
    def _validate_at_least_one_property(
        self,
    ) -> "MeshCatchmentHydraulicPropertiesConfigSchema":
        if self.conductivity is None and self.storage_coefficient is None:
            raise ValueError(
                "hydraulic_properties must define conductivity and/or storage_coefficient."
            )
        return self


# ---------------------------------------------------------------------------
# Main single-run launcher contract
# ---------------------------------------------------------------------------

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
            "When omitted, the launcher writes the mesh to `results_stable/mesh/mesh_catchment.msh` "
            "inside the active catchment workspace in standard layout, or directly to "
            "`workspace.project_root/mesh_catchment.msh` when `output_layout='flat'` is used."
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
    output_figure_regional: str | None = Field(
        default=None,
        description=(
            "Optional regional overview figure path. "
            "When omitted but output_figure is set, the launcher writes a second figure next to the main one "
            "with suffix `_regional` to show where the catchment sits on the full DEM."
        ),
    )
    output_layout: str = Field(
        default="standard",
        description=(
            "Dedicated-launcher output layout. "
            "Use 'standard' to keep final mesh artifacts under `results_stable/mesh/`, "
            "or 'flat' to write final mesh artifacts directly under `workspace.project_root` "
            "while keeping intermediate runtime folders out of that final directory."
        ),
    )
    show_plot: bool = Field(
        default=False,
        description=(
            "If true, open the generated overview figure interactively at the end of the run. "
            "Keep it false for batch or headless execution."
        ),
    )
    geographic_outputs_mode: str = Field(
        default="keep",
        description=(
            "Control what happens to intermediate geographic preprocessing artifacts after the mesh run. "
            "Use 'keep' to preserve the canonical `results_stable/geographic` and `results_stable/demcorrecflow` "
            "folders, or 'cleanup' to delete them at the end of the dedicated mesh launcher once the mesh outputs "
            "and exchange bundle have been written."
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
    watershed_boundary: MeshCatchmentWatershedBoundaryConfigSchema = Field(
        default_factory=MeshCatchmentWatershedBoundaryConfigSchema,
        description=(
            "Optional watershed-boundary mesh constraint. "
            "Enable it to force a conformal mesh line along the catchment boundary while keeping the geology zonation "
            "represented on the whole support domain."
        ),
    )
    hydraulic_properties: MeshCatchmentHydraulicPropertiesConfigSchema | None = Field(
        default=None,
        description=(
            "Optional hydraulic-property tables keyed by geology zones. "
            "The launcher projects geology on the mesh and exports per-cell conductivity/storage values "
            "as weighted averages of geology fractions."
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

    @field_validator("geographic_outputs_mode")
    @classmethod
    def _validate_geographic_outputs_mode(cls, value: object) -> str:
        token = str(value).strip().lower()
        if token not in {"keep", "cleanup"}:
            raise ValueError("geographic_outputs_mode must be 'keep' or 'cleanup'.")
        return token

    @field_validator("output_layout")
    @classmethod
    def _validate_output_layout(cls, value: object) -> str:
        token = str(value).strip().lower()
        if token not in {"standard", "flat"}:
            raise ValueError("output_layout must be 'standard' or 'flat'.")
        return token

    @field_validator(
        "output_mesh",
        "output_summary_json",
        "output_figure",
        "output_figure_regional",
    )
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
        if (
            self.geology is None
            and self.watershed_boundary.geology_conformity.mode
            != "full_domain"
        ):
            raise ValueError(
                "watershed_boundary.geology_conformity requires the geology section."
            )
        if self.hydraulic_properties is not None and self.geology is None:
            raise ValueError(
                "hydraulic_properties requires the geology section because exported properties are keyed by geology zones."
            )
        return self


# ---------------------------------------------------------------------------
# Batch launcher contract
# ---------------------------------------------------------------------------

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
    figure_regional_filename: str | None = Field(
        default=None,
        description=(
            "Relative filename pattern for each regional overview figure written in batch mode."
        ),
    )
    manifest_csv: str | None = Field(
        default=None,
        description=(
            "Manifest CSV path summarizing the status of all outlet runs. "
            "Relative paths are resolved from the base catchment project root."
        ),
    )

    @field_validator(
        "mesh_filename",
        "summary_filename",
        "figure_filename",
        "figure_regional_filename",
        "manifest_csv",
    )
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


def parse_mesh_catchment_config_data(
    config_data: Mapping[str, Any],
) -> MeshCatchmentConfigSchema:
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
        return MeshCatchmentConfigSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def parse_mesh_catchment_batch_config_data(
    config_data: Mapping[str, Any],
) -> MeshCatchmentBatchSectionSchema:
    """Validate one optional `[mesh_catchment_batch]` section and return the typed model."""
    if not isinstance(config_data, Mapping):
        raise ValueError("mesh_catchment_batch configuration must be a mapping.")
    try:
        return MeshCatchmentBatchSectionSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


__all__ = [
    "MeshCatchmentHydraulicConductivitySchema",
    "MeshCatchmentHydraulicPropertiesConfigSchema",
    "MeshCatchmentHydraulicPropertyMappingSchema",
    "MeshCatchmentStorageCoefficientSchema",
    "MeshCatchmentBatchOutputsSchema",
    "MeshCatchmentBatchSectionSchema",
    "MeshCatchmentConfigSchema",
    "MeshCatchmentRiversConfigSchema",
    "MeshCatchmentWatershedBoundaryConfigSchema",
    "MeshCatchmentWatershedBoundarySmoothingConfigSchema",
    "parse_mesh_catchment_batch_config_data",
    "parse_mesh_catchment_config_data",
]
