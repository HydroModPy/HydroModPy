"""Root Pydantic base class shared by every HydroModPy config model.

All HydroModPy configuration classes inherit from :class:`HydroModelBase`
rather than :class:`pydantic.BaseModel` directly. This centralises the
strictness defaults (``extra="forbid"``, ``validate_assignment=True``)
that the architecture spec (``architecture_cible/02_config_pydantic.md``
§3.1) requires to be uniform across the codebase.

The root base also validates any :class:`VisibleWhen` metadata attached to
fields: a ``VisibleWhen("sibling", ...)`` tag must reference an existing
field on the same model (catches refactor drift).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticUndefined

from hydromodpy.core.config_kit.introspect import extract_profile
from hydromodpy.core.config_kit.profile import ProfileName
from hydromodpy.core.config_kit.visible_when import VisibleWhen


def _json_schema_examples(field_info: Any) -> list[Any] | None:
    """Return examples for JSON Schema export."""
    explicit = getattr(field_info, "examples", None)
    if explicit:
        return list(explicit)

    annotation = getattr(field_info, "annotation", None)
    args = get_args(annotation)
    if args and all(isinstance(item, str) for item in args):
        return [args[0]]
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return [next(iter(annotation)).value]

    default = getattr(field_info, "default", PydanticUndefined)
    if default is not PydanticUndefined and default is not None:
        if isinstance(default, Enum):
            return [default.value]
        if isinstance(default, (str, int, float, bool, list, dict)):
            return [default]

    origin = get_origin(annotation)
    target = args[0] if origin is Literal and args else annotation
    if target is str:
        return ["example"]
    if target is int:
        return [1]
    if target is float:
        return [1.0]
    if target is bool:
        return [False]
    if target is Path:
        return ["data/input.csv"]
    return None


class HydroModelBase(BaseModel):
    """Common Pydantic base for every HydroModPy configuration model.

    Sets the strictness defaults required by the architecture spec:

    * ``extra="forbid"`` - typos in TOML keys are rejected.
    * ``validate_assignment=True`` - mutations go through validators.
    * ``str_strip_whitespace=True`` - trims free-form string inputs.
    * ``arbitrary_types_allowed=True`` - needed for pint Quantities and
      other third-party types used in sub-configs.
    * ``ser_json_inf_nan="strings"`` - reproducible JSON even for ``inf``.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
        str_strip_whitespace=True,
        arbitrary_types_allowed=True,
        ser_json_inf_nan="strings",
    )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: Any,
        handler: Any,
    ) -> dict[str, Any]:
        schema = super().__get_pydantic_json_schema__(core_schema, handler)
        schema = handler.resolve_ref_schema(schema)
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for field_name, field_info in cls.model_fields.items():
                field_schema = properties.get(field_name)
                if isinstance(field_schema, dict):
                    field_schema["x-hmp-profile"] = extract_profile(field_info).name.lower()
                    examples = _json_schema_examples(field_info)
                    if examples is not None:
                        field_schema.setdefault("examples", examples)
        return schema

    @model_validator(mode="before")
    @classmethod
    def _strip_computed_fields(cls, data: Any) -> Any:
        """Drop any ``model_computed_fields`` keys that survived a ``model_dump`` round-trip.

        Computed fields appear in ``model_dump()`` output but raise under
        ``extra="forbid"`` when fed back through ``model_validate``. Stripping
        them here keeps ``model_dump`` -> ``model_validate`` symmetric.
        """
        if not isinstance(data, dict) or not cls.model_computed_fields:
            return data
        computed = set(cls.model_computed_fields)
        if not any(key in computed for key in data):
            return data
        return {key: value for key, value in data.items() if key not in computed}

    @model_validator(mode="after")
    def _check_visible_when_targets(self) -> HydroModelBase:
        own_fields = set(type(self).model_fields)
        for field_name, info in type(self).model_fields.items():
            for meta in info.metadata:
                if isinstance(meta, VisibleWhen) and meta.field not in own_fields:
                    raise ValueError(
                        f"VisibleWhen on {type(self).__name__}.{field_name} "
                        f"references unknown sibling {meta.field!r}"
                    )
        return self

    def to_toml(
        self,
        path: str | Path,
        *,
        profile: ProfileName = "user",
    ) -> Path:
        """Serialise this config to a TOML file filtered by *profile*.

        Round-trip guarantee: when ``profile="expert"`` is used on a fully
        resolved :class:`~hydromodpy.config.hydromodpy_config.HydroModPyConfig`,
        calling :meth:`HydroModPyConfig.from_toml` on the written path yields
        an equivalent config.

        Parameters
        ----------
        path
            Destination TOML file path.
        profile
            One of ``"user"``, ``"dev"``, ``"expert"``. Fields whose
            :class:`~hydromodpy.core.config_kit.profile.Profile` exceeds
            the requested profile are omitted.
        """
        from hydromodpy.core.toml_io.io import dump_toml_with_comments

        return dump_toml_with_comments(self, path, profile=profile)


__all__ = ["HydroModelBase"]
