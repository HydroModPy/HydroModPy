"""Root Pydantic base class shared by every HydroModPy config model.

All HydroModPy configuration classes inherit from :class:`HydroModelBase`
rather than :class:`pydantic.BaseModel` directly. This centralizes the
strictness defaults (``extra="forbid"``, ``validate_assignment=True``)
that the architecture spec (``architecture_cible/02_config_pydantic.md``
§3.1) requires to be uniform across the codebase.

The root base also validates any :class:`VisibleWhen` metadata attached to
fields: a ``VisibleWhen("sibling", ...)`` tag must reference an existing
field on the same model (catches refactor drift).
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Iterator, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Literal, NoReturn, get_args, get_origin

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticUndefined

from hydromodpy.core.config_kit.introspect import (
    extract_profile,
    held_tables_of,
    named_tables_of,
    unwrap_members,
)
from hydromodpy.core.config_kit.profile import Profile, ProfileName
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.exceptions import ConfigValidationError, FrozenConfigError

_BOOLEAN_FIELDS: dict[type[BaseModel], frozenset[str]] = {}

_FROZEN_MARK = "__hmp_frozen__"
"""The key of ``__dict__`` that marks a frozen copy of a section."""


class ConfigKeyRenamedWarning(FutureWarning):
    """A configuration file wrote a key under the name it used to have.

    The reader of this warning is the person who wrote the file, not a developer
    of the package, which is what ``FutureWarning`` is for. A
    ``DeprecationWarning`` raised from a validator is hidden by Python's default
    filters, and the rename it announces then happens in silence.
    """


_OLD_FORMS_TOLD: set[tuple[str, str]] = set()
"""What this process has already told, as (file, change)."""

_FIX_CONFIG = "hmp doctor --fix-config"
CANNOT_REWRITE = " left: "
"""Marks a change the migration could not make. The loader then refuses the key."""


def warn_old_form(source: str | Path | None, change: str, *, rewritable: bool = True) -> None:
    """Warn that a file loads through an old form, once per file and per key.

    *change* says the old key and the new one, as the migration wrote them. A
    payload that came from no file has nothing to remember it by, so it is told
    every time. *rewritable* is false for a source the doctor has no file to rewrite
    for, such as ``--set``.
    """
    where = "config" if source is None else str(source)
    if source is not None:
        if (where, change) in _OLD_FORMS_TOLD:
            return
        _OLD_FORMS_TOLD.add((where, change))
    if CANNOT_REWRITE in change:
        message = f"{where}: {change}."
    elif not rewritable:
        message = (
            f"{where}: {change}. This old form still loads, with this warning; write the new name."
        )
    else:
        target = "<file>" if source is None else where
        message = (
            f"{where}: {change}. This old form still loads, with this warning; "
            f"`{_FIX_CONFIG} {target}` rewrites the file."
        )
    # stacklevel=1 names this file: the console routing hides a deprecation it
    # reads as a third party's, and the reader of this one is the file's author.
    warnings.warn(message, ConfigKeyRenamedWarning, stacklevel=1)


def refuse_old_forms(
    source: str | Path | None, changes: Sequence[str], *, rewritable: bool
) -> NoReturn:
    """Refuse a file on old forms that have no delay. Each of *changes* says the new name.

    *rewritable* is false for a source the doctor has no file to rewrite for, such as ``--set``.
    """
    where = "config" if source is None else str(source)
    target = "<file>" if source is None else where
    fix = f"`{_FIX_CONFIG} {target}` rewrites the file" if rewritable else "write the new name"
    raise ConfigValidationError(f"{where}: {'; '.join(changes)}. This old form is refused; {fix}.")


def forget_old_forms_told() -> None:
    """Let a report see the old forms again, whatever was printed before.

    All of them: a file reports the old forms of the files it inherits too.
    """
    _OLD_FORMS_TOLD.clear()


def _admits_only_bool(annotation: Any) -> bool:
    """Return True when *annotation* accepts a boolean and nothing else but ``None``.

    ``bool | str`` is deliberately excluded: a field that documents a string
    meaning of its own still has to accept one.
    """
    leaves = unwrap_members(annotation)
    return bool in leaves and all(leaf is bool for leaf in leaves)


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

    model_refused_keys: ClassVar[Mapping[str, str]] = {}
    """Keys this model no longer accepts, mapped to what to write instead.

    For a key that no step ever read, or that did the job of another key. No
    run can depend on it, so it is refused rather than accepted and ignored:
    the message names the key and the advice says which key does the job.
    """

    @model_validator(mode="before")
    @classmethod
    def _refuse_removed_keys(cls, data: Any) -> Any:
        refused = cls.model_refused_keys
        if not refused or not isinstance(data, Mapping):
            return data
        for key, advice in refused.items():
            if key in data:
                raise ValueError(f"{key!r} is not accepted any more: {advice}")
        return data

    @model_validator(mode="before")
    @classmethod
    def _refuse_quoted_booleans(cls, data: Any) -> Any:
        """Refuse a string given for a field that takes only a boolean.

        TOML has native booleans, so a quoted one is always a mistake. Pydantic's
        lax coercion reads ``"yes"`` as True and refuses ``"maybe"``, which makes
        one class of typo behave two different ways; both are refused here.
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
            tables = named_tables_of(cls, shipped_only=True)
            for name, table in tables.items():
                # Through the generator, so the table is a $ref with its own profile marks.
                generator = handler.generate_json_schema
                table_schema = dict(generator.generate_inner(table.__pydantic_core_schema__))
                table_schema["x-hmp-profile"] = Profile.USER.name.lower()
                properties.setdefault(name, table_schema)
            if tables:
                # A plugin's table is checked by its own class when the file is read.
                schema["additionalProperties"] = {"type": "object"}
        return schema

    def __setattr__(self, name: str, value: Any) -> None:
        """Assign a field, unless this section belongs to a frozen copy."""
        if _FROZEN_MARK in self.__dict__:
            raise FrozenConfigError(
                f"{type(self).__name__}.{name}: this is a frozen copy of the configuration, "
                "so the change would reach nothing. A run takes its changes by "
                "project.simulate(set={...}). A configuration takes them by "
                "config.with_changes({...}), and the result opens a new Project."
            )
        super().__setattr__(name, value)

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
        written_only: bool = False,
    ) -> Path:
        """Serialize this config to a TOML file filtered by *profile*.

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
        written_only
            Keep only the fields this config was given, so the file reads
            back with the same fields set.
        """
        from hydromodpy.core.config_kit.dump import dump_toml_with_comments

        return dump_toml_with_comments(self, path, profile=profile, written_only=written_only)


