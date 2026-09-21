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

import types as stdlib_types
import typing
import warnings
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticUndefined

from hydromodpy.core.config_kit.introspect import extract_profile
from hydromodpy.core.config_kit.profile import ProfileName
from hydromodpy.core.config_kit.visible_when import VisibleWhen

_NONE_TYPE = type(None)

_BOOLEAN_FIELDS: dict[type[BaseModel], frozenset[str]] = {}


def _annotation_leaves(annotation: Any) -> list[Any]:
    """Return the leaf types of *annotation*, unwrapping ``Annotated`` and unions."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _annotation_leaves(get_args(annotation)[0])
    if origin is typing.Union or origin is stdlib_types.UnionType:
        leaves: list[Any] = []
        for arg in get_args(annotation):
            leaves.extend(_annotation_leaves(arg))
        return leaves
    return [annotation]


def _admits_only_bool(annotation: Any) -> bool:
    """Return True when *annotation* accepts a boolean and nothing else but ``None``.

    ``bool | str`` is deliberately excluded: a field that documents a string
    meaning of its own still has to accept one.
    """
    leaves = _annotation_leaves(annotation)
    return bool in leaves and all(leaf is bool or leaf is _NONE_TYPE for leaf in leaves)


def _boolean_field_names(cls: type[BaseModel]) -> frozenset[str]:
    """Return the names of the fields of *cls* that accept only booleans."""
    cached = _BOOLEAN_FIELDS.get(cls)
    if cached is None:
        cached = frozenset(
            name for name, info in cls.model_fields.items() if _admits_only_bool(info.annotation)
        )
        _BOOLEAN_FIELDS[cls] = cached
    return cached


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

    model_legacy_keys: ClassVar[Mapping[str, str]] = {}
    """What a key used to be called, mapped to what it is called now.

    ``extra="forbid"`` makes any rename a hard break for every file that already
    uses the old spelling, so a key that says the wrong thing tends to keep its
    name forever. Declaring the rename here keeps those files loading and warns
    with both spellings, which is the only way a reader learns what to write.

    Only the spellings listed here are accepted; an unknown key is refused as
    before. Writing both spellings of one key is refused too: it is a
    contradiction, and picking a winner silently would hide it.
    """

    model_retired_keys: ClassVar[frozenset[str]] = frozenset()
    """Keys this model used to accept and no longer has, at all.

    ``model_legacy_keys`` covers a key that was renamed; this covers a key that
    was removed. The distinction matters because ``extra="forbid"`` refuses both
    the same way, and a removed key has no new spelling to migrate to.

    A run seals its resolved configuration and ``hmp run --resume`` replays that
    file, so dropping a field from the schema makes every sealed run unreplayable
    unless its key keeps loading. Listing it here accepts it, ignores it, and
    warns, which is what lets the field disappear from the schema without
    rewriting history on disk.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_keys(cls, data: Any) -> Any:
        retired = cls.model_retired_keys
        if not retired or not isinstance(data, Mapping):
            return data
        present = [key for key in retired if key in data]
        if not present:
            return data
        kept = dict(data)
        for key in present:
            warnings.warn(
                f"{key!r} is no longer read by {cls.__name__}; it is accepted so that "
                "files written before its removal keep loading, and it has no effect.",
                DeprecationWarning,
                stacklevel=2,
            )
            kept.pop(key)
        return kept

    @model_validator(mode="before")
    @classmethod
    def _refuse_quoted_booleans(cls, data: Any) -> Any:
        """Refuse a string given for a field that takes only a boolean.

        TOML has native booleans, so a quoted one is always a mistake. Pydantic's
        lax coercion reads ``"yes"`` as True and refuses ``"maybe"``, which makes
        one class of typo behave two different ways; both are refused here.

        Runs after ``_accept_legacy_keys``, so an old spelling is already the key
        it was renamed to and the refusal names the spelling to write.
        """
        if not isinstance(data, Mapping):
            return data
        boolean_fields = _boolean_field_names(cls)
        if not boolean_fields:
            return data
        for key, value in data.items():
            if not isinstance(value, str):
                continue
            if key in boolean_fields:
                raise ValueError(
                    f"{key} = {value!r} is quoted, so it is a string and not a boolean. "
                    f"TOML writes booleans unquoted: write {key} = true or {key} = false."
                )
        return data

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_keys(cls, data: Any) -> Any:
        renames = cls.model_legacy_keys
        if not renames or not isinstance(data, Mapping):
            return data
        present = {old: new for old, new in renames.items() if old in data}
        if not present:
            return data
        migrated = dict(data)
        for old, new in present.items():
            if new in migrated:
                raise ValueError(
                    f"{cls.__name__} was given both {old!r} and {new!r}; {old!r} is the "
                    f"old spelling of {new!r}, so keep one."
                )
            warnings.warn(
                f"{old!r} is now called {new!r} ({cls.__name__}); the old spelling still "
                "loads and will stop being read in a later version.",
                DeprecationWarning,
                stacklevel=2,
            )
            migrated[new] = migrated.pop(old)
        return migrated

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
