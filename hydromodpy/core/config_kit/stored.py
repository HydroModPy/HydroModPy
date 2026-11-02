"""How a stored document is read, and the words a stored field is written with.

A model stays ``extra="forbid"``, so a mistake at writing raises. A document on
disk may come from a later 2.x, which added a key or a word this code does not
know. Every read of a stored document goes through :func:`read_stored`, which
ignores the unknown key, at any depth, and keeps the unknown word.

A stored field that can grow (a status, a kind, a regime) is a ``str`` with a
:class:`Vocabulary`: the words are checked when the model is built to be
written, and any word reads back.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, TypeVar

from pydantic import BaseModel, ValidationInfo
from pydantic_core import CoreSchema, core_schema

_READING_STORED: Final[dict[str, bool]] = {"reading_stored_document": True}
"""The validation context of a read: a :class:`Vocabulary` tolerates any word under it."""

M = TypeVar("M", bound=BaseModel)


def read_stored(model: type[M], payload: Any) -> M:
    """Validate a *payload* read from disk: an unknown key is ignored, an unknown word kept."""
    return model.model_validate(payload, extra="ignore", context=_READING_STORED)


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


__all__ = ["Vocabulary", "read_stored"]
