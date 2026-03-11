from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from hydromodpy.config.param_level import ParamLevel


class GeologyConfig(BaseModel):
    """
    Geology configuration for watershed geology extraction.

    This model stores the inputs required to build the geology zone field
    used in the `Domain` object.
    """

    id: Annotated[str, ParamLevel("user")] = Field(
        default="field_geology",
        description="Identifier of the geology spatial field.",
    )
    geo_path: Annotated[Path, ParamLevel("user")] = Field(
        default=Path("data/France/geology"),
        description="Path to the geology data directory.",
    )
    types_obs: Annotated[str, ParamLevel("user")] = Field(
        default="GEO1M.shp",
        description="Geology shapefile name inside `geo_path`.",
    )
    fields_obs: Annotated[str, ParamLevel("user")] = Field(
        default="CODE_LEG",
        description="Attribute field used to encode geology classes.",
    )
    cell_samples_per_axis: Annotated[int, ParamLevel("dev")] = Field(
        default=8,
        ge=2,
        description=(
            "Sub-sampling density passed to geology_field.on_mesh(...). "
            "Higher values improve interface resolution but increase runtime."
        ),
    )
    landsea: Annotated[bool | None, ParamLevel("dev")] = Field(
        default=None,
        description=(
            "Legacy land/sea activation flag. Kept for compatibility in config "
            "interfaces; not used by the Domain GeologyField pipeline."
        ),
    )

    @field_validator("id", "types_obs", "fields_obs")
    @classmethod
    def _validate_non_empty_text(cls, value: str) -> str:
        text = str(value).strip()
        if text == "":
            raise ValueError("value cannot be empty")
        return text