def frozen_copy(model: HydroModelBase) -> HydroModelBase:
    """Return a deep copy of *model* that refuses every assignment, at every depth.

    The mark sits in the ``__dict__`` of each section. Pydantic reads the fields of a
    model by their names and skips it, so the copy dumps and compares like the original.
    :func:`thawed_copy` gives a copy that can be changed again.
    """
    copied = model.model_copy(deep=True)
    for section in _sections_of(copied):
        section.__dict__[_FROZEN_MARK] = True
    return copied


def thawed_copy(model: HydroModelBase) -> HydroModelBase:
    """Return *model* when it was never frozen, else a deep copy that can be changed."""
    if _FROZEN_MARK not in model.__dict__:
        return model
    copied = model.model_copy(deep=True)
    for section in _sections_of(copied):
        section.__dict__.pop(_FROZEN_MARK, None)
    return copied


def _sections_of(value: Any) -> Iterator[HydroModelBase]:
    """Yield every config model under *value*, itself included, named tables too."""
    if isinstance(value, HydroModelBase):
        yield value
        children: Iterable[Any] = [*value.__dict__.values(), *held_tables_of(value).values()]
    elif isinstance(value, Mapping):
        children = value.values()
    elif isinstance(value, list | tuple):
        children = value
    else:
        return
    for child in children:
        yield from _sections_of(child)


def write_resolved(model: BaseModel, name: str, value: Any) -> None:
    """Write a field a validator read out of what the file wrote, and count it as written.

    ``value = "1e-5 cm/s"`` writes ``unit`` too. The identity of a run and the cache
    of a calibration read a configuration with ``exclude_unset``, so a field left out
    of ``model_fields_set`` would make that value hash like ``"1e-5 m/s"``.
    """
    object.__setattr__(model, name, value)
    model.model_fields_set.add(name)


__all__ = ["HydroModelBase", "frozen_copy", "thawed_copy", "write_resolved"]
