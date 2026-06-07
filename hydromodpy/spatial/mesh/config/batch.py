"""Batch launcher contract for mesh-catchment looping over outlets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr, StripLower


class MeshCatchmentBatchOutputs(HydroModelBase):
    """Output filename patterns for batch meshing."""

    mesh_filename: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Relative filename pattern for each generated mesh, resolved inside the outlet-specific mesh output folder. "
            "Use tokens like {outlet_id} and {catch_name}."
        ),
    )
    summary_filename: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description=("Relative filename pattern for each JSON mesh summary written in batch mode."),
    )
    figure_filename: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description=("Relative filename pattern for each overview figure written in batch mode."),
    )
    figure_regional_filename: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Relative filename pattern for each regional overview figure written in batch mode."
        ),
    )
    manifest_csv: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Manifest CSV path summarizing the status of all outlet runs. "
            "Relative paths are resolved from the base catchment project root."
        ),
    )


class MeshCatchmentBatchSection(HydroModelBase):
    """Optional batch loop over several outlet coordinates."""

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Enable batch mode. When false or omitted, the launcher runs one mono-catchment workflow only."
        ),
    )
    outlets_table_path: Annotated[NonEmptyStr | None, Profile.USER] = Field(
        default=None,
        description=("CSV or vector table listing outlet points to process in batch mode."),
    )
    outlet_id_column: Annotated[NonEmptyStr, Profile.DEV] = Field(
        default="outlet_id",
        description="Column storing the outlet identifier in the batch table.",
    )
    x_column: Annotated[NonEmptyStr, Profile.DEV] = Field(
        default="x_outlet_m",
        description="Column storing the outlet X coordinate in the batch table.",
    )
    y_column: Annotated[NonEmptyStr, Profile.DEV] = Field(
        default="y_outlet_m",
        description="Column storing the outlet Y coordinate in the batch table.",
    )
    selection_mode: Annotated[Literal["all", "selected"], StripLower, Profile.DEV] = Field(
        default="all",
        description=(
            "Batch selection strategy. Use 'all' to process every outlet in the table, or 'selected' "
            "to restrict the batch to the outlet ids listed in selected_outlet_ids."
        ),
    )
    selected_outlet_ids: Annotated[list[str], Profile.DEV] = Field(
        default_factory=list,
        description=("Explicit subset of outlet ids to mesh when selection_mode='selected'."),
    )
    catch_name_pattern: Annotated[NonEmptyStr, Profile.DEV] = Field(
        default="{catch_name}_outlet_{outlet_id}",
        description=(
            "Pattern used to derive the child catchment workspace name for each outlet. "
            "It must contain the {outlet_id} token."
        ),
    )
    continue_on_error: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description=("If true, keep processing later outlets after one batch item fails."),
    )
    outputs: Annotated[MeshCatchmentBatchOutputs, Profile.DEV] = Field(
        default_factory=MeshCatchmentBatchOutputs,
        description=(
            "Optional batch-specific filename patterns. Use them whenever the main [mesh_catchment] section contains fixed output paths, "
            "so each outlet writes distinct artifacts."
        ),
    )

    @field_validator("selected_outlet_ids", mode="before")
    @classmethod
    def _normalize_selected_outlet_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)) or not isinstance(value, list):
            raise ValueError("selected_outlet_ids must be a list when provided.")
        return [str(item).strip() for item in value if str(item).strip() != ""]

    @model_validator(mode="after")
    def _validate_enabled_contract(self) -> MeshCatchmentBatchSection:
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


def parse_mesh_catchment_batch_config_data(
    config_data: Mapping[str, Any],
) -> MeshCatchmentBatchSection:
    """Validate one optional `[mesh_catchment_batch]` section and return the typed model."""
    if not isinstance(config_data, Mapping):
        raise ValueError("mesh_catchment_batch configuration must be a mapping.")
    try:
        return MeshCatchmentBatchSection.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


__all__ = [
    "MeshCatchmentBatchOutputs",
    "MeshCatchmentBatchSection",
    "parse_mesh_catchment_batch_config_data",
]
