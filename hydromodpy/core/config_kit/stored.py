"""How a stored document is read, and the words a stored field is written with.

A model stays ``extra="forbid"``, so a mistake at writing raises. A document on
disk may come from a later 2.x, which added a key or a word this code does not
know. Every read of a stored document goes through :func:`read_stored`, which
accepts the unknown key, at any depth, and keeps the unknown word.

A document this code reads, changes and writes again keeps what it does not
understand: :func:`read_stored` holds the unknown keys on the model, and
:func:`dump_stored` puts them back. A later 2.x then finds what it wrote.

A stored field that can grow (a status, a kind, a regime) is a ``str`` with a
:class:`Vocabulary`: the words are checked when the model is built to be
written, and any word reads back.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final, TypeVar

from pydantic import BaseModel, ValidationInfo
from pydantic_core import CoreSchema, core_schema

_READING_STORED: Final[dict[str, bool]] = {"reading_stored_document": True}
"""The validation context of a read: a :class:`Vocabulary` tolerates any word under it."""

M = TypeVar("M", bound=BaseModel)


def read_stored(model: type[M], payload: Any) -> M:
    """Validate a *payload* read from disk: an unknown key and an unknown word are kept."""
    return model.model_validate(payload, extra="allow", context=_READING_STORED)


def dump_stored(document: BaseModel) -> dict[str, Any]:
    """Return *document* as the JSON a file holds, with the unknown keys its reading kept."""
    rendered = document.model_dump(mode="json", by_alias=True)
    _put_back_unknown_keys(document, rendered)
    return rendered


def _put_back_unknown_keys(value: Any, rendered: Any) -> None:
    """Walk *value* and its rendering side by side: ``model_dump`` leaves the unknown keys out."""
    if isinstance(value, BaseModel) and isinstance(rendered, dict):
        rendered.update(value.__pydantic_extra__ or {})
        for name, field in type(value).model_fields.items():
            key = field.serialization_alias or name
            if key in rendered:
                _put_back_unknown_keys(getattr(value, name), rendered[key])
    elif isinstance(value, Mapping) and isinstance(rendered, dict):
        for key, item in value.items():
            if str(key) in rendered:
                _put_back_unknown_keys(item, rendered[str(key)])
    elif isinstance(value, list | tuple) and isinstance(rendered, list):
        for item, out in zip(value, rendered, strict=False):
            _put_back_unknown_keys(item, out)


class Vocabulary:
    """The words a stored ``str`` field takes: ``Annotated[str, Vocabulary("a", "b")]``."""

    __slots__ = ("words",)

    def __init__(self, *words: str) -> None:
        self.words: tuple[str, ...] = words

    def __get_pydantic_core_schema__(
        self, source: Any, handler: Callable[[Any], CoreSchema]
    ) -> CoreSchema:
        return core_schema.with_info_after_validator_function(self._check, handler(source))

    def __get_pydantic_json_schema__(
        self, schema: CoreSchema, handler: Callable[[CoreSchema], dict[str, Any]]
    ) -> dict[str, Any]:
        document = handler(schema)
        document["x-hmp-vocabulary"] = list(self.words)
        return document

    def _check(self, value: str, info: ValidationInfo) -> str:
        if value in self.words or info.context is _READING_STORED:
            return value
        raise ValueError(f"{value!r} is not one of {', '.join(self.words)}")


__all__ = ["Vocabulary", "dump_stored", "read_stored"]
