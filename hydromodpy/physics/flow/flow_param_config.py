"""FlowParam - typed wrapper around FieldParamConfig with TOML hints."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, PrivateAttr

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.spatial.field.core.field_param_config import (
    FieldParamConfig,
    FieldSection,
    FieldVerticalProfileSection,
    resolve_field_param_config_payload,
)


class FlowParam(FieldParamConfig):
    """Flow parameter payload using native field-param sections."""

    field: Annotated[FieldSection, Profile.USER] = Field(
        ...,
        description="Discriminated parameter section `[field]`.",
    )
    field_vertical_profile: Annotated[FieldVerticalProfileSection | None, Profile.USER] = Field(
        default=None,
        description="Optional depth profile section `[field_vertical_profile]`.",
    )

    _base_dir: Path | None = PrivateAttr(default=None)
    _section_label: str = PrivateAttr(default="flow.param")

    def model_post_init(self, context: Any) -> None:
        super().model_post_init(context)
        if isinstance(context, Mapping):
            raw_base_dir = context.get("base_dir")
            if isinstance(raw_base_dir, Path):
                self._base_dir = raw_base_dir
        self._section_label = self._section_label_from_field()

    def _section_label_from_field(self) -> str:
        field_id = self.field.id
        if field_id:
            return f"flow.param.{field_id}"
        return "flow.param"

    def resolved_payload(
        self,
        *,
        param_id: str | None = None,
        base_dir: Path | None = None,
        section_label: str | None = None,
    ) -> dict[str, Any]:
        """Return the resolved runtime field-parameter payload."""
        return resolve_field_param_config_payload(
            self.model_dump(mode="python", exclude_none=True),
            param_id=param_id,
            base_dir=base_dir or self._base_dir,
            section_label=section_label or self._section_label,
        )


__all__ = ["FlowParam"]
