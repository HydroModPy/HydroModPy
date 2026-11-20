"""The one reader of ``phrases.toml``: the sentence of a code, in English and in French."""

from __future__ import annotations

import tomllib
from importlib.resources import files
from typing import Final, Literal, get_args

Lang = Literal["en", "fr"]
"""A language every phrase is written in."""

LANGS: Final[tuple[str, ...]] = get_args(Lang)
"""The languages every phrase is written in, read from :data:`Lang`."""


def _read() -> dict[str, dict[str, dict[str, str]]]:
    text = files("hydromodpy.schema").joinpath("phrases.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


_TABLES: Final[dict[str, dict[str, dict[str, str]]]] = _read()


def keys(table: str) -> frozenset[str]:
    """Return the closed set of keys of *table*, for example ``label_reason``.

    Raises
    ------
    KeyError
        When *table* is not a table of ``phrases.toml``.
    """
    return frozenset(_TABLES[table])


def phrase(table: str, key: str, lang: str = "en", **values: object) -> str:
    """Return the phrase of *key* in *table*, in *lang*, with its ``{name}`` fields filled.

    Raises
    ------
    ValueError
        When *lang* is not one of ``LANGS``.
    KeyError
        When *table* or *key* is unknown, or a field of the phrase has no value.
    """
    if lang not in LANGS:
        raise ValueError(f"lang {lang!r} is not one of {', '.join(LANGS)}")
    return _TABLES[table][key][lang].format(**values)


__all__ = ["LANGS", "Lang", "keys", "phrase"]
